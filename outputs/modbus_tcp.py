"""
Modbus TCP Slave output — exposes sensor data as holding registers.

A lightweight, zero-dependency Modbus TCP server that maps the latest
sensor values into holding registers (FC 03). Useful for testing
SCADA/HMI integrations without real PLCs or remote I/O.

Register layout (auto-assigned, per sensor):
    Address N  →  uint16( sensor_value * scale_factor )

Example: temperature = 67.84 °C, scale_factor=100 → register = 6784
"""

import socket
import struct
import threading


class ModbusTcpOutput:
    """
    Modbus TCP slave output.

    Parameters (from YAML):
        port         — TCP listen port (default 502; use >1024 for non-root)
        unit_id      — Modbus unit/slave ID (default 1)
        scale_factor — Multiply raw value before casting to uint16 (default 100)
    """

    # Modbus limits
    _MAX_REGS_PER_READ = 125

    def __init__(self, port: int = 502, unit_id: int = 1, scale_factor: float = 100.0):
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.scale_factor = float(scale_factor)

        self._registers = {}          # addr -> uint16
        self._sensor_addrs = {}       # sensor_name -> addr
        self._next_free_addr = 0
        self._lock = threading.Lock()

        self._server_sock = None
        self._accept_thread = None
        self._running = False
        self._clients = []            # list of active client sockets

    # ------------------------------------------------------------------
    # BaseOutput API
    # ------------------------------------------------------------------
    def open(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("0.0.0.0", self.port))
        self._server_sock.listen(5)
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        print(
            f"[ModbusTCP] Slave listening on 0.0.0.0:{self.port} "
            f"(unit_id={self.unit_id}, scale_factor={self.scale_factor})"
        )

    def write(self, record: dict):
        sensor = record["sensor"]
        value = record["value"]

        # Auto-assign register address on first sight
        if sensor not in self._sensor_addrs:
            self._sensor_addrs[sensor] = self._next_free_addr
            self._next_free_addr += 1
            print(
                f"[ModbusTCP] Sensor '{sensor}' mapped to "
                f"holding register {self._sensor_addrs[sensor]}"
            )

        addr = self._sensor_addrs[sensor]
        scaled = int(round(value * self.scale_factor))
        # Clamp to uint16 range
        scaled = max(0, min(scaled, 65535))

        with self._lock:
            self._registers[addr] = scaled

    def close(self):
        self._running = False
        # Close all client sockets to unblock recv threads
        for c in self._clients:
            try:
                c.close()
            except OSError:
                pass
        self._clients.clear()
        if self._server_sock:
            self._server_sock.close()
        if self._accept_thread:
            self._accept_thread.join(timeout=2.0)
        print("[ModbusTCP] Server stopped.")

    # ------------------------------------------------------------------
    # Server internals
    # ------------------------------------------------------------------
    def _accept_loop(self):
        while self._running:
            try:
                self._server_sock.settimeout(1.0)
                conn, client_addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            print(f"[ModbusTCP] Client connected: {client_addr}")
            t = threading.Thread(
                target=self._handle_client, args=(conn, client_addr), daemon=True
            )
            t.start()

    def _handle_client(self, conn: socket.socket, client_addr):
        self._clients.append(conn)
        try:
            while self._running:
                header = self._recv_all(conn, 7)
                if header is None:
                    break  # client closed

                tid, pid, length, uid = struct.unpack(">HHHB", header)
                # Read PDU (length field includes unit_id, already consumed)
                pdu_len = length - 1
                if pdu_len < 1:
                    break
                pdu = self._recv_all(conn, pdu_len)
                if pdu is None:
                    break

                fc = pdu[0]
                resp_pdu = self._process_pdu(fc, pdu[1:], uid)

                # Build MBAP header for response
                resp_length = 1 + len(resp_pdu)  # unit_id + pdu
                resp_header = struct.pack(">HHHB", tid, pid, resp_length, uid)
                conn.sendall(resp_header + resp_pdu)
        except Exception as exc:
            print(f"[ModbusTCP] Client {client_addr} error: {exc}")
        finally:
            self._clients.remove(conn)
            conn.close()
            print(f"[ModbusTCP] Client disconnected: {client_addr}")

    def _recv_all(self, conn: socket.socket, n: int):
        """Read exactly n bytes or return None on EOF."""
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def _process_pdu(self, fc: int, data: bytes, unit_id: int) -> bytes:
        # Unit ID filter
        if unit_id != self.unit_id:
            # Silently ignore (some masters broadcast with unit_id 0)
            return b""

        if fc == 0x03:
            return self._read_holding_registers(data)

        # Illegal function (FC not supported)
        return bytes([fc | 0x80, 0x01])

    def _read_holding_registers(self, data: bytes) -> bytes:
        if len(data) < 4:
            return bytes([0x83, 0x03])  # illegal data value

        start_addr, quantity = struct.unpack(">HH", data[:4])

        if quantity < 1 or quantity > self._MAX_REGS_PER_READ:
            return bytes([0x83, 0x03])  # illegal data value

        with self._lock:
            values = []
            for i in range(quantity):
                addr = start_addr + i
                values.append(self._registers.get(addr, 0))

        # FC 03 response: FC, byte count, data
        resp = bytes([0x03, len(values) * 2])
        for v in values:
            resp += struct.pack(">H", v)
        return resp
