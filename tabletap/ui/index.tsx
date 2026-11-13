import { createSignal, createMemo, For, Show, onCleanup, onMount } from "solid-js"
import { render, useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/solid"
import { TextAttributes, type InputRenderable } from "@opentui/core"
import { readFileSync, writeFileSync, mkdirSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, join } from "node:path"
import {
  actionFieldPath, getActionRows, getProfiles, readTableConfig, updateConfigField,
  type Action, type TableConfig,
} from "./config-store.ts"

type MicDevice = {
  index: number
  name: string
  default: boolean
  channels: number
  sample_rate: number
}

type BridgeMessage =
  | { type: "ready"; category: string; dry_run: boolean; threshold_db: number }
  | { type: "level"; db: number; threshold_db: number; spike: boolean }
  | { type: "gesture"; pattern: string; action: string; dispatched: boolean }
  | { type: "action_result"; pattern: string; status: "launched" | "failed"; message: string }
  | { type: "error"; message: string }
  | { type: "stopped" }
  | { type: "rejected"; reason: string }

const theme = {
  bg: "#1d1c2b",
  pane: "#14131e",
  active: "#302e46",
  text: "#cdd0e9",
  dim: "#8d8fa9",
  border: "#3c3a53",
  accent: "#b8bafb",
  good: "#a9e9c3",
  amber: "#f1c482",
  pink: "#f2a7c3",
}
const PAGES = ["Home", "Actions", "Calibrate", "Settings", "Activity"] as const
const PYTHON = process.env.TABLETAP_PYTHON || "python3"
const CONFIG = join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "tabletap", "config.yaml")
const PREFS = join(dirname(CONFIG), "tui.json")
const IS_DEMO = process.argv.includes("--demo")
const WAVE = "▁▂▃▄▅▆▇█"

function readConfig(): TableConfig {
  try {
    return readTableConfig(CONFIG)
  } catch {
    return { actions: {} }
  }
}
function loadProfile() {
  try {
    const saved = JSON.parse(readFileSync(PREFS, "utf8")) as { profile?: string }
    return saved.profile || "default"
  } catch {
    return "default"
  }
}
function saveProfile(profile: string) {
  if (IS_DEMO) return
  mkdirSync(dirname(PREFS), { recursive: true })
  writeFileSync(PREFS, JSON.stringify({ profile }) + "\n", { mode: 0o600 })
}
function truncate(text: string, width: number): string {
  if (text.length <= width) return text
  return text.slice(0, Math.max(0, width - 1)) + "…"
}
function timeNow() {
  return new Date().toLocaleTimeString("en-GB", { hour12: false })
}
function Bar(props: { level: number; width?: number }) {
  const width = props.width || 34
  return (
    <text fg={theme.accent}>
      {"▮".repeat(Math.max(0, Math.min(width, Math.round((props.level + 80) / 70 * width))))}
      <span style={{ fg: theme.border }}>{"▯".repeat(Math.max(0, width - Math.min(width, Math.round((props.level + 80) / 70 * width))))}</span>
    </text>
  )
}

function App() {
  const renderer = useRenderer()
  const dimensions = useTerminalDimensions()
  const [page, setPage] = createSignal(0)
  const [config, setConfig] = createSignal<TableConfig>(readConfig())
  const [profile, setProfile] = createSignal(loadProfile())
  const [state, setState] = createSignal(IS_DEMO ? "DEMO" : "STOPPED")
  const [preview, setPreview] = createSignal(true)
  const [level, setLevel] = createSignal(-80)
  const [threshold, setThreshold] = createSignal(-30)
  const [wave, setWave] = createSignal(Array(45).fill(0) as number[])
  const [events, setEvents] = createSignal<string[]>([])
  const [rejected, setRejected] = createSignal(0)
  const [notice, setNotice] = createSignal(IS_DEMO ? "Demo mode: no commands execute" : "Press Space for safe preview · c to calibrate")
  const [selected, setSelected] = createSignal(0)
  const [editing, setEditing] = createSignal(false)
  const [editText, setEditText] = createSignal("")
  const [commandOpen, setCommandOpen] = createSignal(false)
  const [commandText, setCommandText] = createSignal("")
  const [help, setHelp] = createSignal(false)
  const [calibrating, setCalibrating] = createSignal(false)
  const [micDevices, setMicDevices] = createSignal<MicDevice[]>([])
  const [calPhase, setCalPhase] = createSignal("ready")
  const [calProgress, setCalProgress] = createSignal(0)
  let editInput: InputRenderable | null = null
  let commandInput: InputRenderable | null = null
  let bridge: ReturnType<typeof Bun.spawn> | null = null
  let calibration: ReturnType<typeof Bun.spawn> | null = null
  let demoTimer: ReturnType<typeof setInterval> | null = null
  let calibrationCancelled = false
  let listenerRequest = 0

  const screens = createMemo(() => PAGES)
  const narrow = createMemo(() => dimensions().width < 85)
  const panelWidth = createMemo(() => Math.max(20, Math.min(dimensions().width - 8, 80)))
  const rows = createMemo(() => getActionRows(config(), profile()))
  const isListening = createMemo(() => state() === "LISTENING" || state() === "PREVIEW")
  const waveText = createMemo(() => wave().map((value) => WAVE[Math.max(0, Math.min(7, value))] || "▁").join(""))

  function addLog(entry: string) {
    setEvents((items) => [timeNow() + "  " + entry, ...items].slice(0, 70))
  }
  async function stopBridge(cancelPending = true) {
    if (cancelPending) listenerRequest++
    const old = bridge
    bridge = null
    if (old) {
      try {
        old.kill("SIGTERM")
        const finished = await Promise.race([
          old.exited.then(() => true),
          new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 1200)),
        ])
        if (!finished) old.kill("SIGKILL")
      } catch {
        // Process already terminated.
      }
    }
    if (!IS_DEMO && !bridge) setState("STOPPED")
  }
  function onMessage(m: BridgeMessage) {
    if (m.type === "ready") {
      setState(m.dry_run ? "PREVIEW" : "LISTENING")
      setThreshold(m.threshold_db)
      setNotice("Microphone active · profile: " + (m.category || "default"))
      addLog("Microphone connected")
    } else if (m.type === "level") {
      setLevel(m.db)
      setThreshold(m.threshold_db)
      const value = Math.max(0, Math.min(7, Math.round((m.db + 65) / 8)))
      setWave((old) => [...old.slice(1), value])
    } else if (m.type === "gesture") {
      addLog(m.pattern.toUpperCase() + "  →  " + m.action + (m.dispatched ? "" : " (preview)"))
      setNotice(m.pattern + " tap → " + m.action)
    } else if (m.type === "action_result") {
      const resultText = m.status === "failed"
        ? m.pattern.toUpperCase() + "  FAILED: " + m.message
        : m.pattern.toUpperCase() + "  command launched"
      addLog(resultText)
      setNotice(resultText)
    } else if (m.type === "rejected") {
      setRejected((v) => v + 1)
      if (rejected() % 10 === 1) addLog("Ignored noise: " + m.reason)
    } else if (m.type === "error") {
      setState("ERROR")
      setNotice(m.message)
      addLog("ERROR: " + m.message)
    }
  }
  async function receiveLines(proc: ReturnType<typeof Bun.spawn>) {
    if (!proc.stdout || typeof proc.stdout === "number") return
    const reader = proc.stdout.getReader()
    const decoder = new TextDecoder()
    let pending = ""
    try {
      while (true) {
        const chunk = await reader.read()
        if (chunk.done) break
        pending += decoder.decode(chunk.value, { stream: true })
        const parts = pending.split("\n")
        pending = parts.pop() || ""
        for (const line of parts) {
          if (bridge !== proc || !line.trim()) continue
          try {
            onMessage(JSON.parse(line) as BridgeMessage)
          } catch {
            addLog("Bridge output: " + truncate(line, 75))
          }
        }
      }
    } catch (error) {
      if (bridge === proc) setNotice("Bridge reader failed: " + String(error))
    }
  }
  async function startBridge() {
    if (IS_DEMO || calibrating()) return
    const ticket = ++listenerRequest
    await stopBridge(false)
    if (ticket !== listenerRequest) return
    try {
      readTableConfig(CONFIG)
    } catch (error) {
      setState("ERROR")
      setNotice("Invalid configuration: " + String(error))
      return
    }
    setState("STARTING")
    setNotice("Opening microphone…")
    const args = [PYTHON, "-u", "-m", "tabletap", "bridge"]
    if (profile() !== "default") args.push("--category", profile())
    if (preview()) args.push("--dry-run")
    try {
      const proc = Bun.spawn(args, { stdout: "pipe", stderr: "pipe", stdin: "ignore" })
      bridge = proc
      void receiveLines(proc)
      void proc.exited.then((code) => {
        if (bridge !== proc) return
        bridge = null
        if (state() !== "ERROR") {
          setState("STOPPED")
          setNotice("Listener exited (" + code + "). Press space to retry.")
        }
      })
      if (proc.stderr && typeof proc.stderr !== "number") {
        void (async () => {
          const output = await new Response(proc.stderr).text()
          if (output.trim() && bridge === proc) addLog("stderr: " + truncate(output.trim(), 120))
        })()
      }
    } catch (error) {
      setState("ERROR")
      setNotice("Unable to start bridge: " + String(error))
    }
  }
  async function toggleListener() {
    if (IS_DEMO) {
      setNotice("Demo mode: live microphone is intentionally disabled")
      return
    }
    if (isListening() || state() === "STARTING") await stopBridge()
    else await startBridge()
  }
  async function selectProfile() {
    const options = getProfiles(config())
    const next = options[(options.indexOf(profile()) + 1) % options.length] || "default"
    setProfile(next)
    setSelected(0)
    saveProfile(next)
    setNotice("Profile: " + next)
    if (isListening()) await startBridge()
  }
  function saveField(path: (string | number)[], value: string | number | boolean | null, label: string) {
    try {
      const updated = updateConfigField(CONFIG, path, value, IS_DEMO)
      setConfig(updated)
      setNotice("Saved " + label + " · original backed up as config.yaml.bak")
      addLog("Updated " + label)
      if (isListening()) void startBridge()
      return true
    } catch (error) {
      setNotice("Not saved: " + String(error))
      addLog("Config error: " + String(error))
      return false
    }
  }
  function updateActionValue() {
    const row = rows()[selected()]
    if (!row) return
    if (saveField(actionFieldPath(profile(), row[0], "value"), editText(),
                  profile() + "/" + row[0])) {
      editInput?.blur()
      setEditing(false)
    }
  }
  function changeActionType() {
    const row = rows()[selected()]
    if (!row) return
    const [key, action] = row
    const options: Action["type"][] = ["exec", "key", "script"]
    const nextType = options[(options.indexOf(action.type || "exec") + 1) % options.length] || "exec"
    saveField(actionFieldPath(profile(), key, "type"), nextType, profile() + "/" + key)
  }
  function editAction() {
    if (IS_DEMO) {
      setNotice("Demo is read-only. Run tabletap without --demo to edit actions.")
      return
    }
    const row = rows()[selected()]
    if (!row) return
    setEditText(row[1]?.value || "")
    setEditing(true)
    queueMicrotask(() => editInput?.focus())
  }
  async function refreshDevices() {
    try {
      const proc = Bun.spawn([PYTHON, "-m", "tabletap", "devices", "--json"], {
        stdout: "pipe", stderr: "ignore", stdin: "ignore",
      })
      const body = proc.stdout && typeof proc.stdout !== "number"
        ? await new Response(proc.stdout).text()
        : ""
      const status = await proc.exited
      if (status === 0) {
        const parsed: { devices?: MicDevice[] } = JSON.parse(body)
        setMicDevices(Array.isArray(parsed.devices) ? parsed.devices : [])
      }
    } catch {
      // Doctor provides detailed errors. The dashboard stays usable.
    }
  }
  function cycleMicrophone() {
    const devices = micDevices()
    if (devices.length === 0) {
      setNotice("No microphones discovered · run tabletap doctor")
      return
    }
    const choices: (number | null)[] = [null, ...devices.map((d) => d.index)]
    const current = config().audio?.device_index
    const choice = typeof current === "number" ? current : null
    const next = choices[(choices.indexOf(choice) + 1) % choices.length] ?? null
    const name = next === null ? "system default" :
      (devices.find((device) => device.index === next)?.name || "microphone " + next)
    saveField(["audio", "device_index"], next, "microphone: " + name)
  }
  function toggleFourTaps() {
    const enable = config().detection?.enable_four_taps !== true
    saveField(["detection", "enable_four_taps"], enable, enable ? "four taps enabled" : "four taps disabled")
  }
  function adjustThreshold(increase: number) {
    const old = Number(config().filter?.sensitivity_offset_db || 0)
    const next = Math.max(-30, Math.min(30, old + increase))
    saveField(["filter", "sensitivity_offset_db"], next, "sensitivity (" + next + " dB)")
  }
  async function calibrate() {
    if (IS_DEMO) {
      setNotice("Calibration requires a connected microphone; exit --demo")
      return
    }
    if (calibrating()) return
    await stopBridge()
    setCalibrating(true)
    calibrationCancelled = false
    setCalPhase("noise")
    setCalProgress(0)
    setState("CALIBRATING")
    setPage(2)
    setNotice("Calibration: stay quiet for the first phase.")
    let errorMessage = ""
    try {
      const proc = Bun.spawn([PYTHON, "-u", "-m", "tabletap", "bridge", "--calibrate"], {
        stdout: "pipe", stderr: "ignore", stdin: "ignore",
      })
      calibration = proc
      const consume = async () => {
        if (!proc.stdout || typeof proc.stdout === "number") return
        const reader = proc.stdout.getReader()
        const decoder = new TextDecoder()
        let pending = ""
        while (true) {
          const part = await reader.read()
          if (part.done) break
          pending += decoder.decode(part.value, { stream: true })
          const lines = pending.split("\n")
          pending = lines.pop() || ""
          for (const line of lines) {
            if (calibration !== proc || !line.trim()) continue
            let data: Record<string, unknown>
            try {
              data = JSON.parse(line)
            } catch {
              continue
            }
            if (data.type === "calibration_progress") {
              const phase = String(data.phase)
              setCalPhase(phase)
              setCalProgress(Math.max(0, Math.min(100, Math.round(
                Number(data.elapsed || 0) / Math.max(0.01, Number(data.duration || 5)) * 100,
              ))))
              if (typeof data.db === "number") setLevel(data.db)
              setNotice(phase === "noise" ? "Stay quiet while measuring room noise…" :
                phase === "work" ? "TYPE AND CLICK NORMALLY NOW." :
                phase === "tap" ? "TAP YOUR DESK 5–10 TIMES NOW." :
                "Get ready to tap your desk…")
            } else if (data.type === "calibration_done") {
              setConfig(readConfig())
              setThreshold(Number(data.threshold_db))
              setCalPhase("done")
              setCalProgress(100)
              addLog("Calibration completed")
              setNotice("Calibration saved. Press space to start listening.")
            } else if (data.type === "error") {
              errorMessage = String(data.message || "Unknown calibration error")
            }
          }
        }
      }
      const consumed = consume()
      const result = await proc.exited
      await consumed
      calibration = null
      if (result !== 0) {
        setCalPhase(calibrationCancelled ? "cancelled" : "failed")
        setNotice(calibrationCancelled ? "Calibration cancelled. Old settings preserved." :
                  "Calibration failed: " + (errorMessage || "microphone unavailable"))
      }
    } catch (error) {
      setCalPhase("failed")
      setNotice("Calibration failed: " + String(error))
    } finally {
      calibration = null
      setCalibrating(false)
      setState("STOPPED")
    }
  }
  function runCommand(value: string) {
    const [cmd, arg] = value.trim().replace(/^\//, "").split(/\s+/, 2)
    setCommandOpen(false)
    setCommandText("")
    if (cmd === "start") void startBridge()
    else if (cmd === "stop") void stopBridge()
    else if (cmd === "calibrate") void calibrate()
    else if (cmd === "preview") {
      if (IS_DEMO) {
        setNotice("Demo mode is always read-only and never executes actions")
      } else {
        setPreview((v) => !v)
        setNotice(preview() ? "Preview only · commands disabled" : "LIVE ACTIONS ARMED")
        if (isListening()) void startBridge()
      }
    } else if (cmd === "profile") {
      const options = getProfiles(config())
      if (arg && options.includes(arg)) {
        setProfile(arg)
        saveProfile(arg)
        if (isListening()) void startBridge()
      } else if (arg) setNotice("Unknown profile: " + arg + " · valid: " + options.join(", "))
      else void selectProfile()
    } else if (cmd === "help") setHelp(true)
    else if (cmd === "quit" || cmd === "exit") shutdown()
    else setNotice("Unknown command. Try /help.")
  }
  function shutdown() {
    if (demoTimer) clearInterval(demoTimer)
    if (calibration) calibration.kill()
    void stopBridge()
    renderer.destroy()
  }

  useKeyboard((key) => {
    if (calibrating() && key.name === "escape") {
      calibrationCancelled = true
      calibration?.kill("SIGTERM")
      setNotice("Cancelling calibration…")
      key.preventDefault()
      return
    }
    if (calibrating() && key.name !== "q" && !(key.ctrl && key.name === "c")) {
      // Prevent accidentally starting another mic listener mid-calibration.
      key.preventDefault()
      return
    }
    if (editing()) {
      if (key.name === "escape") {
        setEditing(false)
        key.preventDefault()
      } else if (key.name === "return" || key.name === "enter") {
        updateActionValue()
        key.preventDefault()
      }
      return
    }
    if (commandOpen()) {
      if (key.name === "escape") {
        setCommandOpen(false)
        key.preventDefault()
      } else if (key.name === "return" || key.name === "enter") {
        runCommand(commandText())
        key.preventDefault()
      }
      return
    }
    if (key.ctrl && key.name === "c") {
      key.preventDefault()
      shutdown()
      return
    }
    if (key.name === "q") shutdown()
    else if (key.name === "tab" || key.name === "right") setPage((v) => (v + 1) % PAGES.length)
    else if (key.name === "left") setPage((v) => (v + PAGES.length - 1) % PAGES.length)
    else if (key.name === "1" || key.name === "2" || key.name === "3" || key.name === "4" || key.name === "5")
      setPage(Number(key.name) - 1)
    else if (key.name === "space") void toggleListener()
    else if (key.name === "p") void selectProfile()
    else if (key.name === "v") {
      if (IS_DEMO) {
        setNotice("Demo mode is always read-only and cannot arm live actions")
      } else {
        const next = !preview()
        setPreview(next)
        setNotice(next ? "Safe preview enabled · commands will NOT execute" : "LIVE ACTIONS ARMED · configured commands can run")
        if (isListening()) void startBridge()
      }
    } else if (key.name === "c") void calibrate()
    else if (key.name === "?") setHelp((v) => !v)
    else if (key.name === "/" || key.name === ":") {
      setCommandOpen(true)
      setCommandText("")
      queueMicrotask(() => commandInput?.focus())
    } else if (page() === 1) {
      if (key.name === "up" || key.name === "k") setSelected((v) => Math.max(0, v - 1))
      if (key.name === "down" || key.name === "j") setSelected((v) => Math.min(rows().length - 1, v + 1))
      if (key.name === "return" || key.name === "enter" || key.name === "e") editAction()
      if (key.name === "t") changeActionType()
    } else if (page() === 3) {
      if (key.name === "+" || key.name === "=") adjustThreshold(2)
      if (key.name === "-") adjustThreshold(-2)
      if (key.name === "m") cycleMicrophone()
      if (key.name === "f") toggleFourTaps()
    }
  })

  onMount(() => {
    let current: TableConfig
    try {
      current = readTableConfig(CONFIG)
    } catch (error) {
      setState("ERROR")
      setNotice("Cannot load config: " + String(error))
      return
    }
    setConfig(current)
    void refreshDevices()
    if (!getProfiles(current).includes(profile())) setProfile("default")
    if (IS_DEMO) {
      setState("DEMO")
      let count = 0
      demoTimer = setInterval(() => {
        count++
        const db = -52 + Math.round(Math.sin(count / 2) * 7)
        setLevel(db)
        setWave((old) => [...old.slice(1), Math.max(0, Math.min(7, Math.round((db + 65) / 8)))])
        if (count % 22 === 0) {
          const sample = ["single", "double", "triple"][(count / 22) % 3] || "single"
          addLog(sample.toUpperCase() + " → example action (demo)")
        }
      }, 110)
    } else {
      // Listening can execute local scripts. Require an explicit Space press.
      setState("STOPPED")
      setNotice("Press Space to listen safely (preview only) · press v to arm live actions")
    }
  })
  onCleanup(() => {
    if (demoTimer) clearInterval(demoTimer)
    if (calibration) calibration.kill()
    void stopBridge()
  })

  return (
    <box flexDirection="column" width="100%" height="100%" backgroundColor={theme.bg} paddingX={2} paddingY={1}>
      <box flexDirection="row" justifyContent="space-between" paddingBottom={1}>
        <text fg={theme.accent} attributes={TextAttributes.BOLD}>◈  tabletap</text>
        <text fg={theme.dim}>{narrow() ? "v0.3" : "acoustic shortcuts  /  v0.4.0"}   <span style={{ fg: state() === "LISTENING" ? theme.good : theme.amber }}>● {state()}</span></text>
      </box>
      <box flexDirection="row" gap={3} paddingBottom={1} border={["bottom"]} borderColor={theme.border}>
        <Show when={!narrow()} fallback={<text fg={theme.accent}>Page {page() + 1}/5 · {screens()[page()]} · Tab next · ? help</text>}>
          <For each={screens()}>{(name, i) =>
            <text fg={page() === i() ? theme.accent : theme.dim}>
              {page() === i() ? "● " : "  "}{i() + 1} {name}
            </text>
          }</For>
        </Show>
      </box>
      <Show when={help()}>
        <box marginTop={1} paddingX={2} paddingY={1} border borderColor={theme.accent} backgroundColor={theme.pane}>
          <text fg={theme.accent}>KEYBOARD SHORTCUTS</text>
          <text fg={theme.text}>1–5 pages  ·  tab next  ·  space start/stop  ·  p profile  ·  v preview</text>
          <text fg={theme.text}>c calibrate  ·  / commands  ·  j/k select action  ·  enter edit  ·  t action type</text>
          <text fg={theme.text}>m microphone · f toggle 4 taps · +/- sensitivity · ? help · q quit</text>
        </box>
      </Show>
      <Show when={page() === 0}>
        <box flexGrow={1} justifyContent="center" alignItems="center" gap={1}>
          <Show when={!narrow()} fallback={<text fg={theme.accent} attributes={TextAttributes.BOLD}>◈  T A B L E T A P</text>}>
            <ascii_font text="tabletap" font="tiny" />
          </Show>
          <text fg={theme.dim}>tap your desk. trigger your workflow.</text>
          <Show when={config().detection?.noise_floor_db === undefined}>
            <text fg={theme.amber}>Not calibrated yet · press c and follow the two steps</text>
          </Show>
          <box width={panelWidth()} marginTop={2} paddingX={2} paddingY={1} backgroundColor={theme.pane} border={["left"]} borderColor={theme.accent} gap={1}>
            <box flexDirection="row" justifyContent="space-between">
              <text fg={theme.text} attributes={TextAttributes.BOLD}>{state() === "LISTENING" ? "● Listening for taps…" : state() === "PREVIEW" ? "◉ Listening (preview — actions disabled)" : "○ " + state()}</text>
              <text fg={theme.dim}>{profile()} profile</text>
            </box>
            <text fg={theme.accent}>{narrow() ? waveText().slice(-Math.max(10, dimensions().width - 14)) : waveText()}</text>
            <box flexDirection="row" justifyContent="space-between">
              <text fg={theme.dim}>mic {level()} dB  /  threshold {threshold().toFixed(1)} dB</text>
              <text fg={theme.dim}>{preview() ? "DRY RUN" : "LIVE ACTIONS"}</text>
            </box>
          </box>
          <box width={panelWidth()} marginTop={1} flexDirection={narrow() ? "column" : "row"} justifyContent="space-between" gap={2}>
            <box width={narrow() ? "100%" : "55%"} backgroundColor={theme.pane} paddingX={2} paddingY={1}>
              <text fg={theme.accent}>ACTIVE MAPPINGS</text>
              <For each={rows().slice(0, 4)}>{([key, action]) =>
                <text fg={theme.text}>{truncate(key.padEnd(11) + " → " + (action?.name || action?.value || "not assigned"), 37)}</text>
              }</For>
            </box>
            <box flexGrow={1} backgroundColor={theme.pane} paddingX={2} paddingY={1}>
              <text fg={theme.accent}>RECENT ACTIVITY</text>
              <For each={events().slice(0, 4)}>{(line) =>
                <text fg={theme.dim}>{truncate(line, 35)}</text>
              }</For>
              <Show when={events().length === 0}><text fg={theme.dim}>No gestures yet.</text></Show>
            </box>
          </box>
        </box>
      </Show>
      <Show when={page() === 1}>
        <box flexGrow={1} paddingX={2} paddingTop={2} gap={1}>
          <text fg={theme.accent} attributes={TextAttributes.BOLD}>ACTIONS</text>
          <text fg={theme.dim}>Profile: {profile()} · Press p to switch · j/k to select · Enter to edit · t to switch action type</text>
          <box border={["bottom"]} borderColor={theme.border} paddingBottom={1}>
            <text fg={theme.dim}>GESTURE             TYPE        COMMAND</text>
          </box>
          <For each={rows()}>{([pattern, action], i) =>
            <box backgroundColor={selected() === i() ? theme.active : "transparent"} paddingLeft={1} paddingY={0}>
              <text fg={selected() === i() ? theme.accent : theme.text}>
                {selected() === i() ? "› " : "  "}
                {(profile() === "default" ? pattern : ["", "single", "double", "triple", "quadruple"][Number(pattern)] || pattern).padEnd(18)}{String(action?.type || "exec").padEnd(12)}{truncate(action?.value || "", Math.max(8, dimensions().width - 44))}
              </text>
            </box>
          }</For>
          <Show when={editing()}>
            <box marginTop={1} backgroundColor={theme.pane} border borderColor={theme.accent} padding={1}>
              <text fg={theme.accent}>EDIT COMMAND · Enter save · Esc cancel</text>
              <input ref={(input) => { editInput = input }} focused value={editText()} onInput={setEditText}
                textColor={theme.text} focusedTextColor={theme.text} backgroundColor={theme.pane} />
            </box>
          </Show>
        </box>
      </Show>
      <Show when={page() === 2}>
        <box flexGrow={1} justifyContent="center" alignItems="center" gap={2}>
          <text fg={theme.accent} attributes={TextAttributes.BOLD}>CALIBRATE YOUR DESK</text>
          <text fg={theme.dim}>Three phases: quiet, normal typing/mousing, then desk taps. Esc cancels.</text>
          <box width={Math.max(22, Math.min(70, dimensions().width - 8))} padding={2} backgroundColor={theme.pane} border borderColor={theme.border} gap={1}>
            <text fg={theme.text}>01  Quiet room      ·  measure ambient noise</text>
            <text fg={theme.text}>02  Work normally   ·  type and click (learn what NOT to trigger)</text>
            <text fg={theme.text}>03  Tap surface     ·  learn deliberate desk knocks</text>
            <text fg={theme.text}>04  Save threshold  ·  require knocks louder than typing</text>
            <text fg={theme.dim}>Saved noise floor: {config().detection?.noise_floor_db ?? "not calibrated"} dB</text>
            <text fg={theme.dim}>Saved work peak:   {config().detection?.work_peak_db ?? "not calibrated"} dB</text>
            <text fg={theme.dim}>Saved tap peak:    {config().detection?.slam_peak_db ?? "not calibrated"} dB</text>
            <text fg={theme.dim}>Current threshold: {threshold()} dB</text>
            <text fg={theme.accent}>Phase: {calPhase().toUpperCase()}  {calProgress()}%</text>
            <text fg={theme.good}>{"━".repeat(Math.round(calProgress() / 5))}<span style={{ fg: theme.border }}>{"┄".repeat(20 - Math.round(calProgress() / 5))}</span></text>
          </box>
          <text fg={calibrating() ? theme.amber : theme.good}>{calibrating() ? (calPhase() === "tap" ? "● TAP YOUR DESK NOW — Esc to cancel" : calPhase() === "work" ? "● TYPE and CLICK like normal — Esc cancels" : "● Stay quiet until instructed — Esc to cancel") : "Press c to begin calibration"}</text>
        </box>
      </Show>
      <Show when={page() === 3}>
        <box flexGrow={1} paddingX={2} paddingTop={2} gap={2}>
          <text fg={theme.accent} attributes={TextAttributes.BOLD}>SETTINGS</text>
          <text fg={theme.dim}>Stored in {CONFIG}</text>
          <box backgroundColor={theme.pane} padding={2} gap={1}>
            <text fg={theme.text}>Microphone     {truncate(
              micDevices().find((dev) => dev.index === config().audio?.device_index)?.name ||
                (config().audio?.device_index === null || config().audio?.device_index === undefined
                  ? "System default" : "Device " + config().audio?.device_index),
              Math.max(12, dimensions().width - 22),
            )}</text>
            <text fg={theme.dim}>Press m to cycle microphone inputs ({micDevices().length} detected)</text>
            <text fg={theme.text}>Sampling rate  {String(config().audio?.sample_rate ?? 44100)} Hz</text>
            <text fg={theme.text}>Bandpass       {String(config().filter?.low ?? 50)} – {String(config().filter?.high ?? 800)} Hz</text>
            <text fg={theme.text}>Rhythm window  {config().detection?.rhythm_window_ms ?? 800} ms</text>
            <text fg={theme.text}>Four taps      {config().detection?.enable_four_taps === true ? "ENABLED" : "DISABLED (safer)"} · press f to toggle</text>
            <text fg={theme.dim}>Rejected noise candidates: {rejected()} (this session)</text>
            <text fg={theme.text}>Tap gap        {config().detection?.min_gap_ms ?? 150} ms</text>
            <text fg={theme.amber}>Threshold      {threshold().toFixed(1)} dB   (+/- tunes sensitivity)</text>
            <text fg={theme.dim}>Sensitivity offset {String(config().filter?.sensitivity_offset_db ?? 0)} dB</text>
            <Bar level={threshold()} />
          </box>
          <text fg={theme.dim}>Changes save atomically; previous YAML is backed up to config.yaml.bak.</text>
        </box>
      </Show>
      <Show when={page() === 4}>
        <box flexGrow={1} paddingX={2} paddingTop={2} gap={1}>
          <text fg={theme.accent} attributes={TextAttributes.BOLD}>ACTIVITY</text>
          <text fg={theme.dim}>Live gestures and bridge diagnostics; most recent first.</text>
          <scrollbox flexGrow={1} contentOptions={{ gap: 0 }}>
            <For each={events()}>{(entry) => <text fg={theme.text}>{entry}</text>}</For>
            <Show when={!events().length}><text fg={theme.dim}>Nothing recorded in this session.</text></Show>
          </scrollbox>
        </box>
      </Show>
      <Show when={commandOpen()}>
        <box marginTop={1} backgroundColor={theme.pane} border={["left"]} borderColor={theme.accent} paddingX={2} paddingY={1}>
          <text fg={theme.dim}>/start  /stop  /calibrate  /profile [name]  /preview  /help  /quit</text>
          <input ref={(input) => { commandInput = input }} focused value={commandText()} onInput={setCommandText}
            textColor={theme.text} focusedTextColor={theme.text} placeholder="Type a command…" />
        </box>
      </Show>
      <box paddingTop={1} border={["top"]} borderColor={theme.border} flexDirection="row" justifyContent="space-between">
        <text fg={theme.dim}>{truncate(notice(), Math.max(8, dimensions().width - (narrow() ? 10 : 67)))}</text>
        <Show when={!narrow()}>
          <text fg={theme.dim}>space <span style={{ fg: theme.text }}>start/stop</span>   / <span style={{ fg: theme.text }}>command</span>   ? <span style={{ fg: theme.text }}>help</span>   q <span style={{ fg: theme.text }}>quit</span></text>
        </Show>
      </box>
    </box>
  )
}

render(() => <App />, { targetFps: 30, exitOnCtrlC: false })
