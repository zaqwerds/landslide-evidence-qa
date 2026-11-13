# -*- coding: utf-8 -*-
"""Launch the local web application from the repository root."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


PROGRAM_DIR = Path(__file__).resolve().parent
APP_PATH = PROGRAM_DIR / "webapp" / "app.py"


def main() -> int:
    print("正在启动滑坡知识图谱网页……")
    print("浏览器未自动打开时，请访问：http://127.0.0.1:8501")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.address=127.0.0.1",
        "--server.port=8501",
        "--server.maxUploadSize=500",
        "--server.showEmailPrompt=false",
        "--browser.gatherUsageStats=false",
    ]
    environment = dict(os.environ)
    environment["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    try:
        return subprocess.call(command, cwd=str(PROGRAM_DIR), env=environment)
    except KeyboardInterrupt:
        print("网页已停止。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
