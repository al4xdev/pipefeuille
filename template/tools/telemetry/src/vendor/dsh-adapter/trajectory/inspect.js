/**
 * Inspector detail — full content, resolved on demand.
 *
 * The projection stores no message bodies: a node keeps `seq` (and `endSeq`)
 * and nothing else about content, so a ten-thousand-row session costs a few
 * hundred kilobytes of index rather than a second copy of the transcript. The
 * price is that opening a row has to go back to the log — which is free,
 * because the log is the same in-memory immutable array the fold read.
 *
 * That is also why this module lives in the adapter: it is the only place that
 * reads raw event payloads for display, and the boundary gate keeps it here.
 * The scene renders the returned sections without knowing what an event is.
 */
import { t } from '../../i18n.js';
import { asRawEvents, readApprovalAsked, readRetry } from './guards.js';
/** Binary search for an event by seq; the log is seq-monotonic. */
function findBySeq(events, seq) {
    let low = 0;
    let high = events.length - 1;
    while (low <= high) {
        const mid = (low + high) >> 1;
        const candidate = events[mid];
        if (candidate.seq === seq)
            return candidate;
        if (candidate.seq < seq)
            low = mid + 1;
        else
            high = mid - 1;
    }
    return undefined;
}
/** Pretty-print a JSON string; returns the input unchanged when it is not JSON. */
function prettyJson(text) {
    const trimmed = text.trim();
    if (!trimmed.startsWith('{') && !trimmed.startsWith('['))
        return text;
    try {
        return JSON.stringify(JSON.parse(trimmed), null, 2);
    }
    catch {
        return text;
    }
}
/** Concatenate every text block of a message content array. */
function allText(content) {
    if (!Array.isArray(content))
        return '';
    const parts = [];
    for (const block of content) {
        if (typeof block !== 'object' || block === null)
            continue;
        const record = block;
        if (typeof record.text === 'string')
            parts.push(record.text);
        else if (record.type === 'image')
            parts.push('[image]');
    }
    return parts.join('\n');
}
/**
 * The answer text of the ask-tool result paired with a question's `callId`.
 *
 * A settled questionnaire reports only its `requestId`; the answer the user
 * picked lands as the ask tool's own result, found by one backwards scan;
 * absence stays absence.
 */
function pairedResultText(events, callId) {
    for (let index = events.length - 1; index >= 0; index--) {
        const event = events[index];
        if (event.type !== 'tool/result')
            continue;
        const message = event.data?.message;
        const source = typeof message === 'object' && message !== null
            ? message.source
            : undefined;
        if (typeof source !== 'object' || source === null)
            continue;
        if (source.callId !== callId)
            continue;
        const body = allText(message.content);
        return body === '' ? undefined : body;
    }
    return undefined;
}
/**
 * Resolve the full detail for one ledger row.
 *
 * @param node - The focused row.
 * @param events - The session's current event snapshot.
 * @returns Display-ready sections. Always succeeds: a row whose owning event
 *   has been compacted away still yields its header facts.
 */
export function inspectNode(node, events) {
    const raw = asRawEvents(events);
    const open = findBySeq(raw, node.seq);
    const close = node.endSeq === undefined ? undefined : findBySeq(raw, node.endSeq);
    const data = open?.data;
    const facts = [];
    if (node.turn > 0)
        facts.push(node.step === undefined ? `turn ${node.turn}` : `turn ${node.turn} · step ${node.step}`);
    if (node.callId !== undefined)
        facts.push(node.callId.slice(0, 12));
    if (node.tokens !== undefined) {
        const { input, output, think, cacheRead } = node.tokens;
        facts.push(`in ${input} · out ${output}${think > 0 ? ` · think ${think}` : ''}${cacheRead > 0 ? ` · cache ${cacheRead}` : ''}`);
    }
    // The neutral AgentEvent source stamps rows whose envelope
    // time came from the trace clock rather than the backend: "this is when
    // we saw it", not "this is when it happened". DSH events never carry the
    // stamp, so their facts are unchanged.
    if (data?.observed === true) {
        facts.push(t('trajectory-time-observed'));
    }
    const sections = [];
    switch (node.kind) {
        case 'tool':
        case 'subtool': {
            const args = node.detail;
            if (args !== undefined && args !== '')
                sections.push({ title: 'input', body: prettyJson(args) });
            const message = close?.data?.message;
            const body = typeof message === 'object' && message !== null
                ? allText(message.content)
                : (node.outcome ?? '');
            if (body !== '')
                sections.push({ title: 'output', body, tone: node.status === 'error' ? 'error' : undefined });
            if (node.errorCode !== undefined)
                sections.push({ title: 'error', body: node.errorCode, tone: 'error' });
            break;
        }
        case 'retry': {
            const payload = open === undefined ? undefined : readRetry(open.data);
            if (payload !== undefined) {
                facts.push(`${node.attempts ?? 1} attempts`);
                if (payload.provider !== undefined)
                    facts.push(payload.provider);
                sections.push({
                    title: 'cause',
                    body: `${payload.code ?? 'unknown'} — ${payload.message ?? ''}`.trim(),
                    tone: 'error',
                });
            }
            // Every attempt of this sequence, so the backoff ladder is visible.
            const ladder = [];
            for (const event of raw) {
                if (event.type !== 'llm/retry')
                    continue;
                const attempt = readRetry(event.data);
                if (attempt === undefined || payload === undefined || attempt.retryId !== payload.retryId)
                    continue;
                ladder.push(`#${attempt.retry} → ${Math.round(attempt.delayMs)}ms`);
            }
            if (ladder.length > 0)
                sections.push({ title: 'backoff', body: ladder.join('  ') });
            break;
        }
        case 'approval': {
            // 审批/问卷的等待时长在表头右侧（已结束）或检视器的 live 行（等待
            // 中）呈现；这里补上响应与来源。settled 事件只带 outcome，来源与
            // 可选项只在 asked 载荷里。
            if (node.detail !== undefined)
                sections.push({ title: 'reason', body: node.detail });
            if (node.outcome !== undefined) {
                sections.push({ title: 'outcome', body: node.outcome, tone: node.status === 'error' ? 'error' : undefined });
            }
            const ask = readApprovalAsked(open?.data);
            if (ask !== undefined) {
                // 问卷的 settled 只报 requestId；答案在 callId 配对的 ask 工具结果里，
                // 找不到就不显示。
                if (ask.ask === 'question') {
                    const answer = ask.callId === undefined ? undefined : pairedResultText(raw, ask.callId);
                    if (answer !== undefined) {
                        sections.push({ title: 'response', body: answer });
                    }
                }
                const source = [];
                if (ask.agentId !== undefined)
                    source.push(`agent ${ask.agentId.slice(0, 12)}`);
                if (ask.title !== undefined && ask.title !== ask.reason)
                    source.push(ask.title);
                if (ask.command !== undefined)
                    source.push(`command: ${ask.command}`);
                if (ask.blockedPath !== undefined)
                    source.push(`blocked: ${ask.blockedPath}`);
                if (ask.options !== undefined && ask.options.length > 0)
                    source.push(`options: ${ask.options.join(' | ')}`);
                if (source.length > 0)
                    sections.push({ title: 'source', body: source.join('\n'), tone: 'dim' });
                if (ask.questions !== undefined && ask.questions.length > 0) {
                    const lines = ask.questions.map((question, index) => {
                        const head = question.header === undefined ? '' : `[${question.header}] `;
                        const options = question.options.length === 0 ? '' : `  (${question.options.join(' | ')})`;
                        return `${index + 1}. ${head}${question.question}${options}`;
                    });
                    sections.push({ title: 'questions', body: lines.join('\n') });
                }
            }
            break;
        }
        case 'user':
        case 'assistant':
        case 'thinking':
        case 'context': {
            const content = data?.content ?? data?.message?.content;
            const body = allText(content);
            sections.push({ title: node.kind, body: body === '' ? (node.detail ?? '') : body });
            break;
        }
        default: {
            if (node.detail !== undefined && node.detail !== '')
                sections.push({ title: 'detail', body: node.detail });
            if (node.outcome !== undefined && node.outcome !== '')
                sections.push({ title: 'outcome', body: node.outcome });
            break;
        }
    }
    if (node.burst !== undefined) {
        sections.unshift({
            title: `${node.burst.members.length} calls`,
            body: node.burst.members
                .map((member, position) => `${position + 1}. ${(member.detail ?? '').replace(/\s+/g, ' ').slice(0, 120)}`)
                .join('\n'),
            tone: 'dim',
        });
    }
    const title = node.label === '' ? node.kind : node.label;
    return { title, facts, sections, ...(open === undefined ? { unresolved: true } : {}) };
}
