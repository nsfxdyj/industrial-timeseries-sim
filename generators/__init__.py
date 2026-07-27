"""
generators package — realistic sensor signal generators with noise and faults.
"""

import math
import random


class BaseGenerator:
    """Abstract base for sensor value generators."""

    def __init__(self, seed: int = None):
        self._rng = random.Random(seed)
        self._tick = 0

    def next_value(self) -> float:
        self._tick += 1
        return self._sample()

    def _sample(self) -> float:
        raise NotImplementedError

    def _noise(self, magnitude: float) -> float:
        """Gaussian noise with given standard deviation."""
        return self._rng.gauss(0.0, magnitude)

    def _drift(self, rate: float) -> float:
        """Linear drift component."""
        return self._tick * rate

    def _sine(self, amplitude: float, period_ticks: float, phase: float = 0.0) -> float:
        """Sinusoidal oscillation."""
        return amplitude * math.sin(2 * math.pi * self._tick / period_ticks + phase)

    def _is_fault(self, probability: float) -> bool:
        """Return True with given probability (for fault injection)."""
        return self._rng.random() < probability


class TemperatureGenerator(BaseGenerator):
    """
    Industrial temperature sensor.
    Base value + slow sinusoidal fluctuation (day/cycle) + noise.
    Optional drift (heating up / cooling down) and spike faults.
    """

    def __init__(self, base: float = 45.0, amplitude: float = 5.0,
                 period: float = 3600.0, noise: float = 0.3,
                 drift_rate: float = 0.0, fault_prob: float = 0.001,
                 fault_spike: float = 15.0, **kwargs):
        super().__init__(**kwargs)
        self.base = base
        self.amplitude = amplitude
        self.period = period
        self.noise_mag = noise
        self.drift_rate = drift_rate
        self.fault_prob = fault_prob
        self.fault_spike = fault_spike

    def _sample(self) -> float:
        val = self.base
        val += self._sine(self.amplitude, self.period)
        val += self._noise(self.noise_mag)
        val += self._drift(self.drift_rate)
        if self._is_fault(self.fault_prob):
            val += self._rng.choice([-1, 1]) * self.fault_spike
        return val


class PressureGenerator(BaseGenerator):
    """
    Hydraulic / pneumatic pressure sensor.
    Base pressure with pump-cycle oscillation and occasional drop faults.
    """

    def __init__(self, base: float = 6.0, amplitude: float = 0.5,
                 period: float = 120.0, noise: float = 0.05,
                 fault_prob: float = 0.0005, fault_drop: float = 2.0, **kwargs):
        super().__init__(**kwargs)
        self.base = base
        self.amplitude = amplitude
        self.period = period
        self.noise_mag = noise
        self.fault_prob = fault_prob
        self.fault_drop = fault_drop

    def _sample(self) -> float:
        val = self.base
        val += self._sine(self.amplitude, self.period)
        val += self._noise(self.noise_mag)
        if self._is_fault(self.fault_prob):
            val -= self.fault_drop
            if val < 0:
                val = 0.0
        return val


class VibrationGenerator(BaseGenerator):
    """
    Vibration / accelerometer sensor (RMS g).
    High-frequency noise with occasional bearing-fault spikes.
    """

    def __init__(self, base: float = 0.02, noise: float = 0.005,
                 fault_prob: float = 0.002, fault_spike: float = 0.5, **kwargs):
        super().__init__(**kwargs)
        self.base = base
        self.noise_mag = noise
        self.fault_prob = fault_prob
        self.fault_spike = fault_spike

    def _sample(self) -> float:
        val = self.base
        val += abs(self._noise(self.noise_mag))  # vibration is always positive
        if self._is_fault(self.fault_prob):
            val += self.fault_spike
        return val


class CurrentGenerator(BaseGenerator):
    """
    Electrical current sensor (Amperes).
    Base load + daily cycle + noise. Fault = overload spike.
    """

    def __init__(self, base: float = 5.0, amplitude: float = 2.0,
                 period: float = 86400.0, noise: float = 0.2,
                 fault_prob: float = 0.001, fault_spike: float = 10.0, **kwargs):
        super().__init__(**kwargs)
        self.base = base
        self.amplitude = amplitude
        self.period = period
        self.noise_mag = noise
        self.fault_prob = fault_prob
        self.fault_spike = fault_spike

    def _sample(self) -> float:
        val = self.base
        val += self._sine(self.amplitude, self.period)
        val += self._noise(self.noise_mag)
        if self._is_fault(self.fault_prob):
            val += self.fault_spike
        return val


class VoltageGenerator(BaseGenerator):
    """
    Electrical voltage sensor (Volts).
    Stable around nominal with small noise and sag/swell events.
    """

    def __init__(self, nominal: float = 220.0, noise: float = 1.0,
                 fault_prob: float = 0.001, fault_sag: float = 30.0,
                 fault_swell: float = 20.0, **kwargs):
        super().__init__(**kwargs)
        self.nominal = nominal
        self.noise_mag = noise
        self.fault_prob = fault_prob
        self.fault_sag = fault_sag
        self.fault_swell = fault_swell

    def _sample(self) -> float:
        val = self.nominal
        val += self._noise(self.noise_mag)
        if self._is_fault(self.fault_prob):
            # 50% sag, 50% swell
            if self._rng.random() < 0.5:
                val -= self.fault_sag
            else:
                val += self.fault_swell
        return val


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_GENERATOR_MAP = {
    "temperature": TemperatureGenerator,
    "pressure": PressureGenerator,
    "vibration": VibrationGenerator,
    "current": CurrentGenerator,
    "voltage": VoltageGenerator,
}


def create_generator(cfg: dict) -> BaseGenerator:
    gen_type = cfg.get("type", "temperature")
    cls = _GENERATOR_MAP.get(gen_type)
    if cls is None:
        raise ValueError(f"Unknown sensor type: {gen_type}")
    # Pass remaining keys (excluding 'name', 'type', 'tags') as kwargs
    kwargs = {k: v for k, v in cfg.items() if k not in ("name", "type", "tags")}
    return cls(**kwargs)
