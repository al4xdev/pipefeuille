#!/usr/bin/env node
// app-agent's check of an agents/<name>/agent.yml: prints the APP_TOOLS value
// (its tools.shared, comma-separated; empty when it lists none), or with
// `limits` the APP_LIMITS value (its limits as one JSON object, null = no
// limit), or exits 2 with why. A bad or missing file stops the run: a typo
// must not quietly start an agent without its tools or its limits.
//
//   node cli.js /opt/app/agents/<name>/agent.yml [tools|limits]
import { readAgent } from './agent.js'

const [file, what = 'tools'] = process.argv.slice(2)
if (!file || !['tools', 'limits'].includes(what)) {
  process.stderr.write('usage: cli.js <agent.yml> [tools|limits]\n')
  process.exit(2)
}
const { agent, error } = readAgent(file)
if (error) {
  process.stderr.write(`app-agent: ${error}\n`)
  process.exit(2)
}
process.stdout.write(what === 'limits' ? JSON.stringify(agent.limits) : [...agent.shared].join(','))
