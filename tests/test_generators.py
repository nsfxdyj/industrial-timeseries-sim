"""
tests/test_generators.py — pytest suite for generator correctness.
"""

import math

import pytest

from generators import (
    BaseGenerator,
    TemperatureGenerator,
    PressureGenerator,
    VibrationGenerator,
    CurrentGenerator,
    VoltageGenerator,
    create_generator,
)


class TestBaseGenerator:
    def test_tick_increments(self):
        g = BaseGenerator(seed=42)
        assert g._tick == 0
        g.next_value()
        assert g._tick == 1

    def test_noise_zero_when_magnitude_zero(self):
        g = BaseGenerator(seed=42)
        for _ in range(100):
            assert g._noise(0.0) == 0.0

    def test_drift(self):
        g = BaseGenerator(seed=42)
        g.next_value()  # tick = 1
        assert g._drift(0.5) == pytest.approx(0.5)

    def test_sine_periodicity(self):
        g = BaseGenerator(seed=42)
        g._tick = 100
        v1 = g._sine(5.0, 50.0)
        g._tick = 150
        v2 = g._sine(5.0, 50.0)
        assert v1 == pytest.approx(v2)


class TestTemperatureGenerator:
    def test_range(self):
        g = TemperatureGenerator(base=50.0, amplitude=5.0, noise=0.1, seed=42)
        for _ in range(500):
            v = g.next_value()
            # With very low fault prob and small noise, values should stay close
            assert 30.0 <= v <= 80.0

    def test_fault_injection(self):
        g = TemperatureGenerator(
            base=50.0, fault_prob=1.0, fault_spike=20.0, noise=0.0, seed=42
        )
        v = g.next_value()
        # Fault always fires on first sample
        assert abs(v - 50.0) >= 15.0

    def test_create_from_cfg(self):
        cfg = {
            "name": "t1",
            "type": "temperature",
            "base": 60.0,
            "amplitude": 2.0,
        }
        g = create_generator(cfg)
        assert isinstance(g, TemperatureGenerator)


class TestPressureGenerator:
    def test_non_negative(self):
        g = PressureGenerator(base=5.0, noise=0.1, seed=42)
        for _ in range(200):
            v = g.next_value()
            assert v >= 0.0


class TestVibrationGenerator:
    def test_positive(self):
        g = VibrationGenerator(base=0.02, noise=0.01, seed=42)
        for _ in range(200):
            v = g.next_value()
            assert v >= 0.0


class TestCurrentGenerator:
    def test_sanity(self):
        g = CurrentGenerator(base=10.0, noise=0.1, seed=42)
        for _ in range(100):
            v = g.next_value()
            assert v >= -5.0  # reasonable lower bound


class TestVoltageGenerator:
    def test_nominal_range(self):
        g = VoltageGenerator(nominal=220.0, noise=0.0, fault_prob=0.0, seed=42)
        for _ in range(50):
            assert g.next_value() == pytest.approx(220.0)
