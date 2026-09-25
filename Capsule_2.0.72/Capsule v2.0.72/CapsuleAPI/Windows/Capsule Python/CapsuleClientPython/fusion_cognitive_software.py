"""
Software-only FusionCognitive preview for GUI/testing when CapsuleClient.dll
does not export clCFusionCognitive_* yet.

Fuses existing classifier outputs (Productivity, Physiological States, Emotions,
Cardio). Replace with native FusionCognitive when the DLL is rebuilt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _valid(v: float) -> bool:
    return v >= 0.0


@dataclass
class FusionInputs:
    """Latest samples from existing SDK modules (-1 = unavailable)."""

    timestamp_milli: int = -1
    concentration: float = -1.0
    fatigue: float = -1.0
    productivity: float = -1.0
    emotions_focus: float = -1.0
    emotions_stress: float = -1.0
    cardio_stress_index: float = -1.0
    phy_concentration: float = -1.0
    phy_stress: float = -1.0


@dataclass
class FusionWeights:
    eeg: float = 0.5
    ppg: float = 0.15
    mems: float = 0.1
    classifier: float = 0.25

    def normalized(self) -> FusionWeights:
        total = self.eeg + self.ppg + self.mems + self.classifier
        if total <= 0:
            return FusionWeights(0.25, 0.25, 0.25, 0.25)
        return FusionWeights(
            self.eeg / total,
            self.ppg / total,
            self.mems / total,
            self.classifier / total,
        )


@dataclass
class FusionSoftwareMetrics:
    timestamp_milli: int
    cognitive_load: float
    confidence: float
    has_artifacts: bool
    cognitive_load_baseline: float = -1.0
    mode: str = "software"


class FusionCognitiveSoftware:
    """Computes a 0–100 cognitive load index from existing metrics."""

    def __init__(self):
        self.weights = FusionWeights()
        self.inputs = FusionInputs()
        self._baseline: Optional[float] = None
        self._calibrating = False
        self._calibration_samples: list[float] = []
        self._calibration_deadline: float = 0.0

    def set_weights(self, eeg: float, ppg: float, mems: float, classifier: float):
        self.weights = FusionWeights(eeg, ppg, mems, classifier)

    def start_baseline_calibration(self, duration_sec: float = 60.0):
        self._calibrating = True
        self._calibration_samples = []
        self._calibration_deadline = time.monotonic() + duration_sec

    def import_baseline(self, baseline: float):
        self._baseline = baseline
        self._calibrating = False
        self._calibration_samples = []

    @property
    def baseline(self) -> float:
        return -1.0 if self._baseline is None else self._baseline

    def update_inputs(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self.inputs, key):
                setattr(self.inputs, key, value)

    def _eeg_component(self) -> Optional[float]:
        """Proxy for EEG-driven load: concentration vs fatigue."""
        parts = []
        if _valid(self.inputs.concentration):
            parts.append(_clamp(self.inputs.concentration, 0.0, 10.0) / 10.0)
        if _valid(self.inputs.fatigue):
            parts.append(_clamp(self.inputs.fatigue, 0.0, 10.0) / 10.0)
        if not parts:
            return None
        conc = parts[0] if len(parts) == 1 else parts[0]
        fat = parts[-1] if len(parts) > 1 else 0.0
        return _clamp(0.5 + 0.5 * (conc - fat), 0.0, 1.0)

    def _ppg_component(self) -> Optional[float]:
        if _valid(self.inputs.cardio_stress_index):
            return _clamp(self.inputs.cardio_stress_index / 10.0, 0.0, 1.0)
        return None

    def _mems_component(self) -> Optional[float]:
        # No MEMS hook in software path — neutral mid until MEMS wired in GUI.
        return 0.5

    def _classifier_component(self) -> Optional[float]:
        parts = []
        if _valid(self.inputs.productivity):
            parts.append(_clamp(self.inputs.productivity, 0.0, 10.0) / 10.0)
        if _valid(self.inputs.phy_concentration):
            parts.append(_clamp(self.inputs.phy_concentration, 0.0, 10.0) / 10.0)
        if _valid(self.inputs.emotions_focus):
            parts.append(_clamp(self.inputs.emotions_focus, 0.0, 1.0))
        if _valid(self.inputs.phy_stress):
            parts.append(_clamp(self.inputs.phy_stress, 0.0, 10.0) / 10.0)
        if not parts:
            return None
        load = sum(parts) / len(parts)
        if _valid(self.inputs.emotions_stress):
            load = _clamp(load + 0.15 * _clamp(self.inputs.emotions_stress, 0.0, 1.0), 0.0, 1.0)
        return load

    def compute(self) -> Optional[FusionSoftwareMetrics]:
        w = self.weights.normalized()
        components = {
            "eeg": (self._eeg_component(), w.eeg),
            "ppg": (self._ppg_component(), w.ppg),
            "mems": (self._mems_component(), w.mems),
            "classifier": (self._classifier_component(), w.classifier),
        }

        used_weight = 0.0
        fused = 0.0
        for name, (value, weight) in components.items():
            if value is None:
                continue
            fused += value * weight
            used_weight += weight

        if used_weight <= 0:
            return None

        fused /= used_weight
        raw_load = fused * 100.0
        if self._baseline is not None and self._baseline >= 0:
            raw_load = _clamp(50.0 + (raw_load - self._baseline) * 0.8, 0.0, 100.0)

        confidence = _clamp(used_weight, 0.0, 1.0)
        has_artifacts = used_weight < 0.5

        ts = self.inputs.timestamp_milli
        if ts < 0:
            ts = int(time.time() * 1000)

        if self._calibrating:
            self._calibration_samples.append(raw_load)
            if time.monotonic() >= self._calibration_deadline and self._calibration_samples:
                self._baseline = sum(self._calibration_samples) / len(self._calibration_samples)
                self._calibrating = False
                self._calibration_samples = []

        return FusionSoftwareMetrics(
            timestamp_milli=ts,
            cognitive_load=raw_load,
            confidence=confidence,
            has_artifacts=has_artifacts,
            cognitive_load_baseline=self.baseline,
            mode="software",
        )
