#!/bin/bash

MCUS=$(/bin/ls MCU)

OPTIONS="--onefile --windowed --add-data tools/linux:tools/linux --add-data bootloaders:bootloaders"
for m in $MCUS; do
    [ -d MCU/$m ] && {
        echo "Adding MCU $m"
        OPTIONS="$OPTIONS --add-data MCU/$m:MCU/$m"
    }
done

pyinstaller $OPTIONS esc_unlocker.py
