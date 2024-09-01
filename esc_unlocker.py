#!/usr/bin/env python3
'''
UI for unlocking ESC MCUs for AM32 project
'''

PROBE_LIST = ["ST Link", "JLink", "CMSIS-DAP"]
MCU_LIST = ["F031", "F051", "G071", "G071_64K", "L431", "E230", "F415", "F421"]
PIN_LIST = ["PA2", "PB4","PA15"]

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
import subprocess
import os
import sys
import threading
import time
from datetime import datetime

import numpy as np
import simpleaudio as sa
import platform

is_windows = platform.system() == "Windows"

pending_tones = []

def play_tone(frequency, duration=0.1, volume=0.2):
    '''
    play a tone
    '''
    try:
        sample_rate = 44100  # samples per second
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        wave = np.sin(frequency * t * 2 * np.pi)
    
        audio = (wave * (32767 * volume)).astype(np.int16)
    
        play_obj = sa.play_buffer(audio, 1, 2, sample_rate)
        play_obj.wait_done()
    except Exception as e:
        print(e)
        pass


def play_searching():
    print("Searching")
    pending_tones.append((300, 0.1))

def play_found():
    print("Found")
    pending_tones.append((880, 0.1))

def play_success():
    pending_tones.append((600, 0.1))
    pending_tones.append((800, 0.1))
    pending_tones.append((1000, 0.1))


def log_message(msg):
    '''append to the log'''
    try:
        tstr = datetime.now().strftime("%c")
        f = open("esc_unlocker.log", "a")
        f.write(tstr + "\n")
        f.write(msg)
        f.write("\n")
        f.close()
    except Exception:
        pass

def get_resource_path(relative_path):
    """ Get the absolute path to a resource, works for development and PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    ret = os.path.join(base_path, relative_path)
    if is_windows:
        # cope with windows paths
        ret = ret.replace("\\", "\\\\")
    return ret

    
def get_openocd():
    '''get path to openocd'''
    if is_windows:
        openocd = "tools/windows/openocd/bin/openocd.exe"
    else:
        # assume Linux
        openocd = "tools/linux/openocd/bin/openocd"
    return get_resource_path(openocd)

def run_openocd():
    '''
    run openocd as a child, looping until running is False or success
    '''
    global running
    running = True
    mcu_type = mcu_var.get()
    probe_type = probe_var.get()
    if probe_type == "ST Link":
        probe_type = "stlink"
    elif probe_type == "JLink":
        probe_type = "jlink"
    elif probe_type == "CMSIS-DAP":
        probe_type = "cmsis-dap"

    pin = pin_var.get()
    if mode_var.get() == "Lock":
        op = "lock"
    else:
        op = "unlock"

    if mcu_type.find("_") != -1:
        mcu_base = mcu_type.split('_')[0]
        k_tag = "_" + mcu_type.split('_')[1]
    else:
        mcu_base = mcu_type
        k_tag = ''
    config_file = f"MCU/{mcu_base}/openocd-{op}.cfg"
    probe_file = get_resource_path(f"probes/{probe_type}.cfg")

    config_file = get_resource_path(config_file)
    custom_bootloader = bootloader_var.get()

    if custom_bootloader:
        bootloader = custom_bootloader
    else:
        bootloader = os.path.join("bootloaders", f"AM32_{mcu_base}_BOOTLOADER_{pin}{k_tag}_V12.bin")
        bootloader = get_resource_path(bootloader)

    log_message("Starting MCU %s PIN %s op %s" % (mcu_type, pin, op))

    print("Using config file '%s'" % config_file)
    print("Using probe file '%s'" % probe_file)
    while running:
        try:

            if is_windows:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            else:
                startupinfo = None

            openocd = get_openocd()
            process = subprocess.Popen([openocd,
                                        '-c', "set BOOTLOADER %s" % bootloader,
                                        '--file', probe_file,
                                        '--file', config_file],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        startupinfo=startupinfo)

            output = process.stdout.read().decode()
            if output:
                output_text.insert(tk.END, output)
                output_text.see(tk.END)
                log_message(output)
            outerr = process.stderr.read().decode()
            if outerr:
                output_text.insert(tk.END, outerr)
                output_text.see(tk.END)
                log_message(outerr)
            if outerr.find("Cortex-M") != -1:
                # found the MCU
                play_found()
                update_status_led("orange")
            else:
                # we're still looking for the MCU
                play_searching()
                update_status_led("red")
            retcode = process.poll()
            if retcode is not None:
                if retcode == 0:
                    log_message("Success")
                    print("%s successful." % mode_var.get())
                    play_success()
                    update_status_led("green")
                    running = False
        except Exception as e:
            print(f"Error running OpenOCD: {e}")

def start_openocd():
    if not running:
        output_text.delete(1.0, tk.END)
        thd = threading.Thread(target=run_openocd)
        thd.start()

def stop_openocd():
    global running
    running = False
    log_message("stopping")

def quit():
    global running
    running = False
    sys.exit(0)

def update_status_led(color):
    canvas.itemconfig(led, fill=color)

# Initialize GUI
root = tk.Tk()
root.title("AM32 ESC Unlocker")

root.grid_rowconfigure(6, weight=1)
root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=1)
root.grid_columnconfigure(2, weight=1)
root.grid_columnconfigure(3, weight=1)

# Probe selection
probe_var = tk.StringVar()
probe_label = ttk.Label(root, text="Select Probe:")
probe_label.grid(row=0, column=2, padx=10, pady=10)
probe_dropdown = ttk.OptionMenu(root, probe_var, PROBE_LIST[0], *PROBE_LIST)
probe_dropdown.grid(row=0, column=3, padx=10, pady=10)

# MCU type selection
mcu_var = tk.StringVar()
mcu_label = ttk.Label(root, text="Select MCU Type:")
mcu_label.grid(row=0, column=0, padx=10, pady=10)
mcu_dropdown = ttk.OptionMenu(root, mcu_var, MCU_LIST[0], *MCU_LIST)
mcu_dropdown.grid(row=0, column=1, padx=10, pady=10)

# pin selection
pin_var = tk.StringVar()
pin_label = ttk.Label(root, text="Signal Pin:")
pin_label.grid(row=1, column=0, padx=10, pady=10)
pin_dropdown = ttk.OptionMenu(root, pin_var, PIN_LIST[0], *PIN_LIST)
pin_dropdown.grid(row=1, column=1, padx=10, pady=10)

# locking mode
mode_var = tk.StringVar()
mode_label = ttk.Label(root, text="Select Mode:")
mode_label.grid(row=1, column=2, padx=10, pady=10)
mode_dropdown = ttk.OptionMenu(root, mode_var, "Unlock", "Unlock", "Lock")
mode_dropdown.grid(row=1, column=3, padx=10, pady=10)

# Start and Stop buttons
start_button = ttk.Button(root, text="Start", command=start_openocd)
start_button.grid(row=2, column=1, padx=10, pady=10)
stop_button = ttk.Button(root, text="Stop", command=stop_openocd)
stop_button.grid(row=2, column=2, padx=10, pady=10)

stop_button = ttk.Button(root, text="Quit", command=quit)
stop_button.grid(row=2, column=3, padx=10, pady=10)

# Status LED
canvas = tk.Canvas(root, width=20, height=20)
canvas.grid(row=2, column=0, columnspan=1, pady=10)
led = canvas.create_oval(5, 5, 20, 20, fill="gray")

# Custom Bootloader selection
def select_bootloader_file():
    file_path = filedialog.askopenfilename(title="Custom Bootloader", filetypes=[("Binary files", "*.bin"), ("Hex files", "*.hex"), ("All files", "*.*")])
    if file_path:
        bootloader_var.set(file_path)

bootloader_var = tk.StringVar()
bootloader_label = ttk.Label(root, text="Custom Bootloader:")
bootloader_label.grid(row=5, column=0, padx=10, pady=10)
bootloader_entry = ttk.Entry(root, textvariable=bootloader_var, width=40)
bootloader_entry.grid(row=5, column=1, columnspan=2, padx=10, pady=10)
bootloader_button = ttk.Button(root, text="Browse...", command=select_bootloader_file)
bootloader_button.grid(row=5, column=3, padx=10, pady=10)

output_text = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=50, height=10)
output_text.grid(row=6, column=0, columnspan=4, padx=10, pady=10, sticky="nsew")

running = False

def play_tones():
    '''callback to play tones'''
    while len(pending_tones) > 0:
        tone,duration = pending_tones.pop()
        play_tone(tone, duration)
    root.after(10, play_tones)

root.after(10, play_tones)

# Start the GUI event loop
root.mainloop()
