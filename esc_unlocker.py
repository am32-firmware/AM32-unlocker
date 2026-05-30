#!/usr/bin/env python3
'''
UI for unlocking ESC MCUs for AM32 project
'''

PROBE_LIST = ["ST Link", "JLink", "CMSIS-DAP"]
MCU_LIST = ["F031", "F051", "G071", "G071_64K", "G431", "L431", "E230", "F415", "F421"]
PIN_LIST = ["PA0","PA2","PA6","PB4","PA15"]
CAN_MCUS = ["F415", "G431", "L431"]
# index of the last flash sector to erase for the larger CAN bootloaders
# (passed to "flash erase_sector 0 0 <last>", which is inclusive)
CAN_ERASE_LAST_SECTOR = {"F415": 15, "G431": 8, "L431": 8}

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
import subprocess
import os
import sys
import threading
import queue
import time
from datetime import datetime
import intelhex

# audio is optional: never let a missing/broken audio backend prevent the
# app from starting. sounddevice ships prebuilt wheels (PortAudio bundled on
# Windows/macOS, system libportaudio2 on Linux); audio_error records why it
# is unavailable so we can surface it once the GUI is up.
try:
    import numpy as np
    import sounddevice as sd
    have_audio = True
    audio_error = None
except Exception as e:
    have_audio = False
    audio_error = str(e)
import platform
import tempfile

is_windows = platform.system() == "Windows"
is_macos = platform.system() == "Darwin"

# In a --windowed/--noconsole PyInstaller build sys.stdout/stderr are None, so
# any print() raises - which would kill the OpenOCD worker thread mid-run.
# Redirect to devnull so the existing print() calls are always safe.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# tones are played on a dedicated thread so blocking PortAudio calls never
# stall the Tk main loop (doing this on the main thread caused severe UI lag
# on macOS)
audio_queue = queue.Queue()

# the currently running openocd child, so Stop can terminate it
current_process = None

# Tkinter is not thread-safe: widgets may only be touched from the thread
# running mainloop(). The OpenOCD worker thread pushes callables onto this
# queue and process_gui_queue() (scheduled on the main thread) runs them.
gui_queue = queue.Queue()

def gui_call(fn):
    '''schedule a callable to run on the main GUI thread'''
    gui_queue.put(fn)

def append_output(text):
    '''append text to the output box from any thread'''
    def do():
        output_text.insert(tk.END, text)
        output_text.see(tk.END)
    gui_call(do)

def play_tone(frequency, duration=0.1, volume=0.2):
    '''
    play a tone
    '''
    if not have_audio:
        return
    try:
        sample_rate = 44100  # samples per second
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        wave = np.sin(frequency * t * 2 * np.pi)
    
        audio = (wave * (32767 * volume)).astype(np.int16)

        sd.play(audio, sample_rate)
        sd.wait()
    except Exception as e:
        log_message("audio error: %s" % e)


def queue_tone(frequency, duration=0.1):
    '''enqueue a tone for the audio thread (bounded so it can't back up)'''
    if have_audio and audio_queue.qsize() < 4:
        audio_queue.put((frequency, duration))

def audio_worker():
    '''play queued tones off the GUI thread'''
    while True:
        frequency, duration = audio_queue.get()
        play_tone(frequency, duration)

def play_searching():
    queue_tone(300, 0.1)

def play_found():
    queue_tone(880, 0.1)

def play_success():
    queue_tone(600, 0.1)
    queue_tone(800, 0.1)
    queue_tone(1000, 0.1)


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
    elif is_macos:
        openocd = "tools/macos/openocd/bin/openocd"
    else:
        # assume Linux
        openocd = "tools/linux/openocd/bin/openocd"
    return get_resource_path(openocd)

def run_openocd(params):
    '''
    run openocd as a child, looping until running is False or success.
    params holds the GUI selections, read on the main thread by the caller -
    the worker must never touch Tk (macOS Aqua wedges the event loop if it does)
    '''
    global running, current_process
    running = True
    mcu_type = params['mcu_type']
    probe_type = params['probe_type']
    if probe_type == "ST Link":
        probe_type = "stlink"
    elif probe_type == "JLink":
        probe_type = "jlink"
    elif probe_type == "CMSIS-DAP":
        probe_type = "cmsis-dap"

    pin = params['pin']
    mode = params['mode']
    if mode == "Lock":
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
    custom_bootloader = params['custom_bootloader']

    use_can = params['can'] and mcu_base in CAN_MCUS
    can_tag = "_CAN" if use_can else ""

    if custom_bootloader:
        bootloader = custom_bootloader
    else:
        bootloader = os.path.join("bootloaders", f"AM32_{mcu_base}_BOOTLOADER_{pin}{can_tag}{k_tag}_V17.bin")
        bootloader = get_resource_path(bootloader)

    log_message("Starting MCU %s PIN %s op %s CAN %s" % (mcu_type, pin, op, use_can))

    using_tempfile = False

    if bootloader.lower().endswith(".hex"):
        thandle = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        tfile = thandle.name
        print("CREATED '%s'" % tfile)
        if intelhex.hex2bin(bootloader, tfile) != 0:
            log_message("Failed to convert hex to bin")
            return
        bootloader = tfile
        using_tempfile = True
        if is_windows:
            bootloader = bootloader.replace("\\", "\\\\")

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
            ocd_args = [openocd,
                        '-c', 'set BOOTLOADER "%s"' % bootloader]
            if use_can and mcu_base in CAN_ERASE_LAST_SECTOR:
                ocd_args += ['-c', 'set ERASE_LAST_SECTOR %d' % CAN_ERASE_LAST_SECTOR[mcu_base]]
            ocd_args += ['--file', probe_file,
                         '--file', config_file]
            process = subprocess.Popen(ocd_args,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        startupinfo=startupinfo)
            # expose to stop_openocd() so Stop can terminate a blocked attempt
            current_process = process

            output = process.stdout.read().decode()
            if output:
                append_output(output)
                log_message(output)
            outerr = process.stderr.read().decode()
            if outerr:
                append_output(outerr)
                log_message(outerr)
            if not running:
                # Stop was pressed (process terminated); don't beep or relaunch
                break
            if outerr.find("Cortex-M") != -1:
                # found the MCU
                play_found()
                gui_call(lambda: update_status_led("orange"))
            else:
                # we're still looking for the MCU
                play_searching()
                gui_call(lambda: update_status_led("red"))
            retcode = process.poll()
            if retcode is not None:
                if retcode == 0:
                    log_message("Success")
                    print("%s successful." % mode)
                    play_success()
                    gui_call(lambda: update_status_led("green"))
                    running = False
        except Exception as e:
            print(f"Error running OpenOCD: {e}")
        # brief pause so a fast-failing attempt doesn't busy-loop relaunching
        if running:
            time.sleep(0.3)

    current_process = None
    if using_tempfile:
        os.unlink(tfile)

def start_openocd():
    if not running:
        output_text.delete(1.0, tk.END)
        # read all GUI state here on the main thread and hand it to the worker;
        # the worker must not call any Tk method (unsafe, hangs macOS)
        params = {
            'mcu_type': mcu_var.get(),
            'probe_type': probe_var.get(),
            'pin': pin_var.get(),
            'mode': mode_var.get(),
            'custom_bootloader': bootloader_var.get(),
            'can': can_var.get(),
        }
        thd = threading.Thread(target=run_openocd, args=(params,), daemon=True)
        thd.start()

def terminate_process():
    '''kill the in-flight openocd child, if any, to unblock the worker thread'''
    p = current_process
    if p is not None:
        try:
            p.terminate()
        except Exception:
            pass

def stop_openocd():
    global running
    running = False
    terminate_process()
    log_message("stopping")

def quit():
    global running
    running = False
    terminate_process()
    # destroy() reliably ends mainloop; sys.exit() can be swallowed by Tk, and
    # the worker is a daemon thread so the process exits cleanly
    root.destroy()

def update_status_led(color):
    canvas.itemconfig(led, fill=color)

# Initialize GUI
root = tk.Tk()
root.title("AM32 ESC Unlocker")

root.grid_rowconfigure(7, weight=1)
root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=1)
root.grid_columnconfigure(2, weight=1)
root.grid_columnconfigure(3, weight=1)
root.grid_columnconfigure(4, weight=1)

# Probe selection
probe_var = tk.StringVar()
probe_label = ttk.Label(root, text="Select Probe:")
probe_label.grid(row=0, column=3, padx=10, pady=10)
probe_dropdown = ttk.OptionMenu(root, probe_var, PROBE_LIST[0], *PROBE_LIST)
probe_dropdown.grid(row=0, column=4, padx=10, pady=10)

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

# CAN bootloader checkbox
can_var = tk.BooleanVar()
can_check = ttk.Checkbutton(root, text="CAN", variable=can_var)
can_check.grid(row=1, column=2, padx=10, pady=10)
can_check.state(['disabled'])

def on_mcu_change(*args):
    mcu = mcu_var.get().split('_')[0]
    if mcu in CAN_MCUS:
        can_check.state(['!disabled'])
    else:
        can_var.set(False)
        can_check.state(['disabled'])

mcu_var.trace_add('write', on_mcu_change)
on_mcu_change()  # sync checkbox state to the initial MCU selection

# locking mode
mode_var = tk.StringVar()
mode_label = ttk.Label(root, text="Select Mode:")
mode_label.grid(row=1, column=3, padx=10, pady=10)
mode_dropdown = ttk.OptionMenu(root, mode_var, "Unlock", "Unlock", "Lock")
mode_dropdown.grid(row=1, column=4, padx=10, pady=10)

# Start and Stop buttons
start_button = ttk.Button(root, text="Start", command=start_openocd)
start_button.grid(row=2, column=1, padx=10, pady=10)
stop_button = ttk.Button(root, text="Stop", command=stop_openocd)
stop_button.grid(row=2, column=2, padx=10, pady=10)

stop_button = ttk.Button(root, text="Quit", command=quit)
stop_button.grid(row=2, column=4, padx=10, pady=10)

# Status LED
canvas = tk.Canvas(root, width=20, height=20)
canvas.grid(row=2, column=0, columnspan=1, pady=10)
led = canvas.create_oval(5, 5, 20, 20, fill="gray")

# Custom Bootloader selection
def select_bootloader_file():
    file_path = filedialog.askopenfilename(title="Custom Bootloader", filetypes=[("Bin and hex files", "*.bin *.hex"), ("All files", "*.*")])
    if file_path:
        bootloader_var.set(file_path)

bootloader_var = tk.StringVar()
bootloader_label = ttk.Label(root, text="Custom Bootloader:")
bootloader_label.grid(row=5, column=0, padx=10, pady=10)
bootloader_entry = ttk.Entry(root, textvariable=bootloader_var, width=40)
bootloader_entry.grid(row=5, column=1, columnspan=3, padx=10, pady=10)
bootloader_button = ttk.Button(root, text="Browse...", command=select_bootloader_file)
bootloader_button.grid(row=5, column=4, padx=10, pady=10)

bootloader_label = ttk.Label(root, text="Custom Bootloader:")
bootloader_label.grid(row=5, column=0, padx=10, pady=10)

warn = tk.Text(root, wrap='word', height=5, bg='lightgrey')
warn.insert(tk.END,
'''NOTE! The included bootloaders are the latest development versions.
For the stable bootloaders please download from
  https://am32.ca/downloads
and use the Custom Bootloader option
''')
warn.config(state=tk.DISABLED)
warn.grid(row=6, column=0, columnspan=5, padx=10, pady=10)


output_text = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=50, height=10)
output_text.grid(row=7, column=0, columnspan=5, padx=10, pady=10, sticky="nsew")

if not have_audio:
    # surface why audio is off instead of failing silently
    msg = "Audio disabled (%s); continuing without sound\n" % (audio_error or "no audio backend")
    output_text.insert(tk.END, msg)
    log_message(msg)

running = False

# play queued tones on a daemon thread, off the Tk main loop
if have_audio:
    try:
        dev = sd.query_devices(kind='output')
        log_message("audio: sounddevice %s, output device '%s'" % (sd.__version__, dev['name']))
    except Exception as e:
        log_message("audio: no usable output device: %s" % e)
    threading.Thread(target=audio_worker, daemon=True).start()

def process_gui_queue():
    '''run GUI actions queued by the worker thread (main thread only)'''
    try:
        while True:
            fn = gui_queue.get_nowait()
            try:
                fn()
            except Exception:
                pass
    except queue.Empty:
        pass
    root.after(50, process_gui_queue)

root.after(50, process_gui_queue)

def apply_cli_args():
    '''optional command-line control, handy for automated/headless testing'''
    import argparse
    parser = argparse.ArgumentParser(description="AM32 ESC Unlocker")
    parser.add_argument('--mcu', choices=MCU_LIST, help='MCU type')
    parser.add_argument('--port', '--pin', dest='pin', choices=PIN_LIST, help='signal pin')
    parser.add_argument('--probe', choices=PROBE_LIST, help='debug probe')
    parser.add_argument('--mode', choices=['Unlock', 'Lock'], help='operation')
    parser.add_argument('--bootloader', help='custom bootloader file')
    parser.add_argument('--can', action='store_true', help='use the CAN bootloader variant')
    parser.add_argument('--start', action='store_true', help='press Start automatically')
    parser.add_argument('--test-audio', action='store_true',
                        help='play test tones and log the outcome (audio diagnostics)')
    parser.add_argument('--exit-after', type=float, default=0,
                        help='quit automatically after N seconds (testing)')
    # parse_known_args so a macOS .app launch arg (-psn_...) doesn't abort
    args, _ = parser.parse_known_args()

    if args.mcu:
        mcu_var.set(args.mcu)        # fires on_mcu_change -> enables CAN if applicable
    if args.pin:
        pin_var.set(args.pin)
    if args.probe:
        probe_var.set(args.probe)
    if args.mode:
        mode_var.set(args.mode)
    if args.bootloader:
        bootloader_var.set(args.bootloader)
    if args.can:
        can_var.set(True)
    if args.test_audio:
        def _audio_test():
            log_message("audio test: starting (have_audio=%s)" % have_audio)
            play_tone(880, 0.3)
            play_tone(660, 0.3)
            log_message("audio test: done (no exception from sd.play)")
        threading.Thread(target=_audio_test, daemon=True).start()
    if args.start:
        root.after(500, start_openocd)
    if args.exit_after > 0:
        root.after(int(args.exit_after * 1000), quit)

apply_cli_args()

# Start the GUI event loop
root.mainloop()
