# src/config.py
import os

# --- NETWORK BRIDGE ---          # options to overide config setting while starting - useful for simulator
WAVESHARE_IP = "192.168.86.185"   # --ip <ip_address> 
WAVESHARE_PORT = 8888             # --port <port_number>

# --- HOME ASSISTANT ---
HA_HOST = "192.168.86.180"

# --- HA MQTT ---
MQTT_IP = "192.168.86.180"
MQTT_PORT_NUMBER = 1883
MQTT_USER = "USERNAME"
MQTT_PASS = "PASSWORD"

# Root directory for shared telemetry / SQLite database
SQLITE_DB_DIR = "data/"

# --- DEVICE IDENTITY ---
# Name used for Home Assistant device registry and MQTT topics.
# Change this if you have multiple units or want a custom label.
# Spaces are fine here — the code slugifies it where needed.
DEVICE_NAME = "Testing Heat Pump"

# --- FILE PATHS ---
# Using absolute paths based on the file location to prevent "File Not Found" errors
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(BASE_DIR, "..", "data", "data_registry.json")
LOG_RAW = os.path.join(BASE_DIR, "..", "data", "raw_frames.log")

# --- PROTOCOL CONSTANTS ---
FRAME_HEADER = 0xA0 # Well almost
FRAME_SIZE = 20
CRC_POLY = 0x31

# --- KNOWN MESSAGE IDs ---
KNOWN_IDS = {
########## Bootup handshake ##############
#    AA 00 00 D4 00 00 01 03 28 55       #
#    AA 01 03 00 00 00 00 00 FC 55 00    #
#    A6 00 62 64 00 A0 A0 00 FA 6A       #
#    A6 01 7D 25 00 0A 0A 00 49 6A 00    #
##########################################
    
    # Primary Operational Frames
    "0001_20": "ODU_CORE",
    "0100_20": "IDU_CORE",
    
    # Heartbeat
    "0001_21": "ODU_DUB",
    "0100_21": "IDU_DUB",
    
     #Sync / only seen during bootup
    "0001_25": "ODU_YCK",
    "0100_25": "IDU_ACK",
    
    # Performance & Diagnostic Frames
    "0001_50": "ODU_50",
    "0100_50": "IDU_50",
    "0001_51": "ODU_51",
    "0100_51": "IDU_51",
    "0001_52": "ODU_52",
    "0100_52": "IDU_52",
    "0001_53": "ODU_53",
    "0100_53": "IDU_53",
    
    # Heartbeat
    "0100_91": "IDU_LUB",
    "0001_91": "ODU_LUB"
}
