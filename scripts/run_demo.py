"""Start the built demo locally; optionally verify and enable Bedrock."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--llm", action="store_true", help="Verify Bedrock with a real request, then start in LLM mode.")
    modes.add_argument("--offline", action="store_true", help="Use templates without model requests.")
    args = parser.parse_args()
    provider = "bedrock" if args.llm else "none" if args.offline else os.environ.get("STUDYFLOW_LLM_PROVIDER", "none").strip().lower()
    if provider not in {"none", "bedrock"}:
        parser.error("STUDYFLOW_LLM_PROVIDER must be 'none' or 'bedrock'")
    node = os.environ.get("STUDYFLOW_NODE") or shutil.which("node")
    if not node:
        raise SystemExit("Node.js is missing from PATH. Install Node 24 or set STUDYFLOW_NODE to its executable.")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    if not vite.exists() or not (ROOT / "frontend/dist/index.html").exists():
        raise SystemExit("Prepare the frontend first: cd frontend && npm ci && npm run build")
    environment = {**os.environ, "STUDYFLOW_ENV": "demo",
                   "STUDYFLOW_ENABLE_DEMO_RESET": "1", "STUDYFLOW_LLM_PROVIDER": provider}
    if provider == "bedrock":
        print("Checking Bedrock with one real model request before startup...", flush=True)
        check = subprocess.run([sys.executable, "-m", "backend.agents.check_bedrock"], cwd=ROOT, env=environment)
        if check.returncode:
            raise SystemExit("Bedrock check failed; demo was not started. Fix AWS credentials/model access, or use --offline.")
    commands = [
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
         "--port", "8000", "--workers", "1", "--log-config", "backend/logging.json", "--no-access-log"],
        [node, str(vite), "preview", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
    ]
    children: list[subprocess.Popen] = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT if command[0] == sys.executable else ROOT / "frontend", env=environment))
        mode = "Bedrock LLM" if provider == "bedrock" else "Offline template"
        print(f"{mode} demo: http://127.0.0.1:5173 — Reset, then Generate Plan. Ctrl-C stops both services.", flush=True)
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
