#!/usr/bin/env node
// Runs INSIDE the harness image (context.sh mounts it): boot the `app` profile
// in-process, create a fresh agent, send one probe message and record the first
// model request it would make: system text by section, every message, every tool.
//
// A prompt-audit capture, made simple by the container: the profile is the
// image's own throwaway copy (dsh rewrites a profile's cordis.yml on boot,
// harmless here) and `docker run --network none`
// keeps it offline, so no fs/net fences are needed.
//
// No fake route: an `llm/stream` middleware answers before any adapter runs, so
// the request keeps the profile's real default provider/model and no provider is
// ever called (nor a credential read).
//
// With --fail-first CODE the first agent request is answered with that error
// instead, and the capture is the request AFTER recovery: what the model sees
// once app-recovery (or llm-retry) has reacted. Written as <profile>.<scenario>.*.
//
// With --limit-seconds N the run gets APP_LIMITS max_run_seconds N (as app-agent
// passes an agent's limits) and the first agent request never answers until it
// is cancelled: the capture is the request after app-limits interrupted the turn
// at 100%, carrying its notice. N/4 (100% to 125%, where app-limits ends the
// process) must be several times the capture's wait after the request
// (IDLE_WAIT_MS + SETTLE_MS).
//
// With --agent NAME the agent boots in a workspace of agents/NAME, assembled
// like app-agent does (symlinks to the template), so its AGENTS.md is captured,
// and under its own profile, <profile>_NAME (app_NAME, generated at image build
// with the agent's plugins), which is the profile app-agent runs. The report and
// file names keep the base --profile (app.NAME); the JSON records the profile
// actually booted (bootedProfile).
//
//   node context.mjs --profile app --out /out [--fail-first PROVIDER_TERMINATED --scenario recovery]
//   node context.mjs --profile app --out /out --agent summarizer --scenario summarizer
//   node context.mjs --profile app --out /out --limit-seconds 60 --scenario limit
import { existsSync, mkdirSync, readdirSync, symlinkSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

const { values: args } = parseArgs({ options: {
  profile: { type: 'string', default: 'app' },
  out: { type: 'string', default: '/out' },
  anchor: { type: 'string', default: '/opt/dsh/node_modules/@deepseek-ai/dsh/package.json' },
  'fail-first': { type: 'string' },
  // How many agent requests in a row fail with --fail-first's code (tests the
  // recovery budget; the baseline scenario uses 1).
  'fail-times': { type: 'string', default: '1' },
  scenario: { type: 'string' },
  agent: { type: 'string' },
  'limit-seconds': { type: 'string' },
} });
if (args.agent) {
  const template = join('/opt/app/agents', args.agent, 'workspace');
  const workspace = join('/tmp/app-work', `context-${args.agent}`);
  mkdirSync(workspace, { recursive: true });
  for (const entry of readdirSync(template)) symlinkSync(join(template, entry), join(workspace, entry));
  process.chdir(workspace);
  // The agent's opt-in tools (tools.shared of its agent.yml), as app-agent
  // exports them, read by the same module (the plugins read APP_TOOLS at load,
  // and check it again).
  const { readAgent } = await import('/opt/dsh/node_modules/dsh-plugin-app-tools/agent.js');
  const { agent, error } = readAgent(join('/opt/app/agents', args.agent, 'agent.yml'));
  if (error) throw new Error(error);
  process.env.APP_TOOLS = [...agent.shared].join(',');
  // And its limits, which app-limits reads at load (null = none).
  process.env.APP_LIMITS = JSON.stringify(agent.limits);
}
const FAIL_FIRST = args['fail-first'];
const FAIL_TIMES = FAIL_FIRST ? Number(args['fail-times']) : 0;
const LIMIT_SECONDS = args['limit-seconds'] ? Number(args['limit-seconds']) : 0;
if (LIMIT_SECONDS) process.env.APP_LIMITS = JSON.stringify({ max_run_seconds: LIMIT_SECONDS, max_tokens: null });
// Which agent request is the capture: the first one that is answered.
const CAPTURED = LIMIT_SECONDS ? 1 : FAIL_TIMES;
const BASENAME = args.scenario ? `${args.profile}.${args.scenario}` : args.profile;
const BOOTED_PROFILE = args.agent ? `${args.profile}_${args.agent}` : args.profile;

const BIN = 'app-context';
const PROBE = 'context probe: reply OK.';
// With --limit-seconds the captured request comes only after the limit.
const IDLE_TIMEOUT_MS = 60_000 + LIMIT_SECONDS * 1000;
const SETTLE_MS = 2_000;
// The most the capture waits for the turn to end after its request. Shorter with
// --limit-seconds: the whole wait (this + SETTLE_MS, 5 s) must stay well inside
// the 100%..125% window (a quarter of the limit), or app-limits exits mid-capture.
const IDLE_WAIT_MS = LIMIT_SECONDS ? 3_000 : 10_000;

const requireHost = createRequire(args.anchor);
const load = name => import(pathToFileURL(requireHost.resolve(`@deepseek-ai/${name}`)).href);
const detach = value => JSON.parse(JSON.stringify(value, (key, item) => (key === 'signal' ? undefined : item)));
const textOf = message => message.content
  .map(block => (block.type === 'text' ? block.text : `<${block.type} block>`)).join('\n');

async function capture() {
  const home = process.env.DSH_HOME;
  const [boot, llm, cmdline, prompt, dshAgent] = await Promise.all(
    ['dsh-app-boot', 'dsh-llm', 'dsh-cmdline', 'dsh-system-prompt', 'dsh-agent'].map(load));
  const dir = join(home, 'profiles', BOOTED_PROFILE);
  if (!existsSync(join(dir, 'package.json'))) throw new Error(`no profile ${BOOTED_PROFILE} in ${home}/profiles`);
  // dsh empties the profile root before every boot; do the same.
  const rootConfig = join(dir, 'cordis.yml');
  writeFileSync(rootConfig, '[]\n');
  const profile = boot.loadProfileDirectory(BIN, dir, args.anchor);
  const overlays = [
    // Next to the output: when the capture fails, the session log says why.
    { id: 'session-persistence-jsonl', config: { root: join(args.out, 'sessions'), compression: 'none' } },
    // The headless app wants a task on the command line; this script drives the
    // agent itself.
    { id: 'headless-startup', disabled: true },
    { id: 'headless-runner', disabled: true },
  ];
  const origin = {
    name: BOOTED_PROFILE, dir, patchPath: join(dir, 'cordis.patch.yml'), installAnchor: args.anchor,
    cwd: process.cwd(), home, startedBundles: profile.layers.map(layer => layer.packageName),
    overlays, telemetryDisabledEnv: '1',
  };
  const resolution = await boot.createRuntimeResolution({ installAnchor: args.anchor, profile, home });
  const ctx = await boot.boot(BIN, rootConfig, boot.readProfilePatches(BIN, origin, profile), async host => {
    host.provide('profileContext', origin);
    await host.plugin(boot.PluginPackages, { resolution });
    cmdline.provideCmdline(host, { args: [], exit: () => {}, ready: { onReady: () => () => {} } });
  });

  // Every model call is recorded and answered here; `purpose` separates the
  // agent's own request from side calls such as session titles.
  const calls = [];
  let gotAgentRequest;
  const agentRequest = new Promise(resolve => { gotAgentRequest = resolve; });
  ctx.on('llm/stream', async function* record(options) {
    calls.push(detach(options));
    const agentCalls = calls.filter(call => !call.purpose).length;
    if (!options.purpose && agentCalls <= FAIL_TIMES) {
      yield { type: 'finish', reason: { kind: 'error', failure: { code: FAIL_FIRST, message: `app-context: simulated ${FAIL_FIRST}` } } };
      return;
    }
    if (!options.purpose && LIMIT_SECONDS && agentCalls === 1) {
      // A request that outlives the run's time limit: it ends only when
      // app-limits cancels the turn.
      await new Promise(resolve => {
        if (options.signal?.aborted) resolve();
        options.signal?.addEventListener('abort', resolve, { once: true });
      });
      yield { type: 'finish', reason: { kind: 'aborted', failure: { code: 'ABORTED', message: 'app-context: cancelled' } } };
      return;
    }
    if (!options.purpose) gotAgentRequest();
    yield { type: 'block-start', index: 0, blockType: 'text' };
    yield { type: 'text-delta', index: 0, text: 'OK' };
    yield { type: 'block-end', index: 0, block: { type: 'text', text: 'OK' } };
    yield { type: 'finish', reason: { kind: 'stop' } };
  });

  // The route and model selection exactly as the headless runner sets them
  // (dsh-headless: agentOptions from agent-default-model's current selection, and
  // installModelSelection in the agent's setup, which carries its reasoning
  // effort). Without agentOptions the agent has no model and the turn stalls
  // silently; without the selection the request falls back to the adapter's own
  // default effort. Shown on the report's `options` line.
  const selection = ctx.get('agentDefaultModel').currentSelection();
  const presets = ctx.get('agentPresets');
  const preset = presets === undefined ? undefined : await presets.resolve(undefined);
  let assembly;
  const { agent } = await ctx.agents.create({
    sessionId: crypto.randomUUID(),
    meta: { cwd: process.cwd(), ...(preset ? { agentPreset: preset.id } : {}) },
    agentOptions: { provider: selection.provider, model: selection.model },
    setup: async agentCtx => {
      dshAgent.installModelSelection(agentCtx, { current: selection, assembled: undefined });
      if (preset) await presets.mount(agentCtx, preset.id);
      agentCtx.on('system-prompt/assemble', async (_assembly, _context, next) => {
        const assembled = await next();
        assembly = detach(assembled);
        return assembled;
      });
    },
  });
  agent.followup(llm.createUserMessage({ content: [{ type: 'text', text: PROBE }], source: { kind: 'user' } }));
  // Wait for the request itself, not for idle: right after followup() the agent
  // can still report idle, which would end the capture before the turn runs.
  let timer;
  await Promise.race([agentRequest, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(FAIL_FIRST
      ? `no retry after a simulated ${FAIL_FIRST} within ${IDLE_TIMEOUT_MS} ms (nothing recovered it)`
      : LIMIT_SECONDS
        ? `no request after the ${LIMIT_SECONDS}s time limit within ${IDLE_TIMEOUT_MS} ms (no limit notice)`
        : `no agent model request after ${IDLE_TIMEOUT_MS} ms`)), IDLE_TIMEOUT_MS);
  })]);
  clearTimeout(timer);
  // Then let the turn end and give fire-and-forget side calls (session titles
  // and the like) a moment to fire, so they land in the report and baseline
  // instead of depending on how fast this process exits. The settle time is a
  // heuristic, not a guarantee.
  await Promise.race([agent.whenIdle(), new Promise(resolve => setTimeout(resolve, IDLE_WAIT_MS))]);
  await new Promise(resolve => setTimeout(resolve, SETTLE_MS));

  // Per-section rendering only labels the system text (the request holds the real
  // text). Some variables, like {{model}}, are bound later than the assembly hook,
  // so a section that uses one is shown as its template.
  const render = section => {
    try {
      return prompt.renderPrompt({ sections: [section], contexts: [], tools: [], variables: assembly.variables });
    } catch {
      return `<template> ${section.template ?? section.text ?? JSON.stringify(section)}`;
    }
  };
  const agentCalls = calls.filter(call => !call.purpose);
  return {
    profile: args.profile,
    bootedProfile: BOOTED_PROFILE,
    bundles: origin.startedBundles,
    preset: preset ? preset.id : null,
    scenario: FAIL_FIRST
      ? `first ${FAIL_TIMES} request(s) failed with ${FAIL_FIRST}`
      : LIMIT_SECONDS ? `max_run_seconds ${LIMIT_SECONDS}, the first request ran past it` : null,
    request: agentCalls[CAPTURED] ?? null,
    agentRequestCount: agentCalls.length,
    allCalls: calls.map(call => ({ provider: call.provider, model: call.model, purpose: call.purpose ?? null, messages: call.messages?.length ?? 0 })),
    sideCalls: calls.filter(call => call.purpose).map(call => ({ provider: call.provider, model: call.model, purpose: call.purpose })),
    systemSections: assembly ? assembly.sections.map(section => ({ name: section.name, text: render(section) })) : [],
  };
}

// The readable view: what the model gets, in order, with sizes so a growing
// prompt is visible at a glance.
function toText(result) {
  const request = result.request;
  const out = [];
  const size = text => `${text.length} chars`;
  out.push(`profile ${result.profile}  route ${request.provider}/${request.model}  preset ${result.preset ?? '-'}`);
  out.push(`bundles ${result.bundles.join(', ')}`);
  if (result.scenario) out.push(`scenario ${result.scenario}; this is the request after ${LIMIT_SECONDS ? 'the limit notice' : 'recovery'}`);
  // Generation options are part of what the model gets; sessionId is per run.
  const { messages: _m, tools: _t, sessionId: _s, provider: _p, model: _mo, ...options } = request;
  out.push(`options ${JSON.stringify(options)}`);
  if (result.sideCalls.length) out.push(`side model calls: ${result.sideCalls.map(call => call.purpose).join(', ')}`);
  out.push('');
  out.push(`== system sections (${result.systemSections.length})`);
  for (const section of result.systemSections) out.push(`-- ${section.name} (${size(section.text)})`, section.text, '');
  out.push(`== messages (${request.messages.length})`);
  request.messages.forEach((message, index) => {
    const text = textOf(message);
    out.push(`-- #${index + 1} ${message.role}/${message.source?.kind ?? message.role} (${size(text)})`, text, '');
  });
  const tools = request.tools ?? [];
  out.push(`== tools (${tools.length})`);
  for (const tool of tools) out.push(`-- ${tool.name}`, tool.description ?? '', JSON.stringify(tool.parameters ?? {}), '');
  return `${out.join('\n')}\n`;
}

try {
  const result = await capture();
  if (!result.request) throw new Error(`the agent made no model request; model calls seen: ${JSON.stringify(result.allCalls)}`);
  mkdirSync(args.out, { recursive: true });
  writeFileSync(join(args.out, `${BASENAME}.json`), JSON.stringify(result, null, 2));
  writeFileSync(join(args.out, `${BASENAME}.txt`), toText(result));
  const tools = result.request.tools ?? [];
  process.stdout.write(`${result.request.messages.length} messages, ${result.systemSections.length} system sections, ${tools.length} tools${tools.length ? `: ${tools.map(tool => tool.name).join(', ')}` : ''}\n`);
  // Teardown skipped: the capture is complete and disposal only adds side effects.
  process.exit(0);
} catch (error) {
  process.stderr.write(`app-context failed: ${error?.stack ?? error}\n`);
  process.exit(1);
}