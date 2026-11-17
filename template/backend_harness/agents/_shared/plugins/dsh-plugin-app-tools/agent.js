/**
 * agents/<name>/agent.yml: the one file that declares an agent to the harness.
 * It sits outside workspace/, so the model never sees it. app-agent (through
 * cli.js), the profile generator (runtime/bin/app-profiles.mjs) and context.mjs
 * read it here, so it is parsed and checked in exactly one place on this side.
 * The template's Python gates read it with two readers of their own (the
 * architecture graph's, tests/support/harness_agents.py, and PyYAML in
 * tests/gates/test_agent_yml.py); all three are held to the verdicts of
 * backend_harness/tests/agent_yml_cases.json (this one by tools.test.mjs).
 *
 *   description: one or two sentences: what the agent does      (required)
 *   limits:                                                      (required, all three)
 *     max_run_seconds: <int> | null     null = no limit
 *     max_tokens: <int> | null          null = no limit
 *     max_attempts: <int>               times one task may run
 *   tools:                                                       (optional)
 *     shared: [read, ...]               tools of agents/_shared/plugins, by name
 *     own:                              one entry per tool its own plugins register
 *       <tool>:
 *         effects: {<value>: <note>, ...}
 *         repeat: {<value>: <note>}
 *   model:                                                       (optional, both keys)
 *     name: deepseek-flash              a model id on the profile's route
 *     reasoning: low                    off | low | high | max
 *
 * max_run_seconds and max_tokens are enforced inside the run by
 * runtime/plugins/dsh-plugin-app-limits (app-agent passes them as APP_LIMITS,
 * printed by cli.js); max_attempts is the harness server's, which reads it from
 * the build's agents.json (app-profiles.mjs --agents-json). The Effects and
 * Repeat values are a closed vocabulary whose one definition is the logic
 * side's (tests/support/architecture.py, the E1 enums): here only the shape
 * is checked, the values by the template's gates on every real file.
 * Whether a successful call ends the run is not declared here: the own
 * plugin says it in its
 * package.json (`harness.ends_run`).
 * Without `model` the agent runs on the app profile's agent-default-model; with
 * it, app-profiles.mjs writes these two values into that entry of the agent's
 * own profile (app_<name>), so the provider stays the profile's one route.
 *
 * YAML through js-yaml, which dsh itself depends on (pinned with DSH_VERSION):
 * no install of ours. CORE_SCHEMA: no timestamps, no merge keys; js-yaml
 * refuses a duplicate key.
 *
 * @module dsh-plugin-app-tools/agent
 */

import { readFileSync } from 'node:fs'
import { CORE_SCHEMA, load } from 'js-yaml'
import { checkTools } from './index.js'

const NAME = /^[a-z][a-z0-9_]*$/
// A model id as a provider route takes it (deepseek-flash): lowercase, digits, . and -.
const MODEL_NAME = /^[a-z][a-z0-9.-]*[a-z0-9]$/
// The reasoning efforts dsh's built-in route takes (llm-deepseek: off, low, high, max).
const REASONING = ['off', 'low', 'high', 'max']
// Every limit is required; a nullable one says "no limit" with null. No upper
// bound: what is too much is a policy for when the limits are enforced.
const LIMITS = { max_run_seconds: true, max_tokens: true, max_attempts: false }
const SENTENCE_END = /[.!?](?=\s|$)/g

const isMapping = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const keysOf = (value, allowed, where) => {
  const unknown = Object.keys(value).filter(key => !allowed.includes(key))
  return unknown.length ? [`${where}: unknown key${unknown.length > 1 ? 's' : ''} ${unknown.join(', ')}`] : []
}
const text = value => typeof value === 'string' && value.trim() !== ''

// `{<value>: <note>}`: a non-empty mapping, every note a non-empty text.
function notes(value, where, single) {
  if (!isMapping(value) || Object.keys(value).length === 0) return [`${where}: a mapping of value to note`]
  const problems = Object.entries(value).filter(([, note]) => !text(note)).map(([key]) => `${where}.${key}: the note is a non-empty text`)
  if (single && Object.keys(value).length !== 1) problems.push(`${where}: exactly one value`)
  return problems
}

// `model`: absent, or exactly `name` and `reasoning`.
function modelProblems(model) {
  if (model === undefined) return []
  if (!isMapping(model)) return ['model: a mapping with name and reasoning']
  const problems = keysOf(model, ['name', 'reasoning'], 'model')
  if (typeof model.name !== 'string' || !MODEL_NAME.test(model.name)) problems.push(`model.name: a model id, ${MODEL_NAME}`)
  if (!REASONING.includes(model.reasoning)) problems.push(`model.reasoning: one of ${REASONING.join(', ')}`)
  return problems
}

/** What is wrong with a parsed agent.yml (empty when it passes the shape). */
export function agentProblems(doc) {
  if (!isMapping(doc)) return ['not a mapping']
  const problems = keysOf(doc, ['description', 'limits', 'tools', 'model'], 'agent.yml')
  const description = typeof doc.description === 'string' ? doc.description.trim() : ''
  const sentences = description.match(SENTENCE_END)?.length ?? 0
  if (sentences < 1 || sentences > 2 || !/[.!?]$/.test(description)) problems.push('description: one or two sentences, required')
  if (!isMapping(doc.limits)) {
    problems.push(`limits: required, with ${Object.keys(LIMITS).join(', ')}`)
  } else {
    problems.push(...keysOf(doc.limits, Object.keys(LIMITS), 'limits'))
    for (const [key, nullable] of Object.entries(LIMITS)) {
      const value = doc.limits[key]
      if (value === undefined) problems.push(`limits.${key}: required${nullable ? ' (null = no limit)' : ''}`)
      else if (value === null && nullable) continue
      else if (!Number.isSafeInteger(value) || value < 1) {
        problems.push(`limits.${key}: a positive integer${nullable ? ', or null' : ''}`)
      }
    }
  }
  problems.push(...modelProblems(doc.model))
  if (doc.tools === undefined) return problems
  if (!isMapping(doc.tools) || Object.keys(doc.tools).length === 0) return [...problems, 'tools: a mapping with shared and/or own']
  problems.push(...keysOf(doc.tools, ['shared', 'own'], 'tools'))
  const { shared, own } = doc.tools
  if (shared !== undefined) {
    if (!Array.isArray(shared) || shared.length === 0 || !shared.every(name => typeof name === 'string')) {
      problems.push('tools.shared: a non-empty list of tool names')
    } else if (new Set(shared).size !== shared.length) {
      problems.push('tools.shared: a tool listed twice')
    } else {
      const { error } = checkTools(shared)
      if (error) problems.push(`tools.shared: ${error}`)
    }
  }
  if (own !== undefined) {
    if (!isMapping(own) || Object.keys(own).length === 0) {
      problems.push('tools.own: a mapping of tool name to its effects and repeat')
    } else {
      for (const [tool, entry] of Object.entries(own)) {
        const where = `tools.own.${tool}`
        if (!NAME.test(tool)) problems.push(`${where}: a tool name is ${NAME}`)
        if (!isMapping(entry)) {
          problems.push(`${where}: a mapping with effects and repeat`)
          continue
        }
        problems.push(...keysOf(entry, ['effects', 'repeat'], where))
        problems.push(...notes(entry.effects, `${where}.effects`, false))
        problems.push(...notes(entry.repeat, `${where}.repeat`, true))
      }
    }
  }
  return problems
}

/**
 * One agent.yml, parsed and checked: `{ agent }`, or `{ error }` (bad YAML, a
 * duplicate key, a shape problem). `agent.shared` is the checked set of shared
 * tools, `agent.own` the own tool names; both empty without `tools`.
 * `agent.model` is `{ name, reasoning }`, or null: the profile's default.
 */
export function parseAgent(source, file = 'agent.yml') {
  let doc
  try {
    doc = load(source, { schema: CORE_SCHEMA, filename: file })
  } catch (error) {
    return { error: `${file}: ${error.message}` }
  }
  const problems = agentProblems(doc)
  if (problems.length) return { error: `${file}: ${problems.join('; ')}` }
  return {
    agent: {
      description: doc.description.trim(),
      limits: { ...doc.limits },
      shared: checkTools(doc.tools?.shared ?? []).tools,
      own: Object.keys(doc.tools?.own ?? {}),
      model: doc.model === undefined ? null : { name: doc.model.name, reasoning: doc.model.reasoning },
    },
  }
}

/** readFileSync + parseAgent; a missing file is an error too (every agent has one). */
export function readAgent(file) {
  let source
  try {
    source = readFileSync(file, 'utf8')
  } catch (error) {
    return { error: `${file}: ${error.code === 'ENOENT' ? 'missing (every agent declares itself in agent.yml)' : error.message}` }
  }
  return parseAgent(source, file)
}
