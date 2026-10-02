"""Open the local panel, starting its small server only when needed."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser
from runtime_config import runtime_directory

ROOT = Path(__file__).resolve().parent
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
STATE = runtime_directory()


def ready():
    try:
        with urlopen(URL + "/api/bootstrap", timeout=1) as response:
            return json.load(response).get("app_id") == "bandbox-studio"
    except (URLError, TimeoutError, ValueError, OSError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if not ready():
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", PORT))
            except OSError:
                raise SystemExit("Port 8765 is occupied by another app. No process was stopped.")
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (STATE / "gui-server.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "gui_server.py"), "--port", str(PORT)],
                cwd=ROOT, env=dict(os.environ, BANDBOX_RUNTIME_DIR=str(STATE)),
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        (STATE / "gui-server.pid").write_text(str(process.pid) + "\n")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if ready():
                break
            if process.poll() is not None:
                raise SystemExit(f"Panel could not start. See {STATE / 'gui-server.log'}")
            time.sleep(0.25)
        else:
            raise SystemExit(f"Panel did not start within 15 seconds. See {STATE / 'gui-server.log'}")
    if not args.no_open:
        webbrowser.open(URL)
    print(URL)


if __name__ == "__main__":
    main()
