"""midea_s1s2 sensor platform — numeric sensors.

This declares which sensor keys are legal in YAML and wires each one to its
C++ setter. It contains NO decode logic — formulas live in midea_s1s2.cpp.

Sensor keys use the Midea service-manual parameter code where one exists
(see the Code column in the field maps). Values are published unrounded;
accuracy_decimals here only controls reported precision and can be
overridden per-sensor in YAML.
"""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import sensor
from esphome.const import (
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_DURATION,
    DEVICE_CLASS_FREQUENCY,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_TEMPERATURE,
    DEVICE_CLASS_VOLTAGE,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
    UNIT_AMPERE,
    UNIT_CELSIUS,
    UNIT_HERTZ,
    UNIT_HOUR,
    UNIT_MINUTE,
    UNIT_REVOLUTIONS_PER_MINUTE,
    UNIT_VOLT,
    UNIT_WATT,
)

from . import CONF_MIDEA_S1S2_ID, MideaS1S2Component

DEPENDENCIES = ["midea_s1s2"]


def _temp():
    return sensor.sensor_schema(
        unit_of_measurement=UNIT_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=2,
    )


def _hz(decimals=0):
    return sensor.sensor_schema(
        unit_of_measurement=UNIT_HERTZ,
        device_class=DEVICE_CLASS_FREQUENCY,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=decimals,
    )


def _rpm():
    return sensor.sensor_schema(
        unit_of_measurement=UNIT_REVOLUTIONS_PER_MINUTE,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=0,
        icon="mdi:fan",
    )


def _raw(diagnostic=False):
    kwargs = dict(state_class=STATE_CLASS_MEASUREMENT, accuracy_decimals=0)
    if diagnostic:
        kwargs["entity_category"] = ENTITY_CATEGORY_DIAGNOSTIC
    return sensor.sensor_schema(**kwargs)


# key -> schema. Keys here MUST match the SUB_SENSOR names in midea_s1s2.h.
SENSORS = {
    # ---- Frame 0100_20 — IDU core -------------------------------------
    "compressor_frequency_indoor_target": _hz(),          # oT  IDU7
    "indoor_setpoint": _temp(),                           # TT  IDU11
    "indoor_ambient_temperature": _temp(),                # T1  IDU13
    "indoor_coil_temperature": _temp(),                   # T2  IDU14
    "indoor_zone_command": _raw(),                        # —   IDU17
    # ---- Frame 0001_20 — ODU core -------------------------------------
    "compressor_frequency_actual_int": _hz(),             # Fr  ODU6
    "outdoor_coil_temperature": _temp(),                  # T3  ODU9
    "outdoor_ambient_temperature": _temp(),               # T4  ODU10+15
    "discharge_temperature": _temp(),                     # TP  ODU11
    "current_draw": sensor.sensor_schema(                 # dL  ODU12
        unit_of_measurement=UNIT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=3,
    ),
    "input_voltage": sensor.sensor_schema(                # Ac  ODU13 (raw!)
        unit_of_measurement=UNIT_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=0,
    ),
    "outdoor_zone_confirmed": _raw(),                     # —   ODU17
    # ---- Frame 0001_50 — HPA ------------------------------------------
    "outdoor_fan_speed_actual": _rpm(),                   # —   HPA11
    "eev_steps": _raw(),                                  # Lr  HPA12
    "dc_bus_voltage": sensor.sensor_schema(               # Uo  HPA14
        unit_of_measurement=UNIT_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=0,
    ),
    "compressor_frequency_actual_avg": _hz(2),            # —   HPA16+17 (~10s avg)
    # ---- Frame 0001_51 — HPB ------------------------------------------
    "outdoor_fan_speed_target": _rpm(),                   # —   HPB5
    "eev_steps_target": _raw(),                           # —   HPB6
    "run_session_minutes": sensor.sensor_schema(          # —   HPB11 (+rollover)
        unit_of_measurement=UNIT_MINUTE,
        device_class=DEVICE_CLASS_DURATION,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=0,
    ),
    "run_lifetime_hours": sensor.sensor_schema(           # —   HPB13*256+HPB12
        unit_of_measurement=UNIT_HOUR,
        device_class=DEVICE_CLASS_DURATION,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        accuracy_decimals=0,
    ),
    # ---- Frame 0001_52 — HPC ------------------------------------------
    "compressor_pid_step": _raw(),                        # —   HPC9 (signed)
    "outdoor_fan_speed_step": _raw(),                     # Pr? HPC13 gear index
    # ---- Frame 0001_53 — HPD ------------------------------------------
    "drive_comp_index": _raw(),                           # —   HPD6 (signed)
    "cycle_stage": _raw(),                                # —   HPD7
    "dc_stage": _raw(),                                   # —   HPD8
    "compressor_state": _raw(),                           # —   HPD9 0=Off 2=Startup 6=Run
    "total_power": sensor.sensor_schema(                  # —   HPD12*256+HPD11 (assumed)
        unit_of_measurement=UNIT_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=0,
    ),
    "compressor_frequency_outdoor_target": _hz(),         # FT  HPD13
    # ---- Undecoded bytes under investigation (diagnostic) -------------
    "unknown_0100_20_b8": _raw(diagnostic=True),          # soft-start flag 0x80?
    "unknown_0100_20_b10": _raw(diagnostic=True),
    "unknown_0001_50_b15_temperature": sensor.sensor_schema(  # NTC-converted HPA15
        unit_of_measurement=UNIT_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=2,
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
    ),
    "unknown_0001_52_b7": _raw(diagnostic=True),
    "unknown_0001_52_b8": _raw(diagnostic=True),
    "unknown_0001_52_b10": _raw(diagnostic=True),
    "unknown_0001_52_b11": _raw(diagnostic=True),
    # ---- Component health ----------------------------------------------
    "crc_errors": sensor.sensor_schema(
        state_class=STATE_CLASS_TOTAL_INCREASING,
        accuracy_decimals=0,
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
}

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_MIDEA_S1S2_ID): cv.use_id(MideaS1S2Component),
        **{cv.Optional(key): schema for key, schema in SENSORS.items()},
    }
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_MIDEA_S1S2_ID])
    for key in SENSORS:
        if key in config:
            sens = await sensor.new_sensor(config[key])
            cg.add(getattr(parent, f"set_{key}_sensor")(sens))
