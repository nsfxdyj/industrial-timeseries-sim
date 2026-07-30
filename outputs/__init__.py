"""
outputs package — adapters for writing simulation records to various sinks.
"""

import csv
import json
import os
import socket
from datetime import datetime, timezone

from outputs.modbus_tcp import ModbusTcpOutput
from outputs.web_dashboard import WebDashboardOutput


class BaseOutput:
    """Abstract base for all output sinks."""

    def open(self):
        pass

    def write(self, record: dict):
        raise NotImplementedError

    def close(self):
        pass


class CsvOutput(BaseOutput):
    """Append records to a CSV file."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._file = None
        self._writer = None
        self._wrote_header = False

    def open(self):
        # Determine if file already exists to know if we need a header
        exists = os.path.isfile(self.filepath)
        self._file = open(self.filepath, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._wrote_header = exists

    def write(self, record: dict):
        if not self._wrote_header:
            headers = ["timestamp", "sensor", "value"] + sorted(record["tags"].keys())
            self._writer.writerow(headers)
            self._wrote_header = True

        row = [
            record["timestamp"],
            record["sensor"],
            record["value"],
        ]
        for key in sorted(record["tags"].keys()):
            row.append(record["tags"][key])
        self._writer.writerow(row)
        self._file.flush()

    def close(self):
        if self._file:
            self._file.close()


class MqttOutput(BaseOutput):
    """Publish records to an MQTT broker as JSON payloads."""

    def __init__(self, broker: str, port: int = 1883, topic: str = "sensors/data",
                 client_id: str = "ts-sim", qos: int = 0, username: str = None,
                 password: str = None):
        self.broker = broker
        self.port = port
        self.topic = topic
        self.client_id = client_id
        self.qos = qos
        self.username = username
        self.password = password
        self._client = None

    def open(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise ImportError(
                "MQTT output requires 'paho-mqtt'. Install: pip install paho-mqtt"
            ) from exc

        self._client = mqtt.Client(client_id=self.client_id)
        if self.username is not None:
            self._client.username_pw_set(self.username, self.password)
        self._client.connect(self.broker, self.port)
        self._client.loop_start()

    def write(self, record: dict):
        payload = json.dumps(record, ensure_ascii=False)
        self._client.publish(self.topic, payload, qos=self.qos)

    def close(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()


class ConsoleOutput(BaseOutput):
    """Print every record to stdout as JSON lines."""

    def write(self, record: dict):
        print(json.dumps(record, ensure_ascii=False))


class InfluxDbOutput(BaseOutput):
    """
    Write records using InfluxDB Line Protocol.

    Supports two transports:

    * **udp** (default, port 8089) — fire-and-forget, zero extra deps.
      Requires InfluxDB to have a UDP listener configured:
      ``[[udp]] enabled = true bind-address = ":8089"``

    * **http** (port 8086) — writes to InfluxDB 1.x ``/write`` endpoint.
      Optional basic-auth via ``username`` / ``password``.

    The measurement name is configurable; sensor name and all tags are
    emitted as InfluxDB tags, while ``value`` is the single field.
    Timestamps are automatically converted from ISO-8601 to the
    requested precision (``s | ms | u | ns``).
    """

    # Precision multiplier: how many units per second
    _PREC_MUL = {
        "s": 1,
        "ms": 1_000,
        "u": 1_000_000,
        "ns": 1_000_000_000,
    }

    def __init__(
        self,
        measurement: str = "sensor_data",
        host: str = "localhost",
        port: int = 8089,
        protocol: str = "udp",
        database: str = "industrial",
        precision: str = "u",
        username: str = None,
        password: str = None,
    ):
        self.measurement = measurement
        self.host = host
        self.port = port
        self.protocol = protocol.lower().strip()
        self.database = database
        if precision not in self._PREC_MUL:
            raise ValueError(f"precision must be one of {list(self._PREC_MUL.keys())}")
        self.precision = precision
        self.username = username
        self.password = password

        self._sock = None
        self._http_session = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _escape_tag(s: str) -> str:
        """Escape commas, spaces and equals in tag values."""
        return s.replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")

    @staticmethod
    def _to_timestamp(iso_str: str, precision: str) -> int:
        """Convert an ISO-8601 string to an integer timestamp at given precision."""
        # Parse ISO-8601 with timezone
        dt = datetime.fromisoformat(iso_str)
        # Ensure UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        # Seconds since epoch as float
        secs = dt.timestamp()
        mul = InfluxDbOutput._PREC_MUL[precision]
        return int(secs * mul)

    def _build_line(self, record: dict) -> str:
        """Build a single Line Protocol line from a record."""
        # measurement
        parts = [self._escape_tag(self.measurement)]

        # tags: sensor name + all user tags (sorted for determinism)
        tags = [("sensor", record["sensor"])]
        for k, v in sorted(record.get("tags", {}).items()):
            tags.append((k, str(v)))
        tag_str = ",".join(f"{self._escape_tag(k)}={self._escape_tag(v)}" for k, v in tags)
        parts.append(tag_str)

        # fields: single value field
        val = record["value"]
        # InfluxDB line protocol: integer if whole number, else float
        if isinstance(val, int) or (isinstance(val, float) and val.is_integer()):
            field_val = f"{int(val)}i"
        else:
            field_val = f"{val}"
        parts.append(f"value={field_val}")

        # timestamp
        ts = self._to_timestamp(record["timestamp"], self.precision)
        parts.append(str(ts))

        return " ".join(parts)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def open(self):
        if self.protocol == "udp":
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        elif self.protocol == "http":
            try:
                import requests
            except ImportError as exc:
                raise ImportError(
                    "InfluxDB HTTP output requires 'requests'. "
                    "Install: pip install requests"
                ) from exc
            self._http_session = requests.Session()
            if self.username:
                self._http_session.auth = (self.username, self.password or "")
        else:
            raise ValueError(f"Unknown protocol: {self.protocol}. Use 'udp' or 'http'.")

    def write(self, record: dict):
        line = self._build_line(record)
        if self.protocol == "udp":
            self._sock.sendto(line.encode("utf-8"), (self.host, self.port))
        else:  # http
            url = f"http://{self.host}:{self.port}/write"
            params = {"db": self.database, "precision": self.precision}
            try:
                resp = self._http_session.post(url, params=params, data=line)
                if resp.status_code not in (200, 204):
                    # Non-fatal: simulation should not crash because DB is down
                    print(f"[InfluxDB] write failed: HTTP {resp.status_code} — {resp.text.strip()}")
            except Exception as exc:
                print(f"[InfluxDB] write error: {exc}")

    def close(self):
        if self._sock:
            self._sock.close()
        if self._http_session:
            self._http_session.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_OUTPUT_MAP = {
    "csv": CsvOutput,
    "mqtt": MqttOutput,
    "console": ConsoleOutput,
    "influxdb": InfluxDbOutput,
    "modbus_tcp": ModbusTcpOutput,
    "web_dashboard": WebDashboardOutput,
}


def create_output(cfg: dict) -> BaseOutput:
    out_type = cfg.get("type", "console")
    cls = _OUTPUT_MAP.get(out_type)
    if cls is None:
        raise ValueError(f"Unknown output type: {out_type}")
    # Pass remaining keys as constructor kwargs
    kwargs = {k: v for k, v in cfg.items() if k != "type"}
    return cls(**kwargs)
