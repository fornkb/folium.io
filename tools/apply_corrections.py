"""Apply a reviewed local JSON patch with a backup and original-text checks."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Store
from repairs import apply_corrections

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--course", required=True)
    parser.add_argument("--patch", required=True, type=Path)
    args = parser.parse_args()
    store = Store(args.data_dir)
    try:
        course = apply_corrections(store, args.course, json.loads(args.patch.read_text("utf-8")))
        print(f"Saved correction; {len(course['modules'])} modules preserved. Original is in data/backups.")
    finally:
        store.close()
