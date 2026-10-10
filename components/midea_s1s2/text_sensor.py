"""midea_s1s2 text_sensor platform.

Two groups:
  * decoded enums (indoor_mode, indoor_blower_speed, outdoor_mode) - the
    enum maps live in midea_s1s2.cpp.
  * raw full-frame hex (raw_frame_*) - one per frame type, published ON CHANGE
    only. These are diagnostic + disabled_by_default, so they stay hidden in
    Home Assistant until you enable one. Enabling a frame lets you watch (via
    the entity's last_changed) whether that frame ever moves - handy for the
    "static" frames (_21 handshake, _91 keepalive, the 0100_5x IDU acks) that
    have no decoded sensor. `raw_frame_other` shows the latest frame whose type
    isn't one of the known ones (e.g. boot frames).
"""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import text_sensor
from esphome.const import CONF_DISABLED_BY_DEFAULT, ENTITY_CATEGORY_DIAGNOSTIC

from . import CONF_MIDEA_S1S2_ID, MideaS1S2Component

DEPENDENCIES = ["midea_s1s2"]

# decoded enum text sensors
TEXT_SENSORS = {
    "indoor_mode": text_sensor.text_sensor_schema(icon="mdi:hvac"),          # IDU6
    "indoor_blower_speed": text_sensor.text_sensor_schema(icon="mdi:fan"),   # IDU12 (mode, not RPM)
    "outdoor_mode": text_sensor.text_sensor_schema(icon="mdi:hvac"),         # ODU14 (shows Defrost)
}

# raw full-frame hex sensors (diagnostic, disabled by default, on-change)
RAW_FRAME_IDS = [
    "0100_20", "0001_20",                        # core (both sides)
    "0001_25", "0100_25",                        # boot (seen only during startup)
    "0001_50", "0001_51", "0001_52", "0001_53",  # ODU performance
    "0100_50", "0100_51", "0100_52", "0100_53",  # IDU acks (normally all-zero)
    "0001_21", "0100_21",                        # handshake
    "0001_91", "0100_91",                        # keepalive
    "other",                                     # catch-all: latest unknown frame
]


def _raw_frame_schema():
    base = text_sensor.text_sensor_schema(
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        icon="mdi:code-braces",
    )
    # hidden until the user enables it in Home Assistant
    return base.extend({cv.Optional(CONF_DISABLED_BY_DEFAULT, default=True): cv.boolean})


RAW_FRAME_SENSORS = {f"raw_frame_{fid}": _raw_frame_schema() for fid in RAW_FRAME_IDS}

ALL_TEXT_SENSORS = {**TEXT_SENSORS, **RAW_FRAME_SENSORS}

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_MIDEA_S1S2_ID): cv.use_id(MideaS1S2Component),
        **{cv.Optional(key): schema for key, schema in ALL_TEXT_SENSORS.items()},
    }
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_MIDEA_S1S2_ID])
    for key in ALL_TEXT_SENSORS:
        if key in config:
            sens = await text_sensor.new_text_sensor(config[key])
            cg.add(getattr(parent, f"set_{key}_text_sensor")(sens))
