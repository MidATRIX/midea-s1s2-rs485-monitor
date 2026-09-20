'''
List of sensors and meaning found in my units service manual for reference.
I added confidence column.
I do not round any values. This can be done in Home Assistant.
All 99% sensors are only validated from other bus projects

Channel	Conf%	Code Meaning Remark
✓ T1	100	Room temperature °C
✓ T2	99	Indoor coil temperature°C
✓ T3	100	Outdoor coil temperature °C
✓ T4	100	Ambient temperature °C
✓ TP	99	Discharge temperature°C
✓ FT	99	Targeted frequency Actual data
✓ Fr	99	Actual frequency Actual data
✓ dL	99*	Running current
✓ Ac	99*	AC voltage
  1Sn		Reserved
  nA		Reserved
✓ Pr	99	Indoor air flow - S1S2 has mode - XYE has true mode even while in auto and CFM is a lookup chart
✓ Lr	99	EXV opening steps
! Ir	XYE	Indoor fan speed - S1S2 has mode - XYE has true mode even while in auto and CFM is a lookup chart
X Hu	NA	Humidity (if a sensor there) - Ill add my own
✓ TT	100	Set temperature including compensation °C
✓ Uo	99*	Outdoor DC bus voltage
✓ oT	99	Target Frequency calculated by indoor Without limitation
! TA	XYE	Evaporator coil inlet temperature,°C
! 2b	XYE	Evaporator coil outlet temperature Actual data

'''

import math


# Tthanks to fmck3516 for this function: https://github.com/fmck3516/midea-telemetry-esphome/blob/main/components/midea_telemetry/midea_telemetry.cpp
def ntc_temp(v: int) -> float:

    if v == 0:
        return -66.0
    if v == 255:
        return 255.0
        
    t = 1.0 / (1.0 / 298.15 + math.log(0.81 * (255.0 - v) / v) / 4150.0) - 273.15
    return t * 2.0 / 2.0

# Thanks to fmck3516 for this function: https://github.com/fmck3516/midea-telemetry-esphome/blob/main/components/midea_telemetry/midea_telemetry.cpp
def Steinhart_temp(v: int) -> float:

    if v == 0:
        return -48.0
    if v >= 254:
        return float(v)
        
    l = math.log((255.0 - v) / v)
    return float(1.0 / (2.873e-3 + 2.491e-4 * l + 9.74e-7 * (l ** 3)) - 273.15)

# def process_payload(msg_id, f, state, outdoor_temp_c):
def process_payload(msg_id, f, state):
    data = {}
    modes = {0x00: "Off", 0x01: "Cool", 0x02: "Heat", 0x03: "Fan", 0x04: "Dry",
             0x06: "Forced Cool", 0x07: "Defrost / Self Clean", 0x09: "ECO", 0x0A: "Forced Defrost"}
    fan_map = {0x01: "High", 0x02: "Medium", 0x03: "Low", 0x06: "Boost", 0x0F: "Auto"}

    if msg_id == "0100_20" and len(f) >= 20:

        # IDU5 Forever 0x11 = 17

        # IDU6:
        idu_mode = f[6]
        idu_mode = modes.get(idu_mode, f"Unknown({idu_mode:02X})")
        data["IDU_Mode"] = idu_mode

        # IDU7: oT
        data["IDU_Demand_Hz"] = f[7]

        # IDU8: assumed flags | ? 0x80 - soft start flag - doesnt show in SQLite due to dropping frames
        data["0100_20_b8"] = f[8]

        # IDU9: assumed flags

        # IDU10:
        data["0100_20_b10"] = f[10]

        # IDU11: TT
        data["Target_Setpoint"] = f[11]

        # IDU12:
        #XYE C0_B09 BIT 7 = Auto mode flag, bit 0-2 = idu fan speed position
        fan = f[12]
        fan = fan_map.get(fan, f"Raw({fan:02X})")
        data["IDU_Blower_Speed"] = fan

        # IDU13: T1
        # Off mode offset = -8.5C | freeze-protection mode confirmed for empty houses.
	# Still need to figure out percision due to skipping values
        room_c = ntc_temp(f[13])
        data["T1_Room_Temp"] = room_c

        # IDU14: T2
        #XYE T2A T2B ((byte - 47.5) / 1.77) Best guess
        data["T2_IDU_Coil_Temp"] = ntc_temp(f[14])

        # IDU15: Forever 0x19 = 25

        # IDU16: Mode Flags (Bit 1 = Boost)

        # IDU17: IDU request for higher demand in Zones
        # zone command {0,20,40,60,80}
        # Zones are a look up table
        # ODU target zone response in ODU17 / just like IDU Hz Demand the ODU can override this with ODU17
        data["IDU_Zone_Cmd"] = f[17]


    elif msg_id == "0001_20" and len(f) >= 20:

        # ODU5:

        # ODU6: Fr
        #Highest seen 70Hz in Defrost. Cooling cap observed = 63Hz.
        data["Compressor_Actual_Hz"] = f[6]
        data["Compressor_Actual_Hz_Pct"] = (f[6] / 75) * 100 # just to see in measurments

        # Cross-check for the HPB11 session-minute unwrap: if the compressor is off,
        # force the session tracker to reset even if a 0001_51 shutoff frame got dropped.
        # Without this, a missed shutoff makes the next session start look like a
        # 255->low rollover and silently adds a phantom +256 minutes.
        if f[6] == 0 and state["is_running"]:
            state["is_running"] = False
            state["rollover_count"] = 0
            state["last_raw_hpb11"] = 0

        # ODU7: assumed flags

        # ODU8: assumed flags

        # ODU9: T3
        # XYE Outdoor Coil T3 C0_B14 ((byte - 21.8) * 1.2435) Best guess
        data["T3_ODU_Coil_Temp"] = ntc_temp(f[9])

        # ODU10: T4
        # XYE Outdoor Temp C4_B21 ((byte - 9.9465) * .95) Best guess
        data["T4_Base_Outdoor_Temp"] = ntc_temp(f[10])

        # ODU11: TP
        data["TP_Discharge_Temp"] = Steinhart_temp(f[11])

        # ODU12: dL
        # Highest value 25 during Defrost / decoding from chart above
        data["Compressor_Actual_Amps"] = f[12] / 1.875

        # ODU13:
        # Left raw until verified with a meter. consider conversion from Testport
        data["AC_Input_Voltage_V"] = f[13]

        # ODU14:
        # ODU Mode / changes to defrost during a defrost cycle
        odu_mode = f[14]
        odu_mode = modes.get(odu_mode, f"Unknown({odu_mode:02X})")
        data["ODU_Mode"] = odu_mode

        # ODU15: T4
        # Byte 15 provides fractions (0, 64, 128, 192) = (0.0, 0.25, 0.50, 0.75 counts) / .25% steps of the .5C outdoor temp / 23.5C vs 23.625C
        data["T4_Outdoor_Temp"] = ntc_temp(f[10] + (f[15] / 256))

        # ODU16: Forever 0x1 = 1

        # ODU17 - ODU confirmed/echoed zone {0,20,40,60,80}
        # just like IDU Hz Demand the ODU can override this which inclued oil return cycles and maintenance
        data["ODU_Zone_Conf"] = f[17]


    elif msg_id == "0001_50" and len(f) >= 19:

        # HPA5-HPA10: Forever 0x0

        # HPA11:
        data["ODU_Fan_Speed_Actual_RPM"] = f[11] * 8

        # HPA12: RELABEL - Per Testport decoding this is labeled EXV
        # added EXV open percent for Home Assistant charting
        exv_position = f[12] * 2
        data["EXV_Position_Steps"] = exv_position
        data["EXV_Position_Pct"] = (exv_position / 480) * 100 # just to see in measurments

        # HPA13: Forever 0x72 = 114
        # This byte is the same value as the lowest byte in HPA15

        # HPA14: Confirmed VIA https://github.com/fmck3516/midea-telemetry-esphome/tree/maint
        data["Inverter_DC_Bus_Voltage_V"] = f[14] * 2 - 29

        # HPA15: 
        # Confirmed VIA https://github.com/fmck3516/midea-telemetry-esphome/tree/main
        # unsure about decoding due to base 114 value = 76.9F even during winter
        # conversion based on Testport
        data["0001_50_b15"] = ntc_temp(f[15])
        
        # HPA16 and HPA 17 are assumed
        # HPA16: integer part of fine actual compressor frequency.
        data["Compressor_Fine_Hz_Int"] = f[16]

        # HPA17: centi-Hz fractional part (0-99).
        data["Compressor_Fine_Hz_Frac"] = f[17]

        # Combined: HPA16 + HPA17/100 lands within 1Hz of ODU6 in 96.6% of running frames.
        data["Compressor_Actual_Hz_Fine"] = f[16] + f[17] / 100


    elif msg_id == "0001_51" and len(f) >= 20:

        # HPB5:
        data["ODU_Fan_Speed_Target_RPM"] = f[5] * 8

        # HPB6: RELABEL - Per Testport decoding this aligns with EXV Target
        data["EXV_Position_Target_Step"] = f[6] * 2

        # HPB7-HPB10: Forever 0x0

        # HPB11: 100%: Active running mins - WRAPS AT 255
        current_raw = f[11]
        
        # Detect startup (Current > 0, but previously thought off)
        if current_raw > 0 and not state["is_running"]:
            state["is_running"] = True
            state["rollover_count"] = 0
            
        # Detect rollover (Massive drop from high to low)
        elif current_raw < state["last_raw_hpb11"] and state["is_running"]:
            if state["last_raw_hpb11"] - current_raw > 200:
                state["rollover_count"] += 1

        # Detect shutoff
        if current_raw == 0:
            state["is_running"] = False
            state["rollover_count"] = 0
            
        # Calculate true minutes and assign to dictionary
        true_minutes = (state["rollover_count"] * 256) + current_raw
        
        data["Run_Session_Minutes"] = true_minutes
        
        # Save current raw back to the state dictionary for the next frame
        state["last_raw_hpb11"] = current_raw

        # HPB12: ticks every 60 active running mins | HPB13: ticks every 256 hours
        # Cross-validated: grew ~86h over 4 days at measured 90.0% compressor duty (96h*0.9=86.4)
        data["Run_Lifetime_Hours"] = (f[13] * 256) + f[12]

        # HPB14: 190 190

        # HPB15: 157 -> 93 ??? CHANGED ONCE AND STAYED STATIC AFTERWARDS...
	# Random bit flip after storm?
	# Season Flag? flipped between May 6th - May 7th
	# database didnt capture 24 hours of frames

        # HPB16: forever 106

        # HPB17: forever 161


    elif msg_id == "0001_52" and len(f) >= 20:

        # HPC5: Forever 0x22 = 34

        # HPC6: Forever 0x0

        # HPC7: PWM carrier frequency in kHz
        data["0001_52_b7"] = f[7]

        # HPC8: Assumed fan byte
        data["0001_52_b8"] = f[8]

        # HPC9: compressor PID's step command
        # predicts the direction of the Hz 
        delta = f[9]
        delta = delta if delta <= 127 else delta - 256
        data["Compressor_PID_Step"] = delta

        # HPC10:
        data["0001_52_b10"] = f[10]
        
        # HPC11
        data["0001_52_b11"] = f[11]

        # HPC12: Forever 0x0

        # HPC13: ODU Fan Speed Step (Gear Index)
        data["0001_52_b13"] = f[13]

        # HPC14-HPC17: Forever 0x0

    elif msg_id == "0001_53" and len(f) >= 20:
   

        # HPD5: Forever 0x0

        # HPD6: Resistance
        drive_comp = f[6]
        drive_comp = drive_comp if drive_comp <= 127 else drive_comp - 256
        data["Drive_Comp_Index"] = drive_comp


        # HPD7:
        data["Cycle_Stage"] = f[7]

        # HPD8: High DC Volts flag
        data["DC_Stage"] = f[8]

        # HPD9: RELABEL - compressor state machine: 0 = Off, 2 = Startup, 6 = Run.
        # (95/99 of the '2' frames were within 30 frames of a compressor start.)
        data["Compressor_State"] = f[9]

        # HPD10: Forever 0x0

        # HPD11:High
        # HPD12:Low
        # Assumed total watt reference due to idle values vs Senville app watt value
        # Previously labled EXV due to low idle value and quick 0 value before some cycles
        # Testport disproves EXV
        data["Total_Power"] = (f[12] * 256) + f[11]

        # HPD13: FT Highest seen 80 in defrost. Cooling cap observed = 63Hz.
        data["ODU_Target_Hz"] = f[13]

        # HPD14-HPD17: Forever 0x0

    return data

