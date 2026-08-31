# tabletap

Turn your desk into a button pad using the laptop's built-in microphone. Tap the table, trigger actions.

## What it does

tabletap listens to your mic, detects percussive taps on the desk surface using bandpass filtering and adaptive thresholds, and maps them to keyboard shortcuts, app launches, or custom scripts.

```
tap → mic → bandpass filter → adaptive threshold → onset detection → pattern recognition → action
```

No extra hardware. No accelerometer required. Just your laptop mic and a hard desk surface.

## Quick Start

```bash
pip install .
tabletap init        # create config at ~/.config/tabletap/config.yaml
tabletap calibrate   # calibrate noise floor and slam threshold
tabletap start       # start the daemon
```

First run auto-calibrates. Tap the table 5-10 times during phase 2 so it learns your slam intensity.

## Commands

| Command | Description |
|---------|-------------|
| `tabletap start` | Start the daemon (auto-calibrates on first run) |
| `tabletap calibrate` | Recalibrate noise floor and threshold |
| `tabletap monitor` | Watch mic levels and spikes in real-time |
| `tabletap test -d 15` | Dry-run: detect taps without executing actions |
| `tabletap status` | Show current config |
| `tabletap init` | Create default config file |

## Tap Patterns

| Pattern | Trigger | Default Action |
|---------|---------|----------------|
| Single tap | 1 tap within 800ms | Launch Spotify |
| Double tap | 2 taps within 800ms | Open Gmail |
| Triple tap | 3 taps within 800ms | Open YouTube |
| Long press | 3+ rapid taps, hold 500ms-2s | Alt+Tab |
| Medium hold | 3+ rapid taps, hold 2s-4s | Volume +5% |
| Extended hold | 3+ rapid taps, hold 4s+ | Lock screen |
| Hold repeat | Every 500ms during sustained hold | Volume +2% |

## Configuration

Config lives at `~/.config/tabletap/config.yaml`:

```yaml
audio:
  sample_rate: 44100
  channels: 1
  chunk_size: 1024

filter:
  enabled: true
  low: 50
  high: 800

detection:
  min_gap_ms: 150
  rhythm_window_ms: 800
  long_press_ms: 500
  medium_hold_ms: 2000
  long_hold_ms: 4000

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
```

### Action Types

| Type | Description | Example |
|------|-------------|---------|
| `key` | Press a keyboard shortcut | `alt+tab`, `ctrl+shift+t`, `super+left` |
| `exec` | Run a command | `spotify`, `xdg-open https://...` |
| `script` | Run a bash script | `~/.local/bin/my-script.sh` |

### Action Categories

Use `tabletap start --category <name>` to switch between action presets:

```yaml
actions:
  productivity:
    1:
      name: "Email"
      type: exec
      value: "xdg-open https://mail.google.com"
    2:
      name: "Terminal"
      type: exec
      value: "alacritty"
    3:
      name: "VS Code"
      type: exec
      value: "code"

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

Single tap = action 1, double tap = action 2, triple tap = action 3.

## Systemd Service

```bash
cp tabletap.service ~/.config/systemd/user/
systemctl --user enable --now tabletap
```

### Config Reload (no restart)

```bash
kill -HUP $(cat ~/.cache/tabletap/daemon.pid)
```

## Features

- **Bandpass filter** — 50-800Hz, removes speech and background noise
- **Adaptive threshold** — auto-tunes based on ambient noise
- **Onset detection** — energy derivative, not just amplitude
- **Debounced silence** — prevents false long-press triggers
- **Async actions** — ThreadPoolExecutor, never blocks detection loop
- **Mic reconnection** — auto-reconnect with exponential backoff on disconnect
- **PID lock** — single-instance, no double-firing
- **Wayland support** — auto-detects wlrctl/ydotool/xdotool
- **SIGHUP reload** — change config without restart
- **Config validation** — warns on invalid values
- **Systemd hardening** — ProtectSystem, NoNewPrivileges, PrivateTmp
- **Desktop notifications** — notify-send on tap detection
- **53 tests** — full coverage with mocked PyAudio

## Requirements

- Python 3.10+
- Linux (tested on Arch with PipeWire)
- Built-in laptop microphone
- Hard desk surface (soft mats absorb vibrations)

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
