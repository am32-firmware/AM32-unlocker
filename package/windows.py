#!/usr/bin/env python3
import os
import subprocess
import sys

# Define the path to the MCU directory
MCUPath = "MCU"

# Initialize the options for PyInstaller
options = "--onefile --windowed --hidden-import=simpleaudio --add-data=tools/windows:tools/windows --add-data bootloaders:bootloaders"

# Get the list of subdirectories in the MCU directory
if os.path.exists(MCUPath):
    mcus = [name for name in os.listdir(MCUPath) if os.path.isdir(os.path.join(MCUPath, name))]

    # Loop through each MCU directory and add it to the PyInstaller options
    for m in mcus:
        mcu_dir = os.path.join(MCUPath, m)
        if os.path.isdir(mcu_dir):
            print(f"Adding MCU {m}")
            # Windows uses ';' instead of ':' to separate source and destination in PyInstaller --add-data
            options += f" --add-data \"{mcu_dir};{mcu_dir}\""
else:
    print(f"Error: The directory '{MCUPath}' does not exist.")
    sys.exit(1)

# Run PyInstaller with the accumulated options
try:
    subprocess.run(f"python -m PyInstaller {options} esc_unlocker.py", shell=True, check=True)
except subprocess.CalledProcessError as e:
    print(f"Error: PyInstaller failed with exit code {e.returncode}")
    sys.exit(1)
