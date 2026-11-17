# Vendored code

`src/vendor/` keeps dsh-tui's directory layout so the copied files import each other unchanged. The license texts travel in `LICENSES/`; keep them with the files.

## Sources (all MIT)

| From | Version | Files | License |
|---|---|---|---|
| `@deepseek-harness-tui/dsh-tui` (author chimney, https://github.com/ccch1mneyyy/dsh-TUI) | 0.14.0 | `screens/TrajectoryScene.js`; `components/trajectory/{Ledger,WaveBand,Inspector,HotspotView,scope,useTrajectoryScope}.js`; `trajectory/{format,query,window,motion}.js`; `dsh-adapter/trajectory/{projection,guards,types,aggregate,wave,inspect,index}.js`: copied as-is, but for the edits below | `LICENSES/dsh-tui.LICENSE`; the project's third-party notices, `LICENSES/dsh-tui.THIRD_PARTY_LICENSES`, kept with it (they name portions of other projects; none of the vendored files is one of the files they list, but the notice does not list every file it covers, so it stays) |
| same | 0.14.0 | `components/Spinner/spinnerUtils.js` (`interpolateColor`, `parseRGB` only), `components/design-system/HintLine.js` | same |
| `@deepseek-ai/dsh-llm` | 0.2.0-rc.2 | `expandAssistantStream` + validator → `src/vendor/dsh-llm.js` | `LICENSES/dsh.LICENSE` (Copyright (c) 2026 DeepSeek) |
| `@deepseek-ai/dsh-session-persistence-jsonl` | 0.2.0-rc.2 | `scanZstdFrames` → `src/decode.js` | `LICENSES/dsh.LICENSE` (the same text) |

The npm dependencies in `package.json` (`@duckdb/node-api`, `ink`, `react`, `chalk`, `string-width`) are installed by `npm ci`, never vendored; their licenses come with them in `node_modules/`.

## Edits to copied files

- `dsh-adapter/trajectory/index.js`: removed `export { createAgentTrajectorySource } from './agent-source.js';` (subagent lanes, not vendored).
- `dsh-adapter/trajectory/guards.js`: `import * as dshLlm from '../../dsh-llm.js'` instead of `'@deepseek-ai/dsh-llm'`.
- `HintLine.js`: imports `Text` from `../../ui.js`.
- `dsh-adapter/trajectory/projection.js` `readTokens` (comment `app-telemetry edit`): also reads dsh-llm 0.2.0-rc.2's `TokenUsage` names (`inputTokens`, `outputTokens`, `reasoningTokens`, `cacheReadTokens`, `cacheWriteTokens`); dsh-tui 0.14.0 only knew `input`/`output`/…, so every token count was 0.
- `dsh-adapter/trajectory/projection.js` `tool/result`: a result with `message.isError` (the tool ran and refused, e.g. a fence or an SQL refusal) closes the row as `error` too; dsh-tui 0.14.0 only looked at `data.error` (the call failed to run), so refusals counted as ok.

## Shims (written here, at the paths the copied files import)

- `ui.js`: `Box`/`Text` over npm ink, theme keys → fixed palette, mouse props dropped (npm ink has no mouse); `useTerminalSize` = ink `useWindowSize`; `useTheme` is constant.
- `theme.js`: dsh-tui's `dark` palette, fixed.
- `i18n.js`: the English `traj-*` / `trajectory-*` strings; hints say "q back" instead of "q exit".
- `ink/stringWidth.js` (npm `string-width`), `ink/hooks/use-animation-frame.js` (plain interval), `components/design-system/Divider.js` (explicit-width rule only).
- `dsh-llm.js`: `snapshotJsonValue` is a JSON round trip and `deepFreeze` is local, instead of `@deepseek-ai/dsh-util-values`.

## Upgrading

Copy the same files from the new dsh-tui release, re-apply the edits above, refresh `LICENSES/` from that release, run `npm test`.
