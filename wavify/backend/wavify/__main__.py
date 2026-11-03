"""Run the WAVIFY API: python -m wavify [--host 0.0.0.0] [--port 8000]

In production put it behind an HTTPS reverse proxy (see README) or pass --ssl-certfile/--ssl-keyfile.
"""
import argparse
import logging

import uvicorn

from .api import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="WAVIFY API")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--ssl-certfile")
    ap.add_argument("--ssl-keyfile")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host=a.host, port=a.port, ssl_certfile=a.ssl_certfile, ssl_keyfile=a.ssl_keyfile,
                proxy_headers=True)


if __name__ == "__main__":
    main()
