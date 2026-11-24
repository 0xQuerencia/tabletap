/** Lossless, atomic edits for a user's commented TableTap YAML file. */
import {
  chmodSync, copyFileSync, existsSync, readFileSync, renameSync,
  statSync, unlinkSync, writeFileSync,
} from "node:fs"
import YAML from "yaml"
import { validateActionDraft, type ActionDraft } from "./action-builder.ts"

export type ConfigField = string | number
export type Action = { name?: string; type?: "key" | "exec" | "script" | "builtin" | "workflow" | "launcher"; value?: string }
export type TableConfig = {
  // YAML contains both flat gesture actions and numbered profile maps.
  actions: Record<string, Action | Record<string | number, Action>>
  detection?: Record<string, number | boolean>
  filter?: Record<string, number | boolean>
  audio?: Record<string, unknown>
  calibration?: { personalized?: boolean; duration_sec?: number; active_name?: string; required?: boolean }
}

export const FOUR_GESTURES = ["single", "double", "triple", "quadruple"] as const


export function readTableConfig(path: string): TableConfig {
  const content = readFileSync(path, "utf8")
  const data: unknown = YAML.parse(content)
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("Configuration must be a YAML mapping")
  }
  const config = data as TableConfig
  if (!config.actions || typeof config.actions !== "object") {
    throw new Error("Configuration has no actions mapping")
  }
  return config
}

export function getProfiles(config: TableConfig): string[] {
  const categories = Object.entries(config.actions)
    .filter(([key, value]) =>
      validProfileName(key) &&
      value !== null && typeof value === "object" &&
      !Array.isArray(value) && Object.keys(value).every((item) => /^\d+$/.test(item)),
    )
    .map(([name]) => name)
  return ["default", ...categories]
}

export function getActionRows(config: TableConfig, profile: string): [string, Action][] {
  if (profile === "default") {
    const order = FOUR_GESTURES
    return order.reduce<[string, Action][]>((rows, gesture) => {
      const action = config.actions[gesture]
      rows.push([gesture, action && typeof action === "object" && "value" in action ? action as Action : {}])
      return rows
    }, [])
  }
  const actions = config.actions[profile]
  if (!actions || typeof actions !== "object") return []
  const mapped = actions as Record<string, Action>
  const keys = [...new Set(["1", "2", "3", "4", ...Object.keys(mapped).filter(k => /^[1-9]\d*$/.test(k))])]
  return keys.sort((a,b) => Number(a)-Number(b)).map(k => [k, mapped[k] || {}])
}

export function actionFieldPath(profile: string, key: string, field: string): ConfigField[] {
  if (profile === "default") {
    if (!FOUR_GESTURES.includes(key as never)) throw new Error("Invalid gesture")
    return ["actions", key, field]
  }
  if (!validProfileName(profile) || !/^[1-9]\d*$/.test(key) || Number(key) > 20) throw new Error("Invalid numbered profile action (1–20)")
  return ["actions", profile, Number(key), field]
}

/** Apply a single field edit without discarding user's YAML comments.
 * Writes a backup and atomically renames a private, temporary file.
 * Re-reads from disk to preserve edits performed by other tools since startup.
 */
type FieldUpdate = { fields: ConfigField[]; value?: unknown; remove?: boolean }

/** Write all fields in one backup and atomic replacement, never a partial action. */
export function updateConfigFields(path: string, edits: FieldUpdate[], demo = false): TableConfig {
  if (demo) throw new Error("Demo mode is read-only")
  if (!existsSync(path)) throw new Error("Configuration not found: " + path)
  const before = statSync(path)
  const source = readFileSync(path, "utf8")
  const document = YAML.parseDocument(source, { keepSourceTokens: true })
  if (document.errors.length) {
    throw new Error("Cannot edit invalid YAML: " + document.errors[0]?.message)
  }
  if (!edits.length || edits.some(({ fields }) => fields.length === 0)) {
    throw new Error("No config field selected")
  }
  for (const { fields, value, remove } of edits) {
    if (remove) document.deleteIn(fields)
    else document.setIn(fields, value)
  }
  const updated = String(document)
  const parsed = YAML.parse(updated) as TableConfig
  if (!parsed || typeof parsed !== "object") throw new Error("Invalid updated configuration")
  const temp = path + ".tmp-" + process.pid + "-" + crypto.randomUUID()
  try {
    writeFileSync(temp, updated, { mode: 0o600, flag: "wx" })
    chmodSync(temp, 0o600)
    const now = statSync(path)
    if (now.mtimeMs !== before.mtimeMs || now.size !== before.size) {
      throw new Error("Configuration changed externally; edit not saved. Reload and retry.")
    }
    copyFileSync(path, path + ".bak")
    renameSync(temp, path)
  } finally {
    if (existsSync(temp)) unlinkSync(temp)
  }
  return parsed
}


/** Keep legacy one-field edits while supporting all-or-nothing builder saves. */
export function updateConfigField(
  path: string, fields: ConfigField[], value: string | number | boolean | null, demo = false,
): TableConfig {
  return updateConfigFields(path, [{ fields, value }], demo)
}

export function updateConfigAction(
  path: string, profile: string, gesture: string, draft: ActionDraft, demo = false,
): TableConfig {
  const problem = validateActionDraft(draft)
  if (problem) throw new Error(problem)
  if (!getProfiles(readTableConfig(path)).includes(profile)) throw new Error("Profile not found")
  return updateConfigFields(path, [
    { fields: actionFieldPath(profile, gesture, "name"), value: draft.name.trim() },
    { fields: actionFieldPath(profile, gesture, "type"), value: draft.type },
    { fields: actionFieldPath(profile, gesture, "value"), value: draft.value.trim() },
  ], demo)
}

export function validProfileName(name: string): boolean {
  return /^[A-Za-z0-9_-]{1,40}$/.test(name) &&
    !["default", "__proto__", "prototype", "constructor", ...FOUR_GESTURES, "long", "medium", "extended", "repeat"].includes(name)
}

export function createActionProfile(path: string, name: string, source?: string, demo = false): TableConfig {
  if (!validProfileName(name)) throw new Error("Use a unique profile name: 1–40 letters, numbers, hyphens or underscores")
  const config = readTableConfig(path)
  if (Object.hasOwn(config.actions, name)) throw new Error("Profile already exists")
  if (source && !getProfiles(config).includes(source)) throw new Error("Source profile not found")
  const entries = source ? getActionRows(config, source).filter(([, action]) => action.value) : []
  const mapped = new Map(entries.flatMap(([key,action]) => {
    const n = source === "default" ? FOUR_GESTURES.indexOf(key as never) + 1 : Number(key)
    return n >= 1 && n <= 20 ? [[n, action] as const] : []
  }))
  return updateConfigFields(path, [{fields:["actions",name],value: mapped}],demo)
}

export function clearAction(path: string, profile: string, key: string, demo = false): TableConfig {
  return updateConfigFields(path,[{fields:actionFieldPath(profile,key,"value").slice(0,-1),remove:true}],demo)
}

export function deleteActionProfile(path: string, name: string, demo = false): TableConfig {
  const cfg = readTableConfig(path)
  if (!validProfileName(name) || !getProfiles(cfg).includes(name)) throw new Error("Named profile not found")
  for (const profile of getProfiles(cfg)) {
    if (profile === name) continue
    if (getActionRows(cfg,profile).some(([,a]) => a.type === "launcher" && a.value === name))
      throw new Error("Profile is used by a gesture launcher; clear that mapping first")
  }
  return updateConfigFields(path,[{fields:["actions",name],remove:true}],demo)
}
