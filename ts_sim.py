#!/usr/bin/env python3
"""
industrial-timeseries-sim
=========================
A lightweight, configurable industrial sensor data simulator for testing
time-series databases, dashboards, and MQTT pipelines.

Generates realistic sensor readings with noise, trends, seasonality,
and configurable fault injection — output to CSV or publish to MQTT.
"""

import argparse
import signal
import sys
import time
from datetime import datetime, timezone

from config import load_scenario
from generators import create_generator
from outputs import create_output


# ---------------------------------------------------------------------------
# Signal handling for clean shutdown
# ---------------------------------------------------------------------------
_shutdown = False


def _on_sigint(signum, frame):
    global _shutdown
    print("\n[ts-sim] Caught SIGINT, shutting down gracefully...")
    _shutdown = True


signal.signal(signal.SIGINT, _on_sigint)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run(scenario_path: str, duration_sec: float = None):
    """Load a scenario and run the simulation loop."""
    scenario = load_scenario(scenario_path)

    sensors = []
    for sensor_cfg in scenario.get("sensors", []):
        gen = create_generator(sensor_cfg)
        sensors.append({
            "name": sensor_cfg["name"],
            "generator": gen,
            "tags": sensor_cfg.get("tags", {}),
        })

    outputs = []
    for out_cfg in scenario.get("outputs", []):
        outputs.append(create_output(out_cfg))

    interval = scenario.get("interval", 1.0)
    start = time.monotonic()
    sample_count = 0

    print(f"[ts-sim] Starting simulation: {scenario.get('name', 'untitled')}")
    print(f"[ts-sim] Sensors: {len(sensors)}  |  Outputs: {len(outputs)}  |  Interval: {interval}s")

    for out in outputs:
        out.open()

    try:
        while not _shutdown:
            now = datetime.now(timezone.utc)
            ts_iso = now.isoformat()

            for sensor in sensors:
                value = sensor["generator"].next_value()
                record = {
                    "timestamp": ts_iso,
                    "sensor": sensor["name"],
                    "value": round(value, 6),
                    "tags": sensor["tags"],
                }
                for out in outputs:
                    out.write(record)

            sample_count += 1

            # Progress print every 10 samples
            if sample_count % 10 == 0:
                print(f"[ts-sim] Samples emitted: {sample_count}")

            elapsed = time.monotonic() - start
            if duration_sec is not None and elapsed >= duration_sec:
                print(f"[ts-sim] Duration reached ({duration_sec}s), stopping.")
                break

            # Sleep until next tick
            time.sleep(interval)

    finally:
        for out in outputs:
            out.close()
        print(f"[ts-sim] Total samples: {sample_count}. Done.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Industrial time-series sensor simulator",
    )
    parser.add_argument(
        "scenario",
        help="Path to YAML scenario file (see scenarios/ for examples)",
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=None,
        help="Run for N seconds (default: infinite until Ctrl-C)",
    )
    args = parser.parse_args()

    run(args.scenario, duration_sec=args.duration)


if __name__ == "__main__":
    main()
