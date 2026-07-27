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
| **Multiple outputs** | Console (JSON lines), CSV append, MQTT publish |
| **YAML scenarios** | One config file defines all sensors, tags, and outputs |
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

  - name: discharge_pressure
    type: pressure
    base: 12.0
    noise: 0.2
    tags:
      unit: "bar"

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
  ├── temperature.py
  ├── pressure.py
  ├── vibration.py
  ├── current.py
  └── voltage.py
outputs/           ← Sink adapters
  ├── csv_out.py
  ├── mqtt_out.py
  └── console_out.py
scenarios/         ← Example YAML configs
```

Adding a new sensor type is two steps:

1. Subclass `BaseGenerator` in `generators/`.
2. Register it in `generators/__init__.py`.

## License

MIT — see [LICENSE](LICENSE).

## Related Projects

- [mqtt-cli-probe](https://github.com/nsfxdyj/mqtt-cli-probe) — MQTT broker diagnostics & stress testing
- [modbus-packet-decoder](https://github.com/nsfxdyj/modbus-packet-decoder) — Modbus TCP/RTU packet analyzer
- [modbus-regmap](https://github.com/nsfxdyj/modbus-regmap) — Modbus register-map toolkit
