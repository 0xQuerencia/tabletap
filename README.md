# tabletap

**Make your desk a programmable shortcut pad — from the terminal.**

TableTap now has a keyboard-first terminal interface built with **OpenTUI**,
the framework used by OpenCode's terminal application. The microphone engine
continues to run locally in Python; no desktop GUI, cloud account, or AI model
is needed. The [Rune](https://github.com/anomalyco/rune) project is a different
GPU-native graphical UI framework and is intentionally not used here.

## Run the terminal app

Requires Linux, Python 3.10+, a microphone, and Bun (1.3.14+; use the latest
stable release). Run these **shell-independent** commands (work in Fish, Bash,
Zsh, and other shells):

```console
git clone https://github.com/0xQuerencia/tabletap
cd tabletap
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/tabletap setup
.venv/bin/tabletap doctor
.venv/bin/tabletap tui --demo
```

Once the demo works, launch the real microphone UI with
`.venv/bin/tabletap`. This avoids globally managed Python installations
and any older `~/.local/bin/tabletap` launcher.

If you prefer activating the virtual environment first, the activation
script is **shell-specific**:

```fish
# Fish (CachyOS users with fish as their login shell)
source .venv/bin/activate.fish
```

```bash
# Bash / Zsh
source .venv/bin/activate
```

After successful activation, `python -m pip install .` and `tabletap`
will use the virtual environment. If `tabletap` still points to an old
global launcher, use `.venv/bin/tabletap` directly. Do not use
`sudo pip` or `--break-system-packages`.

Setup copies an editable YAML configuration to
`~/.config/tabletap/config.yaml` (or `$XDG_CONFIG_HOME/tabletap/config.yaml`).
You can also explicitly launch `tabletap tui`. See the [Arch/CachyOS/Hyprland installation guide](docs/INSTALL_ARCH.md) for audio permissions, Wayland shortcuts and verification.

Run `tabletap doctor` to check your microphone, Bun installation and keyboard tooling.

**Preview the interface without a microphone or executing actions:**

```bash
tabletap tui --demo
```

### First-time setup

1. Run `.venv/bin/tabletap` and press **c**. Phase 1: stay quiet; phase 2: **type and click normally**; phase 3: tap the desk 5–10 times. This teaches the microphone what must *not* trigger shortcuts.
2. Press **Space** to start in **safe preview mode**. Taps will be recognized without launching anything.
3. Select actions with **2**, and switch action profiles with **p**. `Enter` edits the selected action, `t` changes its type.
4. After a clean work-noise audit, press **v**, then **y** within 4 seconds to arm live actions for up to 10 minutes. Press **x** or **Esc** to panic-stop.

You can change the microphone on Settings (**4**) using **m**. Use `.venv/bin/tabletap devices` to list input devices. All action and sensitivity edits preserve YAML comments, write a `config.yaml.bak` backup, and restart the listener if needed.

### Keyboard controls

| Key | Effect |
| --- | --- |
| `1`–`5`, `Tab`, `←`/`→` | Switch Home, Actions, Calibrate, Settings, Activity |
| `Space` | Start/stop the listener (preview-only by default) |
| `p` | Cycle default, productivity, media and other configured profiles |
| `v`, then `y` | Request then confirm live actions; expires after 10 minutes |
| `x`, `Esc` | Panic-stop microphone listener and disarm action execution |
| `c` | Calibrate (quiet → normal work → desk taps); Esc cancels |
| `j`/`k`, `Enter` | Select/edit a mapped action on Actions |
| `t` | Cycle action type: exec, key, script |
| `m` | Cycle microphone inputs on Settings |
| `f` | Enable/disable four-tap detection on Settings (off by default) |
| `+`/`-` | Tune sensitivity on Settings |
| `/` | Command palette, e.g. `/start`, `/stop`, `/arm`, `/confirm`, `/safe`, `/panic`, `/profile media` |
| `?`, `q` | Help, quit |

Action edits are persisted atomically without discarding YAML comments; the previous file is saved as `config.yaml.bak`. An active listener restarts after edits. The JSON-lines bridge is internal and can be invoked
with `tabletap bridge --dry-run`. It reports live levels and gesture/action
events, and executes user-configured commands only when dry-run is off.

**Security note:** actions run locally as your OS user. Review custom commands
and scripts before enabling listening. Tap gestures are not authentication.

**Current limitations:** Distinguishing real desk taps from nearby typing needs
real microphone and terminal testing. If working noise is as loud as tapping,
calibration will refuse to save new settings rather than silently turn normal
keyboard clicks into actions. Hold-duration gestures remain
experimental, and accessibility/noise robustness varies with microphone,
table surface, and room conditions.

---

Turn your desk into a button pad using the laptop's built-in microphone. Tap the table, trigger actions.

## How it works

tabletap listens to your mic, filters out noise with a bandpass filter (50-800Hz), and detects percussive impacts using adaptive thresholds. Detected taps are classified by rhythm (single/double/triple/quadruple). Experimental hold recognition is off by default. Events are mapped to keyboard shortcuts, app launches, or custom scripts.

No extra hardware needed. Just your laptop mic and a hard desk surface.

## Background mode (optional)

The main OpenTUI application runs interactively and does **not** start a
background daemon automatically. If you want TableTap to listen after a
graphical login, install a user-scoped service generated with the exact
Python interpreter from your virtual environment:

```bash
.venv/bin/tabletap service install
systemctl --user daemon-reload
# On Hyprland: import your session variables before starting:
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS
systemctl --user enable --now tabletap.service
```

This mode **executes configured actions** instead of running the TUI's
safe-preview mode, so review your mappings before enabling it. Stop the
service before starting the TUI: `systemctl --user stop tabletap.service`.
To retire it, run `systemctl --user disable --now tabletap.service`, then
`.venv/bin/tabletap service uninstall` and
`systemctl --user daemon-reload`. The obsolete checked-in
`tabletap.service` template with hardcoded executable and display settings
has been replaced by this portable installer.

## Quick start

```console
.venv/bin/tabletap init          # create config at ~/.config/tabletap/config.yaml
.venv/bin/tabletap calibrate     # calibrate noise floor and tap threshold
.venv/bin/tabletap start         # start listening (headless)
```

The interactive TUI starts in a safe stopped state. Press `c` for guided calibration; `tabletap start` (headless daemon) auto-calibrates when no saved calibration is present.

## Commands

| Command | Description |
|---------|-------------|
| `tabletap start` | Start the daemon (auto-calibrates on first run) |
| `tabletap start --category productivity` | Start with a specific action category |
| `tabletap calibrate` | Recalibrate noise floor and slam threshold |
| `tabletap calibrate --no-save` | Dry-run calibration without saving |
| `tabletap monitor` | Watch mic levels and spikes in real-time |
| `tabletap test -d 15` | Dry-run mode: detect taps for 15s, no actions executed |
| `tabletap status` | Show current config |
| `tabletap devices` | List input microphones and their device indices |
| `tabletap devices --json` | Machine-readable microphone discovery |
| `tabletap audit -d 60` | Observe false positives while typing; strictly no actions and no recorded audio |
| `tabletap audit -d 60 --json` | Local, machine-readable audit summary |
| `tabletap service install` | Generate an optional headless systemd user unit using the active Python interpreter |
| `tabletap doctor` | Validate installation, microphone and shortcut tools |

## Tap patterns

| Pattern | Trigger | Default action |
|---------|---------|----------------|
| Single tap | 1 tap within 800ms | Launch Spotify |
| Double tap | 2 taps within 800ms | Open Gmail |
| Triple tap | 3 taps within 800ms | Open YouTube |
| Four taps | 4 taps within 800ms | **Disabled by default** (opt in with Settings `f`; existing Alt+Tab mapping is not armed) |

Hold-duration gestures have experimental mappings in the configuration but are **disabled by default** because acoustic input cannot reliably measure physical pressure.

## Configuration

Config lives at `~/.config/tabletap/config.yaml`:

```yaml
audio:
  device_index: null
  sample_rate: 44100
  channels: 1
  chunk_size: 1024

filter:
  enabled: true
  low: 50
  high: 800
  adaptive: true
  noise_alpha: 0.05
  peak_alpha: 0.1
  snr_gate_db: 6.0

detection:
  min_gap_ms: 150
  rhythm_window_ms: 800
  enable_four_taps: false
  enable_hold_gestures: false
  min_attack_db: 7.0
  max_impact_ms: 220
  long_press_ms: 500
  medium_hold_ms: 2000
  long_hold_ms: 4000
  hold_repeat_ms: 500

actions:
  single:
    type: exec
    value: "spotify"
  double:
    type: exec
    value: "xdg-open https://gmail.com"
  triple:
    type: exec
    value: "xdg-open https://youtube.com"
  long:
    type: key
    value: alt+tab
  medium:
    type: exec
    value: "pactl set-sink-volume @DEFAULT_SINK@ +5%"
  extended:
    type: exec
    value: "loginctl lock-session"
  repeat:
    type: exec
    value: "pactl set-sink-volume @DEFAULT_SINK@ +2%"

feedback:
  notifications: true
  notification_urgency: low
```

### Action types

| Type | Description | Example |
|------|-------------|---------|
| `key` | Press keyboard shortcut | `alt+tab`, `ctrl+shift+t`, `super+left` |
| `exec` | Run a command | `spotify`, `xdg-open https://...` |
| `script` | Run a bash script | `~/.local/bin/my-script.sh` |

### Action categories

Switch between preset action groups with `--category`:

```yaml
actions:
  productivity:
    1:
      name: "Email"
      type: exec
      value: "xdg-open https://mail.google.com"
    2:
      name: "Calendar"
      type: exec
      value: "xdg-open https://calendar.google.com"
    3:
      name: "Terminal"
      type: exec
      value: "alacritty"

  media:
    1:
      name: "Play/Pause"
      type: key
      value: "XF86AudioPlay"
    2:
      name: "Next Track"
      type: key
      value: "XF86AudioNext"
```

Single tap = action 1, double tap = action 2, triple tap = action 3, four taps = action 4.

## Systemd service

Use the optional **`tabletap service install`** command documented above. Do not copy an obsolete hardcoded service file; installation uses the active Python virtual environment and does not start the service automatically.


## Features

- Bandpass filter (50-800Hz) isolates desk impacts from speech and ambient noise
- Adaptive threshold with a calibration minimum learned from normal typing/mouse noise
- Sharp-onset/short-decay impact validation (filters slow/sustained sounds)
- More-than-four-hit bursts discarded instead of misclassified as four taps
- Async action execution via thread pool (never blocks detection)
- Mic reconnection with exponential backoff on disconnect
- PID lock prevents multiple daemon instances
- Wayland support (wtype/ydotool) and X11 support (xdotool)
- Desktop notifications via notify-send
- Config validation with warnings on invalid values
- SIGHUP reload config without restarting
- Optional user-scoped systemd unit generated for the active virtual environment (disabled until explicitly enabled)
- Automated tests with mocked and synthesized audio plus OpenTUI pseudo-terminal smoke tests

## Requirements

- Python 3.10+
- Linux (tested on Arch with PipeWire)
- Built-in laptop microphone
- Hard desk surface (soft mats absorb vibrations)

## Development

```console
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -v
```

## License

MIT


## Reducing accidental taps (v0.4)

The detector now accepts an impact only after a **sharp onset followed by a
quick decay**. Slow or sustained sounds are rejected. More than four acoustic
hits in a typing burst are discarded, not incorrectly treated as four taps.
**Four-tap actions are disabled by default**, including for existing configs:
press `4` → `f` only if you intentionally want to enable them.

Calibration now learns the sound of your normal typing and mouse clicks as
negative examples:

1. Press `c` in the interactive TUI; keep the room quiet for phase 1.
2. In phase 2, **type at your usual speed and click your mouse**, as you
   actually do while working. Do not tap the desk in this phase.
3. In phase 3, stop typing and make 5–10 deliberate table taps near your laptop.
4. Press `Space` to listen in safe preview. Test normal work for at least
   30 seconds, inspect the Activity tab and the rejected noise count.
5. If actual taps are missed, lower the sensitivity offset in Settings (`-`);
   if you still get accidental taps, raise it with `+` or recalibrate.
   Never enable live actions until the preview is reliable.

The saved minimum threshold remains in effect as ambient noise changes.
If your keyboard is as loud as the desk taps, calibration will say it
cannot confidently separate them. Try moving the microphone or tapping
a harder surface; acoustic software cannot guarantee zero false positives
when the source sounds are physically indistinguishable.

**Your existing configuration is preserved**; new calibration fields are
added without deleting comments, and the previous file is saved to
`~/.config/tabletap/config.yaml.bak`.

## Work-noise audit: prove that normal typing stays quiet

Before arming any shortcuts, you can test false positives **without ever
executing an action**:

```console
.venv/bin/tabletap audit --duration 60
```

**Type and click normally** for the whole interval; do not deliberately tap
the desk. TableTap runs the same acoustic bridge as the TUI but forces
`--dry-run`, counts unintended single/double/triple/four patterns, lists
rejected noise, and reports the microphone's maximum level and threshold
headroom. It records **no audio and no keys**, does not save a report by default,
and requires no network or Bun runtime. As with ordinary listening, TableTap
may create its initial configuration and a temporary single-listener lock. An already-running listener must be stopped
first; the existing PID lock prevents racing listeners.

A passing 60-second audit is useful evidence but not proof of zero false
positives. If it reports gestures, recalibrate (`c` in the TUI; type normally
during the middle phase), adjust the threshold, or move the mic and repeat
the audit before enabling real shortcuts.

Local, machine-readable results for your own debugging:

```console
.venv/bin/tabletap audit -d 60 --json
```

Exit codes: `0` = no detected false patterns, `1` = one or more unintended
patterns, `2` = cannot complete the audit (microphone or config error).

## Live-action safety guard (interactive TUI)

The TUI always starts in **safe preview**. Press `Space` to start the
microphone (dry-run), then `V` to request live actions. **Press `Y`
within 4 seconds** to confirm; merely holding or repeating `V` cannot
authorize commands. If you miss the window, it returns to preview.

Live authorization lasts **a maximum of 10 minutes** and then
automatically terminates the action-capable listener and starts safe preview
again. Pressing `V` while live disarms immediately. Press **`X` or
`Esc`** for a *panic stop* that immediately kills the TUI's listening
bridge; it cannot undo a command that was already launched. Switching
profiles, editing the config, stopping the listener, or beginning calibration
also disarms live mode. Authorization is **never saved** between launches.

From the command palette: `/arm` then `/confirm`, `/safe` to
switch to preview, and `/panic` to stop microphone listening.

**Scope:** This guard is for the interactive TUI. Explicitly enabling
`tabletap start` or the optional always-on systemd user service
runs commands without TUI arming; don't enable that service until your
work-noise audit is clean.

The 10-minute limit is enforced twice: by the TUI countdown **and**
independently inside the Python action-capable audio bridge. A frozen terminal
UI therefore cannot silently keep the bridge armed beyond its authorization.

## Speech/noise suppression (experimental)

The built-in low-frequency impact detector now also checks the **unfiltered**
microphone spectrum. High-frequency-rich bursts (often speech or ambient
noise) are vetoed, and the pending tap rhythm is cancelled for 400 ms.
No AI model, external library, online processing, audio recording, or new
background service is introduced.

Recalibrate (`c`) and **speak, type, and click normally in phase 2**,
then make intentional desk knocks in phase 3. Run `tabletap audit -d 60`
while *speaking* without intentional taps to check false positives.
The conservative broadband guard is on by default, including existing
configs. If it incorrectly rejects your actual desk impacts, set
`detection.broadband_guard: false` in the YAML and test in preview.

A single laptop microphone cannot perfectly identify the source of a
sound, especially when speech and desk taps overlap spectrally. This
heuristic should be tested with real recordings from your machine before
claiming speech is reliably eliminated.

### TUI themes and command palette

The top bar contains only listening status; navigation lives in the tabs.
Press **Shift+T** from anywhere (or **h** in Settings) to cycle between
`midnight` (default), `graphite`, `nord`, and `daylight` themes.
The selected theme is saved locally in `~/.config/tabletap/tui.json`
alongside the selected action profile. Older profile preferences still work.
Themes affect only TUI appearance, not thresholds or gesture detection.

Press **Ctrl+K** (or **/**) to open a searchable command palette; type part of
a command or its description and choose with arrow keys and Enter. Commands
include `/actions`, `/settings`, `/activity`, `/theme nord`,
`/theme next`, and existing safe actions such as `/start`,
`/safe`, `/panic`. Press **?** for a shortcut reference.

### Interactive Action Builder (v0.7)

Select an action on the **Actions** page (**2**, then **J/K**) and press
**Enter** or **B** to open the built-in Action Builder. Choose a type
(`exec`, `key`, or `script`), cycle example presets, edit the name and
command, and inspect the **preview** without executing it. The examples
are not an app installer: commands such as `foot` or `xdg-open` must
already exist on your machine.

In the builder, **J/K** or **Tab/Shift+Tab** selects a field,
**Left/Right** cycles a type or example, and **Enter** opens editing for
Name/Command (or cycles a choice). **S** or **Ctrl+S** saves every field
in **one atomic YAML update** with a `config.yaml.bak` backup; **Esc**
cancels. Saving or opening the builder disarms live actions. In demo mode
the builder is read-only and cannot save changes. The palette command
`/builder` opens the builder for the selected action.

The default three-tap map and hardware detection remain unchanged.
