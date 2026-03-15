def process_payload(msg_id, f):
    data = {}

    if msg_id == "0100_20" and len(f) >= 20:
        
        # Byte 5:
        
        # Byte 6:
        raw_idu_mode = f[6]
        modes = {0x00: "Off", 0x01: "Cool", 0x02: "Heat", 0x03: "Fan", 0x04: "Dry"}
        data["IDU_Mode"] = modes.get(raw_idu_mode, f"Unknown({raw_idu_mode:02X})")
       
        # Byte 7:
        data["IDU_Demand_Hz"] = f[7]
        
        # Byte 8: ? 0x80 - soft start flag
        
        # Byte 9:
        
        # Byte 10:
        
        # Byte 11:
        data["Target_Setpoint"] = f[11]

        # Byte 12:
        raw_fan = f[12]
        fan_map = {0x01: "High", 0x02: "Medium", 0x03: "Low", 0x06: "Boost", 0x0F: "Auto"}
        data["IDU_Blower_Speed"] = fan_map.get(raw_fan, f"Raw({raw_fan:02X})")
        
        # Byte 13:
        data["T1_Room_Temp"] = (f[13] - 61) / 2 # if mode off or dry 61 else 66 / clearly not done
        
        # Byte 14:
        data["T2_IDU_Coil_Temp"] = (f[14] - 61) / 2
        
        # Byte 15:
        
        # Byte 16: Mode Flags (Bit 1 = Boost) / forgot about this
#         data["boost_mode"] = True if (f[16] & 2) else False

#        data["0100_20"] = "0100_20"



    elif msg_id == "0001_20" and len(f) >= 20:
        
        # Byte 7: Actual Load
        data["Compressor_Actual_Hz"] = f[6] # In defrost mode it got up to 80Hz
        
        # Byte 8:
        
        # Byte 9:
        data["T3_ODU_Coil_Temp"] = (f[9] - 61) / 2
        
        # Byte 10 & 15: T4 Outdoor Ambient Temperature
        # Base offset of -61. Byte 15 provides fractions (0, 64, 128, 192) = (0.0, 0.125, 0.25, 0.375)
        base_temp_c = (f[10] - 61) / 2
        fraction_c = f[15] / 512
        data["T4_Outdoor_Temp"] = base_temp_c + fraction_c
        
        # Byte 11:
        data["TP_Discharge_Temp"] = f[11] / 2
        
        # Byte 12:
        data["Compressor_Actual_Amps"] = f[12] / 2
        
        # Byte 13: ? Resistance
        data["0001_20_b13"] = f[13]

        # Byte 14: ODU Mode
        raw_odu_mode = f[14]
        modes = {0x00: "Off", 0x01: "Cool", 0x02: "Heat", 0x03: "Fan", 0x04: "Dry", 0x07: "Defrost"}
        data["ODU_Mode"] = modes.get(raw_odu_mode, f"Unknown({raw_odu_mode:02X})")
        
        # Byte 15:
        
        # Byte 16:

#        data["0001_20"] = "0001_20"
   




    elif msg_id == "0001_50" and len(f) >= 19:
    
        # Byte 5:
        
        # Byte 6:
        
        # Byte 7:
        
        # Byte 8:
        
        # Byte 9:
        
        # Byte 10:
        
        # Byte 11:
        data["ODU_Fan_Speed_Actual_RPM"] = f[11] * 8
        
        # Byte 12:
        data["ODU_DC_Bus_Voltage_Actual"] = f[12]
        
        # Byte 13:
        
        # Byte 14:
        data["AC_Input_Voltage_V"] = f[14]
        
        # Byte 15:
        data["Inverter_DC_Bus_Voltage_V"] = f[15]
        
        # Byte 16:
        data["IPM_Load_Index"] = f[16] # I no longer think this is amp average but it is a caculated number
        
#        data["0001_50"] = "0001_50"




    elif msg_id == "0001_51" and len(f) >= 20:         

        # Byte 5:
        data["ODU_Fan_Speed_Target_RPM"] = f[5] * 8
        
        # Byte 6:
        data["ODU_DC_Bus_Voltage_Target"] = f[6]
        
        # Byte 7:
        
        # Byte 8:
        
        # Byte 9:
        
        # Byte 10:
        
        # Byte 11:
        data["Run_Minutes_Clock"] = f[11]
        
        # Byte 12:
        data["Run_Hours_Clock"] = (f[12] * 256) / 60
        
        # Byte 13:
        
        # Byte 14:
        
        # Byte 15:
        
        # Byte 16:
        
#        data["0001_51"] = "0001_51"
        
        
        
    elif msg_id == "0001_52" and len(f) >= 20:

        # Byte 5:
        
        # Byte 6:
        
        # Byte 7:
        data["IPM_Heatsink_Temp_1"] = f[7]
        
        # Byte 8:
        data["IPM_Heatsink_Temp_2"] = f[8]
        
        # Byte 9: Signed integer (Two's Complement)
        raw_delta = f[9]
        data["PID_Step_Delta"] = raw_delta if raw_delta <= 127 else raw_delta - 256 #
        
        # Byte 10:
        data["IPM_Phase_Current_A"] = f[10] # This is not PID_P_Error
        
        # Byte 11:
        data["IPM_Phase_Current_B"] = f[11] # This is not PID_I_Error
        
        # Byte 12:
        
        # Byte 13: HPC13 is the ODU Fan Speed Step (Gear Index)
        data["ODU_Fan_Speed_Step"] = f[13]
        # Byte 14:
        
        # Byte 15:
        
        # Byte 16:
        
#        data["0001_52"] = "0001_52"



    elif msg_id == "0001_53" and len(f) >= 20:

        # Byte 5:
        
        # Byte 6: Routine Phase Modifier (Signed 8-bit)
        raw_phase_mod = f[6]
        data["Phase_Modifier"] = raw_phase_mod if raw_phase_mod <= 127 else raw_phase_mod - 256
        
        # Byte 7: 0-4 = Idle, 5-9 = Active Ramp
        data["Routine_Phase_Step"] = f[7]
        
        # Byte 8: Triggered by Oil Return or High Load
        data["Active_Ramp_Routine"] = f[8]
        
        # Byte 9:
        
        # Byte 10:
        
        # Byte 11: EEV Low
        # Byte 12: EEV High
        data["EXV_Position_Steps"] = (f[12] * 256) + f[11] # in defrost mode it got up to 4000 steps
        
        # Byte 13: The PID target limit
        data["ODU_Target_Hz"] = f[13]
        
        # Byte 14:
        
        # Byte 15:
        
        # Byte 16:
        
#        data["0001_53"] = "0001_53"

        
#    elif msg_id == "0001_25" and len(f) >= 20:      
        # Byte 5:
        
        # Byte 6:
        
        # Byte 7:
        
        # Byte 8:
        
        # Byte 9:
        
        # Byte 10:
        
        # Byte 11:
        
        # Byte 12:
        
        # Byte 13:
        
        # Byte 14:
        
        # Byte 15:
        
        # Byte 16:
        
#        data["0001_25"] = "0001_25"


    return data
