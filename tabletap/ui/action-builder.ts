/** Pure action-draft operations; presets are examples, never executed here. */
import { readFileSync } from "node:fs"

const NATIVE_ACTIONS: { id: string; label: string; argv?: string[]; parameter?: string; example?: string; adapter?: string }[] = JSON.parse(
  readFileSync(new URL("./native-actions.json", import.meta.url), "utf8"),
)
export const ACTION_TYPES = ["exec", "key", "script", "builtin", "workflow", "launcher"] as const
export type ActionType = typeof ACTION_TYPES[number]
export type ActionDraft = { name: string; type: ActionType; value: string }
export type ActionPreset = ActionDraft & { label: string }

export const ACTION_PRESETS: readonly ActionPreset[] = [
  { label: "Open files then pause media", name: "Files and media", type: "workflow", value: JSON.stringify([{type:"exec",value:"xdg-open ."},{type:"wait",value:500},{type:"builtin",value:"media.play_pause"}]) },
  ...NATIVE_ACTIONS.map((item): ActionPreset => ({ label: item.label, name: item.label, type: "builtin", value: item.parameter ? item.id + ":" + item.example : item.id })),
  { label: "Open URL", name: "Open website", type: "exec", value: "xdg-open https://example.com" },
  { label: "File manager", name: "Open files", type: "exec", value: "xdg-open ." },
  { label: "Terminal (example)", name: "Open terminal", type: "exec", value: "foot" },
  { label: "Media play/pause", name: "Play or pause", type: "key", value: "XF86AudioPlay" },
  { label: "Next song", name: "Next song", type: "key", value: "XF86AudioNext" },
  { label: "Workspace 1", name: "Workspace 1", type: "key", value: "super+1" },
  { label: "My script (example)", name: "My script", type: "script", value: "~/.local/bin/my-script.sh" },
] as const

export function presetsFor(type: ActionType, profiles: readonly string[] = []): readonly ActionPreset[] {
  if (type === "launcher") return profiles.filter(p => p !== "default").map(profile => ({
    type: "launcher", label: profile, name: "Open " + profile, value: profile,
  }))
  return ACTION_PRESETS.filter((item) => item.type === type)
}

export function normalizeActionDraft(action: {
  name?: string; type?: string; value?: string
}, gesture: string): ActionDraft {
  const type = ACTION_TYPES.find((item) => item === action.type) || "exec"
  return {
    name: action.name || gesture + " tap",
    type,
    value: action.value || "",
  }
}

function builtinProblem(value: string, parallel = false): string | null {
  const split = value.indexOf(":")
  const id = split < 0 ? value : value.slice(0, split)
  const arg = split < 0 ? "" : value.slice(split + 1)
  const item = NATIVE_ACTIONS.find(x => x.id === id)
  if (!item) return "Choose a known built-in action"
  if (parallel && item.adapter === "key") return "Keyboard actions cannot run in parallel"
  if (!item.parameter) return split < 0 ? null : "Action does not accept a parameter"
  if (!arg.trim() || arg.length > 100 || /[\x00-\x1f\x7f]/.test(arg)) return "Enter a " + item.parameter + " parameter"
  if (item.parameter === "shortcut" && !/^[a-z0-9_]+(\+[a-z0-9_]+)*$/i.test(arg)) return "Invalid configured shortcut"
  if (["light","switch","scene"].includes(item.parameter) && !new RegExp("^" + item.parameter + "\\.[a-z0-9_]+$").test(arg)) return "Expected a " + item.parameter + " entity ID"
  return null
}

export function validateActionDraft(draft: ActionDraft): string | null {
  if (!ACTION_TYPES.includes(draft.type)) return "Choose a supported action type"
  if (!draft.name.trim()) return "Enter a name for this action"
  if (draft.name.length > 100 || /[\r\n\x00-\x1f]/.test(draft.name)) return "Name must be a single line under 100 characters"
  const value = draft.value.trim()
  if (!value) return "Enter a command or shortcut before saving"
  if (draft.type === "workflow") return validateWorkflow(value)
  if (draft.type === "launcher" && (value === "default" || value.length > 100 || /[\r\n\x00-\x1f]/.test(value))) return "Choose a named action profile"
  if (value.length > 1024 || /[\r\n\x00]/.test(value)) return "Command must be a single line under 1024 characters"
  if (draft.type === "builtin") return builtinProblem(value)
  if (draft.type === "key" && !/^[a-z0-9_]+(\+[a-z0-9_]+)*$/i.test(value)) {
    return "Shortcuts use tokens joined by + (example: ctrl+shift+t)"
  }
  return null
}

export const STEP_TYPES = ["builtin", "exec", "key", "script", "wait", "parallel", "if"] as const
export type StepType = typeof STEP_TYPES[number]
export type WorkflowStep = { type: StepType; value: string | number | WorkflowStep[] | ConditionalBlock }
type ConditionalBlock = { condition: { type: string; value?: string }; then: WorkflowStep[]; else: WorkflowStep[] }

export function validateWorkflow(value: string): string | null {
  if (value.length > 8192) return "Workflow exceeds 8192 characters"
  let steps: unknown
  try { steps = JSON.parse(value) } catch { return "Workflow must be a JSON array of steps" }
  if (!Array.isArray(steps) || steps.length < 1 || steps.length > 20) return "Workflow requires 1–20 steps"
  let wait = 0, count = 0
  const validate = (step: any, nested = false, parallel = false): string | null => {
    if (++count > 20) return "Workflow requires at most 20 total steps, including blocks"
    if (!step || typeof step !== "object" || Object.keys(step).sort().join(",") !== "type,value") return "Invalid step"
    if (step.type === "wait") {
      if (typeof step.value !== "number" || !Number.isFinite(step.value) || step.value < 0 || step.value > 10000) return "Wait must be 0–10000 milliseconds"
      wait += step.value
    } else if (["exec","key","script","builtin"].includes(step.type)) {
      if (typeof step.value !== "string" || !step.value.trim() || step.value.length > 1024 || /[\r\n\x00]/.test(step.value)) return "Invalid action value"
      if (step.type === "builtin") { const issue = builtinProblem(step.value, parallel); if (issue) return issue }
      if (parallel && step.type === "key") return "Keyboard shortcuts cannot run in parallel"
    } else if (!nested && step.type === "parallel") {
      if (!Array.isArray(step.value) || step.value.length < 2 || step.value.length > 4) return "Parallel requires 2–4 independent actions"
      for (const child of step.value) { const issue = validate(child, true, true); if (issue) return issue }
    } else if (!nested && step.type === "if") {
      const block = step.value
      if (!block || typeof block !== "object" || Object.keys(block).sort().join(",") !== "condition,else,then") return "Invalid condition block"
      const c = block.condition
      if (!c || typeof c !== "object" || !["tool_available","hyprland","media_playing","microphone_muted","speakers_muted"].includes(c.type)) return "Unsupported condition"
      if (c.type === "tool_available") {
        if (Object.keys(c).sort().join(",") !== "type,value" || typeof c.value !== "string" || !/^[A-Za-z0-9_.+-]{1,100}$/.test(c.value)) return "Invalid tool name"
      } else if (Object.keys(c).join(",") !== "type") return "Unexpected condition value"
      for (const branch of ["then","else"]) {
        const list = block[branch]
        if (!Array.isArray(list) || list.length > 4 || (branch === "then" && !list.length)) return "Invalid " + branch + " branch"
        for (const child of list) { const issue = validate(child, true); if (issue) return issue }
      }
    } else return "Unsupported step type"
    return null
  }
  for (const step of steps) { const issue = validate(step); if (issue) return issue }
  return wait > 30000 ? "Total workflow wait must not exceed 30 seconds" : null
}

export function defaultStep(type: StepType): WorkflowStep {
  if (type === "wait") return {type, value: 500}
  if (type === "parallel") return {type, value: [{type:"exec",value:"xdg-open ."},{type:"exec",value:"xdg-open https://example.com"}]}
  if (type === "if") return {type, value: {condition:{type:"tool_available",value:"playerctl"},then:[{type:"builtin",value:"media.play_pause"}],else:[]}}
  return {type, value: presetsFor(type)[0]?.value || ""}
}

export function editableWorkflow(value: string): WorkflowStep[] {
  if (!value.trim() || value.trim() === "[]") return []
  const issue = validateWorkflow(value)
  if (issue) throw new Error(issue)
  return JSON.parse(value) as WorkflowStep[]
}

export function moveStep(steps: WorkflowStep[], index: number, offset: number): WorkflowStep[] {
  const target = index + offset
  if (index < 0 || index >= steps.length || target < 0 || target >= steps.length) return steps
  const next = steps.slice()
  const step = next.splice(index, 1)[0]!
  next.splice(target, 0, step)
  return next
}

export function stepLabel(step: WorkflowStep): string {
  if (step.type === "wait") return `Wait ${step.value} ms`
  if (step.type === "parallel") return "Parallel · " + (step.value as WorkflowStep[]).length + " actions"
  if (step.type === "if") return "If · " + (step.value as ConditionalBlock).condition.type
  if (step.type === "builtin") return NATIVE_ACTIONS.find(item => item.id === String(step.value).split(":")[0])?.label || String(step.value)
  return step.type + " · " + step.value
}
