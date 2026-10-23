"""
NeuroRaaga EEG Engine
Integrates Capsule SDK (CapsuleClient.dll) for Headband Pro (O1, O2, T3, T4)
with fallback to high-fidelity 250 Hz neural simulation for rapid testing.
"""
from __future__ import annotations

import collections
import ctypes
import math
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Any
import numpy as np

# Path configurations for native Capsule library
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DLL_PATH = (
    WORKSPACE_ROOT
    / "Capsule_2.0.72"
    / "Capsule v2.0.72"
    / "CapsuleAPI"
    / "Windows"
    / "Capsule Python"
    / "CapsuleClientPython"
    / "CapsuleClient.dll"
)
CAPSULE_PYTHON_DIR = DEFAULT_DLL_PATH.parent

# Channels for study
TARGET_CHANNELS = ["O1", "O2", "T3", "T4"]

SDK_CHANNEL_ALIASES = {channel: channel for channel in TARGET_CHANNELS}


def impedance_status(impedance_kohm):
    """Apply the study's contact-quality thresholds to kOhm values."""
    if impedance_kohm is None or not math.isfinite(float(impedance_kohm)):
        return "NO READING"
    if float(impedance_kohm) >= 1000.0:
        return "POOR"
    if float(impedance_kohm) >= 500.0:
        return "ORANGE"
    return "GREEN"


class _Biquad:
    """Small stateful second-order IIR section for display-only filtering."""
    def __init__(self, b0, b1, b2, a0, a1, a2):
        self.b0, self.b1, self.b2 = b0 / a0, b1 / a0, b2 / a0
        self.a1, self.a2 = a1 / a0, a2 / a0
        self.z1 = self.z2 = 0.0

    def process(self, value):
        output = self.b0 * value + self.z1
        self.z1 = self.b1 * value - self.a1 * output + self.z2
        self.z2 = self.b2 * value - self.a2 * output
        return output


def _make_display_filter(sample_rate):
    """0.5–40 Hz Butterworth bandpass plus a 50 Hz mains notch."""
    def section(kind, frequency, q):
        omega = 2.0 * math.pi * frequency / sample_rate
        cosine, sine = math.cos(omega), math.sin(omega)
        alpha = sine / (2.0 * q)
        if kind == "highpass":
            return _Biquad((1 + cosine) / 2, -(1 + cosine), (1 + cosine) / 2,
                           1 + alpha, -2 * cosine, 1 - alpha)
        if kind == "lowpass":
            return _Biquad((1 - cosine) / 2, 1 - cosine, (1 - cosine) / 2,
                           1 + alpha, -2 * cosine, 1 - alpha)
        return _Biquad(1, -2 * cosine, 1, 1 + alpha, -2 * cosine, 1 - alpha)

    q = math.sqrt(0.5)
    return [section("highpass", 0.5, q), section("notch", 50.0, 30.0), section("lowpass", 40.0, q)]

class EEGEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.sample_rate = 250.0  # 250 Hz standard for Capsule Headband/Headphone
        self.is_connected = False
        self.is_streaming = False
        self.device_serial: Optional[str] = None
        self.device_name: Optional[str] = "None"
        self.device_type_name: str = "Simulated"
        self.battery_percent: int = 100
        
        # Native Capsule objects
        self.capsule = None
        self.locator = None
        self.native_device = None
        self.native_channel_labels: List[str] = list(TARGET_CHANNELS)
        self.display_filters = {ch: _make_display_filter(self.sample_rate) for ch in TARGET_CHANNELS}
        self._native_eeg_batches = 0
        self._native_eeg_callbacks = 0
        self._native_eeg_samples_seen = 0
        self._native_invalid_batches = 0
        self._last_poll_error = None
        self._last_eeg_callback_error = None
        self.native_dll_loaded = False
        self.native_init_error: Optional[str] = None
        self.last_scan_error: Optional[str] = None
        self.last_connection_error: Optional[str] = None
        
        # Signal buffers (circular buffer for last 10 seconds = 2500 samples per channel)
        self.buffer_size = 2500
        self.signal_buffer = {ch: collections.deque(maxlen=self.buffer_size) for ch in TARGET_CHANNELS}
        self.time_buffer = collections.deque(maxlen=self.buffer_size)
        
        # Calibration & Resistance state
        self.resistances: Dict[str, Optional[float]] = {ch: None for ch in TARGET_CHANNELS}  # capped value used for thresholds and protocol gating
        self.raw_resistances_kohm: Dict[str, Optional[float]] = {ch: None for ch in TARGET_CHANNELS}  # finite SDK value before cap
        self.resistance_open_circuit: Dict[str, bool] = {ch: False for ch in TARGET_CHANNELS}
        self.resistance_callback_count = 0
        self.last_resistance_values = []
        self.is_calibrating = False
        self.calibration_results: Optional[Dict[str, Any]] = None
        
        # Listeners for real-time streaming
        self.sample_listeners: List[Callable[[List[Dict[str, Any]]], None]] = []
        
        # Background worker threads
        self._poll_stop = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._sim_thread: Optional[threading.Thread] = None
        self.use_simulation = False
        
        # Try loading native Capsule library on init
        self._init_native_capsule()

    def _init_native_capsule(self):
        if str(CAPSULE_PYTHON_DIR) not in sys.path:
            sys.path.insert(0, str(CAPSULE_PYTHON_DIR))
            
        if DEFAULT_DLL_PATH.exists():
            try:
                from Capsule import Capsule
                from DeviceLocator import DeviceLocator
                
                self.capsule = Capsule(str(DEFAULT_DLL_PATH))
                self.locator = DeviceLocator("Logs", self.capsule.get_lib())
                self.native_dll_loaded = True
                print(f"[EEGEngine] Native CapsuleClient loaded: {self.capsule.get_version()}")
                self._start_poll_thread()
            except Exception as e:
                self.native_init_error = str(e)
                print(f"[EEGEngine] Could not initialize native Capsule SDK: {e}. Simulation ready.")
                self.native_dll_loaded = False

    def _start_poll_thread(self):
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(target=self._native_poll_loop, daemon=True)
        self._poll_thread.start()

    def _native_poll_loop(self):
        while not self._poll_stop.is_set():
            if self.locator:
                try:
                    self.locator.update()
                    self._last_poll_error = None
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    if message != self._last_poll_error:
                        print(f"[EEGEngine] Capsule event-pump error: {message}")
                        traceback.print_exc()
                        self._last_poll_error = message
            time.sleep(0.02)  # ~50Hz poll rate for Capsule event queue

    # ---------------- Device Discovery ----------------
    def scan_devices(self, timeout_sec: float = 8.0) -> List[Dict[str, Any]]:
        """Scans Capsule-supported BLE device types and includes the explicit simulator."""
        found = []
        self.last_scan_error = None
        if self.native_dll_loaded and self.locator:
            try:
                from DeviceType import DeviceType
                scan_done = threading.Event()
                discovered = []

                def on_dev(l, info, r):
                    reason = getattr(r, "value", r)
                    print(f"[EEGEngine] Capsule scan callback: reason={reason}, devices={len(info)}")
                    if reason == DeviceLocator.FailReason.BluetoothDisabled:
                        self.last_scan_error = "Windows reports Bluetooth disabled or unavailable to the Capsule SDK."
                    elif reason not in (None, 0):
                        self.last_scan_error = f"Capsule BLE scan returned failure code {reason}."
                    for i in range(len(info)):
                        item = {
                            "serial": info[i].get_serial(),
                            "name": info[i].get_name(),
                            "type": {
                                0: "Band",
                                1: "Buds",
                                2: "Headphones",
                                3: "Impulse",
                                6: "BrainBit",
                            }.get(info[i].get_type(), f"Capsule device ({info[i].get_type()})"),
                            "is_simulated": False
                        }
                        if not any(existing["serial"] == item["serial"] for existing in discovered):
                            discovered.append(item)
                            print(f"[EEGEngine] Capsule BLE device found: {item['name']} (SN: {item['serial']}, {item['type']})")
                    scan_done.set()

                self.locator.set_on_devices_list(on_dev)
                # The Headband Pro was reported by Capsule as device type 0
                # (Band). The SDK's Any scan returned an empty locator list,
                # which makes Device(locator, serial, ...) fail to connect.
                from DeviceLocator import DeviceLocator
                self.locator.request_devices(DeviceType.Band, int(timeout_sec))
                scan_done.wait(timeout=timeout_sec)
                found.extend(discovered)
                if discovered:
                    print(f"[EEGEngine] Capsule scan complete: {len(discovered)} supported device(s).")
                if not discovered and not self.last_scan_error:
                    self.last_scan_error = (
                        "The Capsule SDK returned no Band devices in this scan. "
                        "Check that the Headband Pro is powered on and that Windows Bluetooth is available."
                    )
                if not discovered:
                    print(f"[EEGEngine] Capsule scan found no supported device: {self.last_scan_error}")
            except Exception as e:
                self.last_scan_error = f"Capsule BLE scan failed: {e}"
                print(f"[EEGEngine] Native scan error: {e}")
        elif not self.native_dll_loaded:
            self.last_scan_error = f"Capsule SDK is unavailable: {self.native_init_error or 'DLL not loaded'}"

        # Always offer Synthetic Neural Generator (250 Hz) as an explicit testing option
        found.append({
            "serial": "SIM-NEURORAAGA-250",
            "name": "NeuroRaaga Synthetic EEG Generator (250 Hz)",
            "type": "Synthetic Simulator",
            "is_simulated": True
        })
        found.sort(key=lambda device: (
            device["is_simulated"],
            device["serial"] != "820712",
            device["name"].lower()
        ))
        return found

    # ---------------- Connection ----------------
    def connect_device(self, serial: str, simulated: bool = False) -> bool:
        with self.lock:
            self.disconnect()
            self.last_connection_error = None
            
            if simulated or serial.startswith("SIM-"):
                self.use_simulation = True
                self.device_serial = serial if serial.startswith("SIM-") else "SIM-NEURORAAGA-250"
                self.device_name = "NeuroRaaga Precision EEG Simulator"
                self.device_type_name = "Synthetic Headband Pro (O1, O2, T3, T4)"
                self.is_connected = True
                self.battery_percent = 98
                self.resistances = {
                    "O1": 14.2,
                    "O2": 15.8,
                    "T3": 18.1,
                    "T4": 17.4
                }
                self.raw_resistances_kohm = dict(self.resistances)
                self.resistance_open_circuit = {ch: False for ch in TARGET_CHANNELS}
                print(f"[EEGEngine] Connected in SIMULATION mode: {self.device_serial}")
                return True

            if not self.native_dll_loaded or not self.locator or not self.capsule:
                print("[EEGEngine] Cannot connect to physical device: Capsule SDK is unavailable.")
                return False

            # Native Hardware Connection
            try:
                from Device import Device, Device_Connection_Status
                self.native_device = Device(self.locator, serial, self.capsule.get_lib())
                
                # Setup callbacks
                self.native_device.set_on_connection_status_changed(self._on_native_connection_status)
                self.native_device.set_on_battery_charge_changed(self._on_native_battery)
                self.native_device.set_on_eeg(self._on_native_eeg)
                self.native_device.set_on_resistances(self._on_native_resistances)
                self.native_device.set_on_error(self._on_native_error)
                self.native_device.set_on_mode_changed(self._on_native_mode_changed)
                
                # Keep all four electrode channels separate. Bipolar mode
                # combines electrode pairs and exposes only two channels.
                self.native_device.connect(bipolarChannels=False)
                
                # Wait briefly for connection
                for _ in range(375):
                    if self.is_connected:
                        break
                    time.sleep(0.04)

                if not self.is_connected:
                    raise RuntimeError("Timed out waiting for the physical device connection.")
                    
                info = self.native_device.get_info()
                source_to_target = SDK_CHANNEL_ALIASES
                channel_names = self.native_device.get_channel_names()
                labels = []
                sdk_names = []
                for idx in range(len(channel_names)):
                    source_name = channel_names.get_name_by_index(idx).strip().upper()
                    sdk_names.append(source_name)
                    labels.append(source_to_target.get(source_name, TARGET_CHANNELS[idx] if idx < len(TARGET_CHANNELS) else ""))
                self.native_channel_labels = labels or list(TARGET_CHANNELS)
                self.device_serial = serial
                self.device_name = info.get_name()
                self.device_type_name = str(info.get_type())
                self.use_simulation = False
                try:
                    native_mode = self.native_device.get_mode()
                    native_mode_value = int(getattr(native_mode, "value", native_mode))
                    native_mode = {
                        0: "RESISTANCE",
                        1: "SIGNAL",
                        2: "SIGNAL_AND_RESISTANCE",
                    }.get(native_mode_value, f"UNKNOWN({native_mode_value})")
                except Exception as mode_error:
                    native_mode = f"unavailable: {mode_error}"
                try:
                    native_rate = self.native_device.get_eeg_sample_rate()
                except Exception as rate_error:
                    native_rate = f"unavailable: {rate_error}"
                print(
                    f"[EEGEngine] Connected to native device: {serial} ({self.device_name}); "
                    f"SDK channels={sdk_names} -> {labels}, mode={native_mode}, sample_rate={native_rate}"
                )
                return True
            except Exception as e:
                self.last_connection_error = str(e)
                print(f"[EEGEngine] Failed native connection: {e}.")
                if self.native_device:
                    try:
                        self.native_device.disconnect()
                    except Exception:
                        pass
                    self.native_device = None
                self.is_connected = False
                self.use_simulation = False
                return False

    def _on_native_connection_status(self, device, status):
        status_val = int(status)
        if status_val == 1: # Connected
            self.is_connected = True
        elif status_val == 0: # Disconnected
            self.is_connected = False
            self.is_streaming = False

    def _on_native_battery(self, device, charge: int):
        self.battery_percent = charge

    def _on_native_error(self, device, error):
        print(f"[EEGEngine] Capsule device error callback: {error}")

    def _on_native_mode_changed(self, device, mode):
        print(f"[EEGEngine] Capsule device mode changed: {mode}")

    def _on_native_resistances(self, device, res):
        readings = {}
        raw_names = []
        self.resistance_callback_count += 1
        for idx in range(len(res)):
            raw_value = float(res.get_value(idx))
            source_name = res.get_channel_name(idx).strip().upper()
            raw_names.append((source_name, raw_value))
            ch = SDK_CHANNEL_ALIASES.get(source_name, TARGET_CHANNELS[idx] if idx < len(TARGET_CHANNELS) else None)
            if ch in TARGET_CHANNELS:
                # Capsule documents resistance values in ohms. NaN and negative
                # infinity are invalid; positive infinity indicates open circuit.
                # Treat
                # it as over-range (1000 kOhm capped) so the UI marks the lead POOR.
                is_open_circuit = math.isinf(raw_value) and raw_value > 0
                measured_kohm = raw_value / 1000.0 if math.isfinite(raw_value) and raw_value >= 0 else None
                self.resistance_open_circuit[ch] = is_open_circuit
                self.raw_resistances_kohm[ch] = round(measured_kohm, 1) if measured_kohm is not None else None
                capped_kohm = 1000.0 if is_open_circuit else min(measured_kohm, 1000.0) if measured_kohm is not None else None
                self.resistances[ch] = round(capped_kohm, 1) if capped_kohm is not None else None
                readings[ch] = self.resistances[ch]
        self.last_resistance_values = raw_names
        if readings:
            if self.resistance_callback_count == 1 or self.resistance_callback_count % 100 == 0:
                try:
                    mode = self.native_device.get_mode() if self.native_device else "unavailable"
                    mode = getattr(mode, "value", mode)
                except Exception as exc:
                    mode = f"unavailable: {exc}"
                print(
                    f"[EEGEngine] Capsule resistance callback #{self.resistance_callback_count}: "
                    f"raw_ohms={raw_names}, capped_kohms={readings}, "
                    f"display_kohms={self.get_resistance_readings()}, mode={mode}"
                )
        else:
            print(f"[EEGEngine] Capsule resistance callback had no mapped leads: {raw_names}")

    def get_resistance_readings(self):
        """Return uncapped finite SDK readings, or OPEN for positive infinity."""
        return {
            channel: "OPEN" if self.resistance_open_circuit.get(channel, False)
            else self.raw_resistances_kohm.get(channel)
            for channel in TARGET_CHANNELS
        }

    def _on_native_eeg(self, device, eeg):
        self._native_eeg_callbacks += 1
        try:
            self._process_native_eeg(eeg)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if message != self._last_eeg_callback_error:
                print(f"[EEGEngine] Capsule EEG callback processing error: {message}")
                traceback.print_exc()
                self._last_eeg_callback_error = message

    def _process_native_eeg(self, eeg):
        sample_count = eeg.get_samples_count()
        ch_count = eeg.get_channels_count()
        self._native_eeg_samples_seen += sample_count
        if self._native_eeg_callbacks == 1:
            print(
                f"[EEGEngine] First Capsule EEG callback: samples={sample_count}, "
                f"channels={ch_count}, labels={self.native_channel_labels}"
            )
        samples_batch = []
        now_ts = time.time()
        aliases = SDK_CHANNEL_ALIASES
        # Some Capsule firmware reports EEG channel counts that differ from the
        # names object. Keep SDK indices aligned, and use the study order only
        # when the SDK provides no recognized label for an index.
        channel_labels = list(self.native_channel_labels)
        if len(channel_labels) < ch_count:
            channel_labels.extend(TARGET_CHANNELS[len(channel_labels):ch_count])

        mapped_labels = [aliases.get(str(label).strip().upper()) for label in channel_labels[:ch_count]]
        # Firmware variants may expose aliases that collapse to duplicate names.
        # The SDK's channel order is the study's four-lead order in that case.
        if ch_count == len(TARGET_CHANNELS) and (
            len(set(mapped_labels)) != len(TARGET_CHANNELS)
            or not set(TARGET_CHANNELS).issubset(set(mapped_labels))
        ):
            print(f"[EEGEngine] Using four-lead SDK index order; reported labels={channel_labels}")
            channel_labels = list(TARGET_CHANNELS)
        
        for s in range(sample_count):
            t_ms = eeg.get_timestamp(s)
            t_sec = t_ms / 1000.0 if t_ms > 0 else now_ts
            
            sample_dict = {"timestamp": t_sec}
            display_values = {}
            seen_channels = set()
            for ch_idx in range(ch_count):
                source_name = channel_labels[ch_idx].strip().upper() if ch_idx < len(channel_labels) else ""
                ch_name = aliases.get(source_name)
                if ch_name is None and ch_idx < len(TARGET_CHANNELS):
                    ch_name = TARGET_CHANNELS[ch_idx]
                if ch_name is None:
                    continue
                # Preserve the SDK raw value for CSV. The separately filtered
                # processed stream is used only for the live graph/calibration.
                raw_val = float(eeg.get_raw_value(ch_idx, s))
                processed_val = float(eeg.get_processed_value(ch_idx, s))
                if not math.isfinite(raw_val) or not math.isfinite(processed_val):
                    continue
                uV = processed_val * 1e6 if abs(processed_val) < 1.0 else processed_val
                sample_dict[ch_name] = raw_val
                for filter_section in self.display_filters[ch_name]:
                    uV = filter_section.process(uV)
                display_values[ch_name] = round(uV, 3)
                seen_channels.add(ch_name)

            # Never emit zero-filled placeholders as if they were measured
            # EEG. A batch without all requested leads is not valid study data.
            if not set(TARGET_CHANNELS).issubset(seen_channels):
                self._native_invalid_batches += 1
                if self._native_invalid_batches == 1:
                    print(
                        f"[EEGEngine] Skipping incomplete native EEG batch: "
                        f"received={sorted(seen_channels)}, expected={TARGET_CHANNELS}, "
                        f"channel_labels={channel_labels}, sdk_channels={ch_count}"
                    )
                continue
            sample_dict["display"] = display_values
                
            self._record_sample(sample_dict)
            samples_batch.append(sample_dict)

        if samples_batch:
            self._native_eeg_batches += 1
            if self._native_eeg_batches == 1:
                ranges = {
                    ch: (min(s["display"][ch] for s in samples_batch), max(s["display"][ch] for s in samples_batch))
                    for ch in TARGET_CHANNELS
                }
                print(
                    f"[EEGEngine] First native EEG batch: sdk_channels={ch_count}, "
                    f"labels={channel_labels}, samples={sample_count}, "
                    f"display_uV_min_max={ranges}"
                )
            self._notify_listeners(samples_batch)

    # ---------------- Streaming Control ----------------
    def start_streaming(self) -> bool:
        with self.lock:
            if not self.is_connected:
                return False
            if self.is_streaming:
                return True
                
            self.is_streaming = True
            
            if self.use_simulation:
                self._sim_thread = threading.Thread(target=self._simulation_loop, daemon=True)
                self._sim_thread.start()
            elif self.native_device:
                try:
                    self.native_device.start()
                except Exception as e:
                    self.is_streaming = False
                    print(f"[EEGEngine] Error starting native stream: {e}")
                    return False
                    
            print("[EEGEngine] EEG streaming started (250 Hz)")
            return True

    def stop_streaming(self):
        with self.lock:
            self.is_streaming = False
            if self.native_device:
                try:
                    self.native_device.stop()
                except Exception:
                    pass
            print("[EEGEngine] EEG streaming stopped")

    def disconnect(self):
        with self.lock:
            self.stop_streaming()
            if self.native_device:
                try:
                    self.native_device.disconnect()
                except Exception:
                    pass
                self.native_device = None
            self.is_connected = False
            self.device_serial = None
            self.device_name = "None"
            self.resistances = {ch: None for ch in TARGET_CHANNELS}
            self.raw_resistances_kohm = {ch: None for ch in TARGET_CHANNELS}
            self.resistance_open_circuit = {ch: False for ch in TARGET_CHANNELS}
            self.resistance_callback_count = 0
            self.last_resistance_values = []
            self.display_filters = {ch: _make_display_filter(self.sample_rate) for ch in TARGET_CHANNELS}
            self.time_buffer.clear()
            for channel_buffer in self.signal_buffer.values():
                channel_buffer.clear()

    # ---------------- Sample Recording & Listeners ----------------
    def add_sample_listener(self, listener: Callable[[List[Dict[str, Any]]], None]):
        if listener not in self.sample_listeners:
            self.sample_listeners.append(listener)

    def remove_sample_listener(self, listener: Callable[[List[Dict[str, Any]]], None]):
        if listener in self.sample_listeners:
            self.sample_listeners.remove(listener)

    def _record_sample(self, sample: Dict[str, Any]):
        t = sample["timestamp"]
        self.time_buffer.append(t)
        display_values = sample.get("display", sample)
        for ch in TARGET_CHANNELS:
            self.signal_buffer[ch].append(display_values.get(ch, 0.0))

    def _notify_listeners(self, batch: List[Dict[str, Any]]):
        for listener in list(self.sample_listeners):
            try:
                listener(batch)
            except Exception as e:
                print(f"[EEGEngine] Listener error: {e}")

    def get_latest_buffer(self) -> Dict[str, Any]:
        """Returns recent samples for immediate canvas drawing on connection."""
        with self.lock:
            return {
                "timestamps": list(self.time_buffer),
                "channels": {ch: list(self.signal_buffer[ch]) for ch in TARGET_CHANNELS}
            }

    # ---------------- Calibration & Signal Quality Check ----------------
    def run_calibration(self, duration_sec: float = 3.0) -> Dict[str, Any]:
        """
        Runs a comprehensive calibration & signal quality check:
        1. Electrode contact impedance (kOhms) for O1, O2, T3, T4.
        2. Signal amplitude & stability (rms, peak-to-peak, baseline drift).
        3. Overall quality grade (EXCELLENT, GOOD, FAIR, POOR).
        """
        self.is_calibrating = True
        collected_data = {ch: [] for ch in TARGET_CHANNELS}
        
        # Ensure streaming is active to gather calibration samples
        was_streaming = self.is_streaming
        if not was_streaming and not self.start_streaming():
            self.is_calibrating = False
            raise RuntimeError("EEG streaming could not be started; no calibration data was collected.")
            
        def temp_cal_listener(batch):
            for s in batch:
                for ch in TARGET_CHANNELS:
                    collected_data[ch].append(s.get("display", s).get(ch, 0.0))

        self.add_sample_listener(temp_cal_listener)
        try:
            time.sleep(duration_sec)
        finally:
            self.remove_sample_listener(temp_cal_listener)
            if not was_streaming:
                self.stop_streaming()
            self.is_calibrating = False

        sample_counts = {ch: len(values) for ch, values in collected_data.items()}
        if not any(sample_counts.values()):
            try:
                mode = self.native_device.get_mode() if self.native_device else "unavailable"
            except Exception as exc:
                mode = f"unavailable: {exc}"
            raise RuntimeError(
                "The device is connected, but no usable EEG samples reached the webpage. "
                f"SDK EEG callbacks={self._native_eeg_callbacks}, raw samples={self._native_eeg_samples_seen}, "
                f"incomplete batches={self._native_invalid_batches}, mode={mode}, "
                f"SDK channel mapping={self.native_channel_labels}. Check the server log for the first SDK callback/event-pump error."
            )
        if any(count < 20 for count in sample_counts.values()):
            raise RuntimeError(f"Too few live EEG samples for calibration: {sample_counts}")
            
        # Analyze collected samples
        channel_metrics = {}
        all_passed = True
        
        for ch in TARGET_CHANNELS:
            vals = np.asarray(collected_data[ch], dtype=float)
            rms = float(np.sqrt(np.mean(vals**2)))
            ptp = float(np.ptp(vals))
            std = float(np.std(vals))
            imp_value = self.resistances.get(ch)
            imp = float(imp_value) if imp_value is not None and math.isfinite(float(imp_value)) else None
            measured_imp = self.raw_resistances_kohm.get(ch)
            measured_imp = float(measured_imp) if measured_imp is not None and math.isfinite(float(measured_imp)) else None
            
            # Contact colors: <500 kOhm green, 500-<1000 orange, >=1000 poor.
            imp_status = impedance_status(imp)
            imp_ok = imp_status == "GREEN"
            amp_ok = 2.0 < std < 70.0 and ptp < 400.0
            ch_status = imp_status
            if not imp_ok or not amp_ok:
                all_passed = False
                
            channel_metrics[ch] = {
                "impedance_kohm": round(imp, 1) if imp is not None else None,
                "measured_impedance_kohm": round(measured_imp, 1) if measured_imp is not None else None,
                "open_circuit": self.resistance_open_circuit.get(ch, False),
                "rms_uV": round(rms, 2),
                "std_uV": round(std, 2),
                "ptp_uV": round(ptp, 2),
                "signal_quality": "GOOD" if amp_ok else "POOR",
                "status": ch_status,
                "passed": imp_ok and amp_ok
            }

        overall_grade = "GOOD" if all_passed else "ATTENTION NEEDED"
        
        self.calibration_results = {
            "timestamp": time.time(),
            "duration_sec": duration_sec,
            "overall_status": overall_grade,
            "ready_for_protocol": all_passed,
            "sample_rate_hz": self.sample_rate,
            "channels": channel_metrics,
            "message": (
                "All electrode impedances are below 500 kOhm and signal quality is acceptable. Ready for baseline recording."
                if all_passed else
                "The SDK reports an open circuit for: " + ", ".join(ch for ch in TARGET_CHANNELS if self.resistance_open_circuit.get(ch, False)) + ". Check reference and electrode contact."
                if any(self.resistance_open_circuit.get(ch, False) for ch in TARGET_CHANNELS) else
                "The SDK sent resistance callbacks, but the values were invalid or unavailable for one or more leads. Check SDK mode and electrode contact; no impedance is inferred from the waveform."
                if self.resistance_callback_count and any(value is None for value in self.resistances.values()) else
                "Live EEG samples were received, but the SDK has not reported impedance for every lead. Check SDK resistance reporting; impedance is not inferred from the waveform."
                if any(value is None for value in self.resistances.values()) else
                "Check electrode contact and skin preparation for flagged channels."
            ),
            "resistance_callback_count": self.resistance_callback_count
        }
        self.is_calibrating = False
        return self.calibration_results

    # ---------------- High-Fidelity Neural Simulation ----------------
    def _simulation_loop(self):
        """
        Simulates 250 Hz EEG with physiological components:
        - 1/f background neural noise
        - Alpha rhythm (8-12 Hz) prominent during rest
        - Theta rhythm (4-7 Hz)
        - Beta rhythm (13-28 Hz)
        - Eye blinks / slow saccades
        - Microvolt scale (~ ±40 uV)
        """
        dt = 1.0 / self.sample_rate
        sample_period = 0.04  # Emit batches every 40 ms (10 samples per batch)
        samples_per_batch = int(self.sample_rate * sample_period)
        
        phase_alpha = {ch: np.random.uniform(0, 2*np.pi) for ch in TARGET_CHANNELS}
        phase_theta = {ch: np.random.uniform(0, 2*np.pi) for ch in TARGET_CHANNELS}
        phase_beta = {ch: np.random.uniform(0, 2*np.pi) for ch in TARGET_CHANNELS}
        
        blink_timer = 0.0
        blink_duration = 0.25
        blink_active = False
        
        next_time = time.time()
        
        while self.is_streaming and self.use_simulation:
            batch = []
            now = time.time()
            
            for _ in range(samples_per_batch):
                t = next_time
                next_time += dt
                blink_timer += dt
                
                # Periodic eye blink every 4-7 seconds
                if blink_timer > 5.0 and np.random.rand() < 0.02:
                    blink_active = True
                    blink_progress = 0.0
                    blink_timer = 0.0
                    
                blink_uV = 0.0
                if blink_active:
                    blink_timer += dt
                    if blink_timer < blink_duration:
                        # Half-sine bell curve
                        blink_uV = 45.0 * np.sin(np.pi * (blink_timer / blink_duration))
                    else:
                        blink_active = False
                
                sample_dict = {"timestamp": t}
                for ch in TARGET_CHANNELS:
                    # Update phases
                    phase_alpha[ch] += 2 * np.pi * 10.2 * dt  # 10.2 Hz alpha
                    phase_theta[ch] += 2 * np.pi * 5.8 * dt   # 5.8 Hz theta
                    phase_beta[ch] += 2 * np.pi * 18.5 * dt   # 18.5 Hz beta
                    
                    # Channels have natural inter-hemispheric coherence
                    alpha_amp = 18.0 if "C" in ch else 12.0
                    theta_amp = 7.0
                    beta_amp = 4.5
                    
                    sig = (
                        alpha_amp * np.sin(phase_alpha[ch]) +
                        theta_amp * np.sin(phase_theta[ch]) +
                        beta_amp * np.sin(phase_beta[ch]) +
                        np.random.normal(0, 4.0) # pink/white background noise
                    )
                    
                    # Frontal/central channels pick up blinks more
                    if "C" in ch:
                        sig += blink_uV * 0.7
                    else:
                        sig += blink_uV * 0.2
                        
                    sample_dict[ch] = round(sig, 3)
                    
                self._record_sample(sample_dict)
                batch.append(sample_dict)

            self._notify_listeners(batch)
            
            # Sleep to match real time
            sleep_time = sample_period - (time.time() - now)
            if sleep_time > 0.002:
                time.sleep(sleep_time)

eeg_engine = EEGEngine()
