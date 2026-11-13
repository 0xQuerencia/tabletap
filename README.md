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

1. Run `.venv/bin/tabletap` and press **c** to calibrate (stay quiet, then tap your desk).
2. Press **Space** to start in **safe preview mode**. Taps will be recognized without launching anything.
3. Select actions with **2**, and switch action profiles with **p**. `Enter` edits the selected action, `t` changes its type.
4. When the preview recognizes taps reliably, press **v** to arm live action execution. Press **Space** to stop.

You can change the microphone on Settings (**4**) using **m**. Use `.venv/bin/tabletap devices` to list input devices. All action and sensitivity edits preserve YAML comments, write a `config.yaml.bak` backup, and restart the listener if needed.

### Keyboard controls

| Key | Effect |
| --- | --- |
| `1`–`5`, `Tab`, `←`/`→` | Switch Home, Actions, Calibrate, Settings, Activity |
| `Space` | Start/stop the listener (preview-only by default) |
| `p` | Cycle default, productivity, media and other configured profiles |
| `v` | Toggle preview/live actions (explicitly arms command execution) |
| `c` | Calibrate microphone (quiet phase, then tapping phase); Esc cancels |
| `j`/`k`, `Enter` | Select/edit a mapped action on Actions |
| `t` | Cycle action type: exec, key, script |
| `m` | Cycle microphone inputs on Settings |
| `+`/`-` | Tune sensitivity on Settings |
| `/` | Command palette, e.g. `/start`, `/stop`, `/calibrate`, `/profile media` |
| `?`, `q` | Help, quit |

Action edits are persisted atomically without discarding YAML comments; the previous file is saved as `config.yaml.bak`. An active listener restarts after edits. The JSON-lines bridge is internal and can be invoked
with `tabletap bridge --dry-run`. It reports live levels and gesture/action
events, and executes user-configured commands only when dry-run is off.

**Security note:** actions run locally as your OS user. Review custom commands
and scripts before enabling listening. Tap gestures are not authentication.

**Current limitations:** This is a newly integrated implementation requiring
real microphone and terminal testing. Hold-duration gestures remain
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
| `tabletap service install` | Generate an optional headless systemd user unit using the active Python interpreter |
| `tabletap doctor` | Validate installation, microphone and shortcut tools |

## Tap patterns

| Pattern | Trigger | Default action |
|---------|---------|----------------|
| Single tap | 1 tap within 800ms | Launch Spotify |
| Double tap | 2 taps within 800ms | Open Gmail |
| Triple tap | 3 taps within 800ms | Open YouTube |
| Four taps | 4 taps within 800ms | Alt+Tab |
| Long press | 500ms-2s hold | Alt+Tab |
| Medium hold | 2s-4s hold | Volume +5% |
| Extended hold | 4s+ hold | Lock screen |
| Hold repeat | Every 500ms during sustained hold | Volume +2% |

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

```bash
cp tabletap.service ~/.config/systemd/user/
systemctl --user enable --now tabletap
```

Live config reload without restart:
```bash
kill -HUP $(cat ~/.cache/tabletap/daemon.pid)
```

## Features

- Bandpass filter (50-800Hz) isolates desk impacts from speech and ambient noise
- Adaptive threshold auto-tunes to your environment
- Onset detection via energy derivative for precise tap timing
- Debounced silence prevents false long-press triggers
- Async action execution via thread pool (never blocks detection)
- Mic reconnection with exponential backoff on disconnect
- PID lock prevents multiple daemon instances
- Wayland support (wtype/ydotool) and X11 support (xdotool)
- Desktop notifications via notify-send
- Config validation with warnings on invalid values
- SIGHUP reload config without restarting
- Systemd hardened (ProtectSystem, NoNewPrivileges, PrivateTmp)
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
