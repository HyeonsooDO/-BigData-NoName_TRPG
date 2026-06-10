import subprocess
import time
import os

PID_FILE = "ollama.pid"

def start_server():
    # 이미 실행 중인지 체크
    if os.path.exists(PID_FILE):
        print("Ollama server already running (pid file exists)")
        return

    print("Starting Ollama server...")

    # 백그라운드 실행
    process = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # PID 저장
    with open(PID_FILE, "w") as f:
        f.write(str(process.pid))

    time.sleep(1)
    print(f"Ollama server started (PID: {process.pid})")

if __name__ == "__main__":
    start_server()