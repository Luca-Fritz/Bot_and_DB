#!/bin/bash

# Activate the virtual environment
source /home/gira/Bot_and_DB/dm_bot/bin/activate

# Function to handle SIGINT and forward it to the child process
cleanup() {
    echo "$(date) - Caught SIGINT signal. Stopping the script."
    pkill -P $child_pid  # Kill the child process
    exit 0
}

# Trap SIGINT signal and call cleanup function
trap cleanup SIGINT

if pgrep -f "/home/gira/Bot_and_DB/iterate_DB.py" > /dev/null
then
    echo "$(date) - The script is running."
else
    echo "$(date) - The script is not running. Starting the script."
    python /home/gira/Bot_and_DB/iterate_DB.py &
    child_pid=$!
    wait $child_pid
fi

# Keep only the last 5 lines in the log file
#tail -n 5 /home/gira/Bot_and_DB/log.txt > /home/gira/Bot_and_DB/temp.txt && mv /home/gira/Bot_and_DB/temp.txt /home/gira/Bot_and_DB/log.txt