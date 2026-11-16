#!/usr/bin/env python3
"""Entry point; works with the included Python and with a compatible system Python."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

if __name__ == "__main__":
    from pokemon_red.cli import main
    main()
