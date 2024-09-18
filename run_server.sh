# Find PID of process listening on port 6400
PID=$(lsof -t -i:6400)

# Check if PID is not empty
if [ ! -z "$PID" ]; then
    # Kill the process
    kill $PID
    if [ $? -eq 0 ]; then
        echo "Process on port 6400 killed successfully."
    else
        echo "Failed to kill process on port 6400."
    fi
else
    echo "No process found on port 6400."
fi

# Activate the virtual environment
source venv/bin/activate

# Run the main process
python main.py