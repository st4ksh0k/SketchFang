#!/usr/bin/env python3
"""Compatibility shim — the decryptor now lives in `sketchfang.crypto`.

Equivalent to `sketchfang-decrypt`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sketchfang.cli.decrypt import main  # noqa: E402

if __name__ == "__main__":
    main()
