import { test, expect } from "bun:test"
import { PALETTES, PALETTE_NAMES, isPaletteName, nextPalette } from "./themes.ts"
import { suggestCommands, isKnownCommand } from "./commands.ts"

test("four complete, switchable themes with a stable default", () => {
  expect(PALETTE_NAMES).toEqual(["midnight", "graphite", "nord", "daylight"])
  const required = Object.keys(PALETTES.midnight)
  for (const value of Object.values(PALETTES)) {
    expect(Object.keys(value)).toEqual(required)
    for (const key of Object.values(value)) expect(key).toMatch(/^#[a-fA-F0-9]{6}$/)
  }
  expect(nextPalette("daylight")).toBe("midnight")
  expect(nextPalette("midnight")).toBe("graphite")
  expect(isPaletteName("nord")).toBe(true)
  expect(isPaletteName("__proto__")).toBe(false)
  expect(isPaletteName("fake")).toBe(false)
})

test("command palette prioritizes exact/prefix matches then descriptions", () => {
  expect(suggestCommands("theme")[0]?.command).toBe("theme")
  expect(suggestCommands("set")[0]?.command).toBe("settings")
  expect(suggestCommands("microphone").some(c => c.command === "calibrate")).toBe(true)
  expect(suggestCommands("not-a-command")).toEqual([])
  expect(isKnownCommand("panic")).toBe(true)
  expect(isKnownCommand("fake")).toBe(false)
})
