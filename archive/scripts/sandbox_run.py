#!/usr/bin/env python3
"""Launch run_competition.py inside sandbox-exec with a restricted profile.

Usage:
    python scripts/sandbox_run.py --tag soccer --freq 5min --cash 1000

All arguments are forwarded to scripts/run_competition.py.
"""
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(PROJECT, "config", "backtest.sb")
RUNNER = os.path.join(PROJECT, "scripts", "run_competition.py")

# Detect Python — prefer venv, fallback to system
python = os.path.join(PROJECT, ".venv", "bin", "python3")
if not os.path.exists(python):
    python = os.path.join(PROJECT, ".venv", "bin", "python3.14")
if not os.path.exists(python):
    python = sys.executable

# Strip environment to only what the backtest needs
env = {
    "PATH": os.pathsep.join([
        os.path.dirname(python),
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]),
    "HOME": os.environ.get("HOME", ""),
    "PWD": PROJECT,
    "PYTHONPATH": PROJECT,
    "TERM": os.environ.get("TERM", "xterm-256color"),
    "LC_ALL": "en_US.UTF-8",
    "LANG": "en_US.UTF-8",
}

# macOS temp dirs — needed for .pyc compilation, matplotlib cache etc.
for key in ("TMPDIR", "TEMP", "TMP"):
    if key in os.environ:
        env[key] = os.environ[key]

# Matplotlib cache — project .matplotlib/ is not writable under sandbox
tmpdir = env.get("TMPDIR", "/tmp")
env["MPLCONFIGDIR"] = os.path.join(tmpdir, "matplotlib")
env["PYTHONPYCACHEPREFIX"] = os.path.join(tmpdir, "pycache")

cmd = ["sandbox-exec", "-f", PROFILE, python, RUNNER, *sys.argv[1:]]

if not os.path.exists(PROFILE):
    sys.exit(f"error: sandbox profile not found at {PROFILE}")

os.execvpe(cmd[0], cmd, env)
