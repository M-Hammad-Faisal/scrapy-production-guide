"""Serve mock_iso/ on 127.0.0.1:8765 so the iso_prices spider has something to crawl.

    python scripts/serve_mock.py
"""

from __future__ import annotations

import functools
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "mock_iso"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # keep the crawl output readable
        return


if __name__ == "__main__":
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    server = HTTPServer(("127.0.0.1", 8765), handler)
    print("serving", ROOT, "on http://127.0.0.1:8765")
    server.serve_forever()
