#!/usr/bin/env python3
"""Route reviewed per-label files into processed or issue directories."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.route_label_files import main


if __name__ == "__main__":
    raise SystemExit(main())

