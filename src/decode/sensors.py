def process_payload(msg_id, f):
    data = {}

    if msg_id == "0100_20" and len(f) >= 20:
        
        # IDU5
        
        # IDU6:
        raw_idu_mode = f[6]
        modes = {0x00: "Off", 0x01: "Cool", 0x02: "Heat", 0x03: "Fan", 0x04: "Dry"}
        data["IDU_Mode"] = modes.get(raw_idu_mode, f"Unknown({raw_idu_mode:02X})")
       
        # IDU7:
        data["IDU_Demand_Hz"] = f[7]
        
        # IDU8: ? 0x80 - soft start flag - doesnt show in db due to dropped frames
        
        # IDU9:
        
        # IDU10:
        
        # IDU11:
        data["Target_Setpoint"] = f[11]

        # IDU12:
        raw_fan = f[12]
        fan_map = {0x01: "High", 0x02: "Medium", 0x03: "Low", 0x06: "Boost", 0x0F: "Auto"}
        data["IDU_Blower_Speed"] = fan_map.get(raw_fan, f"Raw({raw_fan:02X})")
        
        # IDU13:
        data["T1_Room_Temp"] = (f[13] - 61) / 2 # if mode off or dry 61 else 66 / clearly not done
        
        # IDU14:
        data["T2_IDU_Coil_Temp"] = (f[14] - 61) / 2
        
        # IDU15:
        
        # IDU16: Mode Flags (Bit 1 = Boost) / forgot about this

        # IDU17:



    elif msg_id == "0001_20" and len(f) >= 20:
        
        # ODU7: Actual Load
        data["Compressor_Actual_Hz"] = f[6] # In defrost mode it got up to 80Hz
        
        # ODU8:
        
        # ODU9:
        data["T3_ODU_Coil_Temp"] = (f[9] - 53) / 2
        
        # ODU10 & 15: T4 Outdoor Ambient Temperature
        # Base offset of -61. Byte 15 provides fractions (0, 64, 128, 192) = (0.0, 0.125, 0.25, 0.375)
        base_temp_c = (f[10] - 61) / 2
        fraction_c = f[15] / 512
        data["T4_Outdoor_Temp"] = base_temp_c + fraction_c
        
        # ODU11:
        data["TP_Discharge_Temp"] = f[11] / 2
        
        # ODU12:
        data["Compressor_Actual_Amps"] = f[12] / 2
        
        # ODU13: ? Resistance
        data["0001_20_b13"] = f[13]

        # ODU14: ODU Mode
        raw_odu_mode = f[14]
        modes = {0x00: "Off", 0x01: "Cool", 0x02: "Heat", 0x03: "Fan", 0x04: "Dry", 0x07: "Defrost"}
        data["ODU_Mode"] = modes.get(raw_odu_mode, f"Unknown({raw_odu_mode:02X})")
        
        # ODU15: Outside temp 1/4 degree / still need to figure out the basics :(
        
        # ODU16:
        
        # ODU17:





    elif msg_id == "0001_50" and len(f) >= 19:
    
        # HPA5:
        
        # HPA6:
        
        # HPA7:
        
        # HPA8:
        
        # HPA9:
        
        # HPA10:
        
        # HPA11:
        data["ODU_Fan_Speed_Actual_RPM"] = f[11] * 8
        
        # HPA12:
        data["ODU_DC_Bus_Voltage_Actual"] = f[12]
        
        # HPA13:
        
        # HPA14:
        data["AC_Input_Voltage_V"] = f[14]
        
        # HPA15:
        data["Inverter_DC_Bus_Voltage_V"] = f[15]
        
        # HPA16:
        data["IPM_Load_Index"] = f[16] # I no longer think this is amp average but it is a caculated number
        
        # HPA17:
        




    elif msg_id == "0001_51" and len(f) >= 20:         

        # HPB5:
        data["ODU_Fan_Speed_Target_RPM"] = f[5] * 8
        
        # HPB6:
        data["ODU_DC_Bus_Voltage_Target"] = f[6]
        
        # HPB7:
        
        # HPB8:
        
        # HPB9:
        
        # HPB10:
        
        # HPB11: Active running mins
        data["Run_Session_Minutes"] = f[11]
        
        # HPB12: ticks every 60 active running mins
        # HPB13: ticks every 256 active running hours
        data["Run_Hours_Clock"] = (f[13] * 256) + f[12]
        
        # HPB14:
        
        # HPB15:
        
        # HPB16:
        
        # HPB17:
        
        
        
        
    elif msg_id == "0001_52" and len(f) >= 20:

        # HPC5:
        
        # HPC6:
        
        # HPC7:
        data["IPM_Heatsink_Temp_1"] = f[7]
        
        # HPC8:
        data["IPM_Heatsink_Temp_2"] = f[8]
        
        # HPC9: Signed integer (Two's Complement)
        raw_delta = f[9]
        data["Compressor_PID_Step"] = raw_delta if raw_delta <= 127 else raw_delta - 256 #
        
        # HPC10:
        data["IPM_Phase_Current_A"] = f[10] # This is not PID_P_Error
        
        # HPC11:
        data["IPM_Phase_Current_B"] = f[11] # This is not PID_I_Error
        
        # HPC12:
        
        # HPC13: HPC13 is the ODU Fan Speed Step (Gear Index)
        data["ODU_Fan_Speed_Step"] = f[13]
        
        # HPC14:
        
        # HPC15:
        
        # HPC16:
        
        # HPC17:
        



    elif msg_id == "0001_53" and len(f) >= 20:

        # HPD5:
                
        # HPD6: Routine Phase Modifier (Signed 8-bit)
        raw_phase_mod = f[6]
        data["Phase_Modifier"] = raw_phase_mod if raw_phase_mod <= 127 else raw_phase_mod - 256
        
        # HPD7: 0-4 = Idle, 5-9 = Active Ramp
        data["Routine_Phase_Step"] = f[7]
        
        # HPD8: Triggered by Oil Return or High Load
        data["Active_Ramp_Routine"] = f[8]
        
        # HPD9:
        
        # HPD10:
        
        # HPD11: EEV Low
        # HPD12: EEV High
        data["EXV_Position_Steps"] = (f[12] * 256) + f[11] # in defrost mode it got up to 4000 steps
        
        # HPD13: The PID target limit
        data["ODU_Target_Hz"] = f[13]
        
        # HPD14:
        
        # HPD15:
        
        # HPD16:
        
        # HPD17:
        

        
#    elif msg_id == "0001_25" and len(f) >= 20:      
        # ODUY5:
        
        # ODUY6:
        
        # ODUY7:
        
        # ODUY8:
        
        # ODUY9:
        
        # ODUY10:
        
        # ODUY11:
        
        # ODUY12:
        
        # ODUY13:
        
        # ODUY14:
        
        # ODUY15:
        
        # ODUY16:
        
        # ODUY17:
        


    return data
