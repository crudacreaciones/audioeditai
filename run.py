#!/usr/bin/env python3
"""Start the app without Electron: `python run.py --open`."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from swc.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
