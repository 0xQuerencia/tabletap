import { test, expect } from "bun:test"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import {
  actionFieldPath, getActionRows, getProfiles, readTableConfig, updateConfigField, updateConfigAction,
} from "./config-store.ts"

function fixture() {
  const dir = mkdtempSync(join(tmpdir(), "tabletap-config-"))
  const path = join(dir, "config.yaml")
  writeFileSync(path, `# My annotated configuration
audio:
  sample_rate: 44100 # stay at 44.1k
filter:
  sensitivity_offset_db: 0 # in dB
actions:
  single:
    type: exec
    value: spotify # original action
  double:
    type: exec
    value: firefox
  media:
    1:
      name: Play
      type: key
      value: XF86AudioPlay
    2:
      name: Next
      type: key
      value: XF86AudioNext
`)
  return { dir, path }
}

test("single field edit preserves comments, unrelated values and backup", () => {
  const { dir, path } = fixture()
  try {
    const result = updateConfigField(path, ["actions", "single", "value"], "firefox")
    expect((result.actions.single as { value: string }).value).toBe("firefox")
    const content = readFileSync(path, "utf8")
    expect(content).toContain("# My annotated configuration")
    expect(content).toContain("# stay at 44.1k")
    expect(content).toContain("# original action")
    expect(readFileSync(path + ".bak", "utf8")).toContain("value: spotify")
    expect((readTableConfig(path).actions.media as Record<number, {value:string}>)[2].value).toBe("XF86AudioNext")
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test("numbered category edits target numeric YAML keys", () => {
  const { dir, path } = fixture()
  try {
    const edited = updateConfigField(path, actionFieldPath("media", "2", "value"), "XF86AudioPrev")
    const media = edited.actions.media as Record<number, {value:string}>
    expect(media[2].value).toBe("XF86AudioPrev")
    expect(getActionRows(edited, "media")[0]?.[0]).toBe("1")
    expect(getProfiles(edited)).toEqual(["default", "media"])
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test("demo cannot modify user configuration", () => {
  const { dir, path } = fixture()
  try {
    const original = readFileSync(path, "utf8")
    expect(() => updateConfigField(path, ["actions", "single", "value"], "bad", true))
      .toThrow(/read-only/)
    expect(readFileSync(path, "utf8")).toBe(original)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test("invalid YAML refuses edits instead of overwriting", () => {
  const { dir, path } = fixture()
  try {
    writeFileSync(path, "actions: [broken")
    expect(() => updateConfigField(path, ["actions", "single", "value"], "oops"))
      .toThrow(/invalid YAML/i)
    expect(readFileSync(path, "utf8")).toBe("actions: [broken")
  } finally { rmSync(dir, { recursive: true, force: true }) }
})


test("system default microphone is represented as YAML null", () => {
  const { dir, path } = fixture()
  try {
    const result = updateConfigField(path, ["audio", "device_index"], null)
    expect(result.audio?.device_index).toBeNull()
    expect(readFileSync(path, "utf8")).toContain("device_index: null")
  } finally { rmSync(dir, { recursive: true, force: true }) }
})


test("builder saves name, type and command atomically with comments and backup", () => {
  const { dir, path } = fixture()
  try {
    const result = updateConfigAction(path, "default", "single", {
      name: "Music toggle", type: "key", value: "XF86AudioPlay",
    })
    const action = result.actions.single as { name: string; type: string; value: string }
    expect(action).toEqual({ name: "Music toggle", type: "key", value: "XF86AudioPlay" })
    const output = readFileSync(path, "utf8")
    expect(output).toContain("# My annotated configuration")
    expect(output).toContain("# original action")
    expect(readFileSync(path + ".bak", "utf8")).toContain("value: spotify")
    expect(getActionRows(result, "default")[0]?.[1].value).toBe("XF86AudioPlay")
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test("builder supports named profile actions with numeric YAML keys", () => {
  const { dir, path } = fixture()
  try {
    const result = updateConfigAction(path, "media", "2", {
      name: "Open notes", type: "exec", value: "xdg-open https://example.com",
    })
    const action = (result.actions.media as Record<number, { name: string; type: string; value: string }>)[2]
    expect(action).toEqual({ name: "Open notes", type: "exec", value: "xdg-open https://example.com" })
    expect(getActionRows(result, "media")[1]?.[0]).toBe("2")
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test("builder rejects invalid or demo updates before touching YAML", () => {
  const { dir, path } = fixture()
  const bad = { name: "Open", type: "exec" as const, value: "" }
  try {
    const before = readFileSync(path, "utf8")
    expect(() => updateConfigAction(path, "default", "single", bad)).toThrow(/Enter a command/)
    expect(() => updateConfigAction(path, "default", "single", { ...bad, value: "xdg-open ." }, true)).toThrow(/read-only/)
    expect(() => updateConfigAction(path, "media", "notnumeric", { ...bad, value: "xdg-open ." })).toThrow(/numeric/)
    expect(readFileSync(path, "utf8")).toBe(before)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
