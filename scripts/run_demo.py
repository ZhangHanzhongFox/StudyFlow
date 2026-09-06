"""Start the built offline demo locally; Ctrl-C stops both owned processes."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    node = os.environ.get("STUDYFLOW_NODE") or shutil.which("node")
    if not node:
        raise SystemExit("Node.js is missing from PATH. Install Node 24 or set STUDYFLOW_NODE to its executable.")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    if not vite.exists() or not (ROOT / "frontend/dist/index.html").exists():
        raise SystemExit("Prepare the frontend first: cd frontend && npm ci && npm run build")
    environment = {**os.environ, "STUDYFLOW_ENV": "demo",
                   "STUDYFLOW_ENABLE_DEMO_RESET": "1", "STUDYFLOW_LLM_PROVIDER": "none"}
    commands = [
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
         "--port", "8000", "--workers", "1", "--log-config", "backend/logging.json", "--no-access-log"],
        [node, str(vite), "preview", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
    ]
    children: list[subprocess.Popen] = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT if command[0] == sys.executable else ROOT / "frontend", env=environment))
        print("Offline demo: http://127.0.0.1:5173 — Reset, then Generate Plan. Ctrl-C stops both services.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(.25)
        raise SystemExit("A demo process stopped. Read the error above; free ports 8000/5173 before retrying.")
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
