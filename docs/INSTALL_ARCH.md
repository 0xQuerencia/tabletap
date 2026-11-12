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

When the demo looks correct, run `.venv/bin/tabletap`. Press `c` to calibrate.
**Keep the room quiet for the first phase**, then tap 5–10 times when the
TUI shows **TAP YOUR DESK**. Calibration saves local acoustic thresholds
in `~/.config/tabletap/config.yaml`.

On the Home screen, use `v` to enable preview mode (listen without
performing actions), then press `Space` to start. Verify each tap
sequence before enabling live actions. You can switch profiles with
`p`, inspect activity with `5`, and quit with `q`.

## 3. Verify the microphone

```bash
tabletap doctor
tabletap monitor
tabletap test -d 20
```

The last command prints detected patterns without executing actions.
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
