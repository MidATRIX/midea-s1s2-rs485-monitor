# src/ha/discovery.py
import json
import time
import paho.mqtt.client as mqtt

class SenvilleMQTT:
    def __init__(self, broker_ip, broker_port=1883, username=None, password=None):
        self.mqtt = mqtt.Client()
        
        # Apply credentials if provided
        if username and password:
            self.mqtt.username_pw_set(username, password)
            
        try:
            self.mqtt.connect(broker_ip, broker_port, 60)
            self.mqtt.loop_start()
            print(f"✅ MQTT CONNECTED | {broker_ip}:{broker_port}")
        except Exception as e:
            print(f"❌ MQTT CONNECTION FAILED: {e}")
            
        self.prefix = "homeassistant"
        self.state_cache = {}

    def register_sensor(self, name, unit=None, device_class=None, state_class=None):
        """Sends discovery payload to HAOS so the sensor appears automatically."""
        topic = f"{self.prefix}/sensor/senville_{name}/config"
        payload = {
            "name": f"Senville {name.replace('_', ' ').title()}",
            "state_topic": f"senville/sensor/{name}/state",
            "value_template": "{{ value_json.state }}",
            "unique_id": f"senville_{name}",
            "force_update": True,
            "device": {
                "identifiers": ["senville_bus"],
                "name": "Senville Heat Pump",
                "model": "Midea Inverter",
                "manufacturer": "Senville"
            }
        }
        if unit: 
            payload["unit_of_measurement"] = unit
            payload["state_class"] = "measurement"  # Auto-graph if it has a unit
            
        if state_class: 
            payload["state_class"] = state_class    # Explicit override for unitless numbers
            
        if device_class: 
            payload["device_class"] = device_class
        
        self.mqtt.publish(topic, json.dumps(payload), retain=True)

    def publish_state(self, name, value, force=False):
        """Handles Send-on-Change and 60-second Heartbeat"""
        current_time = time.time()
        cached = self.state_cache.get(name)

        if force or not cached or cached['value'] != value or (current_time - cached['last_sent'] > 60):
            topic = f"senville/sensor/{name}/state"
            payload = json.dumps({"state": value})
            
            self.mqtt.publish(topic, payload, retain=False)
            
            self.state_cache[name] = {
                "value": value,
                "last_sent": current_time
            }

    def register_all_sensors(self):
        """Registers all known sensors from the Master Dictionary."""
        print("Registering HA Sensors...")
        # 0100_20
        self.register_sensor("IDU_Mode")
        self.register_sensor("IDU_Demand_Hz", unit="Hz", state_class="measurement")
        self.register_sensor("Target_Setpoint", unit="°C", device_class="temperature")
        self.register_sensor("IDU_Blower_Speed")
        self.register_sensor("T1_Room_Temp", unit="°C", device_class="temperature")
        self.register_sensor("T2_IDU_Coil_Temp", unit="°C", device_class="temperature")
        # 0001_20
        self.register_sensor("Compressor_Actual_Hz", unit="Hz", state_class="measurement")
        self.register_sensor("T3_ODU_Coil_Temp", unit="°C", device_class="temperature")
        self.register_sensor("T4_Outdoor_Temp", unit="°C", device_class="temperature")
        self.register_sensor("TP_Discharge_Temp", unit="°C", device_class="temperature")
        self.register_sensor("Compressor_Actual_Amps", unit="A")
        self.register_sensor("0001_20_b13", state_class="measurement")
        self.register_sensor("ODU_Mode")
        # 0001_50
        self.register_sensor("ODU_Fan_Speed_Actual_RPM", unit="RPM")
        self.register_sensor("ODU_DC_Bus_Voltage_Actual", unit="V", device_class="voltage")
        self.register_sensor("AC_Input_Voltage_V", unit="V", device_class="voltage")
        self.register_sensor("Inverter_DC_Bus_Voltage_V", unit="V", device_class="voltage")
        self.register_sensor("IPM_Load_Index", state_class="measurement")
        # 0001_51
        self.register_sensor("ODU_Fan_Speed_Target_RPM", unit="RPM")
        self.register_sensor("ODU_DC_Bus_Voltage_Target", unit="V", device_class="voltage")
        self.register_sensor("Run_Minutes_Clock", unit="min", device_class="duration")
        self.register_sensor("Run_Hours_Clock", unit="h", device_class="duration")
        # 0001_52
        self.register_sensor("IPM_Heatsink_Temp_1", unit="°C", device_class="temperature")
        self.register_sensor("IPM_Heatsink_Temp_2", unit="°C", device_class="temperature")
        self.register_sensor("Compressor_PID_Step", state_class="measurement")
        self.register_sensor("IPM_Phase_Current_A", unit="A", device_class="current")
        self.register_sensor("IPM_Phase_Current_B", unit="A", device_class="current")
        self.register_sensor("ODU_Fan_Speed_Step", state_class="measurement")
        # 0001_53
        self.register_sensor("Phase_Modifier", state_class="measurement")
        self.register_sensor("Routine_Phase_Step", state_class="measurement")
        self.register_sensor("Active_Ramp_Routine")
        self.register_sensor("EXV_Position_Steps", state_class="measurement")
        self.register_sensor("ODU_Target_Hz", unit="Hz", state_class="measurement")
