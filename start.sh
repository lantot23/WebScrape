#!/bin/bash

# Export display
export DISPLAY=:99

# Start virtual display
Xvfb :99 -screen 0 ${SCREEN_WIDTH}x${SCREEN_HEIGHT}x${SCREEN_DEPTH} &
XVFB_PID=$!

# Give Xvfb a moment to initialize
sleep 2


# Kill Xvfb after script finishes
kill $XVFB_PID
