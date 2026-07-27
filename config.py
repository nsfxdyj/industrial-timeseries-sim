"""
config.py — Scenario YAML loader and validation.
"""

import os

import yaml


SCHEMA = {
    "name": str,
    "interval": (int, float),
    "sensors": list,
    "outputs": list,
}


def load_scenario(path: str) -> dict:
    """Load and lightly validate a scenario YAML file."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError("Scenario root must be a mapping.")

    for key, expected in SCHEMA.items():
        if key not in data:
            raise ValueError(f"Missing required key: '{key}'")
        if not isinstance(data[key], expected):
            raise TypeError(
                f"Key '{key}' must be {expected}, got {type(data[key]).__name__}"
            )

    # Validate each sensor has required fields
    for idx, sensor in enumerate(data["sensors"]):
        if "name" not in sensor:
            raise ValueError(f"Sensor #{idx} missing 'name'")
        if "type" not in sensor:
            raise ValueError(f"Sensor '{sensor.get('name', idx)}' missing 'type'")

    # Validate each output has required fields
    for idx, out in enumerate(data["outputs"]):
        if "type" not in out:
            raise ValueError(f"Output #{idx} missing 'type'")

    return data
