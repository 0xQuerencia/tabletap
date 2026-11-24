# Release verification

## Automated gate

- Python tests on 3.12 and 3.14, TypeScript typecheck and Bun tests.
- Wheel and source distribution build, clean-wheel install, installed TUI PTY smoke.
- Fish-shell environment setup, unit tests for profile export/import and IPC authorization.
- Tag must match both package version declarations.

## Real desktop gate (required for stable)

Use a laptop with a built-in microphone; repeat on at least one other device/surface. Record only aggregate counts, not audio or personal commands.

- Setup and doctor on CachyOS/Hyprland and a second supported Linux desktop.
- Calibrate while quiet, speaking, typing and clicking normally, then intentional soft and normal taps.
- Run a 60-second work-noise audit in preview, and count 20 attempts for each enabled tap pattern. Record false activations and missed taps; adjust calibration if needed.
- Check device switching/unplug, per-desk calibration, candidate feedback and rollback.
- Verify single/parallel/conditional workflows using harmless actions, real mute/media state, launcher dismissal, and failed dependency reporting.
- Verify OBS and Home Assistant against test instances with user-provided credentials, Discord and VS Code shortcuts, and KDE/GNOME/Hyprland behavior where available.
- Attach the TUI to the service; exercise safe/arm/reload/stop, expiry, and panic stop. Ensure exiting an attached UI does not silently leave UI-owned live authorization active.
- Verify upgraded configuration and backup, profile pack review/import, and a fresh installation from the release wheel.

Do not describe synthesized audio tests as actual acoustic accuracy measurements. Do not publish a stable tag until this manual gate is complete. An RC can be published for testing, using the version-matched RC tag.
