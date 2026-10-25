import os
import sys
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, "bot.pid")
BOT_SCRIPT = os.path.join(BASE_DIR, "bot_truc_nhom.py")
LOG_FILE = os.path.join(BASE_DIR, "bot_runtime.log")


def is_pid_running(pid):
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True,
            errors="ignore"
        )
        return str(pid) in out and ("python" in out.lower())
    except Exception:
        return False


def ensure_bot_running():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            if is_pid_running(pid):
                print(f"[Watchdog] Bot already running (PID={pid}).")
                return pid
        except Exception:
            pass

    python_exe = sys.executable
    log_handle = open(LOG_FILE, "a", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [python_exe, "-u", BOT_SCRIPT],
        cwd=BASE_DIR,
        env=env,
        stdout=log_handle,
        stderr=log_handle,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    )
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_handle.write(f"[{ts}] [Watchdog] Launched background bot_truc_nhom.py (PID={proc.pid})\n")
    log_handle.flush()
    print(f"[Watchdog] Launched background bot_truc_nhom.py (PID={proc.pid}).")
    return proc.pid


if __name__ == "__main__":
    ensure_bot_running()
