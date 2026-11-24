import { test, expect } from "bun:test"
import { ACTION_TYPES, normalizeActionDraft, presetsFor, validateActionDraft, editableWorkflow, defaultStep, moveStep, stepLabel } from "./action-builder.ts"

test("builder always supplies supported types and deliberate, nonexecuting presets", () => {
  expect(ACTION_TYPES).toEqual(["exec", "key", "script", "builtin", "workflow", "launcher"])
  for (const type of ACTION_TYPES) {
    expect(presetsFor(type, ["default", "media"]).length).toBeGreaterThan(0)
    for (const preset of presetsFor(type, ["default", "media"])) {
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

test("built-in actions use known IDs rather than commands", () => {
  expect(validateActionDraft({name:"Mute", type:"builtin", value:"audio.mic_toggle"})).toBeNull()
  expect(validateActionDraft({name:"Bad", type:"builtin", value:"sh -c something"})).toMatch(/known built-in/)
})

test("workflow validates all steps before saving", () => {
  const draft = {name:"Flow", type:"workflow" as const, value:""}
  expect(validateActionDraft({...draft,value:JSON.stringify([{type:"wait",value:50},{type:"builtin",value:"media.next"}])})).toBeNull()
  expect(validateActionDraft({...draft,value:JSON.stringify([{type:"exec",value:"foo"},{type:"workflow",value:"[]"}])})).toMatch(/Unsupported/)
  expect(validateActionDraft({...draft,value:JSON.stringify([{type:"wait",value:10001}])})).toMatch(/Wait/)
})

test("visual workflow editing preserves order and does not mutate the original", () => {
  const steps = [defaultStep("builtin"), defaultStep("wait"), defaultStep("exec")]
  expect(stepLabel(steps[1]!)).toBe("Wait 500 ms")
  expect(moveStep(steps, 2, -1)).toEqual([steps[0], steps[2], steps[1]])
  expect(steps[1]?.type).toBe("wait")
  expect(moveStep(steps, 0, -1)).toEqual(steps)
  expect(editableWorkflow(JSON.stringify(steps))).toEqual(steps)
  expect(editableWorkflow("[]")).toEqual([])
  expect(() => editableWorkflow("invalid")).toThrow()
})


test("launcher presets use actual named profiles, never the default map", () => {
  expect(presetsFor("launcher", ["default", "study", "media"]).map(p => p.value)).toEqual(["study", "media"])
  expect(presetsFor("launcher")).toEqual([])
  expect(validateActionDraft({name:"Menu", type:"launcher", value:"default"})).toMatch(/named action profile/)
})


test("removed workflow blocks and application presets are rejected", () => {
  const draft = {name:"Action",type:"workflow" as const}
  for (const type of ["parallel","if"]) {
    expect(validateActionDraft({...draft,value:JSON.stringify([{type,value:[]}])})).toMatch(/Unsupported/)
  }
  for (const value of ["obs.record_toggle","home.light_toggle:light.desk","discord.mute:ctrl+m","vscode.build","x.stop"]) {
    expect(validateActionDraft({name:"Removed",type:"builtin",value})).toMatch(/known built-in/)
  }
  expect(validateActionDraft({name:"Notification",type:"builtin",value:"notify:Ready"})).toBeNull()
})

test("library searches across categories and named launchers",async()=>{
  const {searchPresets}=await import("./action-builder.ts")
  expect(searchPresets("media play").some(p=>p.value==="media.play_pause")).toBe(true)
  expect(searchPresets("launcher study",["default","study"])[0]?.value).toBe("study")
  expect(searchPresets("zzzzzzzz")).toEqual([])
})
