"""Radiometric sequence container: SQLite with independently compressed native frames.

Recording runs before the GUI latest-frame queue. Bounded backpressure is reported
as dropped frames; requested FPS samples arrivals and never invents camera frames.
"""

from contextlib import contextmanager
from pathlib import Path

import json
import queue
import sqlite3
import threading
import zlib

import numpy as np

from .acquisition import Frame


class Recorder(threading.Thread):
    def __init__(self, path, fps, metadata):
        super().__init__(name="p3-recording", daemon=True)
        if not np.isfinite(fps) or not 0.1 <= fps <= 240:
            raise ValueError("Requested FPS must be 0.1–240")
        self.path, self.fps, self.metadata = Path(path), float(fps), metadata
        # Exclusive file creation prevents unintended replacement of a recording.
        with self.path.open("xb"):
            pass
        self.pending = queue.Queue(maxsize=128)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.next_time = None
        self.written = 0
        self.dropped = 0
        self.error = None
        self.first_time = self.last_time = None

    def submit(self, frame):
        with self.lock:
            if self.stop_event.is_set() or self.error:
                return
            if self.next_time is not None and frame.timestamp + 1e-9 < self.next_time:
                return
            if self.next_time is None:
                self.next_time = frame.timestamp
            self.next_time += (
                int(max(0, frame.timestamp - self.next_time) * self.fps) + 1
            ) / self.fps
            try:
                self.pending.put_nowait(frame)
            except queue.Full:
                self.dropped += 1

    def stop(self):
        with self.lock:
            self.stop_event.set()

    def run(self):
        connection = None
        try:
            connection = sqlite3.connect(self.path)
            connection.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE frames (id INTEGER PRIMARY KEY, timestamp REAL, height INTEGER, width INTEGER, raw BLOB, brightness BLOB)"
            )
            connection.execute(
                "INSERT INTO metadata VALUES (?, ?)",
                (
                    "session",
                    json.dumps(
                        {"version": 1, "requested_fps": self.fps, **self.metadata}
                    ),
                ),
            )
            connection.commit()
            while not self.stop_event.is_set() or not self.pending.empty():
                try:
                    frame = self.pending.get(timeout=0.1)
                except queue.Empty:
                    continue
                h, w = frame.raw.shape
                connection.execute(
                    "INSERT INTO frames(timestamp,height,width,raw,brightness) VALUES(?,?,?,?,?)",
                    (
                        frame.timestamp,
                        h,
                        w,
                        zlib.compress(frame.raw.astype("<u2").tobytes(), 1),
                        zlib.compress(frame.brightness.tobytes(), 1),
                    ),
                )
                connection.commit()  # each completed frame survives normal process failure
                self.written += 1
                self.first_time = (
                    frame.timestamp if self.first_time is None else self.first_time
                )
                self.last_time = frame.timestamp
            connection.execute(
                "INSERT OR REPLACE INTO metadata VALUES (?, ?)",
                (
                    "result",
                    json.dumps({"written": self.written, "dropped": self.dropped}),
                ),
            )
            connection.commit()
        except Exception as exc:
            self.error = str(exc)
        finally:
            if connection is not None:
                connection.close()

    @property
    def actual_fps(self):
        if (
            self.written < 2
            or self.last_time is None
            or self.first_time is None
            or self.last_time == self.first_time
        ):
            return 0.0
        return (self.written - 1) / (self.last_time - self.first_time)


class Sequence:
    """Read-only random-access sequence. Each call owns its DB connection."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM metadata WHERE key='session'"
            ).fetchone()
            if row is None or len(row[0]) > 16_000_000:
                raise ValueError("Invalid sequence metadata")
            self.metadata = json.loads(row[0])
            if self.metadata.get("version") != 1:
                raise ValueError("Unsupported sequence version")
            self.index = db.execute(
                "SELECT id,timestamp FROM frames ORDER BY id"
            ).fetchall()
        if not self.index:
            raise ValueError("Sequence contains no completed frames")
        stamps = np.array([row[1] for row in self.index], dtype=float)
        if not np.isfinite(stamps).all() or (np.diff(stamps) <= 0).any():
            raise ValueError(
                "Sequence timestamps must be finite and strictly increasing"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _decode(blob, count):
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(blob, count + 1)
        if len(decoded) != count or not decoder.eof:
            raise ValueError("Corrupt sequence frame")
        return decoded

    def frame(self, index):
        with self.connect() as db:
            row = db.execute(
                "SELECT timestamp,height,width,raw,brightness FROM frames WHERE id=?",
                (self.index[index][0],),
            ).fetchone()
        stamp, h, w, raw, brightness = row
        if not 0 < h * w <= 1_048_576 or min(h, w) <= 0:
            raise ValueError("Invalid sequence dimensions")
        return Frame(
            np.frombuffer(self._decode(raw, h * w * 2), "<u2").reshape(h, w).copy(),
            np.frombuffer(self._decode(brightness, h * w), np.uint8)
            .reshape(h, w)
            .copy(),
            stamp,
        )

    @property
    def times(self):
        times = np.array([row[1] for row in self.index])
        return times - times[0]
