import { createSignal, createMemo, For, Show, onCleanup, onMount } from "solid-js"
import { render, useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/solid"
import { TextAttributes, type InputRenderable } from "@opentui/core"
import { readFileSync, writeFileSync, mkdirSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, join } from "node:path"
import {
  actionFieldPath, getActionRows, getProfiles, readTableConfig, updateConfigField, updateConfigAction,
  createActionProfile, clearAction, deleteActionProfile, type Action, type TableConfig,
} from "./config-store.ts"
import { SAFE_ARM, requestArm, confirmArm, expireArm, type ArmState } from "./safety.ts"
import { PALETTES, PALETTE_NAMES, isPaletteName, nextPalette, type Palette, type PaletteName } from "./themes.ts"
import { suggestCommands, isKnownCommand } from "./commands.ts"
import {
  ACTION_TYPES, normalizeActionDraft, presetsFor, validateActionDraft, searchPresets, type ActionDraft,
  STEP_TYPES, editableWorkflow, defaultStep, moveStep, stepLabel, validateWorkflow, type WorkflowStep,
} from "./action-builder.ts"

type MicDevice = {
  index: number
  name: string
  default: boolean
  channels: number
  sample_rate: number
}

type BridgeMessage =
  | { type: "ready"; category: string; dry_run: boolean; threshold_db: number; config_path?: string }
  | { type: "transition"; message: string }
  | { type: "level"; db: number; threshold_db: number; spike: boolean }
  | { type: "gesture"; pattern: string; action: string; dispatched: boolean }
  | { type: "action_result"; pattern: string; status: "launched" | "failed" | "dismissed"; message: string }
  | { type: "error"; message: string }
  | { type: "stopped" }
  | { type: "rejected"; reason: string; db?: number; threshold_db?: number }
  | { type: "near_miss"; db: number; threshold_db: number; attack_db: number }
  | { type: "impact_sample"; db: number; accepted: true }
  | { type: "live_expired"; message: string }

const [activeTheme, setActiveTheme] = createSignal<PaletteName>("midnight")
// Palette getters stay reactive in Solid JSX without repeating colors on every screen.
const theme = new Proxy(PALETTES.midnight as Palette, {
  get(_target, key: keyof Palette) { return PALETTES[activeTheme()][key] },
})
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
type Preferences = { profile?: string; theme?: PaletteName }
function readPreferences(): Preferences {
  try {
    const value: unknown = JSON.parse(readFileSync(PREFS, "utf8"))
    if (!value || typeof value !== "object" || Array.isArray(value)) return {}
    const record = value as Record<string, unknown>
    return {
      profile: typeof record.profile === "string" ? record.profile : undefined,
      theme: isPaletteName(record.theme) ? record.theme : undefined,
    }
  } catch { return {} }
}
function savePreferences(patch: Preferences) {
  if (IS_DEMO) return
  mkdirSync(dirname(PREFS), { recursive: true })
  writeFileSync(PREFS, JSON.stringify({ ...readPreferences(), ...patch }) + "\n", { mode: 0o600 })
}
function loadProfile() {
  return readPreferences().profile || "default"
}
function saveProfile(profile: string) {
  savePreferences({ profile })
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
  const [armState, setArmState] = createSignal<ArmState>(SAFE_ARM)
  const [attached, setAttached] = createSignal(false)
  const [remoteLive, setRemoteLive] = createSignal(false)
  const [remoteConfig, setRemoteConfig] = createSignal(CONFIG)
  const preview = createMemo(() => attached() ? !remoteLive() : armState().mode !== "live")
  const [level, setLevel] = createSignal(-80)
  const [threshold, setThreshold] = createSignal(-30)
  const [wave, setWave] = createSignal(Array(45).fill(0) as number[])
  const [events, setEvents] = createSignal<string[]>([])
  const [rejected, setRejected] = createSignal(0)
  const [candidate, setCandidate] = createSignal<{db:number; accepted:boolean} | null>(null)
  const [acousticBusy, setAcousticBusy] = createSignal(false)
  const [notice, setNotice] = createSignal(IS_DEMO ? "Demo mode: no commands execute" : "Press Space for safe preview · c to calibrate")
  const [selected, setSelected] = createSignal(0)
  const [editing, setEditing] = createSignal(false)
  const [editText, setEditText] = createSignal("")
  const [builderOpen, setBuilderOpen] = createSignal(false)
  const [builderTarget,setBuilderTarget] = createSignal<{profile:string;key:string}>({profile:"default",key:"single"})
  const [libraryOpen,setLibraryOpen] = createSignal(false)
  const [libraryQuery,setLibraryQuery] = createSignal("")
  const [libraryIndex,setLibraryIndex] = createSignal(0)
  const libraryMatches = createMemo(()=>searchPresets(libraryQuery(),getProfiles(config())))
  const libraryStart = createMemo(()=>Math.max(0,libraryIndex()-4))
  const [builderDraft, setBuilderDraft] = createSignal<ActionDraft>({ name: "", type: "exec", value: "" })
  const [builderField, setBuilderField] = createSignal(0)
  const [builderPreset, setBuilderPreset] = createSignal(-1)
  const [builderInputField, setBuilderInputField] = createSignal<"name" | "value">("value")
  const [builderError, setBuilderError] = createSignal("")
  const [workflowOpen, setWorkflowOpen] = createSignal(false)
  const [workflowSteps, setWorkflowSteps] = createSignal<WorkflowStep[]>([])
  const [workflowIndex, setWorkflowIndex] = createSignal(0)
  const workflowStart = createMemo(() => Math.max(0, Math.min(workflowIndex() - 2, workflowSteps().length - 5)))
  const workflowRows = createMemo(() => workflowSteps().slice(workflowStart(), workflowStart() + 5))
  const [commandOpen, setCommandOpen] = createSignal(false)
  const [commandText, setCommandText] = createSignal("")
  const [commandSelection, setCommandSelection] = createSignal(0)
  const commandMatches = createMemo(() => suggestCommands(commandText()))
  const [help, setHelp] = createSignal(false)
  const [calibrating, setCalibrating] = createSignal(false)
  const [micDevices, setMicDevices] = createSignal<MicDevice[]>([])
  const [calPhase, setCalPhase] = createSignal("ready")
  const [calProgress, setCalProgress] = createSignal(0)
  let libraryInput: InputRenderable | null = null
  let editInput: InputRenderable | null = null
  let commandInput: InputRenderable | null = null
  let bridge: ReturnType<typeof Bun.spawn> | null = null
  let calibration: ReturnType<typeof Bun.spawn> | null = null
  let demoTimer: ReturnType<typeof setInterval> | null = null
  let armTimer: ReturnType<typeof setTimeout> | null = null
  let calibrationCancelled = false
  let listenerRequest = 0

  const screens = createMemo(() => PAGES)
  const narrow = createMemo(() => dimensions().width < 85)
  const panelWidth = createMemo(() => Math.max(20, Math.min(dimensions().width - 8, 80)))
  const rows = createMemo(() => getActionRows(config(), profile()))
  const isListening = createMemo(() => state() === "LISTENING" || state() === "PREVIEW")
  const waveText = createMemo(() => wave().map((value) => WAVE[Math.max(0, Math.min(7, value))] || "▁").join(""))

  function switchTheme(name: PaletteName) {
    try {
      savePreferences({ theme: name })
      setActiveTheme(name)
      setNotice("Theme: " + name + " · Shift+T cycles themes")
    } catch (error) {
      setNotice("Theme not saved: " + String(error))
    }
  }
  function openPalette() {
    setCommandOpen(true)
    setCommandText("")
    setCommandSelection(0)
    queueMicrotask(() => commandInput?.focus())
  }
  function addLog(entry: string) {
    setEvents((items) => [timeNow() + "  " + entry, ...items].slice(0, 70))
  }
  function clearArmTimer() {
    if (armTimer) clearTimeout(armTimer)
    armTimer = null
  }
  function setSafety(next: ArmState, restart = true) {
    const before = armState()
    clearArmTimer()
    setArmState(next)
    if (next.mode !== "safe") {
      const expected = next
      armTimer = setTimeout(() => {
        if (armState().mode !== expected.mode || armState().expiresAt !== expected.expiresAt) return
        const expired = expireArm(expected, Date.now())
        if (expired.mode !== "safe") return
        setSafety(SAFE_ARM, false)
        if (expected.mode === "live") {
          addLog("Safety timeout: live actions automatically disabled")
          setNotice("LIVE WINDOW EXPIRED · returning to safe preview")
          if (isListening()) void startBridge(true)
        } else {
          setNotice("Live authorization request timed out · still in safe preview")
        }
      }, Math.max(0, next.expiresAt - Date.now()) + 20)
    }
    if (restart && isListening() && (before.mode === "live") !== (next.mode === "live")) {
      // Leaving LIVE should terminate the action-capable bridge immediately.
      void startBridge(before.mode === "live")
    }
  }
  function disarm(reason: string, restart = true) {
    const wasAuthorized = armState().mode !== "safe"
    setSafety(SAFE_ARM, restart)
    if (wasAuthorized) {
      setNotice(reason)
      addLog(reason)
    }
  }
  function requestLive() {
    if (IS_DEMO) {
      setNotice("Demo mode never executes actions")
      return
    }
    if (!isListening()) {
      setNotice("Start safe microphone preview with Space before arming")
      return
    }
    if (attached() && remoteLive()) {
      disarm("Background live actions disabled", false)
      void backgroundCommand("safe").then(result => setNotice(result?.error || "Disarm requested"))
      return
    }
    const next = requestArm(armState(), Date.now())
    setSafety(next)
    setNotice(next.mode === "confirm"
      ? "LIVE ACTIONS: press Y within 4 seconds to confirm (auto-disarms after 10 minutes)"
      : "Live authorization cancelled · safe preview")
  }
  function confirmLive() {
    if (IS_DEMO || !isListening()) return
    const next = confirmArm(armState(), Date.now())
    if (next.mode !== "live") {
      setSafety(SAFE_ARM)
      setNotice("No valid authorization pending · press V then Y")
      return
    }
    setSafety(next)
    setNotice("LIVE ACTIONS ARMED for up to 10 minutes · press X or Esc for panic stop")
    addLog("Explicitly armed live actions for 10 minutes")
  }
  async function panicStop() {
    setSafety(SAFE_ARM, false)
    if (await stopListening(true)) {
      setNotice("PANIC STOP · listener stopped, actions disarmed")
      addLog("PANIC STOP invoked")
    }
  }
  async function backgroundCommand(operation: string, args: string[] = []) {
    if (IS_DEMO) return null
    try {
      const proc = Bun.spawn([PYTHON, "-m", "tabletap", "control", operation, ...args], {
        stdout: "pipe", stderr: "ignore", stdin: "ignore",
      })
      const content = await new Response(proc.stdout).text()
      await proc.exited
      return JSON.parse(content) as {error?:string; accepted?:boolean; state?:{type:string; dry_run?:boolean; category?:string; config_path?:string}}
    } catch { return null }
  }
  async function ensureBackgroundSafe(): Promise<boolean> {
    if (!attached()) return true
    const result = await backgroundCommand("safe")
    if (!result?.accepted) {
      setNotice(result?.error || "Cannot disarm background listener")
      return false
    }
    return true
  }
  function canEditRemote() {
    if (attached() && remoteConfig() !== CONFIG) {
      setNotice("Background listener uses a different config; edit that file or stop the service")
      return false
    }
    return true
  }
  async function stopListening(immediate = false) {
    const remote = attached()
    if (remote) {
      const response = await backgroundCommand("stop")
      if (!response?.accepted) { setNotice(response?.error || "Unable to stop background listener"); return false }
      // The server cancels actions at acknowledgement, then releases the mic.
      for (let n = 0; n < 50; n++) {
        const status = await backgroundCommand("status")
        if (!status?.state) break
        if (n === 49) { setNotice("Background stop requested; listener is still closing"); return false }
        await new Promise(resolve => setTimeout(resolve, 100))
      }
    }
    await stopBridge(true, immediate)
    return true
  }
  async function stopBridge(cancelPending = true, immediate = false) {
    if (cancelPending) listenerRequest++
    const old = bridge
    bridge = null
    setAttached(false)
    setRemoteLive(false)
    setRemoteConfig(CONFIG)
    if (old) {
      try {
        old.kill(immediate ? "SIGKILL" : "SIGTERM")
        if (!immediate) {
          const finished = await Promise.race([
            old.exited.then(() => true),
            new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 1200)),
          ])
          if (!finished) old.kill("SIGKILL")
        }
      } catch {
        // Process already terminated.
      }
    }
    if (!IS_DEMO && !bridge) setState("STOPPED")
  }
  function onMessage(m: BridgeMessage) {
    if (m.type === "transition") {
      setState("STARTING")
      setNotice(m.message)
    } else if (m.type === "ready") {
      if (attached()) {
        setRemoteLive(!m.dry_run)
        setRemoteConfig(m.config_path || CONFIG)
        setProfile(m.category || "default")
        if (m.dry_run && armState().mode === "live") setSafety(SAFE_ARM, false)
      }
      if (!attached() && !m.dry_run && preview()) {
        void panicStop()
        setState("ERROR")
        setNotice("Safety mismatch: live bridge started without authorization; it was killed")
        return
      }
      setState(m.dry_run ? "PREVIEW" : "LISTENING")
      setThreshold(m.threshold_db)
      setNotice((attached() ? "Background listener connected" : "Microphone active") + " · profile: " + (m.category || "default"))
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
        : m.pattern.toUpperCase() + (m.status === "dismissed" ? "  menu dismissed" : "  command launched")
      addLog(resultText)
      setNotice(resultText)
    } else if (m.type === "live_expired") {
      setSafety(SAFE_ARM, false)
      addLog("Python bridge expired live authorization; switching to preview")
      setNotice("LIVE ACTIONS EXPIRED · restarting safe preview")
      if (!attached()) void startBridge(true)
    } else if (m.type === "impact_sample") {
      if (preview()) setCandidate({db:m.db, accepted:true})
    } else if (m.type === "near_miss") {
      if (preview()) setCandidate({db:m.db, accepted:false})
      addLog(`Possible soft tap: ${m.db} dB (${m.threshold_db} dB threshold) · preview and recalibrate if intentional`)
    } else if (m.type === "rejected") {
      setRejected((v) => v + 1)
      if (rejected() % 10 === 1) addLog("Ignored noise: " + m.reason + (m.db === undefined ? "" : ` · ${m.db} dB / limit ${m.threshold_db} dB`))
    } else if (m.type === "error") {
      setSafety(SAFE_ARM, false)
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
  async function startBridge(forceStop = false, attachOnly = false) {
    if (IS_DEMO || calibrating()) return
    if (acousticBusy()) return
    setCandidate(null)
    const ticket = ++listenerRequest
    const wasRemote = attached()
    const oldRemoteConfig = remoteConfig()
    await stopBridge(false, forceStop)
    if (ticket !== listenerRequest) return
    if (expireArm(armState(), Date.now()).mode === "safe" && armState().mode !== "safe") {
      setSafety(SAFE_ARM, false)
      addLog("Action authorization expired while restarting; preview mode restored")
    }
    try {
      readTableConfig(CONFIG)
    } catch (error) {
      setState("ERROR")
      setNotice("Invalid configuration: " + String(error))
      return
    }
    const remote = await backgroundCommand("status")
    if (ticket !== listenerRequest) return
    if (remote?.state) {
      if (wasRemote) {
        const live = armState().mode === "live"
        const operation = live ? "arm" : oldRemoteConfig === CONFIG ? "reload" : "safe"
        const params = live ? ["--seconds", String(Math.max(0.001, (armState().expiresAt - Date.now()) / 1000))] : operation === "reload" && profile() !== "default" ? ["--category", profile()] : []
        const response = await backgroundCommand(operation, params)
        if (!response?.accepted) { setSafety(SAFE_ARM, false); addLog(response?.error || "Background control failed") }
      }
      if (ticket !== listenerRequest) return
      setAttached(true)
      setState("STARTING")
      try {
        const proc = Bun.spawn([PYTHON, "-u", "-m", "tabletap", "control", "watch"], {stdout:"pipe",stderr:"ignore",stdin:"ignore"})
        bridge = proc
        void receiveLines(proc)
        void proc.exited.then(() => {
          if (bridge !== proc) return
          bridge = null
          setAttached(false)
          setRemoteLive(false)
          setSafety(SAFE_ARM, false)
          setState("STOPPED")
          setNotice("Background listener disconnected · Space starts preview")
        })
      } catch (error) {
        setAttached(false)
        setState("ERROR")
        setNotice("Cannot attach to background listener: " + String(error))
      }
      return
    }
    if (attachOnly) return
    setState("STARTING")
    setNotice("Opening microphone…")
    const args = [PYTHON, "-u", "-m", "tabletap", "bridge"]
    if (profile() !== "default") args.push("--category", profile())
    if (preview()) {
      args.push("--dry-run")
    } else {
      // Independent defense in the Python process: it stops executing when
      // this period elapses even if the UI freezes or is no longer responsive.
      const remainingSec = Math.max(0.001, (armState().expiresAt - Date.now()) / 1000)
      args.push("--max-live-seconds", String(remainingSec))
    }
    try {
      const proc = Bun.spawn(args, { stdout: "pipe", stderr: "pipe", stdin: "ignore" })
      bridge = proc
      void receiveLines(proc)
      void proc.exited.then((code) => {
        if (bridge !== proc) return
        bridge = null
        setSafety(SAFE_ARM, false)
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
    if (isListening() || state() === "STARTING") {
      disarm("Listener stopped · live actions disabled", false)
      await stopListening()
    } else {
      setSafety(SAFE_ARM, false)
      await startBridge()
    }
  }
  async function selectProfile() {
    if (!canEditRemote() || !await ensureBackgroundSafe()) return
    const options = getProfiles(config())
    const next = options[(options.indexOf(profile()) + 1) % options.length] || "default"
    disarm("Profile switched · live actions disabled", false)
    setProfile(next)
    setSelected(0)
    saveProfile(next)
    setNotice("Profile: " + next)
    if (isListening() || attached()) await startBridge()
  }
  async function saveField(path: (string | number)[], value: string | number | boolean | null, label: string) {
    if (!canEditRemote() || !await ensureBackgroundSafe()) return false
    try {
      const updated = updateConfigField(CONFIG, path, value, IS_DEMO)
      disarm("Configuration changed · live actions disabled", false)
      setConfig(updated)
      setNotice("Saved " + label + " · original backed up as config.yaml.bak")
      addLog("Updated " + label)
      if (isListening() || attached()) void startBridge()
      return true
    } catch (error) {
      setNotice("Not saved: " + String(error))
      addLog("Config error: " + String(error))
      return false
    }
  }
  function changeActionType() {
    const row = rows()[selected()]
    if (!row) return
    const [key, action] = row
    if (action.type === "builtin" || action.type === "workflow" || action.type === "launcher") { openBuilder(); return }
    const options: Action["type"][] = ["exec", "key", "script"]
    const nextType = options[(options.indexOf(action.type || "exec") + 1) % options.length] || "exec"
    saveField(actionFieldPath(profile(), key, "type"), nextType, profile() + "/" + key)
  }
  async function openBuilder(extra = false) {
    if (IS_DEMO) {
      setNotice("Demo is read-only. Run tabletap without --demo to build actions.")
      return
    }
    if (!canEditRemote() || !await ensureBackgroundSafe()) return
    const row = extra ? (()=>{
      if (profile()==="default") return undefined
      const keys=new Set(rows().map(([k])=>k))
      const key=Array.from({length:16},(_,i)=>String(i+5)).find(k=>!keys.has(k))
      return key ? [key,{}] as [string,Action] : undefined
    })() : rows()[selected()]
    if (!row) {
      setPage(1)
      setNotice("No action mapping selected. Configure a profile first.")
      return
    }
    // Editing cannot leave a live action-capable listener armed.
    disarm("Action Builder opened · live commands disabled")
    setPage(1)
    setBuilderTarget({profile:profile(),key:row[0]})
    setBuilderDraft(normalizeActionDraft(row[1], row[0]))
    if (!row[1].value) openLibrary()
    setBuilderField(0)
    setWorkflowOpen(false)
    setBuilderPreset(-1)
    setBuilderError("")
    setBuilderOpen(true)
  }
  function openLibrary() {
    setLibraryQuery("")
    setLibraryIndex(0)
    setLibraryOpen(true)
    queueMicrotask(()=>libraryInput?.focus())
  }
  async function editProfiles(operation:string,name:string) {
    if (!canEditRemote() || !await ensureBackgroundSafe()) return
    try {
      disarm("Profile edited · live actions disabled",false)
      const next = operation==="delete" ? deleteActionProfile(CONFIG,name,IS_DEMO) : createActionProfile(CONFIG,name,operation==="clone"?profile():undefined,IS_DEMO)
      setConfig(next)
      setProfile(operation==="delete" ? (profile()===name?"default":profile()) : name)
      saveProfile(profile()); setSelected(0); setPage(1)
      setNotice("Profile "+operation+" complete · config backed up")
      if (isListening() || attached()) void startBridge()
    } catch(error) { setNotice(String(error)); if(isListening() || attached()) void startBridge() }
  }
  async function removeMapping() {
    const row=rows()[selected()]; if(!row?.[1].value) return
    if(!canEditRemote() || !await ensureBackgroundSafe()) return
    try {
      disarm("Mapping cleared · live actions disabled",false)
      setConfig(clearAction(CONFIG,profile(),row[0],IS_DEMO));setSelected(0)
      setNotice("Mapping cleared · previous config backed up")
      if(isListening() || attached()) void startBridge()
    } catch(error){setNotice(String(error));if(isListening() || attached()) void startBridge()}
  }
  function cycleBuilder(step: number) {
    if (builderField() === 0) {
      const draft = builderDraft()
      const current = ACTION_TYPES.indexOf(draft.type)
      const next = ACTION_TYPES[(current + step + ACTION_TYPES.length) % ACTION_TYPES.length] || "exec"
      setBuilderDraft({ ...draft, type: next, value: next === "workflow" ? "[]" : draft.type === "workflow" ? "" : draft.value })
      setBuilderPreset(-1)
    } else if (builderField() === 1) {
      const examples = presetsFor(builderDraft().type, getProfiles(config()))
      if (!examples.length) return
      const at = ((builderPreset() + step) % examples.length + examples.length) % examples.length
      const example = examples[at]
      if (!example) return
      setBuilderPreset(at)
      setBuilderDraft({ name: example.name, type: example.type, value: example.value })
    }
    setBuilderError("")
  }
  function openWorkflow() {
    try {
      setWorkflowSteps(editableWorkflow(builderDraft().value))
      setWorkflowIndex(0)
      setWorkflowOpen(true)
      setBuilderError("")
    } catch (error) {
      setBuilderError(String(error) + " · edit raw value to repair")
      startBuilderInput("value")
    }
  }
  function replaceWorkflowStep(step: WorkflowStep) {
    setWorkflowSteps(steps => steps.map((old, index) => index === workflowIndex() ? step : old))
    setBuilderError("")
  }
  function editWorkflowStep() {
    const step = workflowSteps()[workflowIndex()]
    if (!step) return
    setEditText(typeof step.value === "object" ? JSON.stringify(step.value) : String(step.value))
    setEditing(true)
    queueMicrotask(() => editInput?.focus())
  }
  function applyWorkflow() {
    const value = JSON.stringify(workflowSteps())
    const problem = validateWorkflow(value)
    if (problem) { setBuilderError(problem); return }
    setBuilderDraft(draft => ({...draft, value}))
    setBuilderPreset(-1)
    setBuilderError("")
    setWorkflowOpen(false)
  }
  function startBuilderInput(field: "name" | "value") {
    setBuilderInputField(field)
    setEditText(builderDraft()[field])
    setEditing(true)
    queueMicrotask(() => editInput?.focus())
  }
  function applyBuilderInput() {
    if (workflowOpen()) {
      const step = workflowSteps()[workflowIndex()]
      if (!step) return
      const raw = editText().trim()
      let value: WorkflowStep["value"] = step.type === "wait" && raw ? Number(raw) : raw
      if (step.type === "parallel" || step.type === "if") {
        try { value = JSON.parse(raw) } catch { setBuilderError("Invalid JSON block"); return }
      }
      const problem = validateWorkflow(JSON.stringify([{type: step.type, value}]))
      if (problem) { setBuilderError(problem); return }
      replaceWorkflowStep({type:step.type, value})
      editInput?.blur()
      setEditing(false)
      return
    }
    setBuilderDraft((draft) => ({ ...draft, [builderInputField()]: editText() }))
    setBuilderPreset(-1)
    setBuilderError("")
    editInput?.blur()
    setEditing(false)
  }
  async function saveBuilder() {
    if (!canEditRemote() || !await ensureBackgroundSafe()) return
    const target=builderTarget()
    const row=[target.key] as const
    if (!getProfiles(config()).includes(target.profile)) { setBuilderError("Selected profile no longer exists"); return }
    const issue = validateActionDraft(builderDraft()) || (builderDraft().type === "launcher" && !getProfiles(config()).filter(p => p !== "default").includes(builderDraft().value.trim()) ? "Choose an existing named profile" : null)
    if (issue) { setBuilderError(issue); return }
    try {
      const updated = updateConfigAction(CONFIG, target.profile, row[0], builderDraft(), IS_DEMO)
      disarm("Action updated · live commands disabled", false)
      setConfig(updated)
      setBuilderOpen(false)
      setNotice("Saved " + profile() + "/" + row[0] + " · one atomic update, original backed up")
      addLog("Builder saved " + profile() + "/" + row[0])
      if (isListening() || attached()) void startBridge()
    } catch (error) {
      setBuilderError(String(error))
    }
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
  async function acousticOperation(args: string[]) {
    if (IS_DEMO || acousticBusy() || calibrating()) return
    setAcousticBusy(true)
    try {
      disarm("Acoustic profile operation · live actions disabled", false)
      if (!canEditRemote() || !await stopListening()) return
      const proc = Bun.spawn([PYTHON, "-m", "tabletap", "acoustic", ...args], {
        stdout: "pipe", stderr: "ignore", stdin: "ignore",
      })
      const body = await new Response(proc.stdout).text()
      await proc.exited
      const result = JSON.parse(body)
      setConfig(readConfig())
      setCandidate(null)
      setNotice(result.error || result.message || "Acoustic settings updated")
      addLog(result.error || result.message || "Acoustic settings updated")
    } catch (error) {
      setNotice("Acoustic operation failed: " + String(error))
    } finally { setAcousticBusy(false) }
  }
  function labelCandidate(label: "tap" | "noise") {
    const sample = candidate()
    if (!sample || !preview()) { setNotice("Listen in safe preview and label the most recent impact"); return }
    void acousticOperation(["feedback", "--label", label, "--db", String(sample.db), ...(sample.accepted ? ["--accepted"] : [])])
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
    void acousticOperation(["device", next === null ? "default" : String(next)])
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
    if (calibrating() || acousticBusy()) return
    disarm("Calibration started · live actions disabled", false)
    if (!canEditRemote() || !await stopListening()) return
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
                phase === "work" ? "TYPE, SPEAK AND CLICK NORMALLY NOW." :
                phase === "tap" ? (config().calibration?.personalized ? "MAKE AT LEAST 6 SEPARATE SOFT AND NORMAL TAPS." : "TAP YOUR DESK 5–10 TIMES NOW.") :
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
    const [cmd, arg, extra] = value.trim().replace(/^\//, "").split(/\s+/, 3)
    setCommandOpen(false)
    setCommandText("")
    if (cmd === "start") {
      if (!isListening()) { setSafety(SAFE_ARM, false); void startBridge() }
      else setNotice("Listener already running")
    }
    else if (cmd === "stop") {
      disarm("Listener stopped · live actions disabled", false)
      void stopListening()
    }
    else if (cmd === "calibrate") void calibrate()
    else if (cmd === "acoustic") {
      if (arg === "use" && extra) void acousticOperation(["use", extra])
      else if (arg && ["list","propose","apply","rollback"].includes(arg)) void acousticOperation([arg])
      else setNotice("Try /acoustic use desk-name, list, propose, apply or rollback")
    }
    else if (cmd === "preview" || cmd === "safe") {
      disarm("Safe preview enabled · commands disabled")
      if (attached()) void ensureBackgroundSafe()
    }
    else if (cmd === "arm") requestLive()
    else if (cmd === "confirm") confirmLive()
    else if (cmd === "panic") void panicStop()
    else if (cmd === "profile") {
      const options = getProfiles(config())
      if (arg && extra && ["new","clone","delete"].includes(arg)) void editProfiles(arg,extra)
      else if (arg && options.includes(arg)) {
        void (async () => {
          if (!canEditRemote() || !await ensureBackgroundSafe()) return
          disarm("Profile switched · live actions disabled", false)
          setProfile(arg)
          saveProfile(arg)
          if (isListening() || attached()) void startBridge()
        })()
      } else if (arg) setNotice("Unknown profile: " + arg + " · valid: " + options.join(", "))
      else void selectProfile()
    } else if (cmd === "theme") {
      const name = arg?.toLowerCase()
      if (!name || name === "next") switchTheme(nextPalette(activeTheme()))
      else if (isPaletteName(name)) switchTheme(name)
      else setNotice("Unknown theme · choose: " + PALETTE_NAMES.join(", "))
    } else if (cmd === "home") setPage(0)
    else if (cmd === "actions") setPage(1)
    else if (cmd === "settings") setPage(3)
    else if (cmd === "activity") setPage(4)
    else if (cmd === "builder") openBuilder()
    else if (cmd === "help") setHelp(true)
    else if (cmd === "quit" || cmd === "exit") shutdown()
    else setNotice("Unknown command. Try /help.")
  }
  async function shutdown() {
    const ownedArm = armState().mode === "live"
    setSafety(SAFE_ARM, false)
    if (attached() && ownedArm) await ensureBackgroundSafe()
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
        editInput?.blur()
        setEditing(false)
        key.preventDefault()
      } else if (key.name === "return" || key.name === "enter") {
        applyBuilderInput()
        key.preventDefault()
      }
      return
    }
    if (commandOpen()) {
      if (key.name === "escape") {
        setCommandOpen(false)
        key.preventDefault()
      } else if (key.name === "up" || (key.ctrl && key.name === "p")) {
        setCommandSelection((v) => Math.max(0, v - 1))
        key.preventDefault()
      } else if (key.name === "down" || (key.ctrl && key.name === "n")) {
        setCommandSelection((v) => Math.min(commandMatches().length - 1, v + 1))
        key.preventDefault()
      } else if (key.name === "return" || key.name === "enter") {
        const raw = commandText().trim().replace(/^[/:]/, "")
        if (raw) {
          const exact = isKnownCommand(raw.split(/\s+/, 1)[0] || "")
          const suggestion = commandMatches()[commandSelection()]
          runCommand(exact ? raw : suggestion?.command || raw)
        } else {
          setCommandOpen(false)
        }
        key.preventDefault()
      }
      return
    }
    if (key.ctrl && key.name === "c") {
      key.preventDefault()
      shutdown()
      return
    }
    if (libraryOpen()) {
      if(key.name==="escape"){setLibraryOpen(false);key.preventDefault()}
      else if(key.name==="up"){setLibraryIndex(i=>Math.max(0,i-1));key.preventDefault()}
      else if(key.name==="down"){setLibraryIndex(i=>Math.max(0,Math.min(libraryMatches().length-1,i+1)));key.preventDefault()}
      else if(key.name==="enter"||key.name==="return"){
        const item=libraryMatches()[libraryIndex()]
        if(item){setBuilderDraft({name:item.name,type:item.type,value:item.value});setBuilderPreset(-1);setLibraryOpen(false);setBuilderError("")}
        key.preventDefault()
      }
      return
    }
    if (workflowOpen()) {
      key.preventDefault()
      const steps = workflowSteps()
      const index = workflowIndex()
      const step = steps[index]
      if (key.name === "escape") {
        setWorkflowOpen(false)
        setBuilderError("")
      } else if (key.name === "s") {
        applyWorkflow()
      } else if (key.name === "a" && steps.length < 20) {
        setWorkflowSteps([...steps, defaultStep("builtin")])
        setWorkflowIndex(steps.length)
      } else if (key.name === "d" && step) {
        setWorkflowSteps(steps.filter((_, i) => i !== index))
        setWorkflowIndex(Math.max(0, Math.min(index, steps.length - 2)))
      } else if ((key.name === "up" || key.name === "down") && key.ctrl && step) {
        const offset = key.name === "up" ? -1 : 1
        const moved = moveStep(steps, index, offset)
        if (moved !== steps) {
          setWorkflowSteps(moved)
          setWorkflowIndex(index + offset)
        }
      } else if (key.name === "up" || key.name === "k") {
        setWorkflowIndex(Math.max(0, index - 1))
      } else if (key.name === "down" || key.name === "j") {
        setWorkflowIndex(Math.max(0, Math.min(steps.length - 1, index + 1)))
      } else if ((key.name === "left" || key.name === "right") && step) {
        const offset = key.name === "left" ? -1 : 1
        const kind = STEP_TYPES[(STEP_TYPES.indexOf(step.type) + offset + STEP_TYPES.length) % STEP_TYPES.length]!
        replaceWorkflowStep(defaultStep(kind))
      } else if (key.name === "p" && step && step.type !== "wait" && step.type !== "parallel" && step.type !== "if") {
        const presets = presetsFor(step.type)
        const at = presets.findIndex(preset => preset.value === step.value)
        const next = presets[(at + 1) % presets.length]
        if (next) replaceWorkflowStep({type:step.type, value:next.value})
      } else if ((key.name === "enter" || key.name === "return") && step) {
        editWorkflowStep()
      }
      return
    }
    if (builderOpen()) {
      key.preventDefault()
      if (key.name === "escape") {
        setBuilderOpen(false)
        setNotice("Action edit cancelled · original mapping kept")
      } else if ((key.ctrl && key.name === "s") || key.name === "s") {
        saveBuilder()
      } else if(key.name==="l"){openLibrary()
      } else if (key.name === "tab" || key.name === "j" || key.name === "down") {
        setBuilderField((v) => (v + (key.shift ? 3 : 1)) % 4)
      } else if (key.name === "k" || key.name === "up") {
        setBuilderField((v) => (v + 3) % 4)
      } else if (key.name === "left") {
        cycleBuilder(-1)
      } else if (key.name === "right") {
        cycleBuilder(1)
      } else if (key.name === "enter" || key.name === "return") {
        if (builderField() === 1) openLibrary()
        else if (builderField() === 0) cycleBuilder(1)
        else if (builderField() === 3 && builderDraft().type === "workflow") openWorkflow()
        else startBuilderInput(builderField() === 2 ? "name" : "value")
      }
      return
    }
    if (key.name === "x" || key.name === "escape") {
      key.preventDefault()
      void panicStop()
      return
    }
    if (key.name === "q") shutdown()
    else if (key.name === "tab" || key.name === "right") setPage((v) => (v + 1) % PAGES.length)
    else if (key.name === "left") setPage((v) => (v + PAGES.length - 1) % PAGES.length)
    else if (key.name === "1" || key.name === "2" || key.name === "3" || key.name === "4" || key.name === "5")
      setPage(Number(key.name) - 1)
    else if (key.name === "space") void toggleListener()
    else if (key.name === "p") void selectProfile()
    else if (key.name === "v") requestLive()
    else if (key.name === "y") confirmLive()
    else if (key.name === "c") void calibrate()
    else if (key.name === "?") setHelp((v) => !v)
    else if ((key.ctrl && key.name === "k") || key.name === "/" || key.name === ":") openPalette()
    else if ((key.shift && key.name === "t") || (page() === 3 && key.name === "h")) switchTheme(nextPalette(activeTheme()))
    else if (page() === 1) {
      if (key.name === "up" || key.name === "k") setSelected((v) => Math.max(0, v - 1))
      if (key.name === "down" || key.name === "j") setSelected((v) => Math.min(rows().length - 1, v + 1))
      if (key.name === "return" || key.name === "enter" || key.name === "e" || key.name === "b") openBuilder()
      if (key.name === "t") changeActionType()
      if (key.name === "a") void openBuilder(true)
      if (key.name === "d") void removeMapping()
    } else if (page() === 4) {
      if (key.name === "t") labelCandidate("tap")
      if (key.name === "n") labelCandidate("noise")
    } else if (page() === 3) {
      if (key.name === "+" || key.name === "=") adjustThreshold(2)
      if (key.name === "-") adjustThreshold(-2)
      if (key.name === "m") cycleMicrophone()
      if (key.name === "f") toggleFourTaps()
      if (key.name === "g") saveField(["calibration", "personalized"], config().calibration?.personalized !== true, "calibration mode (press c to recalibrate)")
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
    setActiveTheme(readPreferences().theme || "midnight")
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
      void startBridge(false, true)
    }
  })
  onCleanup(() => {
    if (demoTimer) clearInterval(demoTimer)
    clearArmTimer()
    if (calibration) calibration.kill()
    void stopBridge()
  })

  return (
    <box flexDirection="column" width="100%" height="100%" backgroundColor={theme.bg} paddingX={2} paddingY={1}>
      <box flexDirection="row" justifyContent="flex-end" paddingBottom={1}>
        <text fg={theme.dim}>{narrow() ? "v0.7.0" : "acoustic shortcuts  /  v0.7.0"}   <span style={{ fg: state() === "LISTENING" ? theme.good : theme.amber }}>● {state()}{attached() ? " · SERVICE" : ""}</span></text>
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
          <text fg={theme.text}>1–5 pages · tab next · space start/stop · p profile · v request live · y confirm</text>
          <text fg={theme.text}>c calibrate · / or Ctrl+K searchable commands · Shift+T cycle theme · h theme in Settings</text>
          <text fg={theme.text}>j/k select · Enter/B action builder · S save · Esc cancel · t quick type · X panic</text>
          <text fg={theme.text}>m microphone · f 4 taps · +/- threshold · x/Esc PANIC STOP · ? help · q quit</text>
        </box>
      </Show>
      <Show when={page() === 0}>
        <box flexGrow={1} justifyContent="center" alignItems="center" gap={1}>
          <Show when={!narrow()} fallback={<text fg={theme.accent} attributes={TextAttributes.BOLD}>◈  T A B L E T A P</text>}>
            <ascii_font text="tabletap" font="tiny" />
          </Show>
          <text fg={theme.dim}>tap your desk. trigger your workflow.</text>
          <Show when={config().detection?.noise_floor_db === undefined}>
            <text fg={theme.amber}>Not calibrated yet · press c for quiet → typing → taps</text>
          </Show>
          <box width={panelWidth()} marginTop={2} paddingX={2} paddingY={1} backgroundColor={theme.pane} border={["left"]} borderColor={theme.accent} gap={1}>
            <box flexDirection="row" justifyContent="space-between">
              <text fg={theme.text} attributes={TextAttributes.BOLD}>{state() === "LISTENING" ? "● Listening for taps…" : state() === "PREVIEW" ? "◉ Listening (preview — actions disabled)" : "○ " + state()}</text>
              <text fg={theme.dim}>{profile()} profile</text>
            </box>
            <text fg={theme.accent}>{narrow() ? waveText().slice(-Math.max(10, dimensions().width - 14)) : waveText()}</text>
            <box flexDirection="row" justifyContent="space-between">
              <text fg={theme.dim}>mic {level()} dB  /  threshold {threshold().toFixed(1)} dB</text>
              <text fg={theme.dim}>{attached() ? (remoteLive() ? "BACKGROUND LIVE · X stops" : armState().mode === "confirm" ? "CONFIRM Y · 4s" : "BACKGROUND PREVIEW") : preview() ? (armState().mode === "confirm" ? "CONFIRM Y · 4s" : "DRY RUN") : "LIVE until " + new Date(armState().expiresAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</text>
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
          <text fg={theme.dim}>B edit · A add menu slot · D clear · /profile new|clone|delete NAME</text>
          <Show when={!builderOpen()}>
            <text fg={theme.dim}>Profile: {profile()} · P switch · J/K select · Enter/B build · T quick-cycle action type</text>
            <box border={["bottom"]} borderColor={theme.border} paddingBottom={1}>
              <text fg={theme.dim}>GESTURE             TYPE        ACTION</text>
            </box>
            <For each={rows()}>{([pattern, action], i) =>
              <box backgroundColor={selected() === i() ? theme.active : "transparent"} paddingLeft={1} paddingY={0}>
                <text fg={selected() === i() ? theme.accent : theme.text}>
                  {selected() === i() ? "› " : "  "}
                  {(profile() === "default" ? pattern : ["", "single", "double", "triple", "quadruple"][Number(pattern)] || pattern).padEnd(18)}{String(action?.type || "exec").padEnd(12)}{truncate(action?.name || action?.value || "Not mapped", Math.max(8, dimensions().width - 44))}
                </text>
              </box>
            }</For>
          </Show>
          <Show when={builderOpen() && workflowOpen()}>
            <box backgroundColor={theme.pane} border={["left"]} borderColor={theme.accent} padding={1} gap={1}>
              <text fg={theme.accent} attributes={TextAttributes.BOLD}>WORKFLOW STEPS · {workflowSteps().length}/20</text>
              <text fg={theme.dim}>A add · D delete · J/K select · Ctrl+↑/↓ reorder</text>
              <text fg={theme.dim}>←/→ type · P preset · Enter edit (blocks use JSON) · S apply · Esc discard</text>
              <Show when={!workflowSteps().length}><text fg={theme.dim}>No steps yet. Press A to add one.</text></Show>
              <For each={workflowRows()}>{(step, i) =>
                <text fg={workflowIndex() === i() + workflowStart() ? theme.accent : theme.text}>
                  {workflowIndex() === i() + workflowStart() ? "› " : "  "}{i() + workflowStart() + 1}. {truncate(stepLabel(step), Math.max(8, dimensions().width - 12))}
                </text>
              }</For>
              <Show when={editing()}>
                <input ref={(input) => { editInput = input }} focused value={editText()} onInput={setEditText}
                  textColor={theme.text} focusedTextColor={theme.text} backgroundColor={theme.pane} />
              </Show>
              <Show when={builderError()}><text fg={theme.amber}>{builderError()}</text></Show>
              <text fg={theme.good}>Changes are only a draft until saved in Action Builder.</text>
            </box>
          </Show>
          <Show when={builderOpen() && libraryOpen()}>
            <box backgroundColor={theme.pane} padding={1} gap={1}>
              <text fg={theme.accent} attributes={TextAttributes.BOLD}>ACTION LIBRARY · {libraryMatches().length} matches</text>
              <input ref={(input)=>{libraryInput=input}} focused value={libraryQuery()} onInput={v=>{setLibraryQuery(v);setLibraryIndex(0)}} placeholder="Search media, OBS, shortcuts, apps…" textColor={theme.text} />
              <For each={libraryMatches().slice(libraryStart(),libraryStart()+6)}>{(item,i)=><text fg={libraryIndex()===libraryStart()+i()?theme.accent:theme.text}>{libraryIndex()===libraryStart()+i()?"› ":"  "}{truncate(item.label+" · "+item.type,Math.max(12,dimensions().width-12))}</text>}</For>
              <text fg={theme.dim}>↑/↓ choose · Enter use draft · Esc back · no commands run</text>
            </box>
          </Show>
          <Show when={builderOpen() && !workflowOpen() && !libraryOpen()}>
            <box backgroundColor={theme.pane} border={["left"]} borderColor={theme.accent} padding={2} gap={1}>
              <text fg={theme.accent} attributes={TextAttributes.BOLD}>INTERACTIVE ACTION BUILDER</text>
              <text fg={theme.dim}>{builderTarget().profile} / {builderTarget().key} · J/K/Tab fields · ←/→ choices · Enter select/edit</text>
              <text fg={builderField() === 0 ? theme.accent : theme.text}>
                {builderField() === 0 ? "› " : "  "}Type      {builderDraft().type.toUpperCase()}  {builderField() === 0 ? "← / →" : ""}
              </text>
              <text fg={builderField() === 1 ? theme.accent : theme.text}>
                {builderField() === 1 ? "› " : "  "}Preset    {builderPreset() < 0 ? "Custom (Enter / L to search library)" :
                  presetsFor(builderDraft().type, getProfiles(config()))[builderPreset()]?.label || "Custom"}
              </text>
              <text fg={builderField() === 2 ? theme.accent : theme.text}>
                {builderField() === 2 ? "› " : "  "}Name      {truncate(builderDraft().name, Math.max(12, dimensions().width - 24))}
              </text>
              <text fg={builderField() === 3 ? theme.accent : theme.text}>
                {builderField() === 3 ? "› " : "  "}{builderDraft().type === "workflow" ? "Steps     Enter to edit sequence" : (builderDraft().type === "launcher" ? "Profile   " : "Command   ") + truncate(builderDraft().value, Math.max(12, dimensions().width - 24))}
              </text>
              <Show when={editing()}>
                <box border={["top"]} borderColor={theme.border} paddingTop={1}>
                  <text fg={theme.accent}>EDIT {builderInputField().toUpperCase()} · Enter apply · Esc cancel</text>
                  <input ref={(input) => { editInput = input }} focused value={editText()} onInput={setEditText}
                    textColor={theme.text} focusedTextColor={theme.text} backgroundColor={theme.pane} />
                </box>
              </Show>
              <box marginTop={1} padding={1} backgroundColor={theme.active} gap={1}>
                <text fg={theme.accent}>PREVIEW · NO COMMANDS EXECUTED</text>
                <text fg={theme.text}>{builderDraft().type} → {truncate(builderDraft().value || "(unset)", Math.max(12, dimensions().width - 20))}</text>
                <text fg={theme.dim}>Templates are examples; required programs must be installed locally.</text>
              </box>
              <Show when={builderError()}>
                <text fg={theme.amber}>Cannot save: {builderError()}</text>
              </Show>
              <text fg={theme.good}>S / Ctrl+S save all fields atomically · Esc cancel · backup preserved</text>
            </box>
          </Show>
        </box>
      </Show>
      <Show when={page() === 2}>
        <box flexGrow={1} justifyContent="center" alignItems="center" gap={2}>
          <text fg={theme.accent} attributes={TextAttributes.BOLD}>CALIBRATE YOUR DESK</text>
          <text fg={theme.dim}>Three phases: quiet, normal typing/speaking/clicking, then desk taps. Esc cancels.</text>
          <box width={Math.max(22, Math.min(70, dimensions().width - 8))} padding={2} backgroundColor={theme.pane} border borderColor={theme.border} gap={1}>
            <text fg={theme.text}>01  Quiet room      ·  measure ambient noise</text>
            <text fg={theme.text}>02  Work normally   ·  type, speak and click (negative examples)</text>
            <text fg={theme.text}>03  Tap surface     ·  {config().calibration?.personalized ? "6+ separate soft and normal taps" : "learn deliberate desk knocks"}</text>
            <text fg={theme.text}>04  Save threshold  ·  require knocks louder than typing</text>
            <text fg={theme.dim}>Saved noise floor: {config().detection?.noise_floor_db ?? "not calibrated"} dB</text>
            <text fg={theme.dim}>Saved work peak:   {config().detection?.work_peak_db ?? "not calibrated"} dB</text>
            <text fg={theme.dim}>Saved tap reference: {config().detection?.slam_peak_db ?? "not calibrated"} dB</text>
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
            <text fg={theme.text}>Theme          {activeTheme()} · h or Shift+T to cycle</text>
            <text fg={theme.dim}>Available themes: {PALETTE_NAMES.join(" / ")} · /theme nord</text>
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
            <text fg={theme.text}>Calibration    {config().calibration?.personalized ? "Personalized" : "Standard"} · g to switch, c to recalibrate</text>
            <text fg={theme.text}>Desk profile   {config().calibration?.active_name || "default"}{config().calibration?.required ? " · calibration required" : ""}</text>
            <text fg={theme.dim}>/acoustic use NAME · list · propose · apply · rollback</text>
            <text fg={theme.dim}>Rejected noise candidates: {rejected()} (this session)</text>
            <text fg={theme.dim}>Work-noise QA: stop listening, then run tabletap audit -d 60</text>
            <text fg={theme.text}>Tap gap        {config().detection?.min_gap_ms ?? 150} ms</text>
            <text fg={theme.amber}>Threshold      {threshold().toFixed(1)} dB   (+/- tunes sensitivity)</text>
            <text fg={theme.dim}>Sensitivity offset {String(config().filter?.sensitivity_offset_db ?? 0)} dB</text>
            <text fg={theme.amber}>Live: V → Y to confirm; expires after 10 minutes. X stops immediately.</text>
            <Bar level={threshold()} />
          </box>
          <text fg={theme.dim}>Changes save atomically; previous YAML is backed up to config.yaml.bak.</text>
        </box>
      </Show>
      <Show when={page() === 4}>
        <box flexGrow={1} paddingX={2} paddingTop={2} gap={1}>
          <text fg={theme.accent} attributes={TextAttributes.BOLD}>ACTIVITY</text>
          <text fg={theme.dim}>Live gestures and bridge diagnostics; most recent first.</text>
          <text fg={theme.accent}>{candidate() ? `Latest ${candidate()!.accepted ? "detected" : "possible missed"} impact: ${candidate()!.db} dB · T tap / N noise` : "Safe preview: T/N label latest impact · /acoustic propose"}</text>
          <scrollbox flexGrow={1} contentOptions={{ gap: 0 }}>
            <For each={events()}>{(entry) => <text fg={theme.text}>{entry}</text>}</For>
            <Show when={!events().length}><text fg={theme.dim}>Nothing recorded in this session.</text></Show>
          </scrollbox>
        </box>
      </Show>
      <Show when={commandOpen()}>
        <box marginTop={1} backgroundColor={theme.pane} border={["left"]} borderColor={theme.accent} paddingX={2} paddingY={1}>
          <text fg={theme.accent}>COMMAND PALETTE · ↑/↓ choose · Enter run · Esc cancel</text>
          <input ref={(input) => { commandInput = input }} focused value={commandText()}
            onInput={(value) => { setCommandText(value); setCommandSelection(0) }}
            textColor={theme.text} focusedTextColor={theme.text} placeholder="Search commands or type /theme nord…" />
          <For each={commandMatches()}>{(item, index) =>
            <box backgroundColor={index() === commandSelection() ? theme.active : "transparent"} paddingX={1}>
              <text fg={index() === commandSelection() ? theme.accent : theme.dim}>
                {item.command.padEnd(12)} {item.description}  [{item.shortcut}]
              </text>
            </box>
          }</For>
          <Show when={commandMatches().length === 0}>
            <text fg={theme.dim}>No matches. Try /help or /theme nord.</text>
          </Show>
        </box>
      </Show>
      <box paddingTop={1} border={["top"]} borderColor={theme.border} flexDirection="row" justifyContent="space-between">
        <text fg={theme.dim}>{truncate(notice(), Math.max(8, dimensions().width - (narrow() ? 10 : 67)))}</text>
        <Show when={!narrow()}>
          <text fg={theme.dim}>Ctrl+K <span style={{ fg: theme.text }}>commands</span>   Shift+T <span style={{ fg: theme.text }}>theme</span>   v+y <span style={{ fg: theme.text }}>arm</span>   x <span style={{ fg: theme.amber }}>STOP</span>   ? <span style={{ fg: theme.text }}>help</span></text>
        </Show>
      </box>
    </box>
  )
}

render(() => <App />, { targetFps: 30, exitOnCtrlC: false })
