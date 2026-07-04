"""Regenerate Arctic slot-slide snippets (see gen_arctic_slot_snippets.py)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gen_arctic_slot_snippets import main

if __name__ == "__main__":
    main()
