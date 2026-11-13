# TableTap on Arch / CachyOS / Hyprland

TableTap is entirely local and has no desktop GUI. The OpenTUI dashboard
is rendered inside your terminal, while the built-in laptop mic produces
a short stream of audio levels for the Python gesture recognizer.

## 1. Install system dependencies

```bash
sudo pacman -S --needed python python-pip portaudio wtype xdg-utils
```

Install [Bun](https://bun.sh/docs/installation) if it is not already on your PATH.
A recent release is recommended; OpenTUI requires at least Bun 1.3.14.

`wtype` is the recommended Wayland shortcut backend because it uses the
compositor's virtual-keyboard protocol and typically avoids a privileged
`/dev/uinput` service. If your compositor does not support it, TableTap
falls back to `ydotool`, which requires an operational `ydotoold` daemon.
Run `tabletap doctor` to check what's installed.

## 2. Install TableTap

Use explicit virtual-environment binaries so the commands work in **Fish,
Bash or Zsh** without shell activation. They also avoid CachyOS/Arch's
externally managed system Python (PEP 668).

```console
git clone https://github.com/0xQuerencia/tabletap
cd tabletap
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/tabletap setup
.venv/bin/tabletap doctor
.venv/bin/tabletap tui --demo
```

If you already cloned TableTap and created `.venv`, **do not clone again**:
start at the `.venv/bin/python -m pip install .` command from inside the
repository.

To activate the environment instead, use **Fish**:
```fish
source .venv/bin/activate.fish
```

For **Bash or Zsh**, use `source .venv/bin/activate`.

If you see `case builtin not inside of switch`, you ran the Bash
activation script in Fish. If you see `externally-managed-environment`,
the virtual environment was not active and `pip` targeted system Python.
If `~/.local/bin/tabletap` reports `ModuleNotFoundError: tabletap`,
you have an older, broken executable on your PATH; invoke
`.venv/bin/tabletap` explicitly (or activate the environment) rather than
reinstalling system Python. **Never use `sudo pip` or
`--break-system-packages`.**

When the demo looks correct, run `.venv/bin/tabletap`. Press `c` to calibrate: keep quiet in phase 1, type/click normally in phase 2, then tap the desk in phase 3.
**Keep the room quiet in phase 1**, type on your keyboard and use your mouse
normally during phase 2 (negative examples), and tap 5–10 times in phase 3. Calibration saves local acoustic thresholds
in `~/.config/tabletap/config.yaml`.

On the Home screen, press `Space` to listen in **preview-only mode** (no commands executed). Verify each tap sequence, then press `v` when you explicitly want to arm live actions. You can switch profiles with
`p`, inspect activity with `5`, and quit with `q`.

## 3. Verify the microphone

```bash
tabletap doctor
tabletap devices  # list microphones and device indices
tabletap monitor
tabletap test -d 20
```

The last command prints detected patterns without executing actions. On TUI Settings (press `4`), press `m` to switch microphone sources and `+`/`-` to tune sensitivity. Calibration and action changes make a `config.yaml.bak` backup without deleting YAML comments.
Firm taps on a hard desk generally work better than light taps on a
thick desk mat.

For Wayland, you can independently test whether the compositor accepts
virtual-keyboard shortcuts:

```bash
wtype -M alt -k Tab -m alt
```

This switches windows. It is an end-to-end test of the shortcut backend,
not the acoustic detection system.

## 4. Configuration and privacy

The config is at `$XDG_CONFIG_HOME/tabletap/config.yaml`, or
`~/.config/tabletap/config.yaml` by default. TableTap does not upload
microphone audio; its terminal bridge sends levels and detected gesture
metadata locally between Python and Bun.

Action values can run executables or scripts **as your current user**.
Review every command in your config and do not map destructive commands
or sensitive actions to accidental gestures. There is no tap-based
authentication.

Hold gestures are experimental and disabled by default because
sustained physical pressure cannot be inferred reliably from a
microphone. Single/double/triple/four-tap rhythms are the supported
default interaction.

## 5. Troubleshooting

- **No microphone detected:** check the device and input permission in your
  PipeWire/desktop audio settings, then rerun `tabletap doctor`.
- **Taps are missed:** rerun calibration, use a harder surface, and adjust
  sensitivity with `+`/`-` on Settings.
- **False triggers:** calibrate in your normal room and increase the
  sensitivity offset (+ dB makes the event threshold higher).
- **Shortcuts fail on Wayland:** install `wtype` and verify the independent
  shortcut test above; `ydotool` is a fallback if `wtype` is unsupported.
- **OpenTUI doesn't start:** run `tabletap setup` and ensure `bun --version`
  works in the same shell.
- **Another TableTap process is listening:** stop the existing
  `tabletap start` service/session before launching the interactive TUI.


## 6. Optional always-on systemd user service

The default TUI starts **stopped and safe**, and lets you inspect taps
before arming commands. Background service mode is different: it can execute
configured commands whenever a pattern is detected. Enable it only after
you have tested the mic and verified your mappings.

```console
.venv/bin/tabletap service install
systemctl --user daemon-reload
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS
systemctl --user enable --now tabletap.service
```

The generated unit uses the Python interpreter that ran `tabletap`, so
it does not require a stale `~/.local/bin/tabletap` launcher, a hardcoded
display name, or system-wide `pip` installation.

Stop it before opening the interactive app:
`systemctl --user stop tabletap.service`.

To uninstall:
```console
systemctl --user disable --now tabletap.service
.venv/bin/tabletap service uninstall
systemctl --user daemon-reload
```


## False-positive troubleshooting

If random four-tap detections switch your windows while you're typing,
upgrade to v0.4 and recalibrate. Four-tap execution now requires opting in:
Settings (key `4`) → `f`. The acoustic gate rejects sustained noise
and bursts of five or more impacts instead of classifying them as four taps.

After calibration, press `Space` for safe preview. **Type and click normally
for 30 seconds without deliberate taps**. If a single/double/triple gesture
appears anyway, raise the sensitivity offset using `+` on Settings or
recalibrate in your normal working environment. Press `5` for Activity
and inspect rejected sound diagnostics.

If intentional desk taps fail during calibration, your keyboard/mouse and
desk tapping are too close in loudness for the current mic placement.
Use a harder tap surface or a closer microphone. Do not arm actions with
`v` until the safe preview stops falsely detecting ordinary work.
