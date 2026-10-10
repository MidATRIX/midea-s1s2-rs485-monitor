"""midea_s1s2 hub — passive S1S2 bus sniffer.

This file is ESPHome *codegen*, not the decoder. It declares the component,
binds it to a UART, and exposes the raw-frame MQTT topic option.
All decode formulas live in midea_s1s2.cpp.
"""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import uart
from esphome.const import CONF_ID

CODEOWNERS = ["@MidATRIX"]
DEPENDENCIES = ["uart"]
AUTO_LOAD = ["sensor", "text_sensor"]
MULTI_CONF = True

CONF_MIDEA_S1S2_ID = "midea_s1s2_id"
CONF_RAW_TOPIC_PREFIX = "raw_topic_prefix"
CONF_RAW_PUBLISH_RESIDUE = "raw_publish_residue"

midea_s1s2_ns = cg.esphome_ns.namespace("midea_s1s2")
MideaS1S2Component = midea_s1s2_ns.class_(
    "MideaS1S2Component", cg.Component, uart.UARTDevice
)

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(MideaS1S2Component),
            # When set AND an `mqtt:` block exists in the YAML, EVERY
            # CRC-validated frame (decoded or not: _20 core, _50..53, the _21
            # handshake, _91 keepalive, IDU acks, and any boot frames) is
            # published as uppercase hex to "<prefix>/<msg_id>", e.g.
            #   midea_s1s2/frames/0001_20 -> "A00001200C120F000077742604B5010001001D51"
            # Consumer: tools/s1s2_capture.py (or any MQTT consumer).
            cv.Optional(CONF_RAW_TOPIC_PREFIX, default=""): cv.string,
            # When true, bytes that never form a valid frame (leading junk, CRC
            # failures, non-A0 framing) are published to "<prefix>/residue",
            # with 0xAA and 0x55 (UART idle/noise) filtered out. Off by default
            # because it can be noisy; useful for chasing unknown boot framing.
            cv.Optional(CONF_RAW_PUBLISH_RESIDUE, default=False): cv.boolean,
        }
    )
    .extend(uart.UART_DEVICE_SCHEMA)
    .extend(cv.COMPONENT_SCHEMA)
)

FINAL_VALIDATE_SCHEMA = uart.final_validate_device_schema(
    "midea_s1s2", baud_rate=4800, require_rx=True
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await uart.register_uart_device(var, config)
    if config[CONF_RAW_TOPIC_PREFIX]:
        cg.add(var.set_raw_topic_prefix(config[CONF_RAW_TOPIC_PREFIX]))
    if config[CONF_RAW_PUBLISH_RESIDUE]:
        cg.add(var.set_raw_publish_residue(True))
