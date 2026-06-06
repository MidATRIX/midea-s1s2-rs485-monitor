#!/usr/bin/env python3
"""
Midea S1S2 Bus Simulator
========================
Replays LOW OUTPUT captured frames from a daily SQLite database over a 
TCP socket, reproducing the original bus timing as closely as possible.
This means 6 frames every 3 seconds vs 24 frames every 3 seconds.

Usage
-----
  python3 simulator.py <database.db> [HHMM]
  python3 simulator.py HeatModeSample.db 0321 - This will start a defrost cycle
  python3 simulator.py CoolModeSample.db 1052 - This will start a 8hr cycle

  <database.db>   Path to a daily telemetry database
  [HHMM]          Optional start time (e.g. 1430 to start from 2:30 PM)

The simulator listens on localhost:5555 and waits for a client (e.g. main.py
with --ip 127.0.0.1 --port 5555). Each time a client connects, it streams the
full database from the requested start time, then waits for the next connection.

Frame format
------------
All frames are emitted as clean LL+8 bytes with no trailing padding:
  [A0][addr_hi][addr_lo][msg_id][LL][payload x LL][0x00][CRC_lo][CRC_hi]
This matches the output of the new FrameBuffer which strips padding itself.

Timing
------
  - Inter-frame gap within a cycle : FRAME_GAP_S  (default 0.10 s)
  - Between cycles                 : actual timestamp delta from the DB,
                                     minus the time spent transmitting,
                                     clamped to [0, MAX_CYCLE_GAP_S]
"""

import sys
import sqlite3
import time
import socket
from datetime import datetime

# ── Tunables ──────────────────────────────────────────────────────────────────
HOST           = 'localhost'
PORT           = 5555
FRAME_GAP_S    = 0.10   # pause between frames within one cycle (seconds)
MAX_CYCLE_GAP_S = 10.0  # any DB gap longer than this is treated as a dead zone

# ── Frame construction ────────────────────────────────────────────────────────

def _crc16(data: bytes) -> tuple:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFF, (crc >> 8) & 0xFF


def build_frame(msg_id: str, payload: list, byte17: int = 0x00) -> bytes:
    """
    Reconstruct a full wire frame from a DB row's msg_id and payload bytes.
 
    msg_id format: '<addr_hex>_<type_hex>'  e.g. '0001_20' or '0100_53'
    payload      : list of 12 integers (DB columns *5 through *16)
 
    Returns LL+8 bytes — NO trailing padding byte regardless of direction.
    """
    addr_str, type_str = msg_id.split('_')
    addr_hi  = int(addr_str[:2], 16)
    addr_lo  = int(addr_str[2:], 16)
    msg_type = int(type_str, 16)

    payload_bytes = bytes(payload)
    ll = len(payload_bytes)

    # Header + payload + fixed 0x00 pre-CRC byte (part of the wire format)
    body = bytes([0xA0, addr_hi, addr_lo, msg_type, ll]) + payload_bytes + bytes([byte17])
    crc_lo, crc_hi = _crc16(body)
    return body + bytes([crc_lo, crc_hi])


# ── DB helpers ────────────────────────────────────────────────────────────────

# Columns for each of the 6 frame slots stored in the DB
FRAME_SLOTS = [
    ('frame1', 'IDU'),
    ('frame2', 'ODU'),
    ('frame3', 'HPA'),
    ('frame4', 'HPB'),
    ('frame5', 'HPC'),
    ('frame6', 'HPD'),
]


def _discover_table(cur) -> str:
    """Find the data table — works regardless of what it's named."""
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall() if r[0] != 'sqlite_sequence']
    if not tables:
        raise RuntimeError("No data tables found in database.")
    for preferred in ('scomms_logs', 'raw_frames'):
        if preferred in tables:
            return preferred
    return tables[0]


def load_rows(db_path: str, start_time: str = None) -> list:
    """
    Load all rows from the DB, optionally filtered to start_time (HHMM string).
    Returns a list of dicts, one per row.
    """
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    table = _discover_table(cur)
    print(f"  Table: {table}")

    if start_time:
        hh = start_time[:2]
        mm = start_time[2:]
        time_str = f"{hh}:{mm}:00"
        cur.execute(
            f"SELECT * FROM {table} WHERE time(timestamp) >= ? ORDER BY id ASC",
            (time_str,)
        )
    else:
        cur.execute(f"SELECT * FROM {table} ORDER BY id ASC")

    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def row_to_frames(row: dict) -> list:
    """
    Convert one DB row into a list of raw frame bytes (one per slot).
    Skips any slot whose msg_id is NULL.
    """
    frames = []
    for frame_col, prefix in FRAME_SLOTS:
        msg_id = row.get(frame_col)
        if not msg_id:
            continue
        payload = [row[f'{prefix}{j}'] for j in range(5, 17)]
        byte17  = row.get(f'{prefix}17', 0x00) or 0x00
        frames.append(build_frame(msg_id, payload))
    return frames


# ── Simulator main loop ───────────────────────────────────────────────────────

def stream_to_client(client: socket.socket, rows: list):
    """
    Replay all rows to a connected client, respecting original timestamps.
    Returns when the stream ends or the client disconnects.
    """
    total = len(rows)
    sent_cycles = 0

    for i, row in enumerate(rows):

        cycle_start = time.monotonic()

        # Build and send the 6 frames for this cycle
        frames = row_to_frames(row)
        for frame in frames:
            client.sendall(frame)
            time.sleep(FRAME_GAP_S)

        sent_cycles += 1

        # Progress heartbeat every 100 cycles
        if sent_cycles % 100 == 0:
            pct = (i + 1) / total * 100
            ts  = row['timestamp']
            print(f"  [{ts}]  cycle {i+1}/{total}  ({pct:.1f}%)")

        # ── Inter-cycle timing ────────────────────────────────────────────
        if i + 1 >= total:
            print("  End of database reached.")
            break

        next_row  = rows[i + 1]
        this_ts   = datetime.strptime(row['timestamp'],      "%Y-%m-%d %H:%M:%S")
        next_ts   = datetime.strptime(next_row['timestamp'], "%Y-%m-%d %H:%M:%S")
        db_gap    = (next_ts - this_ts).total_seconds()
        time_used = time.monotonic() - cycle_start

        # Clamp: skip dead zones (compressor off, DB gaps), never go negative
        wait = db_gap - time_used
        if wait > MAX_CYCLE_GAP_S:
            print(f"  Dead zone of {db_gap:.1f}s — skipping to next cycle.")
            wait = 0.5          # brief pause so the receiver can breathe
        elif wait < 0:
            wait = 0            # we're already behind, don't sleep

        if wait > 0:
            time.sleep(wait)


def run(db_path: str, start_time: str = None):

    rows = load_rows(db_path, start_time)
    if not rows:
        print(f"No rows found" + (f" at or after {start_time}" if start_time else "") + ".")
        sys.exit(1)

    print(f"Loaded {len(rows)} cycles from {db_path}")
    if start_time:
        print(f"Starting from {start_time[:2]}:{start_time[2:]}:00  "
              f"(first row: {rows[0]['timestamp']})")

    # Verify our frame builder produces valid frames
    test_frames = row_to_frames(rows[0])
    print(f"Frame check on row 0: {len(test_frames)} frames, "
          f"sizes={[len(f) for f in test_frames]}")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"Listening on {HOST}:{PORT} — waiting for client...")

    try:
        while True:
            client, addr = srv.accept()
            print(f"\nClient connected from {addr}")
            try:
                stream_to_client(client, rows)
            except (ConnectionResetError, BrokenPipeError):
                print(f"Client {addr} disconnected early.")
            finally:
                client.close()
                print(f"Connection closed. Waiting for next client...")

    except KeyboardInterrupt:
        print("\nSimulator stopped.")
    finally:
        srv.close()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 simulator.py <database.db> [HHMM]")
        sys.exit(1)

    db_file    = sys.argv[1]
    start_arg  = sys.argv[2] if len(sys.argv) >= 3 else None

    if start_arg:
        if len(start_arg) != 4 or not start_arg.isdigit():
            print("Error: Time must be exactly 4 digits, e.g. 1430")
            sys.exit(1)

    run(db_file, start_arg)
