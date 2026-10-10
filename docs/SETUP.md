# Setup & Troubleshooting Guide

Hands-on companion to the [README](../README.md). The README is the protocol
reference and overview; this file is the "how do I actually build and run it,
and what do I do when it doesn't work" doc. It grows as people hit issues — PRs
and notes welcome.

---

## 1. Wiring

Read-only tap: only the RS-485 module's `RXD` goes to the ESP. `TXD` is left
unconnected — that is what guarantees the monitor can never transmit on the bus.

![ESP32 to S1/S2 bus, read-only sniffing](../images/wiring.png)

| RS-485 module | Connects to | Notes |
|---|---|---|
| `A` | S1 (bus) | differential pair; no ground on the bus |
| `B` | S2 (bus) | if no frames decode, swap `A`/`B` — polarity isn't critical for a listener |
| `RXD` | ESP32 RX pin | GPIO must match `rx_pin:` in your YAML (see note below) |
| `VCC` | ESP32 `3V3` | some modules want 5 V — check yours |
| `GND` | ESP32 `GND` | **required.** Both GND pads if the module has two |
| `TXD` | **leave unconnected** | keeps the tap read-only |

> **Pick the RX pin for your board.** The diagram shows `RX2` (GPIO16 on a
> classic ESP32). The shipped `example_midea_s1s2.yaml` targets an **ESP32-C3
> SuperMini** and uses **GPIO20**. Set `uart: rx_pin:` to a free RX-capable pin
> on *your* board and wire `RXD` to that pin — the two just have to agree.

> **Measure the bus voltage first.** On separate-supply central/ducted systems
> S1/S2 is ~5 V. Shared-supply mini-splits can run this pair at mains-level,
> hazardous potentials on the same terminals. Never assume — measure.

---

## 2. Install

One-time setup on the PC.

**Get the repo.** Everyone needs it — the ESP firmware builds from the local
`components/` folder. These docs and the systemd unit use
`/opt/midea-s1s2-rs485-monitor`:

```bash
sudo git clone https://github.com/MidATRIX/midea-s1s2-rs485-monitor.git /opt/midea-s1s2-rs485-monitor
sudo chown -R $USER: /opt/midea-s1s2-rs485-monitor
cd /opt/midea-s1s2-rs485-monitor
```

The `chown` makes the folder yours, so creating the venv, editing
`secrets.yaml` and running the capture don't need `sudo`. To update later:
`git pull` (your `secrets.yaml` is gitignored and stays put).

*No git?* GitHub → **Code → Download ZIP** works too: it extracts as
`midea-s1s2-rs485-monitor-main`, so move it to `/opt/midea-s1s2-rs485-monitor`
and run the same `chown`. Updating means downloading again — don't overwrite
your `secrets.yaml`.

*Somewhere other than `/opt`?* Fine — e.g. `~/midea-s1s2-rs485-monitor`. Only
the paths in `tools/midea-s1s2-capture.service` need to match.

Everything below runs from the repo folder.

**Python packages, in a virtual environment:**

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Run `source venv/bin/activate` again in any new terminal before using
`esphome` or the capture script.

**Using `--amqtt` (the built-in broker, see §5)? Open the MQTT port.** The ESP
then sends its frames to port 1883 on this PC, so that port must be reachable
across your LAN. (Using your own broker on another machine? Skip this.) Check
your firewall:

```bash
sudo ufw status                   # Ubuntu/Debian
sudo firewall-cmd --state         # Fedora/RHEL
```

If one is active, allow MQTT:

```bash
sudo ufw allow 1883/tcp
# or
sudo firewall-cmd --permanent --add-port=1883/tcp && sudo firewall-cmd --reload
```

InfluxDB needs no inbound rule — the capture connects out to it.

---

## 3. Configure: `secrets.yaml` (the one config file)

Everything lives in one file in the repo root. The ESP is flashed from it and
the capture script reads the same file, so the two can't disagree. It's
gitignored.

```bash
cp secrets.yaml.example secrets.yaml
# edit secrets.yaml
```

| Key | Used by | What to put |
|---|---|---|
| `wifi_ssid`, `wifi_password` | ESP | your WiFi |
| `mqtt_broker` | ESP + capture | IP of your MQTT broker (or of this PC with `--amqtt`, see §5) |
| `mqtt_user`, `mqtt_pass` | ESP + capture | your broker's login. Ships as `midea-s1s2` / `midea-s1s2`, which is the login `--amqtt` creates |
| `influx_url` | capture | where InfluxDB runs, e.g. your HA host if you use HA's InfluxDB add-on |
| `influx_token` | capture | an InfluxDB API token with write access to the bucket |

> **Flashing from the ESPHome dashboard inside Home Assistant?** Then your
> `secrets.yaml` lives on the HA box. Copy it to the PC that runs the capture
> (repo root), or pass its path: `python3 s1s2_capture.py /path/to/secrets.yaml`.

### Optional settings

These have defaults that match the Grafana dashboard, so most people never add
them. To change one, add the key to `secrets.yaml`:

| Key | Default |
|---|---|
| `mqtt_port` | `1883` |
| `mqtt_topic_prefix` | `midea_s1s2/frames` |
| `influx_org` | `midea` |
| `influx_bucket` | `midea_s1s2` |
| `influx_measurement` | `s1s2_raw` |
| `sqlite_path` | *(off)* — set a file path to also mirror frames to a local SQLite database |

> **`mqtt_port` and `mqtt_topic_prefix` must also be changed on the ESP side**,
> because ESPHome can't treat a secret as optional. Edit
> `example_midea_s1s2.yaml`: add `port: <n>` under `mqtt:`, or change
> `raw_topic_prefix:`. Then add the matching key to `secrets.yaml`.
>
> Changing `influx_bucket` or `influx_measurement` means the Grafana dashboard
> queries need the same change.

---

## 4. Flash the ESP

```bash
source venv/bin/activate
esphome run example_midea_s1s2.yaml
```

Decoded values arrive in Home Assistant over the **native API** (add the
ESPHome integration / accept the discovered device) — no MQTT needed for HA.
Raw frames go to MQTT separately, for archiving.

---

## 5. MQTT broker: yours, or `--amqtt`

The ESP publishes raw frames to exactly **one** broker — ESPHome has no
failover. `mqtt_broker` in `secrets.yaml` is the only broker it talks to, and
the capture script reads the same value.

### Your own broker (recommended)

Already running Mosquitto, Home Assistant's Mosquitto add-on, or any other MQTT
broker? Use it. In `secrets.yaml`, set `mqtt_broker` to its IP and
`mqtt_user` / `mqtt_pass` to a login it accepts. That's all: the ESP and the
capture both connect with exactly those values.

Your broker must accept connections from the ESP over the LAN (Mosquitto 2.x
only listens on localhost until you configure a listener). If it runs on your
Home Assistant box, capture stops whenever HA is down.

### No broker? Use `--amqtt`

Run the capture with `--amqtt` and it becomes the broker: it starts a built-in
MQTT broker on this PC (port 1883) whose only login is `mqtt_user` /
`mqtt_pass` from `secrets.yaml`. It always requires that login; there's no
anonymous access.

What `--amqtt` needs:

1. **`secrets.yaml`:** `mqtt_broker` = **this PC's** LAN IP. Leave `mqtt_user` /
   `mqtt_pass` at the shipped `midea-s1s2` (or change both; they just can't be
   empty).
2. **The ESP flashed with that `secrets.yaml`**, so it uses the same IP and
   login.
3. **Port 1883 open** in this PC's firewall (§2).
4. **Nothing else on this PC using port 1883.** The capture refuses to start if
   it is, and says so.
5. **This PC's IP doesn't change.** Give it a DHCP reservation in your router.
   If its IP changes, the ESP keeps trying the old address.
6. **Running as a service?** The systemd unit doesn't use `--amqtt` by default;
   add it to the end of `ExecStart`.

You'll know it's working when the capture prints
`[broker] built-in broker listening on :1883 (login: midea-s1s2)`, then
`[mqtt] connected`, and frames start scrolling; `esphome logs` shows the ESP's
MQTT connected.

---

## 6. Run the capture

```bash
source venv/bin/activate
python3 tools/s1s2_capture.py            # your broker (mqtt_broker)
python3 tools/s1s2_capture.py --amqtt    # or: be the broker (see §5)
```

It reads `secrets.yaml` from the repo root (pass a path to use another one). At
startup it prints which broker it's using, then
`[influx] startup check OK` if InfluxDB accepts the URL, token, org and bucket.

It writes the six data frames (`0100_20`, `0001_20`, `0001_50`–`53`) to
**InfluxDB** as per-byte integer fields — `IDU13`, `ODU6`, `HPD13`, … — in
measurement `s1s2_raw`. The Grafana dashboard decodes those in Flux. Every frame
is also printed to the console.

### Run it as a service (do this)

Frames published while the capture is down are **lost** — MQTT at QoS 0 does not
backfill. Keep it always-on with the included systemd unit so InfluxDB has no
gaps:

Before installing it, edit the unit:

- **`User=`** — the user that owns the repo folder (the one you ran `chown`
  for in §2).
- **The paths** — only if you put the repo somewhere other than
  `/opt/midea-s1s2-rs485-monitor`.
- **`--amqtt`** — add it to the end of `ExecStart` if you use the built-in
  broker.

```bash
sudo cp tools/midea-s1s2-capture.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now midea-s1s2-capture
journalctl -u midea-s1s2-capture -f
```

---

## 7. Troubleshooting

### No sensors / no valid frames in Home Assistant

1. **Ground.** The #1 cause. Every GND pad on the RS-485 module must tie to the
   ESP's `GND`. The S1/S2 bus has no ground of its own — all grounding is on the
   ESP side. No shared reference → no decode.
2. **Wrong RX pin.** `uart: rx_pin:` must match the pin `RXD` is physically on.
3. **Swap A/B.** Polarity isn't critical for a listener; if nothing decodes,
   try swapping.
4. **Baud.** Must be `4800`. The component enforces this and warns otherwise.
5. **CRC errors climbing.** Watch the `crc_errors` diagnostic sensor. A few at
   boot is normal (syncing mid-stream); a steadily rising count means noise or a
   marginal connection.

### Frames in HA but nothing in InfluxDB

- Is the capture running? `systemctl status midea-s1s2-capture` or check the
  console. `[influx] STARTUP CHECK FAILED` or `[influx] write failed` lines mean
  it can't write to InfluxDB — check `influx_url` and `influx_token` in
  `secrets.yaml` (and `influx_org` / `influx_bucket` if you overrode them).
- Is the ESP actually publishing? Check `raw_topic_prefix` is set in the YAML
  and the ESP's `mqtt_broker` matches the broker the capture is subscribed to.
- Quick broker sanity check (`mosquitto_sub` comes in the `mosquitto-clients`
  package; it works against the built-in broker too):
  ```bash
  mosquitto_sub -h <broker> -t 'midea_s1s2/frames/#' -v
  ```

### ESP keeps reconnecting to MQTT

Look at the error in `esphome logs`:

- **`not authorized` / `rc=5`:** the login was rejected. `mqtt_user` /
  `mqtt_pass` the ESP was flashed with don't match the broker (with `--amqtt`:
  don't match the `secrets.yaml` the capture is reading). Reflash after fixing.
- **`select() timeout` / `connection refused`:** the ESP can't reach the broker.
  Wrong `mqtt_broker` IP, the broker isn't running, or a firewall is blocking
  port 1883.

The ESP retries one IP forever; it will not find a second broker.

### Capture says `port 1883 is already in use`

You ran `--amqtt` while another MQTT broker is already running on this PC. Use
that broker instead (run without `--amqtt`, `mqtt_broker` = this PC's IP), or
stop it.

### Watching whether a "static" frame ever moves

Enable the matching `raw_frame_*` diagnostic text sensor in HA (they ship hidden
+ disabled). Its `last_changed` tells you if/when that frame type moved. With the
SQLite mirror on (`sqlite_path`), the `byte_changes` table shows exactly which
byte index changed and when.

---

## 8. FAQ

**Do I need Home Assistant?** No. HA gets decoded sensors over the native API,
but the raw MQTT → InfluxDB → Grafana path is fully independent of HA.

**Do I need MQTT if I only want HA sensors?** No. Drop the `mqtt:` block and the
`raw_topic_prefix` line; decoded sensors still flow over the native API.

**Can this control the heat pump?** No, by design. `TXD` is unconnected and the
component is receive-only. It can never transmit on the bus.

**Why per-frame publishing instead of per-cycle?** A flag that's set for a single
frame survives, instead of being averaged away across a ~3.6 s cycle.
