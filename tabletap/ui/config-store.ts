/** Lossless, atomic edits for a user's commented TableTap YAML file. */
import {
  chmodSync, copyFileSync, existsSync, readFileSync, renameSync,
  statSync, unlinkSync, writeFileSync,
} from "node:fs"
import YAML from "yaml"

export type ConfigField = string | number
export type Action = { name?: string; type?: "key" | "exec" | "script"; value?: string }
export type TableConfig = {
  // YAML contains both flat gesture actions and numbered profile maps.
  actions: Record<string, Action | Record<string | number, Action>>
  detection?: Record<string, number | boolean>
  filter?: Record<string, number | boolean>
  audio?: Record<string, unknown>
}

export const FOUR_GESTURES = ["single", "double", "triple", "quadruple"] as const
export const HOLD_GESTURES = ["long", "medium", "extended", "repeat"] as const

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
      ![...FOUR_GESTURES, ...HOLD_GESTURES].includes(key as never) &&
      value !== null && typeof value === "object" &&
      Object.keys(value).some((item) => /^\d+$/.test(item)),
    )
    .map(([name]) => name)
  return ["default", ...categories]
}

export function getActionRows(config: TableConfig, profile: string): [string, Action][] {
  if (profile === "default") {
    const order = [
      ...FOUR_GESTURES,
      ...(config.detection?.enable_hold_gestures ? HOLD_GESTURES : []),
    ]
    return order.reduce<[string, Action][]>((rows, gesture) => {
      const action = config.actions[gesture]
      if (action && typeof action === "object" && "value" in action) {
        rows.push([gesture, action as Action])
      }
      return rows
    }, [])
  }
  const actions = config.actions[profile]
  if (!actions || typeof actions !== "object") return []
  return Object.entries(actions)
    .filter(([key, action]) => /^\d+$/.test(key) && typeof action === "object" && action !== null)
    .sort(([a], [b]) => Number(a) - Number(b)) as [string, Action][]
}

export function actionFieldPath(profile: string, key: string, field: string): ConfigField[] {
  if (profile === "default") return ["actions", key, field]
  if (!/^\d+$/.test(key)) throw new Error("Invalid numbered profile action")
  return ["actions", profile, Number(key), field]
}

/** Apply a single field edit without discarding user's YAML comments.
 * Writes a backup and atomically renames a private, temporary file.
 * Re-reads from disk to preserve edits performed by other tools since startup.
 */
export function updateConfigField(
  path: string, fields: ConfigField[], value: string | number | boolean, demo = false,
): TableConfig {
  if (demo) throw new Error("Demo mode is read-only")
  if (!existsSync(path)) throw new Error("Configuration not found: " + path)
  const before = statSync(path)
  const source = readFileSync(path, "utf8")
  const document = YAML.parseDocument(source, { keepSourceTokens: true })
  if (document.errors.length) {
    throw new Error("Cannot edit invalid YAML: " + document.errors[0]?.message)
  }
  if (fields.length === 0) throw new Error("No config field selected")
  document.setIn(fields, value)
  const updated = String(document)
  const parsed = YAML.parse(updated) as TableConfig
  if (!parsed || typeof parsed !== "object") throw new Error("Invalid updated configuration")
  const temp = path + ".tmp-" + process.pid
  try {
    writeFileSync(temp, updated, { mode: 0o600, flag: "w" })
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
