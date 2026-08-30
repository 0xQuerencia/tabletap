# tabletap

Turn your laptop table into a button pad using the built-in microphone.

Tap the table surface and map patterns to keyboard shortcuts, app launches, or custom scripts.

## Install

```bash
pip install -e .
```

## Setup

```bash
tabletap init                  # create config at ~/.config/tabletap/config.yaml
tabletap calibrate             # calibrate noise floor for your mic
tabletap start                 # run the daemon
```

## Tap patterns

| Pattern | Default action |
|---------|---------------|
| 1 tap | Launch Spotify |
| 2 taps | Open Gmail |
| 3 taps | Open YouTube |
| Hold | Alt+Tab |

## Config

Edit `~/.config/tabletap/config.yaml`:

```yaml
actions:
  single:
    type: exec              # launch app
    value: "spotify"
  double:
    type: key               # keyboard shortcut
    value: ctrl+c
  triple:
    type: script            # run shell script
    value: "~/.config/tabletap/my_script.sh"
  long:
    type: exec
    value: "firefox https://reddit.com"
```

Action types:
- **exec** - run any terminal command
- **key** - press keyboard shortcut (e.g. `ctrl+c`, `alt+tab`, `XF86AudioPlay`)
- **script** - run a bash script file

## Commands

```bash
tabletap start               # run the daemon
tabletap calibrate           # listen for 10s and set threshold
tabletap monitor             # watch mic dB levels live
tabletap status              # show current config
tabletap init                # create default config
```

## Systemd (autostart)

```bash
cp tabletap.service ~/.config/systemd/user/
systemctl --user enable tabletap
systemctl --user start tabletap
```

## How it works

The laptop mic picks up vibrations through the table surface. tabletap monitors the audio level in real-time, detects transient spikes (taps), counts them within a rhythm window, and maps the count to actions.

- **Rhythm mode** - 1/2/3+ taps within 800ms window
- **Long press** - sustained pressure for 500ms+
- **Calibration** - sets threshold above your room's noise floor

## Requirements

- Linux with ALSA/PulseAudio/PipeWire
- Python 3.10+
- `pyaudio`, `numpy`, `pyyaml`
- `xdotool` (for keyboard shortcuts)

## License

MIT
