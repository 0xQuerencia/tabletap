/** Pure action-draft operations; presets are examples, never executed here. */
import { readFileSync } from "node:fs"

const NATIVE_ACTIONS: { id: string; label: string; argv: string[] }[] = JSON.parse(
  readFileSync(new URL("./native-actions.json", import.meta.url), "utf8"),
)
export const ACTION_TYPES = ["exec", "key", "script", "builtin", "workflow", "launcher"] as const
export type ActionType = typeof ACTION_TYPES[number]
export type ActionDraft = { name: string; type: ActionType; value: string }
export type ActionPreset = ActionDraft & { label: string }

export const ACTION_PRESETS: readonly ActionPreset[] = [
  { label: "Open files then pause media", name: "Files and media", type: "workflow", value: JSON.stringify([{type:"exec",value:"xdg-open ."},{type:"wait",value:500},{type:"builtin",value:"media.play_pause"}]) },
  ...NATIVE_ACTIONS.map((item): ActionPreset => ({ label: item.label, name: item.label, type: "builtin", value: item.id })),
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

export function validateActionDraft(draft: ActionDraft): string | null {
  if (!ACTION_TYPES.includes(draft.type)) return "Choose a supported action type"
  if (!draft.name.trim()) return "Enter a name for this action"
  if (draft.name.length > 100 || /[\r\n\x00-\x1f]/.test(draft.name)) return "Name must be a single line under 100 characters"
  const value = draft.value.trim()
  if (!value) return "Enter a command or shortcut before saving"
  if (draft.type === "workflow") return validateWorkflow(value)
  if (draft.type === "launcher" && (value === "default" || value.length > 100 || /[\r\n\x00-\x1f]/.test(value))) return "Choose a named action profile"
  if (value.length > 1024 || /[\r\n\x00]/.test(value)) return "Command must be a single line under 1024 characters"
  if (draft.type === "builtin" && !NATIVE_ACTIONS.some((item) => item.id === value)) return "Choose a known built-in action"
  if (draft.type === "key" && !/^[a-z0-9_]+(\+[a-z0-9_]+)*$/i.test(value)) {
    return "Shortcuts use tokens joined by + (example: ctrl+shift+t)"
  }
  return null
}

export function validateWorkflow(value: string): string | null {
  if (value.length > 8192) return "Workflow exceeds 8192 characters"
  let steps: unknown
  try { steps = JSON.parse(value) } catch { return "Workflow must be a JSON array of steps" }
  if (!Array.isArray(steps) || steps.length < 1 || steps.length > 20) return "Workflow requires 1–20 steps"
  let wait = 0
  for (const [index, step] of steps.entries()) {
    if (!step || typeof step !== "object" || Object.keys(step).sort().join(",") !== "type,value") return "Invalid step " + (index + 1)
    if (step.type === "wait") {
      if (typeof step.value !== "number" || !Number.isFinite(step.value) || step.value < 0 || step.value > 10000) return "Wait must be 0–10000 milliseconds"
      wait += step.value
    } else if (["exec","key","script","builtin"].includes(step.type)) {
      if (typeof step.value !== "string" || !step.value.trim() || step.value.length > 1024 || /[\r\n\x00]/.test(step.value)) return "Invalid action value at step " + (index + 1)
      if (step.type === "builtin" && !NATIVE_ACTIONS.some(item => item.id === step.value)) return "Unknown built-in at step " + (index + 1)
    } else return "Unsupported step type"
  }
  return wait > 30000 ? "Total workflow wait must not exceed 30 seconds" : null
}

export const STEP_TYPES = ["builtin", "exec", "key", "script", "wait"] as const
export type StepType = typeof STEP_TYPES[number]
export type WorkflowStep = { type: StepType; value: string | number }

export function defaultStep(type: StepType): WorkflowStep {
  if (type === "wait") return {type, value: 500}
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
  if (step.type === "builtin") return NATIVE_ACTIONS.find(item => item.id === step.value)?.label || String(step.value)
  return step.type + " · " + step.value
}
