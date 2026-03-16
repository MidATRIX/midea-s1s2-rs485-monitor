class FrameBuffer:
    """
    RS485 byte stream → validated raw frame slices.

    - Every frame starts with 0xA0
    - Byte[4] is payload length (LL)
    - Real wire frame layout (confirmed on ODU and IDU captures):

        [A0][addr_hi][addr_lo][msg_id][LL][payload x LL][B??][CRC_lo][CRC_hi]
          0     1        2       3     4    5 .. LL+4    LL+5   LL+6    LL+7

      Total mandatory bytes = LL + 8
      CRC-16/MODBUS covers bytes[0 .. LL+5] (i.e. frame[:-2])
      byte[LL+5] is an undocumented fixed byte (0x00 in all known examples);
      it is part of the frame and is covered by the CRC.

    - A single 0x00 byte may follow a complete frame as bus padding (seen on
      IDU / direction-01 frames); it is consumed silently.
    - Any other byte after a valid frame is left in the buffer unchanged.
    - CRC is the only validity test — no addresses, IDs, or lengths are hardcoded.

    The parser is deliberately tolerant:
    - Unknown device addresses are accepted
    - Unknown message IDs are accepted
    - Any payload length <= MAX_PAYLOAD is accepted
    - On a CRC miss the leading 0xA0 is emitted as noise and the search resumes
      from the very next byte — no data is skipped beyond that one byte
    """

    # Hard ceiling on payload length. Not a protocol rule — just protection
    # against a garbage length byte causing us to wait for hundreds of bytes
    # before discovering the frame is invalid. Raise if you ever see legitimate
    # frames larger than this.
    MAX_PAYLOAD = 64

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> None:
        """Push raw bytes from the TCP/serial stream into the buffer."""
        self._buf.extend(data)

    def get_frame(self):
        """
        Try to extract the next valid frame from the internal buffer.

        Returns
        -------
        frame : bytes or None
            Raw frame bytes (header through CRC, padding stripped) if a valid
            frame was found, otherwise None.
        noise : bytes
            Any bytes that were consumed but could not be part of any valid
            frame. May be empty. Caller should log these for analysis.
        """
        noise = bytearray()

        while True:

            # ── Find the next candidate start byte ──────────────────────────
            a0 = self._buf.find(b'\xa0')

            if a0 == -1:
                # No 0xA0 anywhere — everything currently buffered is noise
                noise.extend(self._buf)
                self._buf.clear()
                return None, bytes(noise)

            # Everything before the 0xA0 is noise
            if a0 > 0:
                noise.extend(self._buf[:a0])
                del self._buf[:a0]

            # ── Need at least 5 bytes to know the frame size ─────────────────
            if len(self._buf) < 5:
                return None, bytes(noise)

            length = self._buf[4]  # payload length byte (LL)

            # ── Sanity check on length ────────────────────────────────────────
            # A suspiciously large value almost certainly means this 0xA0 is
            # embedded data, not a frame start. Discard it as noise and resume.
            if length > self.MAX_PAYLOAD:
                noise.append(self._buf[0])
                del self._buf[0]
                continue  # search for the next 0xA0

            frame_size = length + 8  # see class docstring

            # ── Wait for the full frame to arrive ────────────────────────────
            if len(self._buf) < frame_size:
                return None, bytes(noise)

            candidate = bytes(self._buf[:frame_size])

            # ── CRC check — the only real validation ─────────────────────────
            if self._crc_ok(candidate):
                del self._buf[:frame_size]

                # Consume a trailing 0x00 padding byte if present — but only
                # exactly 0x00. Anything else belongs to the next frame (or is
                # noise that the next call will handle).
                if self._buf and self._buf[0] == 0x00:
                    del self._buf[0]

                return candidate, bytes(noise)

            else:
                # CRC failed — this 0xA0 was not a real frame start.
                # Emit it as noise and try again from the next byte.
                noise.append(self._buf[0])
                del self._buf[0]
                # Loop — the next iteration will search for the next 0xA0

    # ── CRC-16/MODBUS ─────────────────────────────────────────────────────────

    @staticmethod
    def _crc_ok(frame: bytes) -> bool:
        """
        Verify CRC-16/MODBUS on a candidate frame.
        CRC covers all bytes except the final two (which carry the CRC itself).
        Wire order is little-endian: frame[-2] = CRC low byte, frame[-1] = CRC high byte.
        """
        crc = 0xFFFF
        for byte in frame[:-2]:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return frame[-2] == (crc & 0xFF) and frame[-1] == (crc >> 8)
