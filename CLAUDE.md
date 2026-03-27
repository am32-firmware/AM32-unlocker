# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AM32 ESC Unlocker - a Python/Tkinter GUI tool for unlocking flash protection on ARM Cortex-M0 ESCs and flashing AM32 bootloaders. Eliminates the need to solder SWD cables by providing a simple GUI-driven workflow using OpenOCD and debug adapters (ST-Link v2, CMSIS-DAP, JLink).

## Build Commands

**Install dependencies:**
```
pip install pyinstaller simpleaudio setuptools intelhex numpy
```

**Build standalone executable (via PyInstaller):**
```
python package/build.py
```

**Run directly:**
```
python esc_unlocker.py
```

CI builds for Linux/Windows/macOS are in `.github/workflows/`. There are no tests.

## Architecture

**Single-file application**: `esc_unlocker.py` is the entire GUI app (~323 lines). It spawns OpenOCD as a subprocess with the appropriate config files, monitors output for MCU detection ("Cortex-M") and completion ("Success!"), and provides audio/visual feedback.

**OpenOCD config files per MCU** (`MCU/{type}/`):
- `openocd-unlock.cfg` — disables flash protection, erases sectors, programs bootloader
- `openocd-lock.cfg` — re-enables flash protection
- These configs contain the actual flash manipulation logic (register writes, option byte changes)

**Supported MCUs**: F031, F051, G071 (+ 64K variant), G431, L431, E230, F415, F421 — each with different unlock procedures (STM32 vs Arterytek AT32).

**Bootloaders** (`bootloaders/`): Pre-compiled `.bin` files named `AM32_{MCU}_BOOTLOADER_{PIN}[_{VARIANT}]_V17.bin`. Selected based on MCU type, signal pin, and variant.

**Platform-specific OpenOCD** (`tools/{linux,macos,windows}/openocd/`): Bundled custom OpenOCD builds that include Arterytek AT32 support.

## Key Design Details

- Threading: OpenOCD runs in a background thread to keep the GUI responsive
- Resource paths: `get_resource_path()` handles both development and PyInstaller-bundled paths via `sys._MEIPASS`
- Windows paths require backslash escaping when passed to OpenOCD
- Audio feedback uses NumPy-generated waveforms via simpleaudio (searching=300Hz, found=880Hz, success=ascending tones)
- The bootloader path is passed to OpenOCD configs via a variable, which the `.cfg` files reference during `program` commands
