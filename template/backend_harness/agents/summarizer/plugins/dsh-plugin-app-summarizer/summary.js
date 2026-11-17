/**
 * The local admission of a summary: what finalize_summary accepts. The rules
 * mirror workspace/style.md (the text the model reads); a summary the model
 * proposes becomes the run's output only after these checks pass.
 *
 * @module dsh-plugin-app-summarizer/summary
 */

export const MAX_CHARS = 600
export const MAX_SENTENCES = 3

// A sentence ends at . ! or ? followed by a space or the end of the text.
const SENTENCE_END = /[.!?](?=\s|$)/g

/** What is wrong with a proposed summary (empty when it is accepted). */
export function problemsOf(summary) {
  if (typeof summary !== 'string' || summary.trim() === '') return ['the summary is empty']
  const text = summary.trim()
  const problems = []
  if (text.length > MAX_CHARS) problems.push(`the summary has ${text.length} characters; at most ${MAX_CHARS}`)
  const sentences = text.match(SENTENCE_END)?.length ?? 0
  if (sentences > MAX_SENTENCES) problems.push(`the summary has ${sentences} sentences; at most ${MAX_SENTENCES}`)
  if (/^\s*(#|[-*] )/m.test(text)) problems.push('the summary is plain prose: no headings or list items')
  return problems
}
