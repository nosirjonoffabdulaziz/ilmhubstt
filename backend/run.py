"""ilmhubstt serverini ishga tushirish.

  python run.py            -> http://127.0.0.1:8000 (faqat shu kompyuter)
  python run.py --lan      -> lokal tarmoqdagi telefon ham ulanadi (0.0.0.0)
"""
from __future__ import annotations

import argparse
import socket
import sys

import uvicorn

from app.config import load_settings
from app.main import create_app


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(description="ilmhubstt server")
    parser.add_argument("--lan", action="store_true", help="lokal tarmoqqa ochish (telefon uchun)")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()

    settings = load_settings()
    host = args.host or ("0.0.0.0" if args.lan else settings.host)
    port = args.port or settings.port
    app = create_app(settings)

    print("=" * 60)
    print("  ilmhubstt ishga tushdi")
    print(f"  Kompyuterda:  http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        print(f"  Telefonda:    http://{lan_ip()}:{port}   (bir Wi-Fi tarmog'ida)")
    print("  To'xtatish:   Ctrl + C")
    print("=" * 60)
    sys.stdout.flush()
    uvicorn.run(app, host=host, port=port, access_log=False, log_level="info",
                timeout_keep_alive=30)


if __name__ == "__main__":
    main()
