"""
Capsule metrics viewer — simple GUI to test device connection, calibration, and live SDK metrics.

Usage (from this folder, with CapsuleClient.dll alongside the script):
    python capsule_metrics_gui.py

Requires: Python 3.11+, tkinter (stdlib), CapsuleClient.dll
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from Capsule import Capsule
from Calibrator import Calibrator
from Cardio import Cardio, Cardio_Data
from Device import Device, Device_Connection_Status
from DeviceLocator import DeviceLocator
from DeviceType import DeviceType
from Emotions import Emotions, Emotions_States
from Error import CapsuleException
from PhysiologicalStates import (
    PhysiologicalStates,
    PhysiologicalStates_Baselines,
    PhysiologicalStates_Value,
)
from Productivity import Productivity, Productivity_Baselines, Productivity_Metrics

try:
    from FusionCognitive import (
        FusionCognitive,
        FusionCognitive_BaselinesV2,
        FusionCognitive_Config,
        FusionCognitive_FusionWeights,
        FusionCognitive_MetricsV2,
        FusionCognitiveNotSupportedError,
        is_available as fusion_dll_is_available,
        missing_exports as fusion_missing_exports,
    )

    FUSION_MODULE_AVAILABLE = True
except ImportError:
    FUSION_MODULE_AVAILABLE = False
    fusion_dll_is_available = lambda _lib: False  # type: ignore
    fusion_missing_exports = lambda _lib: []  # type: ignore
    FusionCognitiveNotSupportedError = RuntimeError  # type: ignore

from fusion_cognitive_software import FusionCognitiveSoftware


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DLL_WIN = os.path.join(SCRIPT_DIR, "CapsuleClient.dll")
DEFAULT_DLL_MAC = os.path.join(SCRIPT_DIR, "libCapsuleClient.dylib")
POLL_INTERVAL_SEC = 0.02

# Matches Device_Connection_Status in Device.py (not "Connected"/"Disconnected").
_CONN_CONNECTED = Device_Connection_Status.Device_ConnectionState_Connected
_CONN_DISCONNECTED = Device_Connection_Status.Device_ConnectionState_Disconnected
_CONN_UNSUPPORTED = Device_Connection_Status.Device_ConnectionState_UnsupportedConnection

_CONN_NAMES = {
    int(_CONN_DISCONNECTED): "Disconnected",
    int(_CONN_CONNECTED): "Connected",
    int(_CONN_UNSUPPORTED): "UnsupportedConnection",
}


def _status_code(status) -> int:
    """Normalize status from enum or raw int (ctypes callback)."""
    return int(status)


def default_dll_path() -> str:
    if sys.platform == "win32":
        return DEFAULT_DLL_WIN
    return DEFAULT_DLL_MAC


class CapsuleMetricsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Capsule Metrics Viewer")
        self.root.minsize(720, 640)

        self.ui_queue: queue.Queue = queue.Queue()
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None

        self.capsule: Capsule | None = None
        self.locator: DeviceLocator | None = None
        self.device: Device | None = None
        self.calibrator: Calibrator | None = None
        self.emotions: Emotions | None = None
        self.cardio: Cardio | None = None
        self.prod: Productivity | None = None
        self.phy: PhysiologicalStates | None = None
        self.fusion: FusionCognitive | None = None
        self.fusion_supported = False
        self.fusion_use_software = False
        self.fusion_software = FusionCognitiveSoftware()
        self._fusion_skip_reason = ""

        self._devices_info: list = []
        self._connected = False
        self._streaming = False
        self._eyes_calibrated = False
        self._prod_baselines_done = False
        self._phy_baselines_done = False
        self._fusion_baselines_done = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_ui_drain()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="CapsuleClient library:").grid(row=0, column=0, sticky=tk.W)
        self.dll_var = tk.StringVar(value=default_dll_path())
        ttk.Entry(top, textvariable=self.dll_var, width=52).grid(row=0, column=1, padx=4, sticky=tk.EW)
        ttk.Button(top, text="Browse…", command=self._browse_dll).grid(row=0, column=2)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Device type:").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self.device_type_var = tk.StringVar(value="Headphones")
        ttk.Combobox(
            top,
            textvariable=self.device_type_var,
            values=["Headphones", "Band", "Buds", "BrainBit", "SinWave", "Noise"],
            state="readonly",
            width=16,
        ).grid(row=1, column=1, sticky=tk.W, pady=(6, 0))

        self.bipolar_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Bipolar channels", variable=self.bipolar_var).grid(
            row=1, column=2, sticky=tk.W, pady=(6, 0)
        )

        conn = ttk.LabelFrame(self.root, text="Connection", padding=8)
        conn.pack(fill=tk.X, padx=8, pady=4)

        btn_row = ttk.Frame(conn)
        btn_row.pack(fill=tk.X)
        self.btn_load = ttk.Button(btn_row, text="1. Load library", command=self._load_library)
        self.btn_load.pack(side=tk.LEFT, padx=2)
        self.btn_scan = ttk.Button(btn_row, text="2. Scan devices", command=self._scan_devices, state=tk.DISABLED)
        self.btn_scan.pack(side=tk.LEFT, padx=2)
        self.btn_connect = ttk.Button(btn_row, text="3. Connect", command=self._connect_device, state=tk.DISABLED)
        self.btn_connect.pack(side=tk.LEFT, padx=2)
        self.btn_start = ttk.Button(btn_row, text="4. Start stream", command=self._start_stream, state=tk.DISABLED)
        self.btn_start.pack(side=tk.LEFT, padx=2)
        self.btn_stop = ttk.Button(btn_row, text="Stop", command=self._stop_stream, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=2)
        self.btn_disconnect = ttk.Button(btn_row, text="Disconnect", command=self._disconnect, state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT, padx=2)

        ttk.Label(conn, text="Found device:").pack(anchor=tk.W)
        self.device_combo = ttk.Combobox(conn, state="readonly", width=70)
        self.device_combo.pack(fill=tk.X, pady=2)

        cal = ttk.LabelFrame(self.root, text="Calibration (after Start stream)", padding=8)
        cal.pack(fill=tk.X, padx=8, pady=4)

        cal_row = ttk.Frame(cal)
        cal_row.pack(fill=tk.X)
        self.btn_eyes = ttk.Button(
            cal_row, text="Closed-eyes (quick)", command=self._calibrate_eyes, state=tk.DISABLED
        )
        self.btn_eyes.pack(side=tk.LEFT, padx=2)
        self.btn_prod = ttk.Button(
            cal_row, text="Productivity baselines", command=self._calibrate_prod, state=tk.DISABLED
        )
        self.btn_prod.pack(side=tk.LEFT, padx=2)
        self.btn_phy = ttk.Button(
            cal_row, text="Physiological baselines", command=self._calibrate_phy, state=tk.DISABLED
        )
        self.btn_phy.pack(side=tk.LEFT, padx=2)
        self.btn_fusion = ttk.Button(
            cal_row, text="FusionCognitive baselines", command=self._calibrate_fusion, state=tk.DISABLED
        )
        self.btn_fusion.pack(side=tk.LEFT, padx=2)

        self.cal_status_var = tk.StringVar(
            value="Eyes: — | Productivity: — | Physiological: — | Fusion: —"
        )
        ttk.Label(cal, textvariable=self.cal_status_var).pack(anchor=tk.W, pady=4)

        fusion_cfg = ttk.LabelFrame(self.root, text="FusionCognitive weights (SetConfig)", padding=8)
        fusion_cfg.pack(fill=tk.X, padx=8, pady=4)
        self.weight_vars = {
            "eeg": tk.DoubleVar(value=0.5),
            "ppg": tk.DoubleVar(value=0.15),
            "mems": tk.DoubleVar(value=0.1),
            "classifier": tk.DoubleVar(value=0.25),
        }
        for i, (key, label) in enumerate(
            [("eeg", "EEG"), ("ppg", "PPG"), ("mems", "MEMS"), ("classifier", "Classifiers")]
        ):
            ttk.Label(fusion_cfg, text=f"{label}:").grid(row=0, column=i * 2, sticky=tk.W, padx=(0, 2))
            ttk.Entry(fusion_cfg, textvariable=self.weight_vars[key], width=6).grid(row=0, column=i * 2 + 1, padx=(0, 8))
        self.btn_apply_weights = ttk.Button(
            fusion_cfg, text="Apply weights", command=self._apply_fusion_weights, state=tk.DISABLED
        )
        self.btn_apply_weights.grid(row=0, column=8, padx=4)

        self.software_fusion_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            fusion_cfg,
            text="Software fusion preview (no DLL — for testing until native build)",
            variable=self.software_fusion_var,
            command=self._on_software_fusion_toggle,
        ).grid(row=1, column=0, columnspan=9, sticky=tk.W, pady=(6, 0))

        metrics_outer = ttk.LabelFrame(self.root, text="Live metrics", padding=8)
        metrics_outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        canvas = tk.Canvas(metrics_outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(metrics_outer, orient=tk.VERTICAL, command=canvas.yview)
        self.metrics_frame = ttk.Frame(canvas)
        self.metrics_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.metrics_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.metric_vars: dict[str, tk.StringVar] = {}
        sections = [
            ("Device", ["battery", "connection", "firmware"]),
            ("Emotions", ["focus", "chill", "stress", "anger", "selfControl"]),
            (
                "Productivity",
                [
                    "fatigueScore",
                    "concentrationScore",
                    "relaxationScore",
                    "productivityScore",
                    "accumulatedFatigue",
                ],
            ),
            (
                "Physiological States",
                ["relaxation", "fatigue", "concentration", "involvement", "stress"],
            ),
            ("Cardio", ["heartRate", "stressIndex", "kaplanIndex", "hasArtifacts"]),
            (
                "FusionCognitive v2",
                ["cognitiveLoad", "confidence", "hasArtifacts", "cognitiveLoadBaseline"],
            ),
        ]
        for section_title, keys in sections:
            lf = ttk.LabelFrame(self.metrics_frame, text=section_title, padding=6)
            lf.pack(fill=tk.X, pady=4)
            for row, key in enumerate(keys):
                full_key = f"{section_title}.{key}" if section_title != "Device" else key
                ttk.Label(lf, text=key + ":", width=22).grid(row=row, column=0, sticky=tk.W)
                var = tk.StringVar(value="—")
                self.metric_vars[full_key] = var
                ttk.Label(lf, textvariable=var, width=28).grid(row=row, column=1, sticky=tk.W)

        log_frame = ttk.LabelFrame(self.root, text="Log", padding=4)
        log_frame.pack(fill=tk.BOTH, padx=8, pady=(0, 8))
        self.log = scrolledtext.ScrolledText(log_frame, height=8, state=tk.DISABLED, font=("Consolas", 9))
        self.log.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="Load the CapsuleClient library to begin.")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(
            fill=tk.X, padx=8, pady=(0, 8)
        )

    def _browse_dll(self):
        path = filedialog.askopenfilename(
            title="Select CapsuleClient library",
            initialdir=SCRIPT_DIR,
            filetypes=[("Libraries", "*.dll *.dylib *.so"), ("All", "*.*")],
        )
        if path:
            self.dll_var.set(path)

    def _log(self, msg: str):
        self.ui_queue.put(("log", msg))

    def _set_status(self, msg: str):
        self.ui_queue.put(("status", msg))

    def _set_metric(self, key: str, value):
        self.ui_queue.put(("metric", key, value))

    def _refresh_cal_status(self):
        self.ui_queue.put(
            (
                "cal_status",
                self._eyes_calibrated,
                self._prod_baselines_done,
                self._phy_baselines_done,
                self._fusion_baselines_done,
                self.fusion_supported,
            )
        )

    def _schedule_ui_drain(self):
        self._drain_ui_queue()
        self.root.after(50, self._schedule_ui_drain)

    def _drain_ui_queue(self):
        while True:
            try:
                item = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "log":
                self.log.configure(state=tk.NORMAL)
                self.log.insert(tk.END, item[1] + "\n")
                self.log.see(tk.END)
                self.log.configure(state=tk.DISABLED)
            elif kind == "status":
                self.status_var.set(item[1])
            elif kind == "metric":
                key, value = item[1], item[2]
                if key in self.metric_vars:
                    self.metric_vars[key].set(value)
            elif kind == "cal_status":
                _, eyes, prod, phy, fusion, fusion_ok = item
                fusion_txt = "done" if fusion else ("n/a" if not fusion_ok else "pending")
                self.cal_status_var.set(
                    f"Eyes: {'done' if eyes else 'pending'} | "
                    f"Productivity: {'done' if prod else 'pending'} | "
                    f"Physiological: {'done' if phy else 'pending'} | "
                    f"Fusion: {fusion_txt}"
                )
            elif kind == "devices":
                self._devices_info = item[1]
                labels = [
                    f"{i}: {d.get_name()} [{d.get_serial()}] type={d.get_type()}"
                    for i, d in enumerate(self._devices_info)
                ]
                self.device_combo["values"] = labels
                if labels:
                    self.device_combo.current(0)
                self.btn_connect.configure(state=tk.NORMAL if labels else tk.DISABLED)
            elif kind == "fusion_flag":
                dll_ok, software = item[1], item[2] if len(item) > 2 else False
                self.fusion_supported = dll_ok or software
                self.fusion_use_software = software and not dll_ok
                if self.fusion_supported:
                    label = "native DLL" if dll_ok else "software preview"
                    for k in self.metric_vars:
                        if k.startswith("FusionCognitive"):
                            self.metric_vars[k].set(f"Active ({label})")
                else:
                    self.btn_fusion.configure(state=tk.DISABLED)
                    for k in self.metric_vars:
                        if k.startswith("FusionCognitive"):
                            self.metric_vars[k].set("Enable software fusion or rebuild DLL")
            elif kind == "enable_cal":
                self.btn_eyes.configure(state=tk.NORMAL)
                self.btn_prod.configure(state=tk.NORMAL)
                self.btn_phy.configure(state=tk.NORMAL)
                if self.fusion_supported or self.software_fusion_var.get():
                    self.btn_fusion.configure(state=tk.NORMAL)
                    self.btn_apply_weights.configure(state=tk.NORMAL)
            elif kind == "connection":
                self._handle_connection_on_main_thread(item[1])
            elif kind == "eyes_calibrated":
                self._eyes_calibrated = True
                self._log("Closed-eyes calibration finished.")
                self._refresh_cal_status()
            elif kind == "prod_baselines":
                self._prod_baselines_done = True
                self._log("Productivity baselines ready.")
                self._refresh_cal_status()
            elif kind == "phy_baselines":
                self._phy_baselines_done = True
                self._log("Physiological States baselines ready.")
                self._refresh_cal_status()
            elif kind == "fusion_baselines":
                self._fusion_baselines_done = True
                self._set_metric(
                    "FusionCognitive v2.cognitiveLoadBaseline",
                    f"{item[1]:.1f}",
                )
                self._log("FusionCognitive baselines ready.")
                self._refresh_cal_status()
            elif kind == "error":
                messagebox.showerror("Error", item[1])

    # ------------------------------------------------------------------ Library / device
    def _load_library(self):
        path = self.dll_var.get().strip()
        if not os.path.isfile(path):
            messagebox.showerror("Missing library", f"File not found:\n{path}")
            return
        try:
            self.capsule = Capsule(path)
            self.locator = DeviceLocator("Logs", self.capsule.get_lib())
            self.locator.set_on_devices_list(self._on_device_list)
            self._log(f"Loaded {path}")
            self._log(f"API version: {self.capsule.get_version()}")
            lib = self.capsule.get_lib()
            dll_fusion = FUSION_MODULE_AVAILABLE and fusion_dll_is_available(lib)
            if dll_fusion:
                self._log("FusionCognitive v2: found in DLL.")
                self.fusion_supported = True
                self.software_fusion_var.set(False)
                self._fusion_skip_reason = ""
                self.ui_queue.put(("fusion_flag", True, False))
            else:
                missing = fusion_missing_exports(lib) if FUSION_MODULE_AVAILABLE else ["FusionCognitive.py"]
                self._fusion_skip_reason = (
                    "FusionCognitive v2 not in DLL (missing: "
                    + ", ".join(missing)
                    + "). Enable software fusion preview below to test the panel."
                )
                self.fusion_supported = False
                self._log(self._fusion_skip_reason)
                use_sw = self.software_fusion_var.get()
                self.ui_queue.put(("fusion_flag", False, use_sw))
                if use_sw:
                    self._log("Software fusion preview enabled (checkbox).")
            self._set_status("Library loaded. Scan for devices.")
            self.btn_scan.configure(state=tk.NORMAL)
            self._start_poll_thread()
        except OSError as e:
            messagebox.showerror("Load failed", str(e))
        except CapsuleException as e:
            messagebox.showerror("Capsule error", f"{e.code}: {e.message}")

    def _on_software_fusion_toggle(self):
        use_sw = self.software_fusion_var.get()
        dll_ok = (
            self.capsule is not None
            and FUSION_MODULE_AVAILABLE
            and fusion_dll_is_available(self.capsule.get_lib())
        )
        self.ui_queue.put(("fusion_flag", dll_ok, use_sw and not dll_ok))
        if use_sw and not dll_ok:
            self._log("Software fusion preview enabled.")
        self._apply_fusion_weights()

    def _sync_fusion_weights_to_engine(self):
        self.fusion_software.set_weights(
            self.weight_vars["eeg"].get(),
            self.weight_vars["ppg"].get(),
            self.weight_vars["mems"].get(),
            self.weight_vars["classifier"].get(),
        )

    def _publish_fusion_software_metrics(self):
        m = self.fusion_software.compute()
        if m is None:
            return
        self._set_metric("FusionCognitive v2.cognitiveLoad", f"{m.cognitive_load:.1f}")
        self._set_metric("FusionCognitive v2.confidence", f"{m.confidence:.3f}")
        self._set_metric("FusionCognitive v2.hasArtifacts", str(m.has_artifacts))
        if m.cognitive_load_baseline >= 0:
            self._set_metric(
                "FusionCognitive v2.cognitiveLoadBaseline",
                f"{m.cognitive_load_baseline:.1f}",
            )

    def _device_type_enum(self) -> DeviceType:
        return getattr(DeviceType, self.device_type_var.get())

    def _scan_devices(self):
        if not self.locator:
            return
        self._log(f"Scanning for {self.device_type_var.get()}…")
        self._devices_info = []
        self.device_combo.set("")
        self.locator.request_devices(self._device_type_enum(), 15)

    def _on_device_list(self, locator, info, fail_reason):
        devices = [info[i] for i in range(len(info))]
        self.ui_queue.put(("devices", devices))
        self._log(f"Scan finished: {len(devices)} device(s), reason={fail_reason}")

    def _selected_device_index(self) -> int:
        sel = self.device_combo.current()
        return 0 if sel < 0 else sel

    def _connect_device(self):
        if not self.locator or not self._devices_info:
            return
        idx = self._selected_device_index()
        serial = self._devices_info[idx].get_serial()
        try:
            self.device = Device(self.locator, serial, self.capsule.get_lib())
            self.device.set_on_connection_status_changed(self._on_connection_changed)
            self.device.set_on_battery_charge_changed(self._on_battery)
            self.device.connect(bipolarChannels=self.bipolar_var.get())
            self._log(f"Connecting to {serial}…")
            self._set_status("Connecting…")
            self.btn_connect.configure(state=tk.DISABLED)
        except CapsuleException as e:
            messagebox.showerror("Connect failed", f"{e.code}: {e.message}")

    def _on_connection_changed(self, device, status):
        # Called from native DLL thread — only queue work; never touch tkinter here.
        try:
            self.ui_queue.put(("connection", _status_code(status)))
        except Exception as exc:
            self.ui_queue.put(("log", f"Connection callback error: {exc}"))

    def _handle_connection_on_main_thread(self, status: int):
        name = _CONN_NAMES.get(status, str(status))
        self._log(f"Connection: {name}")
        self._set_metric("connection", name)

        if status == int(_CONN_CONNECTED):
            self._connected = True
            self._set_status("Connected. Click Start stream, then run calibrations.")
            self.btn_start.configure(state=tk.NORMAL)
            self.btn_disconnect.configure(state=tk.NORMAL)
            if self.device:
                try:
                    fw = self.device.get_firmware_version()
                    self._set_metric("firmware", fw or "—")
                except CapsuleException:
                    pass
        elif status == int(_CONN_DISCONNECTED):
            self._connected = False
            self._streaming = False
            self._reset_after_disconnect()
        elif status == int(_CONN_UNSUPPORTED):
            self._set_status("Unsupported connection.")
            messagebox.showwarning(
                "Connection",
                "Device reported unsupported connection. Try another mode or device.",
            )

    def _on_battery(self, device, charge: int):
        try:
            self.ui_queue.put(("metric", "battery", f"{charge}%"))
        except Exception as exc:
            self.ui_queue.put(("log", f"Battery callback error: {exc}"))

    def _setup_classifiers(self):
        lib = self.capsule.get_lib()
        self.calibrator = Calibrator(self.device, lib)
        self.calibrator.set_on_calibration_finished(self._on_eyes_calibrated)

        self.emotions = Emotions(self.device, lib)
        self.emotions.set_on_states_update(self._on_emotions)

        self.cardio = Cardio(self.device, lib)
        self.cardio.set_on_indexes_update(self._on_cardio)

        self.prod = Productivity(self.device, lib)
        self.prod.set_on_metrics_update(self._on_prod_metrics)
        self.prod.set_on_baseline_update(self._on_prod_baselines)

        self.phy = PhysiologicalStates(self.device, lib)
        self.phy.set_on_states(self._on_phy_states)
        self.phy.set_on_calibrated(self._on_phy_baselines)

        self.fusion = None
        self.fusion_use_software = self.software_fusion_var.get() and not (
            FUSION_MODULE_AVAILABLE and fusion_dll_is_available(lib)
        )
        if self.fusion_use_software:
            self._sync_fusion_weights_to_engine()
            self._log("Using software FusionCognitive preview (fuses existing metrics).")
            self.ui_queue.put(("fusion_flag", False, True))
        elif self.fusion_supported and FUSION_MODULE_AVAILABLE:
            try:
                weights = FusionCognitive_FusionWeights(
                    eeg_weight=self.weight_vars["eeg"].get(),
                    ppg_weight=self.weight_vars["ppg"].get(),
                    mems_weight=self.weight_vars["mems"].get(),
                    classifier_weight=self.weight_vars["classifier"].get(),
                )
                self.fusion = FusionCognitive(self.device, lib)
                self.fusion.set_config(FusionCognitive_Config(weights))
                self.fusion.set_on_metrics_update(self._on_fusion_metrics)
                self.fusion.set_on_baseline_update(self._on_fusion_baselines)
                self._log("FusionCognitive v2 module created.")
            except (CapsuleException, FusionCognitiveNotSupportedError, AttributeError, OSError) as e:
                self.fusion_supported = False
                self._fusion_skip_reason = str(e)
                self._log(self._fusion_skip_reason)
                self.ui_queue.put(("fusion_flag", False, self.software_fusion_var.get()))
        elif self._fusion_skip_reason:
            self._log(self._fusion_skip_reason)
            self.ui_queue.put(("fusion_flag", False, self.software_fusion_var.get()))
        else:
            self.ui_queue.put(("fusion_flag", False, False))

    def _start_stream(self):
        if not self.device or not self._connected:
            return
        try:
            self._setup_classifiers()
            self.device.start()
            self._streaming = True
            self._log("Device started.")
            self._set_status("Streaming. Run calibrations in order.")
            self.btn_start.configure(state=tk.DISABLED)
            self.btn_stop.configure(state=tk.NORMAL)
            self.ui_queue.put(("enable_cal",))
            self._refresh_cal_status()
        except CapsuleException as e:
            messagebox.showerror("Start failed", f"{e.code}: {e.message}")

    def _stop_stream(self):
        if self.device and self._streaming:
            try:
                self.device.stop()
            except CapsuleException as e:
                self._log(f"Stop error: {e.message}")
            self._streaming = False
            self._log("Device stopped.")
            self.btn_stop.configure(state=tk.DISABLED)
            self.btn_start.configure(state=tk.NORMAL)
            for btn in (self.btn_eyes, self.btn_prod, self.btn_phy, self.btn_fusion):
                btn.configure(state=tk.DISABLED)

    def _disconnect(self):
        self._stop_stream()
        if self.device:
            try:
                self.device.disconnect()
            except CapsuleException as e:
                self._log(f"Disconnect error: {e.message}")
        self._reset_after_disconnect()

    def _reset_after_disconnect(self):
        self.btn_connect.configure(state=tk.NORMAL if self._devices_info else tk.DISABLED)
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.DISABLED)
        self.btn_disconnect.configure(state=tk.DISABLED)
        for btn in (self.btn_eyes, self.btn_prod, self.btn_phy, self.btn_fusion, self.btn_apply_weights):
            btn.configure(state=tk.DISABLED)
        self._set_status("Disconnected.")

    # ------------------------------------------------------------------ Calibrations
    def _calibrate_eyes(self):
        if not self.calibrator:
            return
        self._log("Starting quick closed-eyes calibration…")
        self.calibrator.calibrate_quick()

    def _on_eyes_calibrated(self, calibrator):
        self.ui_queue.put(("eyes_calibrated",))

    def _calibrate_prod(self):
        if self.prod:
            self._log("Productivity baseline calibration started.")
            self.prod.calibrate_baselines()

    def _on_prod_baselines(self, prod, baselines: Productivity_Baselines):
        self.ui_queue.put(("prod_baselines",))

    def _calibrate_phy(self):
        if self.phy:
            self._log("Physiological States baseline calibration started.")
            self.phy.calibrate_baselines()

    def _on_phy_baselines(self, phy, baselines: PhysiologicalStates_Baselines):
        self.ui_queue.put(("phy_baselines",))

    def _calibrate_fusion(self):
        if self.fusion_use_software:
            self._sync_fusion_weights_to_engine()
            self.fusion_software.start_baseline_calibration(duration_sec=60.0)
            self._log("Software fusion baseline calibration started (~60 s).")
            return
        if self.fusion:
            self._log("FusionCognitive baseline calibration started (DLL).")
            self.fusion.calibrate_baselines()

    def _on_fusion_baselines(self, fusion, baselines: FusionCognitive_BaselinesV2):
        self.ui_queue.put(
            ("fusion_baselines", float(baselines.cognitiveLoadBaseline))
        )

    def _apply_fusion_weights(self):
        self._sync_fusion_weights_to_engine()
        if self.fusion_use_software:
            self._log("Software fusion weights applied.")
            self._publish_fusion_software_metrics()
            return
        if not self.fusion:
            messagebox.showinfo(
                "FusionCognitive",
                "Native module not in DLL. Enable “Software fusion preview” to test.",
            )
            return
        try:
            w = FusionCognitive_FusionWeights(
                eeg_weight=self.weight_vars["eeg"].get(),
                ppg_weight=self.weight_vars["ppg"].get(),
                mems_weight=self.weight_vars["mems"].get(),
                classifier_weight=self.weight_vars["classifier"].get(),
            )
            self.fusion.set_config(FusionCognitive_Config(w))
            self._log("Fusion weights applied (DLL).")
        except CapsuleException as e:
            messagebox.showerror("Config failed", e.message)

    # ------------------------------------------------------------------ Metric callbacks
    def _on_emotions(self, emotions, states: Emotions_States):
        try:
            self._on_emotions_impl(states)
        except Exception as exc:
            self.ui_queue.put(("log", f"Emotions callback error: {exc}"))

    def _on_emotions_impl(self, states: Emotions_States):
        self._set_metric("Emotions.focus", f"{states.focus:.3f}")
        self._set_metric("Emotions.chill", f"{states.chill:.3f}")
        self._set_metric("Emotions.stress", f"{states.stress:.3f}")
        self._set_metric("Emotions.anger", f"{states.anger:.3f}")
        self._set_metric("Emotions.selfControl", f"{states.selfControl:.3f}")
        if self.fusion_use_software:
            self.fusion_software.update_inputs(
                timestamp_milli=states.timestampMilli,
                emotions_focus=states.focus,
                emotions_stress=states.stress,
            )
            self._publish_fusion_software_metrics()
            if self.fusion_software._calibrating and self.fusion_software.baseline >= 0:
                self.ui_queue.put(("fusion_baselines", self.fusion_software.baseline))

    def _on_cardio(self, cardio, data: Cardio_Data):
        try:
            self._on_cardio_impl(data)
        except Exception as exc:
            self.ui_queue.put(("log", f"Cardio callback error: {exc}"))

    def _on_cardio_impl(self, data: Cardio_Data):
        self._set_metric("Cardio.heartRate", f"{data.heartRate:.1f}")
        self._set_metric("Cardio.stressIndex", f"{data.stressIndex:.3f}")
        self._set_metric("Cardio.kaplanIndex", f"{data.kaplanIndex:.3f}")
        self._set_metric("Cardio.hasArtifacts", str(data.hasArtifacts))
        if self.fusion_use_software:
            self.fusion_software.update_inputs(
                timestamp_milli=data.timestampMilli,
                cardio_stress_index=data.stressIndex,
            )
            self._publish_fusion_software_metrics()

    def _on_prod_metrics(self, prod, metrics: Productivity_Metrics):
        try:
            self._on_prod_metrics_impl(metrics)
        except Exception as exc:
            self.ui_queue.put(("log", f"Productivity callback error: {exc}"))

    def _on_prod_metrics_impl(self, metrics: Productivity_Metrics):
        self._set_metric("Productivity.fatigueScore", f"{metrics.fatigueScore:.3f}")
        self._set_metric("Productivity.concentrationScore", f"{metrics.concentrationScore:.3f}")
        self._set_metric("Productivity.relaxationScore", f"{metrics.relaxationScore:.3f}")
        self._set_metric("Productivity.productivityScore", f"{metrics.productivityScore:.3f}")
        self._set_metric("Productivity.accumulatedFatigue", f"{metrics.accumulatedFatigue:.3f}")
        if self.fusion_use_software:
            self.fusion_software.update_inputs(
                timestamp_milli=metrics.timestampMilli,
                concentration=metrics.concentrationScore,
                fatigue=metrics.fatigueScore,
                productivity=metrics.productivityScore,
            )
            self._publish_fusion_software_metrics()
            if self.fusion_software._calibrating and self.fusion_software.baseline >= 0:
                self.ui_queue.put(("fusion_baselines", self.fusion_software.baseline))

    def _on_phy_states(self, phy, states: PhysiologicalStates_Value):
        try:
            self._on_phy_states_impl(states)
        except Exception as exc:
            self.ui_queue.put(("log", f"Physiological States callback error: {exc}"))

    def _on_phy_states_impl(self, states: PhysiologicalStates_Value):
        self._set_metric("Physiological States.relaxation", f"{states.relaxation:.3f}")
        self._set_metric("Physiological States.fatigue", f"{states.fatigue:.3f}")
        self._set_metric("Physiological States.concentration", f"{states.concentration:.3f}")
        self._set_metric("Physiological States.involvement", f"{states.involvement:.3f}")
        self._set_metric("Physiological States.stress", f"{states.stress:.3f}")
        if self.fusion_use_software:
            self.fusion_software.update_inputs(
                timestamp_milli=states.timestampMilli,
                phy_concentration=states.concentration,
                phy_stress=states.stress,
            )
            self._publish_fusion_software_metrics()

    def _on_fusion_metrics(self, fusion, metrics: FusionCognitive_MetricsV2):
        try:
            self._on_fusion_metrics_impl(metrics)
        except Exception as exc:
            self.ui_queue.put(("log", f"FusionCognitive callback error: {exc}"))

    def _on_fusion_metrics_impl(self, metrics: FusionCognitive_MetricsV2):
        if metrics.cognitiveLoad >= 0:
            self._set_metric("FusionCognitive v2.cognitiveLoad", f"{metrics.cognitiveLoad:.1f}")
        self._set_metric("FusionCognitive v2.confidence", f"{metrics.confidence:.3f}")
        self._set_metric("FusionCognitive v2.hasArtifacts", str(metrics.hasArtifacts))

    # ------------------------------------------------------------------ Poll thread
    def _start_poll_thread(self):
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self):
        while not self._poll_stop.is_set():
            if self.locator:
                try:
                    self.locator.update()
                except Exception as e:
                    self._log(f"Poll error: {e}")
            time.sleep(POLL_INTERVAL_SEC)

    def _on_close(self):
        self._poll_stop.set()
        self._disconnect()
        self.locator = None
        self.root.destroy()


def main():
    root = tk.Tk()
    CapsuleMetricsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
