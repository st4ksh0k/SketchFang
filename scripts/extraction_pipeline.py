#!/usr/bin/env python3
"""Extraction pipeline entry — thin shim over ``sketchfang.cli.rip``.

Equivalent to ``python -m sketchfang``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sketchfang.cli.rip import main  # noqa: E402

if __name__ == "__main__":
    main()
