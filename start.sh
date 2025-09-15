#!/bin/bash

# Start Xvfb virtual display
Xvfb $DISPLAY -screen 0 ${SCREEN_WIDTH}x${SCREEN_HEIGHT}x${SCREEN_DEPTH} -ac +extension RANDR +extension GLX +extension MIT-SHM &
XVFB_PID=$!

# Wait for Xvfb to start
sleep 2

# Start a simple window manager (optional but helps with some applications)
fluxbox &
FLUXBOX_PID=$!

# Set display for all subsequent commands
export DISPLAY=:99

# Function to cleanup processes on exit
cleanup() {
    echo "Cleaning up processes..."
    kill $FLUXBOX_PID 2>/dev/null
    kill $XVFB_PID 2>/dev/null
    exit 0
}

# Set trap to cleanup on exit
trap cleanup SIGINT SIGTERM

# Run the Python script
# python checkscrape.py

# Cleanup after Python script exits
cleanup