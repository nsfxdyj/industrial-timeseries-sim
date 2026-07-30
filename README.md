# industrial-timeseries-sim

A lightweight, **dependency-light** industrial sensor data simulator for testing time-series databases, dashboards, and MQTT data pipelines. Built for embedded & Industrial IoT engineers who need realistic — but synthetic — data without deploying real hardware.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Why?

- You are building an MQTT → InfluxDB pipeline and want data **now**, not after the next site visit.
- You need to test Grafana alarms against known fault patterns (spikes, drops, drift).
- You want to validate Modbus/SCADA integration logic before the PLC is wired up.
- You need reproducible, seeded datasets for CI regression tests.

## Features

| Feature | Description |
|---------|-------------|
| **5 sensor types** | Temperature, Pressure, Vibration, Current, Voltage — each with realistic physics |
| **Signal models** | Base value + sinusoidal cycle + Gaussian noise + linear drift |
| **Fault injection** | Configurable spike, drop, sag/swell probabilities — test your alerting |
| **Multiple outputs** | Console (JSON lines), CSV append, MQTT publish, InfluxDB Line Protocol, Modbus TCP Slave, **Web Dashboard** |
| **YAML scenarios** | One config file defines all sensors, tags, and outputs |
| **Grafana ready** | Bundled dashboard JSON for instant visualization |
| **Pure Python** | Runs on anything that has Python 3.8+ (laptop, CI runner, ARM edge box) |
| **Deterministic** | Optional RNG seed for repeatable test datasets |

## Quick Start

```bash
# 1. Clone
$ git clone https://github.com/nsfxdyj/industrial-timeseries-sim.git
$ cd industrial-timeseries-sim

# 2. Install deps
$ pip install -r requirements.txt

# 3. Run the bundled factory-floor demo
$ python ts_sim.py scenarios/factory_floor.yaml --duration 30
```

You will see JSON lines like:

```json
{"timestamp": "2026-07-27T04:25:10.123456+00:00", "sensor": "motor_temp", "value": 67.842301, "tags": {"location": "motor_A", "unit": "degC"}}
{"timestamp": "2026-07-27T04:25:10.123456+00:00", "sensor": "bus_voltage", "value": 381.452112, "tags": {"location": "bus_bar", "unit": "V"}}
```

…and a `factory_floor_data.csv` will be created in the working directory.

## Scenario File Format

Scenarios are YAML files. Here is a minimal example:

```yaml
name: "Compressor Room"
interval: 2.0

sensors:
  - name: compressor_temp
    type: temperature
    base: 75.0
    amplitude: 4.0
    period: 300.0
    noise: 0.5
    drift_rate: 0.005
    fault_prob: 0.001
    fault_spike: 25.0
    tags:
      machine: "compressor_01"
      unit: "degC"

outputs:
  - type: console
  - type: csv
    filepath: "./compressor_room.csv"
```

### Sensor Parameters (common)

| Param | Default | Description |
|-------|---------|-------------|
| `base` / `nominal` | varies | Sensor operating point |
| `amplitude` | varies | Sinusoidal fluctuation amplitude |
| `period` | varies | Oscillation period in **samples** (not seconds) |
| `noise` | varies | Gaussian noise standard deviation |
| `drift_rate` | 0.0 | Linear drift per sample |
| `fault_prob` | 0.0 | Probability of a fault event per sample (0‒1) |
| `fault_spike` / `fault_drop` / `fault_sag` / `fault_swell` | varies | Fault magnitude |
| `seed` | `None` | RNG seed for reproducibility |

### Output Types

| Type | Required params | Optional params |
|------|-----------------|-----------------|
| `console` | — | — |
| `csv` | `filepath` | — |
| `mqtt` | `broker` | `port` (1883), `topic` (`sensors/data`), `client_id`, `qos` (0), `username`, `password` |
| `influxdb` | — | `measurement` (`sensor_data`), `host` (`localhost`), `port` (8089), `protocol` (`udp`), `database` (`industrial`), `precision` (`u`), `username`, `password` |
| `modbus_tcp` | — | `port` (502), `unit_id` (1), `scale_factor` (100) |
| `web_dashboard` | — | `host` (`0.0.0.0`), `port` (8080) |

## InfluxDB + Grafana Stack

The simulator can feed directly into **InfluxDB** via Line Protocol, and a pre-built **Grafana dashboard** is included.

### 1. Start InfluxDB (Docker example)

```bash
$ docker run -d \
  --name influxdb \
  -p 8086:8086 -p 8089:8089/udp \
  -e INFLUXDB_DB=industrial \
  -e INFLUXDB_UDP_ENABLED=true \
  -e INFLUXDB_UDP_BIND_ADDRESS=:8089 \
  influxdb:1.8
```

### 2. Run the simulator with InfluxDB output

```bash
$ python ts_sim.py scenarios/influxdb_udp.yaml --duration 120
```

### 3. Import the Grafana dashboard

1. Open Grafana → **Create** → **Import**.
2. Upload `dashboards/grafana_factory_floor.json`.
3. Select your InfluxDB data source.
4. Enjoy live sensor panels with color-coded thresholds.

The dashboard includes:

- **5 live stat tiles** — current value with color thresholds (green → orange → red)
- **5 trend graphs** — time-series history with mean / max / min aggregations
- **Auto-refresh** — updates every 5 seconds

### InfluxDB Output Config Reference

```yaml
outputs:
  - type: influxdb
    measurement: "factory_floor"   # InfluxDB measurement name
    host: "localhost"              # InfluxDB host
    port: 8089                     # 8089 for UDP, 8086 for HTTP
    protocol: "udp"                # "udp" or "http"
    database: "industrial"         # Only used for HTTP
    precision: "u"                 # s | ms | u (μs) | ns
    # username: "admin"            # HTTP basic-auth (optional)
    # password: "secret"
```

> **Note:** UDP is the default because it requires **zero extra Python packages**
> (standard-library `socket` only). For HTTP, install `requests`.

## Modbus TCP Slave

The simulator can act as a **Modbus TCP slave** (server), exposing sensor values as holding registers. Perfect for testing SCADA/HMI integrations without a real PLC.

### Quick test

```bash
# Terminal 1 — start the simulator with Modbus TCP output
$ python ts_sim.py scenarios/modbus_tcp.yaml --duration 120

# Terminal 2 — read registers with mbpoll or any Modbus master
$ mbpoll -m tcp -a 1 -r 1 -c 3 localhost:1502
# or use pymodbus:
$ python -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('localhost', port=1502)
c.connect()
rr = c.read_holding_registers(0, 3, slave=1)
print(rr.registers)  # [6784, 552, 38012]  ← scaled by 100
"
```

### How register mapping works

- Each sensor is auto-assigned to a sequential holding register address (`0, 1, 2…`)
- The raw float value is multiplied by `scale_factor` (default `100`) and cast to `uint16`
- Example: `temperature = 67.84 °C` → `register = 6784`
- On the client side, divide by `scale_factor` to recover the original value

### Modbus TCP Config Reference

```yaml
outputs:
  - type: modbus_tcp
    port: 1502          # TCP listen port (use >1024 for non-root)
    unit_id: 1          # Modbus slave/unit ID
    scale_factor: 100   # value multiplier before uint16 cast
```

> **Note:** Modbus TCP output uses **only the Python standard library** (`socket` + `threading`). No extra packages required.
>
> The implementation supports **Function Code 03** (Read Holding Registers) only, which covers the vast majority of SCADA polling use-cases.

## Web Dashboard (Built-in)

No Grafana? No InfluxDB? No problem. The simulator now includes a **zero-dependency web dashboard** served directly from Python.

### Quick start

```bash
$ python ts_sim.py scenarios/web_dashboard.yaml --duration 120
# Open http://localhost:8080 in your browser
```

You get a live, dark-themed dashboard with:

- **Per-sensor cards** — current value, unit, location, and real-time status badge (Normal / Warning / Alarm)
- **Sparkline mini-charts** — 60-sample rolling history rendered on HTML5 Canvas
- **Smart thresholds** — each sensor type has built-in color bands (green → orange → red)
- **Server-Sent Events** — pure HTTP streaming, no WebSocket library needed

### Web Dashboard Config Reference

```yaml
outputs:
  - type: web_dashboard
    host: "0.0.0.0"   # Bind address
    port: 8080        # HTTP port
```

> **Note:** The dashboard is entirely self-contained — the HTML, CSS, and JavaScript are embedded in the Python module, so there are no external static files to manage.

## Running with MQTT

```yaml
outputs:
  - type: mqtt
    broker: "test.mosquitto.org"
    port: 1883
    topic: "factory/motor_A/data"
    client_id: "ts-sim-01"
```

Then subscribe from another terminal:

```bash
$ mosquitto_sub -h test.mosquitto.org -t factory/motor_A/data
```

## Testing

```bash
$ pytest tests/ -v
```

## Architecture

```
ts_sim.py          ← CLI entry point & main loop
config.py          ← YAML scenario loader
generators/        ← Sensor signal models
  ├── __init__.py  (temperature, pressure, vibration, current, voltage)
outputs/           ← Sink adapters
  ├── __init__.py  (csv, mqtt, console, influxdb, modbus_tcp, web_dashboard)
  ├── modbus_tcp.py
  └── web_dashboard.py
scenarios/         ← Example YAML configs
dashboards/        ← Grafana dashboard JSON
```

Adding a new sensor type is two steps:

1. Subclass `BaseGenerator` in `generators/__init__.py`.
2. Register it in `_GENERATOR_MAP`.

Adding a new output type is similar:

1. Implement a class with `open()`, `write(record)`, `close()` in `outputs/`.
2. Register it in `_OUTPUT_MAP` inside `outputs/__init__.py`.

## CI

Every push and PR is tested on Python 3.9, 3.11, and 3.12 via GitHub Actions.

## License

MIT — see [LICENSE](LICENSE).

## Related Projects

- [mqtt-cli-probe](https://github.com/nsfxdyj/mqtt-cli-probe) — MQTT broker diagnostics & stress testing
- [modbus-packet-decoder](https://github.com/nsfxdyj/modbus-packet-decoder) — Modbus TCP/RTU packet analyzer
- [modbus-regmap](https://github.com/nsfxdyj/modbus-regmap) — Modbus register-map toolkit
