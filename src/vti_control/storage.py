"""Single SQLite writer with bounded retry data and durable interval summaries."""
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
import json
import logging
import sqlite3
import threading
import time

log = logging.getLogger(__name__)

class Archive(threading.Thread):
    def __init__(self, directory, channels, interval=10, backup_dir=None):
        super().__init__(name='archive', daemon=True)
        self.directory = Path(directory)
        self.backup_dir = Path(backup_dir) if backup_dir else None
        self.interval, self.channels = interval, channels
        self.pending = deque(maxlen=12000)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.health = {'ok': True, 'error': '', 'last_commit': None, 'dropped_records': 0}
        self.db, self.month, self.last_backup = None, None, None
    def enqueue(self, record):
        with self.lock:
            if len(self.pending) == self.pending.maxlen:
                self.health['dropped_records'] += 1
            self.pending.append(record)
    def event(self, kind, message, stamp=None):
        self.enqueue(('event', stamp or time.time(), kind, message))
    def sample(self, key, value, quality, stamp):
        self.enqueue(('sample', stamp, key, value, quality))
    def connect(self, stamp):
        month = datetime.fromtimestamp(stamp, timezone.utc).strftime('%Y-%m')
        if self.db is not None and self.month == month:
            return
        if self.db is not None:
            self.db.close()
        self.db, self.month = None, None
        path = self.directory / month[:4] / f'vti-{month}.sqlite'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript("""CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS channels(key TEXT PRIMARY KEY,definition TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS summaries(start REAL,end REAL,key TEXT,last REAL,min REAL,max REAL,mean REAL,valid INTEGER,total INTEGER,PRIMARY KEY(start,key));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,time REAL,kind TEXT,message TEXT);
        CREATE INDEX IF NOT EXISTS event_time ON events(time);""")
        self.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('schema_version', '1'))
        self.db.commit()
        self.month, self.path = month, path
    def persist(self, events, summaries):
        groups = defaultdict(lambda: ([], []))
        for event in events:
            groups[datetime.fromtimestamp(event[0], timezone.utc).strftime('%Y-%m')][0].append(event)
        for row in summaries:
            groups[datetime.fromtimestamp(row[0], timezone.utc).strftime('%Y-%m')][1].append(row)
        if not groups:
            groups[datetime.now(timezone.utc).strftime('%Y-%m')]
        for month, (evs, rows) in sorted(groups.items()):
            self.connect(datetime.strptime(month, '%Y-%m').replace(tzinfo=timezone.utc).timestamp())
            with self.db:
                for key, ch in list(self.channels.items()):
                    self.db.execute('INSERT OR REPLACE INTO channels VALUES(?,?)', (key, json.dumps(ch)))
                for stamp, kind, message in evs:
                    self.db.execute('INSERT INTO events(time,kind,message) VALUES(?,?,?)', (stamp, kind, message))
                self.db.executemany('INSERT OR REPLACE INTO summaries VALUES(?,?,?,?,?,?,?,?,?)', rows)
        self.health.update(ok=True, error='', last_commit=time.time())
        day = datetime.now(timezone.utc).date().isoformat()
        if self.backup_dir and day != self.last_backup:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.backup_dir / f'{self.path.stem}-latest.sqlite') as dest:
                self.db.backup(dest)
            self.last_backup = day
    def run(self):
        buckets = defaultdict(list)
        events, ready, states = [], [], {}
        deadline = time.monotonic() + self.interval
        try:
            while True:
                stopping = self.stop_event.is_set()
                with self.lock:
                    incoming = list(self.pending)
                    self.pending.clear()
                for rec in incoming:
                    if rec[0] == 'event':
                        events.append(rec[1:])
                    else:
                        _, stamp, key, value, quality = rec
                        if isinstance(value, (float, int)) or value is None:
                            start = int(stamp // self.interval) * self.interval
                            buckets[(start, key)].append((stamp, value, quality))
                        state = quality if isinstance(value, (float, int)) else (value, quality)
                        if states.get(key) != state:
                            states[key] = state
                            events.append((stamp, 'channel_state', json.dumps({'key': key, 'value': value, 'quality': quality})))
                cutoff = int(time.time() // self.interval) * self.interval
                for (start, key), readings in list(buckets.items()):
                    if start < cutoff or stopping:
                        valid = [v for _, v, q in readings if v is not None and q == 'ok']
                        ready.append((start, max(t for t, _, _ in readings), key, valid[-1] if valid else None,
                                      min(valid) if valid else None, max(valid) if valid else None,
                                      sum(valid)/len(valid) if valid else None, len(valid), len(readings)))
                        del buckets[(start, key)]
                if events or ready or time.monotonic() >= deadline or stopping:
                    try:
                        self.persist(events, ready)
                        events.clear(); ready.clear()
                    except Exception as exc:
                        log.exception('Archive write failed')
                        self.health.update(ok=False, error=str(exc))
                        if len(events) + len(ready) > 12000:
                            kept_events, kept_ready = events[-6000:], ready[-6000:]
                            self.health['dropped_records'] += len(events)+len(ready)-len(kept_events)-len(kept_ready)
                            events, ready = kept_events, kept_ready
                    deadline = time.monotonic() + self.interval
                if stopping:
                    break
                self.stop_event.wait(.2)
        finally:
            if self.db:
                self.db.close()
