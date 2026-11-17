/**
 * The guidance the model gets with the file tools. Which tools this process
 * gets (APP_TOOLS) is dsh-plugin-app-tools' to say.
 *
 * @module dsh-plugin-app-fs/tools
 */

/** The one guidance block the model gets, built from the selected tools only. */
export function guidance(tools) {
  if (!tools.size) return ''
  const lines = ['Your file tools see only your workspace. Paths are relative to it; nothing outside it exists for them.']
  const changes = tools.has('write') || tools.has('edit') || tools.has('apply_patch')
  if (changes) {
    lines.push('Read an existing file before changing it.')
    if (tools.has('write')) lines.push('Put scratch and intermediate files in .dumps/.')
  }
  if (tools.has('trash')) lines.push('Remove files with trash: it moves them to .dumps/.trash/, where they stay readable for this run. There is no permanent delete.')
  // Only an agent that can write needs telling not to hand its answer over as a
  // file; a read-only one may end its run some other way (a finalize_* tool).
  if (changes) lines.push('Your answer is your final message, not a file.')
  return lines.join('\n')
}