# frontend/app.py
"""一站式启动脚本：启动 FastAPI（智能体 API）+ 静态前端。

用法（在项目根目录或 frontend 目录均可）：
    python frontend/app.py
    python frontend/app.py --port 8080 --no-browser
"""
import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402


def open_browser_later(url: str) -> None:
    def _open() -> None:
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP 智能办公助手前端")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument("--reload", action="store_true", help="开启热重载（开发用）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    # 让智能体工具（如读取 README.md）以项目根目录为基准路径
    os.chdir(ROOT)

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print("=" * 56)
    print("  MCP 智能办公助手已启动")
    print(f"  访问地址: {url}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)

    if not args.no_browser:
        open_browser_later(url)

    uvicorn.run(
        "backend.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(ROOT),
    )


if __name__ == "__main__":
    main()
