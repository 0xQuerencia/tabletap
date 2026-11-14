import { test, expect } from "bun:test"
import { ACTION_TYPES, normalizeActionDraft, presetsFor, validateActionDraft } from "./action-builder.ts"

test("builder always supplies 3 types and deliberate, nonexecuting presets", () => {
  expect(ACTION_TYPES).toEqual(["exec", "key", "script"])
  for (const type of ACTION_TYPES) {
    expect(presetsFor(type).length).toBeGreaterThan(0)
    for (const preset of presetsFor(type)) {
      expect(preset.type).toBe(type)
      expect(validateActionDraft(preset)).toBeNull()
    }
  }
})

test("normalizes older action mappings without a name", () => {
  expect(normalizeActionDraft({ type: "key", value: "alt+tab" }, "double"))
    .toEqual({ name: "double tap", type: "key", value: "alt+tab" })
  expect(normalizeActionDraft({ value: "xdg-open ." }, "single").type).toBe("exec")
})

test("validation rejects unsafe empty and malformed fields", () => {
  expect(validateActionDraft({ name: " ", type: "exec", value: "foot" })).toMatch(/name/)
  expect(validateActionDraft({ name: "Music", type: "key", value: "" })).toMatch(/command/)
  expect(validateActionDraft({ name: "Music", type: "key", value: "alt+ tab" })).toMatch(/Shortcuts/)
  expect(validateActionDraft({ name: "Bad\nname", type: "exec", value: "firefox" })).toMatch(/single line/)
  expect(validateActionDraft({ name: "Good", type: "exec", value: "firefox\nrm -rf" })).toMatch(/single line/)
  expect(validateActionDraft({ name: "Okay", type: "key", value: "ctrl+shift+t" })).toBeNull()
})
