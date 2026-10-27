"""Bounded recent-context read for reopening the live display."""
from pathlib import Path
import sqlite3
import time

def recent(directory, hours=24):
    cutoff = time.time() - min(24, max(0, hours)) * 3600
    result = {}
    for path in sorted(Path(directory).glob('????/vti-????-??.sqlite'))[-2:]:
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2) as db:
            for stamp, key, value, valid in db.execute(
                'SELECT end,key,last,valid FROM summaries WHERE start>=? ORDER BY start LIMIT 100000', (cutoff,)):
                result.setdefault(key, []).append([stamp, value if valid else None])
    return result
