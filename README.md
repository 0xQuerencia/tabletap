# tabletap

Turn your desk into a button pad using the laptop's built-in microphone. Tap the table, trigger actions.

## How it works

tabletap listens to your mic, filters out noise with a bandpass filter (50-800Hz), and detects percussive impacts using adaptive thresholds. Detected taps are classified by rhythm (single/double/triple) and hold duration (short/medium/long), then mapped to keyboard shortcuts, app launches, or custom scripts.

No extra hardware needed. Just your laptop mic and a hard desk surface.

## Quick start

```bash
pip install .
tabletap init          # create config at ~/.config/tabletap/config.yaml
tabletap calibrate     # calibrate noise floor and slam threshold
tabletap start         # start listening
```

First run auto-calibrates. Tap the table 5-10 times during phase 2 so it learns your slam intensity.

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

## Tap patterns

| Pattern | Trigger | Default action |
|---------|---------|----------------|
| Single tap | 1 tap within 800ms | Launch Spotify |
| Double tap | 2 taps within 800ms | Open Gmail |
| Triple tap | 3 taps within 800ms | Open YouTube |
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

Single tap = action 1, double tap = action 2, triple tap = action 3.

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
- Wayland support (wlrctl/ydotool) with X11 fallback (xdotool)
- Desktop notifications via notify-send
- Config validation with warnings on invalid values
- SIGHUP reload config without restarting
- Systemd hardened (ProtectSystem, NoNewPrivileges, PrivateTmp)
- 53 tests with mocked PyAudio (no hardware required)

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
