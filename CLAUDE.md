# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AM32 ESC Unlocker - a Python/Tkinter GUI tool for unlocking flash protection on ARM Cortex-M0 ESCs and flashing AM32 bootloaders. Eliminates the need to solder SWD cables by providing a simple GUI-driven workflow using OpenOCD and debug adapters (ST-Link v2, CMSIS-DAP, JLink).

## Build Commands

**Install dependencies:**
```
pip install pyinstaller sounddevice setuptools intelhex numpy
```

**Build standalone executable (via PyInstaller):**
```
python package/build.py
```
`package/build.py` is the canonical build: it discovers every `MCU/*` directory and bundles `bootloaders/`, `probes/`, and only the *current* platform's `tools/{platform}` via `--add-data`, then copies the result to `esc_unlocker_{linux,windows,macos}`. The checked-in `esc_unlocker.spec` is a generated artifact (Linux-only datas) — don't hand-edit it; regenerate via `build.py`.

**Run directly:**
```
python esc_unlocker.py
```

CI builds for Linux/Windows/macOS are in `.github/workflows/`. There are no tests.

## Architecture

**Single-file application**: `esc_unlocker.py` is the entire GUI app (~320 lines). `run_openocd()` *loops*, re-launching OpenOCD as a subprocess until the operation succeeds or the user hits Stop (so the user can plug in / re-seat the probe while it keeps retrying). Per iteration it inspects the child's output:
- stderr containing `"Cortex-M"` → MCU found (orange LED, found tone)
- otherwise → still searching (red LED, searching tone)
- child **exit code 0** → success (green LED, ascending tones, loop ends). Success is detected via the return code, *not* by parsing the `"Success!"` string — the `.cfg` files `echo "Success!"` then `exit`, which is what produces the 0 return code.

Each OpenOCD invocation is `openocd -c 'set BOOTLOADER "<path>"' --file <probe>.cfg --file MCU/<base>/openocd-<op>.cfg`.

**OpenOCD config files per MCU** (`MCU/{type}/`):
- `openocd-unlock.cfg` — disables flash protection, erases sectors, programs bootloader
- `openocd-lock.cfg` — re-enables flash protection
- These configs contain the actual flash manipulation logic (register writes, option byte changes)

**Supported MCUs** (`MCU_LIST` in `esc_unlocker.py`): F031, F051, G071, G071_64K, G431, L431, E230, F415, F421 — each with different unlock procedures (STM32 vs Arterytek AT32 vs Geehy). The selected MCU string is split on `_`: the part before `_` is the directory/config base (`G071`), the suffix becomes a `k_tag` (`_64K`) appended to the bootloader filename. So a flash-size or feature variant is modeled as a `MCU_LIST` entry sharing one `MCU/<base>/` config dir, distinguished only by the bootloader file it picks.

**Bootloaders** (`bootloaders/`): Pre-compiled `.bin` files named `AM32_{base}_BOOTLOADER_{PIN}{k_tag}_V17.bin` (e.g. `AM32_G071_BOOTLOADER_PA6_64K_V17.bin`). Auto-selected from MCU base + signal pin + tag. A **custom bootloader** chosen via the Browse field overrides auto-selection; if it ends in `.hex` it is converted to a temp `.bin` using `intelhex.hex2bin` before flashing. The included bins are dev builds — the GUI points users at https://am32.ca/downloads for stable bootloaders via the custom field.

**Adding a new MCU**: create `MCU/<base>/openocd-{unlock,lock}.cfg` (the unlock cfg does the register/option-byte work, ends with `echo "Success!"` + `exit`; it reads the `BOOTLOADER` tcl var and falls back to a hardcoded default for standalone testing), add matching `bootloaders/AM32_<base>_BOOTLOADER_<PIN>[_<tag>]_V17.bin` for each pin, and add the name to `MCU_LIST`. `build.py` auto-discovers the new `MCU/` dir.

**Platform-specific OpenOCD** (`tools/{linux,macos,windows}/openocd/`): Bundled custom OpenOCD builds that include Arterytek AT32 support.

## Key Design Details

- Threading: OpenOCD runs in a background thread to keep the GUI responsive
- Resource paths: `get_resource_path()` handles both development and PyInstaller-bundled paths via `sys._MEIPASS`
- Windows paths require backslash escaping (`\\`) when passed to OpenOCD — done in `get_resource_path()` and for the temp hex→bin path
- Audio feedback uses NumPy-generated waveforms played via `sounddevice` (PortAudio). Audio is optional: the import is guarded (`have_audio`) so a missing backend disables sound instead of crashing, and the reason is shown in the output box. The OpenOCD thread only *appends* to a `pending_tones` list; an `after(10ms)` callback on the Tk main thread drains and plays it, keeping audio off the worker thread.
- The bootloader path is injected via `-c 'set BOOTLOADER "<path>"'`, which the `.cfg` files read for their `flash write_bank` / `verify_bank` commands
- Probe selection maps GUI labels to `probes/{stlink,jlink,cmsis-dap}.cfg`
- All activity is appended to `esc_unlocker.log` in the working directory
