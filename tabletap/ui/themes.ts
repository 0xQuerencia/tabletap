/** Terminal-only visual palettes. Theme changes never affect detection or actions. */
export const PALETTES = {
  midnight: {
    bg: "#1d1c2b", pane: "#14131e", active: "#302e46",
    text: "#cdd0e9", dim: "#8d8fa9", border: "#3c3a53",
    accent: "#b8bafb", good: "#a9e9c3", amber: "#f1c482", pink: "#f2a7c3",
  },
  graphite: {
    bg: "#16191e", pane: "#20252c", active: "#303944",
    text: "#e0e5eb", dim: "#a4acb7", border: "#47505b",
    accent: "#8bd5e8", good: "#9fdaa3", amber: "#f3ca90", pink: "#eaa9ba",
  },
  nord: {
    bg: "#242933", pane: "#2e3440", active: "#434d60",
    text: "#eceff4", dim: "#b0bac9", border: "#4c566a",
    accent: "#88c0d0", good: "#a3be8c", amber: "#ebcb8b", pink: "#b48ead",
  },
  daylight: {
    bg: "#f3f3ee", pane: "#ffffff", active: "#e4e8f2",
    text: "#252c3a", dim: "#535d70", border: "#bec6d4",
    accent: "#4259a7", good: "#246647", amber: "#895300", pink: "#933d62",
  },
} as const

export type PaletteName = keyof typeof PALETTES
export type Palette = { [K in keyof typeof PALETTES.midnight]: string }
export const PALETTE_NAMES = Object.keys(PALETTES) as PaletteName[]

export function isPaletteName(value: unknown): value is PaletteName {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(PALETTES, value)
}

export function nextPalette(current: PaletteName): PaletteName {
  return PALETTE_NAMES[(PALETTE_NAMES.indexOf(current) + 1) % PALETTE_NAMES.length] || "midnight"
}
