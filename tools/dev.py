"""One-command local install and launch: python tools/dev.py [--check]."""
import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Install, migrate, seed and build without starting servers")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=5173)
    args = parser.parse_args()
    backend = ROOT / "backend"
    py = backend / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        venv.create(backend / ".venv", with_pip=True)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise SystemExit("Install Node.js 20+ and try again.")
    def run(command, directory):
        subprocess.run(command, cwd=directory, check=True)
    run([str(py), "-m", "pip", "install", "-r", "requirements.txt"], backend)
    run([str(py), "-m", "scripts.seed_demo"], backend)
    run([npm, "ci"], ROOT / "frontend")
    if args.check:
        run([npm, "run", "build"], ROOT / "frontend")
        return
    env = dict(os.environ, KRUVIM_API_URL=f"http://127.0.0.1:{args.api_port}")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    processes = []
    try:
        processes.append(subprocess.Popen([str(py), "-m", "uvicorn", "app.main:app", "--port", str(args.api_port)], cwd=backend, env=env, creationflags=flags))
        processes.append(subprocess.Popen([npm, "run", "dev", "--", "--port", str(args.web_port), "--strictPort"], cwd=ROOT / "frontend", env=env, creationflags=flags))
        print(f"Kruvim: http://localhost:{args.web_port} · demo@kruvim.local / kruvim-demo-2026", flush=True)
        while all(p.poll() is None for p in processes):
            try:
                processes[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)


if __name__ == "__main__":
    main()
