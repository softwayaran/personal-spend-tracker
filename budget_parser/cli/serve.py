"""Serve subcommand — launches the Streamlit dashboard."""

import subprocess
import sys
from pathlib import Path


def add_parser(subparsers):
    p = subparsers.add_parser("serve", help="Launch the Streamlit dashboard")
    p.add_argument("--port", type=int, default=8501, help="Port to run dashboard on (default: 8501)")
    p.set_defaults(func=serve_main)
    return p


def serve_main(args) -> int:
    app_path = Path(__file__).parent.parent / "dashboard" / "app.py"
    result = subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(args.port)]
    )
    return result.returncode
