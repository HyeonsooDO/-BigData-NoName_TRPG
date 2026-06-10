import os
import signal

PID_FILE = "ollama.pid"

def stop_server():
    if not os.path.exists(PID_FILE):
        print("No running server found")
        return

    with open(PID_FILE, "r") as f:
        pid = int(f.read())

    try:
        print(f"Stopping Ollama server (PID: {pid})...")
        os.kill(pid, signal.SIGTERM)
        print("Stopped successfully")
    except Exception as e:
        print("Error:", e)

    os.remove(PID_FILE)

if __name__ == "__main__":
    stop_server()