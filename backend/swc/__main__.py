"""Entry point: `python -m swc [--port 8765] [--data-dir DIR] [--open]`."""
from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from .app import create_app
from .config import load_config


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Spotify to WAV Converter - servidor local")
    ap.add_argument("--port", type=int, default=None, help="Puerto local (por defecto 8765)")
    ap.add_argument("--data-dir", default=None, help="Carpeta de datos (biblioteca, logs, WAV)")
    ap.add_argument("--open", action="store_true", help="Abrir la interfaz en el navegador")
    args = ap.parse_args(argv)

    cfg = load_config(args.data_dir, args.port)
    app = create_app(cfg)
    url = f"http://{cfg.host}:{cfg.port}/"
    print(f"SWC_READY {url}", flush=True)
    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
