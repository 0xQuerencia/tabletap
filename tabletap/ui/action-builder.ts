/** Pure action-draft operations; presets are examples, never executed here. */
export const ACTION_TYPES = ["exec", "key", "script"] as const
export type ActionType = typeof ACTION_TYPES[number]
export type ActionDraft = { name: string; type: ActionType; value: string }
export type ActionPreset = ActionDraft & { label: string }

export const ACTION_PRESETS: readonly ActionPreset[] = [
  { label: "Open URL", name: "Open website", type: "exec", value: "xdg-open https://example.com" },
  { label: "File manager", name: "Open files", type: "exec", value: "xdg-open ." },
  { label: "Terminal (example)", name: "Open terminal", type: "exec", value: "foot" },
  { label: "Media play/pause", name: "Play or pause", type: "key", value: "XF86AudioPlay" },
  { label: "Next song", name: "Next song", type: "key", value: "XF86AudioNext" },
  { label: "Workspace 1", name: "Workspace 1", type: "key", value: "super+1" },
  { label: "My script (example)", name: "My script", type: "script", value: "~/.local/bin/my-script.sh" },
] as const

export function presetsFor(type: ActionType): readonly ActionPreset[] {
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
  if (value.length > 1024 || /[\r\n\x00]/.test(value)) return "Command must be a single line under 1024 characters"
  if (draft.type === "key" && !/^[a-z0-9_]+(\+[a-z0-9_]+)*$/i.test(value)) {
    return "Shortcuts use tokens joined by + (example: ctrl+shift+t)"
  }
  return null
}
