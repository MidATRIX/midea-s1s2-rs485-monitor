#include "midea_s1s2.h"
#include "esphome/core/log.h"
#include "esphome/core/helpers.h"

#ifdef USE_MQTT
#include "esphome/components/mqtt/mqtt_client.h"
#endif

#include <cmath>

namespace esphome {
namespace midea_s1s2 {

static const char *const TAG = "midea_s1s2";

// Largest sane payload length; anything bigger means we synced on noise.
static const uint8_t MAX_PAYLOAD_LEN = 32;

// One-liner publish helpers so every decode line stays readable:
//   PUB(current_draw, f[12] / 1.875f);
#define PUB(key, value) \
  if (this->key##_sensor_ != nullptr) this->key##_sensor_->publish_state(value)
#define PUB_TEXT(key, value) \
  if (this->key##_text_sensor_ != nullptr) this->key##_text_sensor_->publish_state(value)

// =====================================================================
// CONVERSION HELPERS — edit formulas here
// =====================================================================

// NTC thermistor curve (thanks fmck3516 / midea-telemetry-esphome).
// Takes float so the T4 fractional byte can be folded into the input:
//   ntc_temp(f[10] + f[15] / 256.0f)
static float ntc_temp(float v) {
  if (v <= 0.0f)
    return -66.0f;
  if (v >= 255.0f)
    return 255.0f;
  return 1.0f / (1.0f / 298.15f + std::log(0.81f * (255.0f - v) / v) / 4150.0f) - 273.15f;
}

// Steinhart-Hart curve for the discharge (TP) sensor (thanks fmck3516).
static float steinhart_temp(uint8_t v) {
  if (v == 0)
    return -48.0f;
  if (v >= 254)
    return (float) v;
  float l = std::log((255.0f - v) / (float) v);
  return 1.0f / (2.873e-3f + 2.491e-4f * l + 9.74e-7f * (l * l * l)) - 273.15f;
}

// Two's-complement signed byte.
static inline int8_t signed_byte(uint8_t v) { return (int8_t) v; }

// Mode enum — shared by IDU6 and ODU14.
static std::string mode_to_string(uint8_t v) {
  switch (v) {
    case 0x00: return "Off";
    case 0x01: return "Cool";
    case 0x02: return "Heat";
    case 0x03: return "Fan";
    case 0x04: return "Dry";
    case 0x06: return "Forced Cool";
    case 0x07: return "Defrost / Self Clean";
    case 0x09: return "ECO";
    case 0x0A: return "Forced Defrost";
    default: return str_sprintf("Unknown (0x%02X)", v);
  }
}

// IDU blower setting (IDU12). This is the commanded mode, not RPM —
// S1S2 does not carry a true indoor blower RPM byte.
static std::string fan_to_string(uint8_t v) {
  switch (v) {
    case 0x01: return "High";
    case 0x02: return "Medium";
    case 0x03: return "Low";
    case 0x06: return "Boost";
    case 0x0F: return "Auto";
    default: return str_sprintf("Raw (0x%02X)", v);
  }
}

// CRC-16/MODBUS: poly 0xA001 (reflected), init 0xFFFF, LSB-first.
static uint16_t crc16_modbus(const uint8_t *data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (uint8_t b = 0; b < 8; b++) {
      if (crc & 0x0001)
        crc = (crc >> 1) ^ 0xA001;
      else
        crc >>= 1;
    }
  }
  return crc;
}

// =====================================================================
// COMPONENT
// =====================================================================

void MideaS1S2Component::setup() {
  this->buf_.reserve(64);
  PUB(crc_errors, 0);
  // Build the msg_id -> raw-frame text_sensor map (only configured ones).
  this->register_frame_sensor_("0100_20", this->raw_frame_0100_20_text_sensor_);
  this->register_frame_sensor_("0001_20", this->raw_frame_0001_20_text_sensor_);
  this->register_frame_sensor_("0001_25", this->raw_frame_0001_25_text_sensor_);
  this->register_frame_sensor_("0100_25", this->raw_frame_0100_25_text_sensor_);
  this->register_frame_sensor_("0001_50", this->raw_frame_0001_50_text_sensor_);
  this->register_frame_sensor_("0001_51", this->raw_frame_0001_51_text_sensor_);
  this->register_frame_sensor_("0001_52", this->raw_frame_0001_52_text_sensor_);
  this->register_frame_sensor_("0001_53", this->raw_frame_0001_53_text_sensor_);
  this->register_frame_sensor_("0100_50", this->raw_frame_0100_50_text_sensor_);
  this->register_frame_sensor_("0100_51", this->raw_frame_0100_51_text_sensor_);
  this->register_frame_sensor_("0100_52", this->raw_frame_0100_52_text_sensor_);
  this->register_frame_sensor_("0100_53", this->raw_frame_0100_53_text_sensor_);
  this->register_frame_sensor_("0001_21", this->raw_frame_0001_21_text_sensor_);
  this->register_frame_sensor_("0100_21", this->raw_frame_0100_21_text_sensor_);
  this->register_frame_sensor_("0001_91", this->raw_frame_0001_91_text_sensor_);
  this->register_frame_sensor_("0100_91", this->raw_frame_0100_91_text_sensor_);
  this->register_frame_sensor_("other", this->raw_frame_other_text_sensor_);
}

void MideaS1S2Component::dump_config() {
  ESP_LOGCONFIG(TAG, "Midea S1S2 passive monitor:");
  ESP_LOGCONFIG(TAG, "  Raw frame topic prefix: %s",
                this->raw_topic_prefix_.empty() ? "(disabled)" : this->raw_topic_prefix_.c_str());
  this->check_uart_settings(4800);
}

void MideaS1S2Component::loop() {
  uint8_t b;
  while (this->available()) {
    if (!this->read_byte(&b))
      break;
    this->buf_.push_back(b);
  }
  this->drain_buffer_();
}

// Byte stream -> validated frames. Sync on 0xA0, length-driven, CRC-checked.
// Bytes that never form a valid frame are "residue": when raw_publish_residue_
// is on they are collected (minus 0xAA/0x55 UART noise) and published, so
// unknown framing (e.g. boot frames that don't use A0/CRC16) can be inspected.
void MideaS1S2Component::drain_buffer_() {
  while (true) {
    // leading non-A0 bytes are residue (between-frame junk / line noise)
    size_t start = 0;
    while (start < this->buf_.size() && this->buf_[start] != 0xA0)
      start++;
    if (start > 0) {
      this->collect_residue_(this->buf_.data(), start);
      this->buf_.erase(this->buf_.begin(), this->buf_.begin() + start);
    }

    if (this->buf_.size() < 5)
      return;  // need header + addr(2) + id + LL before we know the length

    uint8_t ll = this->buf_[4];
    if (ll > MAX_PAYLOAD_LEN) {
      // this 0xA0 was not a real header -> residue, skip it and rescan
      this->collect_residue_(this->buf_.data(), 1);
      this->buf_.erase(this->buf_.begin());
      continue;
    }

    size_t frame_len = (size_t) ll + 8;  // A0 + addr2 + id + LL + payload + B17 + CRC2
    if (this->buf_.size() < frame_len)
      return;  // wait for the rest

    uint16_t calc = crc16_modbus(this->buf_.data(), (size_t) ll + 6);  // A0..B17 inclusive
    uint16_t recv = (uint16_t) this->buf_[ll + 6] | ((uint16_t) this->buf_[ll + 7] << 8);

    if (calc == recv) {
      this->flush_residue_();  // emit residue gathered just before this good frame
      std::vector<uint8_t> f(this->buf_.begin(), this->buf_.begin() + frame_len);
      this->buf_.erase(this->buf_.begin(), this->buf_.begin() + frame_len);
      this->process_frame_(f);
    } else {
      // bad CRC: the leading A0 is residue; resync one byte forward
      this->crc_error_count_++;
      PUB(crc_errors, this->crc_error_count_);
      this->collect_residue_(this->buf_.data(), 1);
      this->buf_.erase(this->buf_.begin());
    }
  }
}

void MideaS1S2Component::process_frame_(const std::vector<uint8_t> &f) {
  // f[1..2] = device address (00 01 = ODU, 01 00 = IDU), f[3] = message id
  uint32_t key = ((uint32_t) f[1] << 16) | ((uint32_t) f[2] << 8) | f[3];

  // Publish EVERY CRC-valid frame, decoded or not — handshake (_21),
  // keepalive (_91), IDU acks, boot frames, anything. Topic is
  // <prefix>/<addr>_<type>, e.g. midea_s1s2/frames/0001_91.
  std::string msg_id = str_sprintf("%02X%02X_%02X", f[1], f[2], f[3]);
  this->publish_raw_(msg_id.c_str(), f);

  // Decode only the six frames we understand; the rest are published raw above.
  switch (key) {
    case 0x010020: this->decode_0100_20_(f); break;  // IDU core
    case 0x000120: this->decode_0001_20_(f); break;  // ODU core
    case 0x000150: this->decode_0001_50_(f); break;  // HPA
    case 0x000151: this->decode_0001_51_(f); break;  // HPB
    case 0x000152: this->decode_0001_52_(f); break;  // HPC
    case 0x000153: this->decode_0001_53_(f); break;  // HPD
    default: break;                                  // valid CRC, no decoder
  }
}

// Accumulate bytes that are not part of a valid frame. 0xAA (10101010) and
// 0x55 (01010101) are dropped as UART idle/transition noise. Everything else
// is buffered and published to <prefix>/residue on the next good frame (or
// when the buffer fills), so non-A0 framing can be studied.
void MideaS1S2Component::collect_residue_(const uint8_t *data, size_t n) {
  if (!this->raw_publish_residue_)
    return;
  for (size_t i = 0; i < n; i++) {
    uint8_t b = data[i];
    if (b == 0x00 || b == 0xAA || b == 0x55)
      continue;  // inter-frame padding (0x00) + alternating-bit line noise
    this->residue_.push_back(b);
    if (this->residue_.size() >= 64)
      this->flush_residue_();
  }
}

void MideaS1S2Component::flush_residue_() {
  if (this->residue_.empty())
    return;
  static const char HEX_CHARS[] = "0123456789ABCDEF";
  std::string hex;
  hex.reserve(this->residue_.size() * 2);
  for (uint8_t b : this->residue_) {
    hex += HEX_CHARS[b >> 4];
    hex += HEX_CHARS[b & 0x0F];
  }
  this->residue_.clear();  // clear regardless, so it can't grow unbounded
#ifdef USE_MQTT
  if (this->raw_topic_prefix_.empty())
    return;
  if (mqtt::global_mqtt_client == nullptr || !mqtt::global_mqtt_client->is_connected())
    return;
  mqtt::global_mqtt_client->publish(this->raw_topic_prefix_ + "/residue", hex);
#endif
}

// Build the full validated frame as uppercase hex, publish it to the HA
// raw-frame text_sensor (on change), and publish it to <prefix>/<msg_id> over
// MQTT if configured. Consumers (tools/s1s2_capture.py -> InfluxDB/SQLite,
// or any MQTT consumer) timestamp on receipt.
void MideaS1S2Component::publish_raw_(const char *msg_id, const std::vector<uint8_t> &f) {
  static const char HEX_CHARS[] = "0123456789ABCDEF";
  std::string hex;
  hex.reserve(f.size() * 2);
  for (uint8_t b : f) {
    hex += HEX_CHARS[b >> 4];
    hex += HEX_CHARS[b & 0x0F];
  }

  // Update the HA raw-frame text_sensor for this frame (on change only).
  this->publish_frame_sensor_(msg_id, hex);

#ifdef USE_MQTT
  if (this->raw_topic_prefix_.empty())
    return;
  if (mqtt::global_mqtt_client == nullptr || !mqtt::global_mqtt_client->is_connected())
    return;
  std::string topic = this->raw_topic_prefix_ + "/" + msg_id;
  mqtt::global_mqtt_client->publish(topic, hex);
#endif
}

// ---- raw full-frame text sensors (on change only) --------------------
void MideaS1S2Component::register_frame_sensor_(const char *id, text_sensor::TextSensor *ts) {
  if (ts != nullptr)
    this->frame_sensors_[id] = ts;
}

void MideaS1S2Component::publish_frame_sensor_(const std::string &msg_id, const std::string &hex) {
  if (this->frame_sensors_.empty())
    return;
  text_sensor::TextSensor *ts = nullptr;
  auto it = this->frame_sensors_.find(msg_id);
  if (it != this->frame_sensors_.end()) {
    ts = it->second;
  } else {
    // unknown frame type (e.g. boot frame) -> the "other" catch-all, if set
    auto other = this->frame_sensors_.find("other");
    if (other == this->frame_sensors_.end())
      return;
    ts = other->second;
  }
  // publish only when the frame actually changed, so HA's last_changed is a
  // true "this frame moved" timestamp and the recorder isn't flooded.
  if (ts->has_state() && ts->state == hex)
    return;
  ts->publish_state(hex);
}

// =====================================================================
// DECODERS — the editable part. Byte indices are frame-absolute and
// match the SQLite column names (IDU5..IDU17, ODU5..ODU17, HPA.., ...).
// One line per sensor: PUB(<sensor.py key>, <formula>);
// =====================================================================

// ---- Frame 0100_20 — IDU core (Indoor Unit -> ODU) -------------------
void MideaS1S2Component::decode_0100_20_(const std::vector<uint8_t> &f) {
  if (f.size() < 20)
    return;

  // IDU5: forever 0x11

  // IDU6: mode
  PUB_TEXT(indoor_mode, mode_to_string(f[6]));

  // IDU7: oT — IDU's requested compressor Hz, proportional to (T1 - setpoint)
  PUB(compressor_frequency_indoor_target, f[7]);

  // IDU8: assumed flags | 0x80 soft-start flag? (single-frame event —
  // this is exactly why we publish per-frame instead of per-cycle)
  PUB(unknown_0100_20_b8, f[8]);

  // IDU9: assumed flags

  // IDU10:
  PUB(unknown_0100_20_b10, f[10]);

  // IDU11: TT — user setpoint, no offset/scaling
  PUB(indoor_setpoint, f[11]);

  // IDU12: blower setting (mode, not RPM)
  PUB_TEXT(indoor_blower_speed, fan_to_string(f[12]));

  // IDU13: T1 — off-mode offset -8.5C / freeze-protection confirmed
  PUB(indoor_ambient_temperature, ntc_temp(f[13]));

  // IDU14: T2
  PUB(indoor_coil_temperature, ntc_temp(f[14]));

  // IDU15: forever 0x19 | IDU16: mode flags (bit 1 = Boost)

  // IDU17: IDU zone command {0,20,40,60,80}; ODU echoes/overrides in ODU17
  PUB(indoor_zone_command, f[17]);
}

// ---- Frame 0001_20 — ODU core (ODU -> IDU) ---------------------------
void MideaS1S2Component::decode_0001_20_(const std::vector<uint8_t> &f) {
  if (f.size() < 20)
    return;

  // ODU6: Fr — actual compressor Hz, rounded but fast-updating.
  // Highest seen: 70 Hz in defrost; cooling cap observed 63 Hz.
  PUB(compressor_frequency_actual_int, f[6]);

  // Cross-check for the HPB11 session-minute unwrap: if the compressor is
  // off, force the session tracker to reset even if a 0001_51 shutoff frame
  // got dropped. Without this a missed shutoff makes the next start look
  // like a 255->low rollover and silently adds a phantom +256 minutes.
  if (f[6] == 0 && this->run_session_active_) {
    this->run_session_active_ = false;
    this->run_rollover_count_ = 0;
    this->last_raw_hpb11_ = 0;
  }

  // ODU7/ODU8: assumed flags

  // ODU9: T3 — outdoor coil; goes strongly negative when iced
  PUB(outdoor_coil_temperature, ntc_temp(f[9]));

  // ODU10 + ODU15: T4 — outdoor ambient. Byte 15 carries the quarter-step
  // fraction (0,64,128,192), folded into the NTC input. No separate ODU10
  // sensor on purpose.
  PUB(outdoor_ambient_temperature, ntc_temp((float) f[10] + f[15] / 256.0f));

  // ODU11: TP — discharge line temperature
  PUB(discharge_temperature, steinhart_temp(f[11]));

  // ODU12: dL — 95%: highest value 25 during defrost
  PUB(current_draw, f[12] / 1.875f);

  // ODU13: Ac — left RAW until verified with a meter.
  // Testport conversion is the candidate once ground-truthed.
  PUB(input_voltage, f[13]);

  // ODU14: ODU mode — flips to Defrost during defrost cycles
  PUB_TEXT(outdoor_mode, mode_to_string(f[14]));

  // ODU16: forever 0x01

  // ODU17: ODU confirmed/override zone {0,20,40,60,80} — can override IDU17
  // (oil return cycles, maintenance)
  PUB(outdoor_zone_confirmed, f[17]);
}

// ---- Frame 0001_50 — ODU Performance A (HPA) -------------------------
void MideaS1S2Component::decode_0001_50_(const std::vector<uint8_t> &f) {
  if (f.size() < 19)
    return;

  // HPA5-HPA10: forever 0x00

  // HPA11: outdoor fan actual speed; zero during defrost (fan off confirmed)
  PUB(outdoor_fan_speed_actual, f[11] * 8);

  // HPA12: Lr — EXV position, relabeled per testport decoding
  PUB(eev_steps, f[12] * 2);

  // HPA13: forever 0x72 (mirrors low byte of HPA15)

  // HPA14: Uo — DC bus voltage. Current best decoding, still being dialed in.
  PUB(dc_bus_voltage, f[14] * 2.0f - 29.0f);

  // HPA15: NTC-converted, meaning unconfirmed (base 114 even in winter)
  PUB(unknown_0001_50_b15_temperature, ntc_temp(f[15]));

  // HPA16 + HPA17: ~10 s rolling average of compressor Hz (int + centi-Hz).
  // NOT the same signal as Fr — it wanders while ODU6 tracks fast.
  // Lands within 1 Hz of ODU6 in 96.6% of running frames.
  PUB(compressor_frequency_actual_avg, f[16] + f[17] / 100.0f);
}

// ---- Frame 0001_51 — ODU Performance B (HPB) -------------------------
void MideaS1S2Component::decode_0001_51_(const std::vector<uint8_t> &f) {
  if (f.size() < 20)
    return;

  // HPB5: outdoor fan target speed
  PUB(outdoor_fan_speed_target, f[5] * 8);

  // HPB6: EXV target, relabeled per testport decoding
  PUB(eev_steps_target, f[6] * 2);

  // HPB7-HPB10: forever 0x00

  // HPB11: 100%: active running minutes — WRAPS AT 255.
  // Rollover unwrap (see also the f[6]==0 cross-check in decode_0001_20_).
  uint8_t current_raw = f[11];
  if (current_raw > 0 && !this->run_session_active_) {
    this->run_session_active_ = true;   // startup detected
    this->run_rollover_count_ = 0;
  } else if (current_raw < this->last_raw_hpb11_ && this->run_session_active_) {
    if (this->last_raw_hpb11_ - current_raw > 200)
      this->run_rollover_count_++;      // rollover detected
  }
  if (current_raw == 0) {
    this->run_session_active_ = false;  // shutoff detected
    this->run_rollover_count_ = 0;
  }
  PUB(run_session_minutes, this->run_rollover_count_ * 256 + current_raw);
  this->last_raw_hpb11_ = current_raw;

  // HPB12 ticks every ~60 active minutes; HPB13 every 256 hours.
  // Cross-validated: grew ~86 h over 4 days at 90.0% measured duty.
  PUB(run_lifetime_hours, f[13] * 256 + f[12]);

  // HPB14: 190 | HPB15: 157->93, changed once and stayed (season flag?)
  // HPB16: forever 106 | HPB17: forever 161
}

// ---- Frame 0001_52 — ODU Performance C (HPC) -------------------------
void MideaS1S2Component::decode_0001_52_(const std::vector<uint8_t> &f) {
  if (f.size() < 20)
    return;

  // HPC5: forever 0x22 | HPC6: forever 0x00

  // HPC7: PWM carrier frequency in kHz? / EXV zone row index?
  PUB(unknown_0001_52_b7, f[7]);

  // HPC8: assumed fan byte
  PUB(unknown_0001_52_b8, f[8]);

  // HPC9: compressor PID step command — predicts the direction of Hz.
  // +7 aggressive ramp (soft-start), 0 off, -1 steady trim, -2 decel/protect.
  PUB(compressor_pid_step, signed_byte(f[9]));

  // HPC10 / HPC11:
  PUB(unknown_0001_52_b10, f[10]);
  PUB(unknown_0001_52_b11, f[11]);

  // HPC12: forever 0x00

  // HPC13: outdoor fan gear index (step, not RPM). Possibly the manual's
  // "Pr" — unconfirmed, see docs.
  PUB(outdoor_fan_speed_step, f[13]);

  // HPC14-HPC17: forever 0x00
}

// ---- Frame 0001_53 — ODU Performance D (HPD) -------------------------
void MideaS1S2Component::decode_0001_53_(const std::vector<uint8_t> &f) {
  if (f.size() < 20)
    return;

  // HPD5: forever 0x00

  // HPD6: drive compensation / resistance index (signed)
  PUB(drive_comp_index, signed_byte(f[6]));

  // HPD7: cycle stage
  PUB(cycle_stage, f[7]);

  // HPD8: high-DC-volts flag
  PUB(dc_stage, f[8]);

  // HPD9: compressor state machine: 0=Off, 2=Startup, 6=Run
  // (95/99 of the '2' frames were within 30 frames of a compressor start)
  PUB(compressor_state, f[9]);

  // HPD10: forever 0x00

  // HPD11 (low) + HPD12 (high): assumed total watts — idle values match
  // the Senville app; testport disproved the earlier EXV label.
  PUB(total_power, f[12] * 256 + f[11]);

  // HPD13: FT — ODU's internal PID target Hz. Leads Fr; 25 Hz at soft-start,
  // 80 Hz ceiling in defrost, 63 Hz cooling cap observed.
  PUB(compressor_frequency_outdoor_target, f[13]);

  // HPD14-HPD17: forever 0x00
}

}  // namespace midea_s1s2
}  // namespace esphome
