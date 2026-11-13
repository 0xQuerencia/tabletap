import { test, expect } from "bun:test"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import {
  actionFieldPath, getActionRows, getProfiles, readTableConfig, updateConfigField,
} from "./config-store"

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
