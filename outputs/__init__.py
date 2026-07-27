"""
outputs package — adapters for writing simulation records to various sinks.
"""

import csv
import json
import os


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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_OUTPUT_MAP = {
    "csv": CsvOutput,
    "mqtt": MqttOutput,
    "console": ConsoleOutput,
}


def create_output(cfg: dict) -> BaseOutput:
    out_type = cfg.get("type", "console")
    cls = _OUTPUT_MAP.get(out_type)
    if cls is None:
        raise ValueError(f"Unknown output type: {out_type}")
    # Pass remaining keys as constructor kwargs
    kwargs = {k: v for k, v in cfg.items() if k != "type"}
    return cls(**kwargs)
