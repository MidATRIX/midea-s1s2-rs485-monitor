#pragma once

// midea_s1s2 — passive sniffer for the Midea/Senville S1S2 indoor<->outdoor bus.
//
// RX-only. 4800 8N1 RS485 half-duplex; the ODU is bus master, we never transmit.
// Frame:  [A0][DD DD][CC][LL][ payload LL bytes ][B17][CRC lo][CRC hi]
// CRC-16/MODBUS over A0..B17 inclusive, little-endian on the wire.
//
// All decode formulas are in midea_s1s2.cpp — edit them there, nothing here.

#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/components/uart/uart.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/text_sensor/text_sensor.h"

#include <map>
#include <string>
#include <vector>

namespace esphome {
namespace midea_s1s2 {

class MideaS1S2Component : public Component,
                          public uart::UARTDevice {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }

  void set_raw_topic_prefix(const std::string &prefix) { this->raw_topic_prefix_ = prefix; }
  void set_raw_publish_residue(bool v) { this->raw_publish_residue_ = v; }

  // ---- numeric sensors (names must match sensor.py keys) --------------
  // 0100_20 — IDU core
  SUB_SENSOR(compressor_frequency_indoor_target)  // oT  IDU7
  SUB_SENSOR(indoor_setpoint)                     // TT  IDU11
  SUB_SENSOR(indoor_ambient_temperature)          // T1  IDU13
  SUB_SENSOR(indoor_coil_temperature)             // T2  IDU14
  SUB_SENSOR(indoor_zone_command)                 // —   IDU17
  // 0001_20 — ODU core
  SUB_SENSOR(compressor_frequency_actual_int)     // Fr  ODU6
  SUB_SENSOR(outdoor_coil_temperature)            // T3  ODU9
  SUB_SENSOR(outdoor_ambient_temperature)         // T4  ODU10+15
  SUB_SENSOR(discharge_temperature)               // TP  ODU11
  SUB_SENSOR(current_draw)                        // dL  ODU12
  SUB_SENSOR(input_voltage)                       // Ac  ODU13
  SUB_SENSOR(outdoor_zone_confirmed)              // —   ODU17
  // 0001_50 — HPA
  SUB_SENSOR(outdoor_fan_speed_actual)            // —   HPA11
  SUB_SENSOR(eev_steps)                           // Lr  HPA12
  SUB_SENSOR(dc_bus_voltage)                      // Uo  HPA14
  SUB_SENSOR(compressor_frequency_actual_avg)     // —   HPA16+17
  // 0001_51 — HPB
  SUB_SENSOR(outdoor_fan_speed_target)            // —   HPB5
  SUB_SENSOR(eev_steps_target)                    // —   HPB6
  SUB_SENSOR(run_session_minutes)                 // —   HPB11 (+rollover state)
  SUB_SENSOR(run_lifetime_hours)                  // —   HPB13*256+HPB12
  // 0001_52 — HPC
  SUB_SENSOR(compressor_pid_step)                 // —   HPC9 signed
  SUB_SENSOR(outdoor_fan_speed_step)              // Pr? HPC13 gear index
  // 0001_53 — HPD
  SUB_SENSOR(drive_comp_index)                    // —   HPD6 signed
  SUB_SENSOR(cycle_stage)                         // —   HPD7
  SUB_SENSOR(dc_stage)                            // —   HPD8
  SUB_SENSOR(compressor_state)                    // —   HPD9
  SUB_SENSOR(total_power)                         // —   HPD12*256+HPD11 (assumed)
  SUB_SENSOR(compressor_frequency_outdoor_target) // FT  HPD13
  // undecoded bytes under investigation
  SUB_SENSOR(unknown_0100_20_b8)
  SUB_SENSOR(unknown_0100_20_b10)
  SUB_SENSOR(unknown_0001_50_b15_temperature)
  SUB_SENSOR(unknown_0001_52_b7)
  SUB_SENSOR(unknown_0001_52_b8)
  SUB_SENSOR(unknown_0001_52_b10)
  SUB_SENSOR(unknown_0001_52_b11)
  // component health
  SUB_SENSOR(crc_errors)

  // ---- text sensors ----------------------------------------------------
  SUB_TEXT_SENSOR(indoor_mode)          // IDU6
  SUB_TEXT_SENSOR(indoor_blower_speed)  // IDU12
  SUB_TEXT_SENSOR(outdoor_mode)         // ODU14

  // ---- raw full-frame hex (diagnostic, disabled by default, on-change) -
  // Watch any frame for movement from inside HA. raw_frame_other catches
  // valid frames whose type isn't one of the known ones (e.g. boot frames).
  SUB_TEXT_SENSOR(raw_frame_0100_20)
  SUB_TEXT_SENSOR(raw_frame_0001_20)
  SUB_TEXT_SENSOR(raw_frame_0001_25)
  SUB_TEXT_SENSOR(raw_frame_0100_25)
  SUB_TEXT_SENSOR(raw_frame_0001_50)
  SUB_TEXT_SENSOR(raw_frame_0001_51)
  SUB_TEXT_SENSOR(raw_frame_0001_52)
  SUB_TEXT_SENSOR(raw_frame_0001_53)
  SUB_TEXT_SENSOR(raw_frame_0100_50)
  SUB_TEXT_SENSOR(raw_frame_0100_51)
  SUB_TEXT_SENSOR(raw_frame_0100_52)
  SUB_TEXT_SENSOR(raw_frame_0100_53)
  SUB_TEXT_SENSOR(raw_frame_0001_21)
  SUB_TEXT_SENSOR(raw_frame_0100_21)
  SUB_TEXT_SENSOR(raw_frame_0001_91)
  SUB_TEXT_SENSOR(raw_frame_0100_91)
  SUB_TEXT_SENSOR(raw_frame_other)

 protected:
  void drain_buffer_();
  void process_frame_(const std::vector<uint8_t> &f);
  void publish_raw_(const char *msg_id, const std::vector<uint8_t> &f);
  void collect_residue_(const uint8_t *data, size_t n);
  void flush_residue_();
  // on-change publish of a full frame's hex to its HA diagnostic text_sensor
  void register_frame_sensor_(const char *id, text_sensor::TextSensor *ts);
  void publish_frame_sensor_(const std::string &msg_id, const std::string &hex);


  // per-frame decoders — the editable part, see midea_s1s2.cpp
  void decode_0100_20_(const std::vector<uint8_t> &f);
  void decode_0001_20_(const std::vector<uint8_t> &f);
  void decode_0001_50_(const std::vector<uint8_t> &f);
  void decode_0001_51_(const std::vector<uint8_t> &f);
  void decode_0001_52_(const std::vector<uint8_t> &f);
  void decode_0001_53_(const std::vector<uint8_t> &f);

  std::vector<uint8_t> buf_;
  std::string raw_topic_prefix_{};
  bool raw_publish_residue_{false};
  std::vector<uint8_t> residue_;   // non-frame bytes (minus 0xAA/0x55 noise)
  uint32_t crc_error_count_{0};

  // msg_id -> raw-frame text_sensor (only the ones configured in YAML)
  std::map<std::string, text_sensor::TextSensor *> frame_sensors_;

  // Run_Session_Minutes rollover tracking (stateful across frames,
  // includes the 0001_20 f[6]==0 cross-check)
  bool run_session_active_{false};
  uint32_t run_rollover_count_{0};
  uint8_t last_raw_hpb11_{0};
};

}  // namespace midea_s1s2
}  // namespace esphome
