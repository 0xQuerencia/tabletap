/** Searchable command reference for the existing slash palette. */
export const COMMANDS = [
  { command: "actions", description: "Open action mappings", shortcut: "2" },
  { command: "builder", description: "Build the selected action", shortcut: "B" },
  { command: "home", description: "Open overview", shortcut: "1" },
  { command: "settings", description: "Open settings", shortcut: "4" },
  { command: "activity", description: "Open recent activity", shortcut: "5" },
  { command: "theme", description: "Cycle theme (or /theme nord)", shortcut: "Shift+T" },
  { command: "profile", description: "Switch profile (or /profile media)", shortcut: "P" },
  { command: "calibrate", description: "Start microphone calibration", shortcut: "C" },
  { command: "start", description: "Start safe preview listener", shortcut: "Space" },
  { command: "stop", description: "Stop microphone listener", shortcut: "Space" },
  { command: "safe", description: "Return to safe preview", shortcut: "V while live" },
  { command: "arm", description: "Request live authorization", shortcut: "V" },
  { command: "confirm", description: "Confirm live authorization", shortcut: "Y" },
  { command: "panic", description: "Stop listening immediately", shortcut: "X" },
  { command: "help", description: "Show shortcut reference", shortcut: "?" },
  { command: "quit", description: "Quit the application", shortcut: "Q" },
] as const

export function suggestCommands(input: string, limit = 6) {
  const query = input.trim().replace(/^[/:]/, "").toLowerCase()
  if (!query) return COMMANDS.slice(0, limit)
  return COMMANDS
    .map((item) => ({
      item,
      rank: item.command === query ? 0
        : item.command.startsWith(query) ? 1
        : item.description.toLowerCase().includes(query) ? 2
        : 3,
    }))
    .filter(({ rank }) => rank < 3)
    .sort((a, b) => a.rank - b.rank)
    .slice(0, limit)
    .map(({ item }) => item)
}

export function isKnownCommand(name: string): boolean {
  return COMMANDS.some((item) => item.command === name)
}
