#!/usr/bin/env python3
"""s1s2_capture.py - PC-side raw-frame logger for midea-s1s2-rs485-monitor.

Subscribes to the ESP's raw-frame MQTT firehose (<prefix>/#) and persists every
CRC-valid frame. Two sinks, from one subscription:

  * InfluxDB v2  - the forever store. One point per data frame (0100_20,
    0001_20, 0001_50..53) in measurement `s1s2_raw`, with each frame-absolute
    byte 5..17 as an integer field named IDU5..17 / ODU5..17 / HPA / HPB / HPC /
    HPD (e.g. ODU6, HPD13). Decoding happens in the Grafana Flux queries, so the
    raw bytes are never lost to a decode bug. Written over plain HTTP (urllib) -
    no influxdb-client dependency.
  * SQLite (WAL) - optional, off unless you pass --sqlite DIR. Daily files
    (telemetry_YYYY_MM_DD.db), one table per data frame (IDU, ODU, HPA, HPB,
    HPC, HPD): timestamp + payload bytes 5..17, one row per bus cycle.

Ghost-byte watcher (always on): prints a [ghost] line, and appends it to
ghost_bytes.log next to this script, whenever a watched byte changes. Watched =
every payload byte NOT already published to Home Assistant (see KNOWN_BYTES),
plus every payload byte of the frames we don't decode (_21, _91, acks, boot).

Console output is quiet by default (startup status, errors, ghost bytes).
--live-hex also prints every frame as it arrives, plus the Influx
"wrote N points" heartbeat.

Config: everything comes from the same secrets.yaml the ESP is flashed with
(repo root by default), so the ESP and this script can't disagree.

Dependencies (from the repo root, inside the venv):
    pip install -r requirements.txt

Broker: the ESP always publishes to one broker.
  * default  -> connect to your broker at mqtt_broker (Mosquitto, HA's add-on...)
      Run:
        python3 s1s2_capture.py
  * --amqtt  -> run a built-in broker (amqtt) on this PC instead, with the
                mqtt_user / mqtt_pass login; point mqtt_broker at this PC.
      Run:
        python3 s1s2_capture.py --amqtt
"""

import argparse
import asyncio
import atexit
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SECRETS = os.path.join(REPO_ROOT, "secrets.yaml")


# ---------------------------------------------------------------------------
# Config (secrets.yaml)
# ---------------------------------------------------------------------------
# Optional keys and their defaults. Add any of these to secrets.yaml to
# override (see docs/SETUP.md). mqtt_port / mqtt_topic_prefix must ALSO be
# changed in example_midea_s1s2.yaml so the ESP matches.
DEFAULTS = {
    "mqtt_port": 1883,
    "mqtt_topic_prefix": "midea_s1s2/frames",
    "influx_url": "http://127.0.0.1:8086",
    "influx_org": "midea",
    "influx_bucket": "midea_s1s2",
    "influx_measurement": "s1s2_raw",
}


def load_secrets(path, amqtt_mode):
    try:
        import yaml
    except ImportError:
        sys.exit("[config] reading secrets.yaml needs PyYAML: "
                 "`pip install -r requirements.txt` inside the venv")
    if not os.path.exists(path):
        sys.exit(f"[config] {path} not found - copy secrets.yaml.example to "
                 f"secrets.yaml in the repo root and fill it in")
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        sys.exit(f"[config] {path} is not a key: value file")

    # YAML may turn values like 123456 or 1883 into numbers - use strings
    cfg = {k: ("" if v is None else str(v)) for k, v in DEFAULTS.items()}
    cfg.update({k: ("" if v is None else str(v)) for k, v in raw.items()})

    required = ["mqtt_user", "mqtt_pass", "influx_token"]
    if not amqtt_mode:
        required.append("mqtt_broker")
    missing = [k for k in required if k not in raw]
    if missing:
        sys.exit(f"[config] {path} is missing: {', '.join(missing)}")
    if amqtt_mode and not (cfg["mqtt_user"] and cfg["mqtt_pass"]):
        sys.exit("[config] --amqtt needs mqtt_user and mqtt_pass set in secrets.yaml "
                 "(the built-in broker always requires a login)")
    try:
        cfg["mqtt_port"] = int(cfg["mqtt_port"])
    except ValueError:
        sys.exit(f"[config] mqtt_port must be a number, got {cfg['mqtt_port']!r}")
    return cfg


# ---------------------------------------------------------------------------
# InfluxDB v2 line-protocol writer (batched, urllib - no extra deps)
# ---------------------------------------------------------------------------
#   msg_id  -> InfluxDB field prefix (matches the Grafana dashboard + the
#   frame-absolute byte naming in midea_s1s2.cpp: IDU13, ODU6, HPD13, ...)
FIELD_PREFIX = {
    "0100_20": "IDU",   # IDU core
    "0001_20": "ODU",   # ODU core
    "0001_50": "HPA",
    "0001_51": "HPB",
    "0001_52": "HPC",
    "0001_53": "HPD",
}


class InfluxWriter:
    def __init__(self, url, org, bucket, measurement, token, heartbeat=False):
        self.enabled = True
        self.heartbeat = heartbeat   # print "wrote N points" lines (--live-hex only)
        query = urllib.parse.urlencode({"org": org, "bucket": bucket, "precision": "ns"})
        self.url = f"{url.rstrip('/')}/api/v2/write?{query}"
        self.measurement = measurement
        self.token = token
        self.flush_interval = 2.0    # seconds between batched writes
        self.flush_max = 200         # or sooner, once this many lines are queued
        self._buf = []
        self._written = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._startup_check()
        threading.Thread(target=self._flusher, daemon=True).start()

    def _startup_check(self):
        # Empty-body write: validates URL reachability + token + org/bucket
        # WITHOUT writing any point. 204 = all good; 401 = bad token; 404 = bad
        # org/bucket or not InfluxDB v2.
        req = urllib.request.Request(
            self.url, data=b"",
            headers={"Authorization": f"Token {self.token}",
                     "Content-Type": "text/plain; charset=utf-8"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            print(f"[influx] startup check OK - reachable, token + bucket valid "
                  f"({self.url.split('?')[0]})")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode(errors="replace")[:300]
            except Exception:
                pass
            print(f"[influx] STARTUP CHECK FAILED: HTTP {e.code} {e.reason}: {body}")
        except (urllib.error.URLError, OSError) as e:
            print(f"[influx] STARTUP CHECK FAILED: {e}")

    def add(self, msg_id, hex_payload, ts_ns):
        if not self.enabled:
            return
        prefix = FIELD_PREFIX.get(msg_id)
        if prefix is None:          # only the six data frames go to Influx
            return
        try:
            b = bytes.fromhex(hex_payload)
        except ValueError:
            return
        if len(b) < 18:
            return
        # frame-absolute bytes 5..17 as integer fields: ODU6=18i, HPD13=63i ...
        # These names are what grafana/grafana-dashboard.json queries.
        fields = ",".join(f"{prefix}{i}={b[i]}i" for i in range(5, 18))
        line = f"{self.measurement} {fields} {ts_ns}"
        with self._lock:
            self._buf.append(line)
            if len(self._buf) >= self.flush_max:
                self._flush_locked()

    def _flusher(self):
        while not self._stop.wait(self.flush_interval):
            with self._lock:
                self._flush_locked()

    def _flush_locked(self):
        if not self._buf:
            return
        body = "\n".join(self._buf).encode()
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Authorization": f"Token {self.token}",
                     "Content-Type": "text/plain; charset=utf-8"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            n = len(self._buf)
            self._written += n
            self._buf.clear()
            # heartbeat so you can SEE writes happening (throttled)
            if self.heartbeat and self._written // 100 != (self._written - n) // 100:
                print(f"[influx] wrote {self._written} points total")
        except urllib.error.HTTPError as e:
            # Influx puts the real reason (bad bucket/org/token, parse error,
            # wrong API version) in the response body - surface it.
            body = ""
            try:
                body = e.read().decode(errors="replace")[:300]
            except Exception:
                pass
            print(f"[influx] HTTP {e.code} {e.reason}: {body}  "
                  f"({len(self._buf)} lines buffered)")
            self._cap_buffer()
        except (urllib.error.URLError, OSError) as e:
            # transient: keep the buffer and retry on the next flush
            print(f"[influx] write failed ({e}); {len(self._buf)} lines buffered")
            self._cap_buffer()

    def _cap_buffer(self):
        if len(self._buf) > 10000:
            dropped = len(self._buf) - 10000
            self._buf = self._buf[-10000:]
            print(f"[influx] buffer cap hit, dropped {dropped} oldest lines")

    def close(self):
        if not self.enabled:
            return
        self._stop.set()
        with self._lock:
            self._flush_locked()


# ---------------------------------------------------------------------------
# SQLite (opt-in: --sqlite DIR) - daily files, one table per data frame,
# one row per bus cycle
# ---------------------------------------------------------------------------
class SqliteWriter:
    FLUSH_ON = "0001_53"   # last data frame of a bus cycle -> write the cycle

    def __init__(self, db_dir):
        self.enabled = bool(db_dir)
        if not self.enabled:
            return
        self.db_dir = db_dir
        os.makedirs(db_dir, exist_ok=True)
        self.conn = None
        self.day = None
        self.latch = {}    # msg_id -> (timestamp, frame bytes), latest this cycle

    def _open_for_today(self):
        today = datetime.now().date()
        if self.conn is not None and self.day == today:
            return
        if self.conn is not None:          # day rolled over: close yesterday's file
            self.conn.commit()
            self.conn.close()
        path = os.path.join(self.db_dir, f"telemetry_{today:%Y_%m_%d}.db")
        self.conn = sqlite3.connect(path)
        # WAL: a crash or power loss can't corrupt the file; worst case the
        # last cycle is lost. synchronous=NORMAL is the safe, fast pairing.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        for prefix in FIELD_PREFIX.values():
            cols = ", ".join(f"{prefix}{i} INTEGER" for i in range(5, 18))
            self.conn.execute(
                f"CREATE TABLE IF NOT EXISTS {prefix} (timestamp TEXT NOT NULL, {cols})")
        self.conn.commit()
        self.day = today
        print(f"[sqlite] writing {path}")

    def add(self, msg_id, frame, ts_local):
        if not self.enabled or msg_id not in FIELD_PREFIX or len(frame) < 18:
            return
        self.latch[msg_id] = (ts_local, frame)   # 0001_20 repeats: last one wins
        if msg_id == self.FLUSH_ON:
            self._flush()

    def _flush(self):
        self._open_for_today()
        for msg_id, (ts, b) in self.latch.items():
            prefix = FIELD_PREFIX[msg_id]
            cols = ", ".join(["timestamp"] + [f"{prefix}{i}" for i in range(5, 18)])
            marks = ", ".join("?" * 14)
            self.conn.execute(f"INSERT INTO {prefix} ({cols}) VALUES ({marks})",
                              [ts] + [b[i] for i in range(5, 18)])
        self.conn.commit()
        self.latch.clear()

    def close(self):
        if self.enabled and self.conn is not None:
            self.conn.commit()
            self.conn.close()


# ---------------------------------------------------------------------------
# Ghost-byte watcher (always on)
# ---------------------------------------------------------------------------
# Payload bytes already published to Home Assistant (decoded sensors plus the
# unknown_* raw sensors) - NOT watched. Every other byte 5..17 of these frames
# is a ghost. Based on the old capture's SETTLED_BYTES, plus IDU8 / IDU10,
# which now go to HA. Frames not listed here (_21, _91, IDU acks, boot/other)
# have every payload byte watched.
KNOWN_BYTES = {
    "0100_20": {6, 7, 8, 10, 11, 12, 13, 14, 17},
    "0001_20": {6, 9, 10, 11, 12, 13, 14, 15, 17},
    "0001_50": {11, 12, 14, 15, 16, 17},
    "0001_51": {5, 6, 11, 12, 13},
    "0001_52": {7, 8, 9, 10, 11, 13},
    "0001_53": {6, 7, 8, 9, 11, 12, 13},
}
GHOST_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ghost_bytes.log")


class GhostWatcher:
    def __init__(self, log_path=GHOST_LOG):
        self.log_path = log_path
        self.last = {}     # msg_id -> previous frame bytes

    def check(self, msg_id, frame):
        prev = self.last.get(msg_id)
        self.last[msg_id] = frame
        if prev is None:
            return
        known = KNOWN_BYTES.get(msg_id, set())
        prefix = FIELD_PREFIX.get(msg_id)
        end = min(len(prev), len(frame)) - 2      # stop before the 2 CRC bytes
        lines = []
        for i in range(5, end):
            if i in known or prev[i] == frame[i]:
                continue
            name = f"{prefix}{i}" if prefix else f"B{i}"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{ts}  {msg_id}  {name}  0x{prev[i]:02X} -> 0x{frame[i]:02X}  "
                         f"{frame.hex().upper()}")
        if not lines:
            return
        for ln in lines:
            print("[ghost]", ln)
        try:
            with open(self.log_path, "a") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError as e:
            print(f"[ghost] can't write {self.log_path}: {e}")


# ---------------------------------------------------------------------------
# Built-in broker (--amqtt): amqtt with a single username/password login
# ---------------------------------------------------------------------------
def _port_free(port):
    # Try to bind the port ourselves - fails if another broker is listening.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def start_builtin_broker(port, user, password):
    try:
        from amqtt.broker import Broker
        from pwdlib.hashers.argon2 import Argon2Hasher   # ships with amqtt 0.12
    except ImportError:
        sys.exit("[broker] --amqtt needs amqtt 0.12: "
                 "`pip install -r requirements.txt` inside the venv")
    if not _port_free(port):
        sys.exit(f"[broker] port {port} is already in use - another MQTT broker is "
                 f"probably running on this PC. Run without --amqtt to use it, or "
                 f"stop it first.")

    # amqtt checks logins against a password file of `user:argon2-hash` lines.
    # Write one to a private temp dir (removed on exit).
    tmpdir = tempfile.mkdtemp(prefix="s1s2_amqtt_")
    atexit.register(shutil.rmtree, tmpdir, True)
    pwfile = os.path.join(tmpdir, "passwd")
    with open(pwfile, "w") as f:
        f.write(f"{user}:{Argon2Hasher().hash(password)}\n")
    os.chmod(pwfile, 0o600)

    config = {
        "listeners": {"default": {"type": "tcp", "bind": f"0.0.0.0:{port}"}},
        # Only the password-file plugin: no anonymous access, no $SYS topics,
        # no topic ACLs. Tested against amqtt 0.12.1.
        "plugins": {
            "amqtt.plugins.authentication.FileAuthPlugin": {"password_file": pwfile},
        },
    }

    ready = threading.Event()
    failure = []

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _start():
            # amqtt's Broker() calls get_running_loop() in __init__, so it must
            # be constructed inside the running loop, not before it exists.
            broker = Broker(config)
            await broker.start()

        try:
            loop.run_until_complete(_start())
        except Exception as e:      # surface startup errors to the main thread
            failure.append(e)
            ready.set()
            return
        ready.set()
        loop.run_forever()

    threading.Thread(target=_run, daemon=True).start()
    if not ready.wait(10) or failure:
        sys.exit(f"[broker] built-in broker failed to start: "
                 f"{failure[0] if failure else 'timed out'}")
    print(f"[broker] built-in broker listening on :{port} (login: {user})")


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, *args):
    if rc == 0:
        topic = userdata["topic"]
        client.subscribe(topic)
        print(f"[mqtt] connected, subscribed to {topic}")
    elif rc == 5:
        print("[mqtt] connect refused: not authorized - mqtt_user / mqtt_pass in "
              "secrets.yaml don't match the broker's login")
    else:
        print(f"[mqtt] connect failed rc={rc}")


def on_message(client, userdata, msg):
    msg_id = msg.topic.rsplit("/", 1)[-1]           # .../frames/0001_20 -> 0001_20
    hex_payload = msg.payload.decode(errors="replace").strip().upper()
    if not hex_payload:
        return
    now = datetime.now(timezone.utc)
    ts_iso = now.isoformat()
    ts_ns = int(now.timestamp() * 1_000_000_000)
    userdata["influx"].add(msg_id, hex_payload, ts_ns)
    if userdata["live_hex"]:
        print(f"{ts_iso}  {msg_id:10s}  {hex_payload}")
    if msg_id == "residue":
        return
    try:
        frame = bytes.fromhex(hex_payload)
    except ValueError:
        return
    userdata["ghost"].check(msg_id, frame)
    ts_local = now.astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    userdata["sqlite"].add(msg_id, frame, ts_local)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Midea S1S2 raw-frame capture (MQTT -> InfluxDB)")
    ap.add_argument("secrets", nargs="?", default=DEFAULT_SECRETS,
                    help="path to secrets.yaml (default: the repo root)")
    ap.add_argument("--amqtt", action="store_true",
                    help="run the built-in broker on this PC (login = mqtt_user / "
                         "mqtt_pass) instead of connecting to mqtt_broker")
    ap.add_argument("--live-hex", action="store_true",
                    help="also print every frame as it arrives, and the Influx "
                         "write heartbeat")
    ap.add_argument("--sqlite", metavar="DIR",
                    help="also write daily SQLite files (telemetry_YYYY_MM_DD.db) to DIR")
    args = ap.parse_args()
    cfg = load_secrets(args.secrets, args.amqtt)

    port = cfg["mqtt_port"]
    user = cfg["mqtt_user"] or None
    passwd = cfg["mqtt_pass"] or None
    topic = cfg["mqtt_topic_prefix"].rstrip("/") + "/#"

    if args.amqtt:
        start_builtin_broker(port, user, passwd)
        host = "127.0.0.1"      # we are the broker; connect locally
        print(f"[mqtt] using the built-in broker (--amqtt) on :{port}")
    else:
        host = cfg["mqtt_broker"]
        print(f"[mqtt] using your broker at {host}:{port}")

    influx = InfluxWriter(cfg["influx_url"], cfg["influx_org"], cfg["influx_bucket"],
                          cfg["influx_measurement"], cfg["influx_token"],
                          heartbeat=args.live_hex)
    sqlite_w = SqliteWriter(args.sqlite)
    ghost = GhostWatcher()
    print(f"[sinks] influxdb=on sqlite={args.sqlite or 'off'} "
          f"ghost-log={ghost.log_path} live-hex={'on' if args.live_hex else 'off'}")

    userdata = {"influx": influx, "sqlite": sqlite_w, "ghost": ghost,
                "topic": topic, "live_hex": args.live_hex}
    client = mqtt.Client(userdata=userdata)
    if user:
        client.username_pw_set(user, passwd)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    try:
        client.connect(host, port, keepalive=60)
    except OSError as e:
        sys.exit(f"[mqtt] can't reach the broker at {host}:{port} ({e}). Check "
                 f"mqtt_broker in secrets.yaml and that the broker is running.")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[exit] stopping")
    finally:
        influx.close()
        sqlite_w.close()


if __name__ == "__main__":
    main()
