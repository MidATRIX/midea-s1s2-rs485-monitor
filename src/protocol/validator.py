import logging

class FrameValidator:
    def __init__(self):
        self.logger = logging.getLogger("validator")

    def crc16_modbus(self, data: bytes):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc.to_bytes(2, 'little')

    def process(self, frame: bytes):
        if not frame or len(frame) < 9:
            return "🗑️", 0, "NONE"

        # Frame is now guaranteed to have NO padding byte.
        # The last 2 bytes are ALWAYS the CRC.
        data_packet = frame[:-2]
        actual_crc_bytes = frame[-2:]   

        actual_crc_int = int.from_bytes(actual_crc_bytes, 'little')
        expected_crc_bytes = self.crc16_modbus(data_packet)
        
        msg_id = f"{frame[1]:02X}{frame[2]:02X}_{frame[3]:02X}"
        
        if actual_crc_bytes == expected_crc_bytes:
            return "✅", actual_crc_int, msg_id 
        else:
            self.logger.error(f"CRC FAIL: {actual_crc_bytes.hex()} != {expected_crc_bytes.hex()}")
            return "❌", actual_crc_int, msg_id

    def get_sensor_data(self, frame: bytes):
        return {}
