#!/bin/bash

while :; do
    echo "trying unlock at $(date)"
    openocd --file g071/openocd-unlock.cfg && {
        echo "Success!"
        exit 0
    }
done
