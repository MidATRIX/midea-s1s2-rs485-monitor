# src/main.py
import asyncio
import json
import os
import time
import datetime
import argparse
import sys
import paho.mqtt.client as mqtt
from database.db_handler import init_db, save_frame
from src.config import WAVESHARE_IP, WAVESHARE_PORT, KNOWN_IDS, REGISTRY_FILE, FRAME_SIZE, MQTT_IP, MQTT_PORT_NUMBER, MQTT_USER, MQTT_PASS
from src.serial.frame_buffer import FrameBuffer
from src.protocol.validator import FrameValidator
from src.decode.sensors import process_payload
from src.ha.discovery import SenvilleMQTT

def get_target_connection():
    # Set up the command line argument parser
    parser = argparse.ArgumentParser(description="Senville Matrix - S1/S2 Decoder")
    parser.add_argument('--ip', type=str, help="Override target IP address (e.g., 127.0.0.1)")
    parser.add_argument('--port', type=int, help="Override target Port number (e.g., 5555)")

    # simulated setup:
    # e.g., PYTHONPATH=. python3  src/main.py --ip 127.0.0.1 --port 5555
    #
    # production setup
    # e.g., PYTHONPATH=. python3  src/main.py
    # e.g., PYTHONPATH=. python3  src/main.py --ip 192.168.86.185 --port 8888
    
    # Parse the arguments from the terminal
    args = parser.parse_args()
    
    # Fix: Use the directly imported variables, not "config.WAVESHARE_IP"
    target_ip = args.ip if args.ip else WAVESHARE_IP
    target_port = args.port if args.port else WAVESHARE_PORT
    
    return target_ip, target_port

async def main():

    target_ip, target_port = get_target_connection()
    
    fb = FrameBuffer()
    validator = FrameValidator()
    
    current_state = [[] for _ in range(6)]
    
    if not os.path.exists("data"):
        os.makedirs("data")
        
# --- INITIALIZE HOME ASSISTANT MQTT ---
    ha = SenvilleMQTT(MQTT_IP, MQTT_PORT_NUMBER, MQTT_USER, MQTT_PASS)
    
    print("⏳ Waiting for MQTT CONNACK handshake...")
    time.sleep(5)
    
    ha.register_all_sensors()
    
    print(f"🦅 ENGAGE | {target_ip}:{target_port}")

    while True:
        try:
            reader, writer = await asyncio.open_connection(target_ip, target_port)
            print("🔗 TCP CONNECTION ESTABLISHED")

            while True:
                try:
                    # Wait 15 seconds for data. If nothing comes, print a warning and loop.
                    data = await asyncio.wait_for(reader.read(1024), timeout=15.0)
                except asyncio.TimeoutError:
                    print("⏳ Still listening... No data from Waveshare in 15 seconds.")
                    continue
                if not data:
                    print("⚠️ CONNECTION CLOSED BY BRIDGE")
                    await asyncio.sleep(5)
                    break
                
                fb.feed(data)
                
                while True:
                    frame, noise = fb.get_frame()
                        
                    if noise:
                        with open("data/bus_noise.log", "a") as f:
                            f.write(f"{noise.hex().upper()}\n")
                    
                    if frame is None:
                        break
#                    print(f"{frame.hex().upper()}\n")
                    
                    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    status_icon, seed, msg_id = validator.process(frame)
                    raw_hex = frame.hex().upper()
                    sensor_name = KNOWN_IDS.get(msg_id, f"trash_{msg_id}")
                    
 #                   if sensor_name.startswith("trash"): 
 #                       continue
                    
                    decoded_data = {}
                    if status_icon in ["✅", "🔒"]:
                        print(f"{status_icon} {raw_hex} [{ts}] [{sensor_name}]") # Comment to stop printing to terminal
                        
                        from src.decode.sensors import process_payload
                        decoded_data = process_payload(msg_id, frame)
                        
#            #            for key, value in decoded_data.items(): #--------------------------- Comment to disable HA MQTT
#            #                ha.publish_state(key, value)        #--------------------------- Comment to disable HA MQTT
                    
                    # Database Save Logic
                    if sensor_name == "IDU_CORE":
                        current_state[0] = [msg_id] + list(frame[5:18])
                    elif sensor_name == "ODU_CORE":
                        current_state[1] = [msg_id] + list(frame[5:18])
                    elif sensor_name == "ODU_50":
                        current_state[2] = [msg_id] + list(frame[5:18])
                    elif sensor_name == "ODU_51":
                        current_state[3] = [msg_id] + list(frame[5:18])
                    elif sensor_name == "ODU_52":
                        current_state[4] = [msg_id] + list(frame[5:18])
                    elif sensor_name == "ODU_53":
                        current_state[5] = [msg_id] + list(frame[5:18])
                        
                        payload_ints = [byte for section in current_state for byte in section]
#                        if len(payload_ints) == 84: #-------------------------------------- Comment to disable database
#                            save_frame(list(payload_ints))#-------------------------------- Comment to disable database
  #                          current_state = [[] for _ in range(6)]
                    print(f"{current_state}") #------------------------------------ Comment to stop printing to terminal
                        
        except Exception as e:
            print(f"❌ CONNECTION ERROR: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
