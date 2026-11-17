/**
 * apply_patch and apply_patch_undo, on the fence in workspace.js.
 *
 * Copied from dsh-customs plugins/apply-patch: parsePatch and applyChunks
 * verbatim (parser.mjs, Codex format, exact context only); prepare / publish /
 * settle / undo follow index.mjs. Changed: every path goes through the fence,
 * receipts and backups live in .dumps/.patch/ inside the workspace, removals go
 * through our trash, the quota counts the whole patch before anything is
 * written, and undo accepts only receipts of this process.
 *
 * @module dsh-plugin-app-fs/patch
 */

import { randomBytes } from 'node:crypto'
import { mkdir, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { contentBytes, readTextFile, trashOne } from './files.js'
import { FenceError, PATCHES, atomicWrite, under, versionOf } from './workspace.js'

// Format based on OpenAI Codex apply-patch parser; see dsh-customs REFERENCE.md.
// This adapter deliberately requires exact context instead of fuzzy matching.
export function parsePatch(patch) {
  const lines = patch.trim().split(/\r?\n/);
  if (lines.shift() !== '*** Begin Patch' || lines.pop() !== '*** End Patch') throw new Error('Expected *** Begin Patch and *** End Patch boundaries.');
  const operations = [];
  let i = 0;
  while (i < lines.length) {
    const header = /^\*\*\* (Add|Delete|Update) File: (.+)$/.exec(lines[i++]);
    if (!header) throw new Error(`Invalid file header at patch line ${i + 1}.`);
    const op = { kind: header[1].toLowerCase(), path: header[2], chunks: [] };
    if (op.kind === 'add') {
      const content = [];
      while (i < lines.length && !lines[i].startsWith('*** ')) {
        if (!lines[i].startsWith('+')) throw new Error('Added file lines must start with +.');
        content.push(lines[i++].slice(1));
      }
      op.content = content.length ? content.join('\n') + '\n' : '';
    } else if (op.kind === 'update') {
      if (lines[i]?.startsWith('*** Move to: ')) op.move = lines[i++].slice(13);
      while (i < lines.length && !lines[i].startsWith('*** ')) {
        let anchor;
        if (lines[i] === '@@' || lines[i].startsWith('@@ ')) anchor = lines[i++].slice(3);
        const chunk = { anchor, old: [], replacement: [], eof: false };
        while (i < lines.length && !lines[i].startsWith('@@') && !lines[i].startsWith('*** ')) {
          const line = lines[i++];
          if (![' ', '-', '+'].includes(line[0])) throw new Error(`Invalid change line ${i + 1}.`);
          if (line[0] !== '+') chunk.old.push(line.slice(1));
          if (line[0] !== '-') chunk.replacement.push(line.slice(1));
        }
        if (lines[i] === '*** End of File') { chunk.eof = true; i++; }
        if (!chunk.old.length && !chunk.replacement.length) throw new Error('Empty change chunk.');
        op.chunks.push(chunk);
      }
      if (!op.chunks.length && !op.move) throw new Error('Empty update operation.');
    }
    operations.push(op);
  }
  if (!operations.length) throw new Error('Patch has no operations.');
  return operations;
}
export function applyChunks(text, chunks) {
  const newline = text.endsWith('\n');
  const source = text === '' ? [] : text.split('\n');
  if (newline) source.pop();
  const edits = [], covered = new Set();
  let cursor = 0;
  for (const chunk of chunks) {
    if (chunk.anchor) {
      const index = source.indexOf(chunk.anchor, cursor);
      if (index < 0) throw new Error(`Anchor not found: ${chunk.anchor}`);
      covered.add(index); cursor = index + 1;
    }
    let index;
    if (!chunk.old.length) { index = source.length; if (source.length) covered.add(source.length - 1); }
    else {
      const matches = [];
      for (let j = cursor; j <= source.length - chunk.old.length; j++) {
        if (chunk.eof && j + chunk.old.length !== source.length) continue;
        if (chunk.old.every((line, k) => source[j + k] === line)) matches.push(j);
      }
      if (matches.length !== 1) {
        const hint = !matches.length && chunk.anchor === chunk.old[0] ? ` Lines are searched strictly after the "@@ ${chunk.anchor}" anchor line (Codex semantics); do not repeat the anchor as the first context line.` : '';
        throw new Error(`Expected unique exact context, found ${matches.length}; re-read or add context.${hint}`);
      }
      index = matches[0];
      chunk.old.forEach((_, k) => covered.add(index + k));
    }
    edits.push({ index, count: chunk.old.length, replacement: chunk.replacement });
    cursor = index + chunk.old.length;
  }
  for (const edit of edits.toReversed()) source.splice(edit.index, edit.count, ...edit.replacement);
  return { after: source.length ? source.join('\n') + (newline || text === '' ? '\n' : '') : '', covered: [...covered] };
}

const conflict = message => new FenceError(`Conflict: ${message}`, 'APP_FS_CONFLICT')

async function prepare(ws, obs, operation, target, destination) {
  if (operation.kind === 'add') {
    if (target.leaf) throw conflict(`Add target already exists: ${target.rel}`)
    const bytes = contentBytes(operation.content)
    return { operation, target, after: operation.content, grow: bytes, entries: target.missing }
  }
  if (!target.leaf) throw new FenceError(`"${target.rel}": not found`, 'APP_FS_NOT_FOUND')
  if (!target.leaf.isFile()) throw new FenceError(`patch target must be a regular file: ${target.rel}`, 'APP_FS_NOT_FOUND')
  const version = versionOf(target.leaf)
  const full = operation.kind === 'delete' || !!destination
  obs.require(target.abs, version, target.rel, { full })
  const { text: before, version: readVersion } = await readTextFile(target.abs, target.rel)
  if (readVersion !== version) throw conflict(`${target.rel} changed since it was read; read it again and rebuild the patch.`)
  let after = ''
  if (operation.kind === 'update') {
    let change
    try {
      change = applyChunks(before, operation.chunks)
    } catch (error) {
      throw new Error(`Context not found in ${target.rel}: ${error.message}`)
    }
    if (!full) obs.require(target.abs, version, target.rel, { lines: change.covered })
    after = change.after
  }
  if (destination?.leaf) throw conflict(`Move destination exists: ${destination.rel}`)
  const beforeBytes = Buffer.byteLength(before)
  // The backup stays in .dumps/.patch and a removed source stays in the trash:
  // both still count against the quota, as do a destination's missing folders.
  let grow = beforeBytes
  let entries = operation.kind === 'delete' || destination ? 2 : 1
  if (operation.kind === 'update') {
    const afterBytes = contentBytes(after)
    grow += destination ? afterBytes : afterBytes - beforeBytes
    if (destination) entries += destination.missing
  }
  return { operation, target, destination, before, after, version, grow, entries }
}

/** Where a failed operation left the files, re-observed rather than assumed. */
async function settle(ws, plan, record) {
  const source = await ws.stamp(plan.target.abs)
  const output = plan.destination ? await ws.stamp(plan.destination.abs) : source
  const written = record.version !== undefined && output === record.version
  const kind = plan.operation.kind
  if (kind === 'add') return source === null ? 'unchanged' : written ? 'changed' : 'uncertain'
  if (kind === 'update' && !plan.destination) return source === plan.version ? 'unchanged' : written ? 'changed' : 'uncertain'
  const present = source !== null
  const removed = source === null && !!record.trash
  if (kind === 'delete') return present ? 'unchanged' : removed ? 'changed' : 'uncertain'
  if (output === null && present) return 'unchanged'
  return written && present ? 'partial' : written && removed ? 'changed' : 'uncertain'
}

async function newReceiptDir(ws) {
  const id = `${new Date().toISOString().replace(/[:.]/g, '-')}-${randomBytes(3).toString('hex')}`
  const dir = join(PATCHES, id)
  // Same no-link rule as any change, on the way to the receipt.
  await ws.resolveMutation(join(dir, 'manifest.json'), { internal: true })
  await mkdir(join(ws.root, dir), { recursive: true })
  return dir
}

async function publish(ws, obs, receipts, plans) {
  const dir = await newReceiptDir(ws)
  const manifest = join(dir, 'manifest.json')
  const receipt = { manifest, atomic: false, status: 'applying', operations: [] }
  const save = () => atomicWrite(join(ws.root, manifest), JSON.stringify(receipt, null, 2))
  const note = error => { receipt.manifest_error = ws.scrub(error) }
  await save()
  for (let i = 0; i < plans.length; i++) {
    const plan = plans[i]
    const kind = plan.operation.kind
    const record = { kind, path: plan.target.rel, status: 'prepared' }
    if (kind !== 'delete') record.output = (plan.destination ?? plan.target).rel
    if (plan.destination) record.move = true
    receipt.operations.push(record)
    try {
      if (plan.before !== undefined) {
        record.backup = join(dir, `${i}.original`)
        await writeFile(join(ws.root, record.backup), plan.before, { flag: 'wx', mode: 0o644 })
      }
      await save()
      if (kind !== 'delete') {
        const output = plan.destination ?? plan.target
        const now = await ws.stamp(output.abs)
        const expected = kind === 'add' || plan.destination ? null : plan.version
        if (now !== expected) throw conflict(`${output.rel} changed while the patch was applied.`)
        await ws.ensureParent(output.abs)
        await atomicWrite(output.abs, plan.after)
        record.version = await ws.stamp(output.abs)
        record.status = 'written'
        obs.wrote(output.abs, record.version)
      }
      if (kind === 'delete' || plan.destination) {
        if ((await ws.stamp(plan.target.abs)) !== plan.version) throw conflict(`${plan.target.rel} changed while the patch was applied.`)
        record.trash = await trashOne(ws, obs, plan.target.rel)
      }
      record.status = 'applied'
      record.state = 'changed'
    } catch (error) {
      record.error = ws.scrub(error)
      record.state = await settle(ws, plan, record)
      receipt.not_attempted = plans.slice(i + 1).map(p => p.target.rel)
      break
    }
    await save().catch(note)
  }
  const failed = receipt.operations.find(r => r.error)
  if (failed?.state === 'unchanged' && receipt.operations.length === 1) {
    // Nothing changed and nothing to undo: drop the receipt and its backup.
    await rm(join(ws.root, dir), { recursive: true, force: true })
    throw new Error(failed.error)
  }
  receipts.set(manifest, receipt)
  receipt.status = failed ? 'partial_failure' : 'applied'
  await save().catch(note)
  return JSON.stringify(receipt)
}

/** Any thrown error means nothing was written; partial outcomes come back as receipts. */
export async function applyPatch(ws, obs, receipts, patch) {
  try {
    if (typeof patch !== 'string') throw new Error('patch must be a string')
    let operations
    try {
      operations = parsePatch(patch)
    } catch (error) {
      throw new Error(`Invalid patch format: ${error.message}`)
    }
    // A parent and its child in one patch (a, a/b) would change each other's path.
    const seen = []
    const plans = []
    for (const operation of operations) {
      const target = await ws.resolveMutation(operation.path)
      const destination = operation.move ? await ws.resolveMutation(operation.move) : undefined
      for (const { abs } of destination ? [target, destination] : [target]) {
        if (seen.some(prev => under(abs, prev) || under(prev, abs))) throw new Error('Invalid path: patch paths overlap; split into separate calls.')
        seen.push(abs)
      }
      plans.push(await prepare(ws, obs, operation, target, destination))
    }
    // .dumps, .dumps/.patch, the receipt folder and manifest, .dumps/.trash.
    const grow = plans.reduce((sum, plan) => sum + plan.grow, 64 * 1024)
    await ws.assertFits(grow, plans.reduce((sum, plan) => sum + plan.entries, 5))
    return await publish(ws, obs, receipts, plans)
  } catch (error) {
    throw new Error(`Patch not applied; no file changed. ${ws.scrub(error)}`, { cause: error })
  }
}

async function backupText(ws, record) {
  const { real, rel } = await ws.resolveRead(record.backup)
  return (await readTextFile(real, rel)).text
}

async function undoOne(ws, obs, record) {
  const original = await ws.resolveMutation(record.path)
  const output = record.output === undefined ? undefined : await ws.resolveMutation(record.output)
  if (output && (await ws.stamp(output.abs)) !== record.version) throw new Error('File changed after the patch; undo refuses to overwrite newer work.')
  const recreate = record.kind === 'delete' || record.move
  if (recreate) {
    if ((await ws.stamp(original.abs)) !== null) throw new Error('Original path was recreated after the patch; undo refuses to overwrite it.')
    const text = await backupText(ws, record)
    await ws.assertFits(Buffer.byteLength(text), original.missing)
    await ws.ensureParent(original.abs)
    await atomicWrite(original.abs, text)
    obs.wrote(original.abs, await ws.stamp(original.abs))
  }
  if (record.kind === 'add' || record.move) return { state: 'restored', trash: await trashOne(ws, obs, output.rel) }
  if (record.kind === 'update') {
    const text = await backupText(ws, record)
    await ws.assertFits(Buffer.byteLength(text) - Number(output.leaf.size), 0)
    await atomicWrite(output.abs, text)
    obs.wrote(output.abs, await ws.stamp(output.abs))
  }
  return { state: 'restored' }
}

export async function undoPatch(ws, obs, receipts, manifest) {
  let key
  try {
    key = ws.lexical(manifest).rel
  } catch {
    key = undefined
  }
  // Only receipts this process made: never execute a manifest from disk.
  const receipt = key === undefined ? undefined : receipts.get(key)
  if (!receipt) throw new Error('Unknown recovery receipt for this process.')
  for (const record of receipt.operations.toReversed()) {
    if (record.undo?.state === 'restored' || !record.state || record.state === 'unchanged') continue
    if (record.state !== 'changed') {
      record.undo = { state: 'not_restored', error: 'Patch outcome was not clean; recover by hand from the backup or trash entry.' }
      continue
    }
    record.undo = await undoOne(ws, obs, record).catch(error => ({ state: 'not_restored', error: ws.scrub(error) }))
  }
  const pending = receipt.operations.filter(r => r.state && r.state !== 'unchanged' && r.undo?.state !== 'restored')
  receipt.status = pending.length ? 'partial_undo' : 'undone'
  await ws.resolveMutation(receipt.manifest, { internal: true })
    .then(() => atomicWrite(join(ws.root, receipt.manifest), JSON.stringify(receipt, null, 2)))
    .catch(error => { receipt.manifest_error = ws.scrub(error) })
  return JSON.stringify(receipt)
}