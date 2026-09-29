"""
NeuroRaaga — Native Desktop GUI Dashboard
Built with Python Tkinter for acquisition of 4-channel EEG (A1, A2, C3, C4)
during Carnatic raga listening (Anandabhairavi, Shubhapantuvarali, Mohanam).
"""
from __future__ import annotations

import collections
import csv
import json
import math
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np

# Add project root and native Capsule path to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CAPSULE_PATH = (
    BASE_DIR
    / "Capsule_2.0.72"
    / "Capsule v2.0.72"
    / "CapsuleAPI"
    / "Windows"
    / "Capsule Python"
    / "CapsuleClientPython"
)
if str(CAPSULE_PATH) not in sys.path:
    sys.path.insert(0, str(CAPSULE_PATH))

from app.mci_audio_player import MCIAudioPlayer
from app.audio_manager import audio_manager
from app.data_exporter import RECORDINGS_DIR

TARGET_CHANNELS = ["A1", "A2", "C3", "C4"]

# Color palette for neurotech theme
C_BG = "#0B0F19"
C_PANEL = "#111827"
C_CARD = "#162032"
C_BORDER = "#1F293D"
C_TEXT = "#F8FAFC"
C_TEXT_MUTED = "#94A3B8"
C_TEXT_DIM = "#64748B"

# Accents
C_CYAN = "#00F2FE"
C_GOLD = "#F59E0B"
C_EMERALD = "#10B981"
C_ROSE = "#F43F5E"
C_ORANGE = "#F97316"

# Channel Trace Colors
CH_COLORS = {
    "A1": "#38BDF8",  # Cyan Blue (Left Mastoid)
    "A2": "#818CF8",  # Periwinkle (Right Mastoid)
    "C3": "#FBBF24",  # Carnatic Amber (Left Central)
    "C4": "#34D399"   # Mint Emerald (Right Central)
}

PROTOCOL_STAGES = [
    {"id": "baseline", "name": "Baseline (Eyes Closed / Rest)", "duration": 120, "audio": None},
    {"id": "raga1", "name": "Raga 1 (Anandabhairavi)", "duration": 120, "audio": "raga1"},
    {"id": "rest1", "name": "Silence / Post-Raga 1 Rest", "duration": 120, "audio": None},
    {"id": "raga2", "name": "Raga 2 (Shubhapantuvarali)", "duration": 120, "audio": "raga2"},
    {"id": "rest2", "name": "Silence / Post-Raga 2 Rest", "duration": 120, "audio": None},
    {"id": "raga3", "name": "Raga 3 (Mohanam)", "duration": 120, "audio": "raga3"}
]

class NeuroRaagaApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NeuroRaaga — Carnatic Ragas Acute EEG Acquisition Platform")
        self.root.geometry("1400x880")
        self.root.minsize(1200, 780)
        self.root.configure(bg=C_BG)

        # Application State
        self.participant = None
        self.is_connected = False
        self.device_serial = None
        self.device_name = "None"
        self.battery = 100
        
        # 3-Stage Electrode State: "GREEN", "ORANGE", "RED"
        # Initial state before connection: RED (not connected)
        self.electrode_states = {ch: "RED" for ch in TARGET_CHANNELS}
        self.electrode_impedances = {ch: 999.9 for ch in TARGET_CHANNELS}  # in kOhms
        self.electrode_frequencies = {ch: 0.0 for ch in TARGET_CHANNELS}  # in Hz
        self.electrode_bands = {ch: "Disconnected" for ch in TARGET_CHANNELS}

        # Waveform ring buffers (2500 points = 10 seconds @ 250 Hz)
        self.sample_rate = 250
        self.time_window_sec = 10
        self.buffer_len = self.sample_rate * self.time_window_sec
        self.wave_buffers = {ch: collections.deque([0.0]*self.buffer_len, maxlen=self.buffer_len) for ch in TARGET_CHANNELS}
        self.latest_uv = {ch: 0.0 for ch in TARGET_CHANNELS}
        self.gain_uv = 50.0  # +/- 50 uV default scale

        # Audio Player (Windows Native MCI)
        self.audio_player = MCIAudioPlayer()
        self.active_audio_track = None

        # Protocol Engine
        self.protocol_running = False
        self.protocol_paused = False  # Auto-pause trigger
        self.auto_pause_reason = ""
        self.current_stage_idx = 0
        self.stage_duration_sec = 120  # Default 2 minutes
        self.valid_stage_samples = 0
        self.total_target_samples = self.stage_duration_sec * self.sample_rate
        
        # Data Logger
        self.session_dir = None
        self.master_csv_file = None
        self.master_writer = None
        self.slice_csv_file = None
        self.slice_writer = None
        self.subjective_ratings = {}
        self.total_session_samples = 0
        self.generated_slices = []

        # Native Capsule SDK
        self.capsule = None
        self.locator = None
        self.native_device = None
        self.use_simulation = False
        self._init_capsule_sdk()

        # Build GUI Layout
        self._build_ui()
        self._setup_protocols()

        # Thread-safe UI dispatch queue
        self.ui_queue = collections.deque()
        self.root.after(30, self._ui_queue_tick)

        # Start Real-Time UI Dispatch Loops
        self.root.after(33, self._canvas_render_loop)   # ~30 FPS oscilloscope
        self.root.after(100, self._eeg_stream_tick)      # EEG acquisition & auto-pause watchdog
        self.root.after(500, self._status_watchdog)

    def _ui_queue_tick(self):
        while self.ui_queue:
            try:
                fn = self.ui_queue.popleft()
                fn()
            except Exception as e:
                print(f"[UI Queue Error]: {e}")
        self.root.after(30, self._ui_queue_tick)

    # ------------------------------------------------------------------
    # Capsule SDK & Native Device Integration
    # ------------------------------------------------------------------
    def _init_capsule_sdk(self):
        self._poll_stop = threading.Event()
        self._poll_thread = None
        dll_path = CAPSULE_PATH / "CapsuleClient.dll"
        if dll_path.exists():
            try:
                from Capsule import Capsule
                from DeviceLocator import DeviceLocator
                self.capsule = Capsule(str(dll_path))
                self.locator = DeviceLocator("Logs", self.capsule.get_lib())
                print(f"[NeuroRaaga] Native Capsule SDK loaded: {self.capsule.get_version()}")
                self._start_capsule_poll_thread()
            except Exception as e:
                print(f"[NeuroRaaga] Capsule SDK load error: {e}")

    def _start_capsule_poll_thread(self):
        if self.locator and (not self._poll_thread or not self._poll_thread.is_alive()):
            self._poll_stop.clear()
            self._poll_thread = threading.Thread(target=self._capsule_poll_loop, daemon=True)
            self._poll_thread.start()

    def _capsule_poll_loop(self):
        while not self._poll_stop.is_set():
            if self.locator:
                try:
                    self.locator.update()
                except Exception:
                    pass
            time.sleep(0.02)  # ~50Hz poll rate for Capsule internal event queue

    # ------------------------------------------------------------------
    # GUI Layout Construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # 1. Header Bar
        header = tk.Frame(self.root, bg=C_PANEL, height=64, padx=20, pady=10, relief=tk.FLAT)
        header.pack(fill=tk.X, side=tk.TOP)

        # Brand / Title
        title_box = tk.Frame(header, bg=C_PANEL)
        title_box.pack(side=tk.LEFT)
        lbl_title = tk.Label(
            title_box,
            text="NeuroRaaga",
            font=("Segoe UI", 16, "bold"),
            fg=C_CYAN,
            bg=C_PANEL
        )
        lbl_title.pack(side=tk.LEFT)
        lbl_tag = tk.Label(
            title_box,
            text="CARNATIC EEG PLATFORM",
            font=("Segoe UI", 8, "bold"),
            fg=C_GOLD,
            bg="#2A2010",
            padx=8,
            pady=2
        )
        lbl_tag.pack(side=tk.LEFT, padx=12)
        lbl_sub = tk.Label(
            title_box,
            text="4-Channel EEG (A1, A2, C3, C4) • 250 Hz Continuous Segment-Labeled Acquisition",
            font=("Segoe UI", 9),
            fg=C_TEXT_MUTED,
            bg=C_PANEL
        )
        lbl_sub.pack(side=tk.LEFT)

        # Header Status Badges (Right side)
        status_box = tk.Frame(header, bg=C_PANEL)
        status_box.pack(side=tk.RIGHT)

        self.lbl_hdr_conn = tk.Label(
            status_box,
            text="● DISCONNECTED (BLANK WAVEFORM)",
            font=("Segoe UI", 9, "bold"),
            fg=C_ROSE,
            bg=C_CARD,
            padx=12,
            pady=4
        )
        self.lbl_hdr_conn.pack(side=tk.LEFT, padx=6)

        self.lbl_hdr_serial = tk.Label(
            status_box,
            text="Serial: None",
            font=("Consolas", 9),
            fg=C_TEXT_MUTED,
            bg=C_CARD,
            padx=10,
            pady=4
        )
        self.lbl_hdr_serial.pack(side=tk.LEFT, padx=6)

        self.lbl_hdr_segment = tk.Label(
            status_box,
            text="STAGE: IDLE",
            font=("Segoe UI", 9, "bold"),
            fg=C_GOLD,
            bg="#2E2305",
            padx=12,
            pady=4
        )
        self.lbl_hdr_segment.pack(side=tk.LEFT, padx=6)

        # 2. Main Content Split (Left: Control Tabs, Right: Oscilloscope & Signal Quality)
        content_frame = tk.Frame(self.root, bg=C_BG, padx=16, pady=12)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Left Column: Tabbed Notebook
        left_col = tk.Frame(content_frame, bg=C_BG, width=540)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 12))
        left_col.pack_propagate(False)

        # Right Column: Oscilloscope & Audio Bar
        right_col = tk.Frame(content_frame, bg=C_BG)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._build_notebook_tabs(left_col)
        self._build_oscilloscope_panel(right_col)

    # ------------------------------------------------------------------
    # Left Column: Tabs for Workflow
    # ------------------------------------------------------------------
    def _build_notebook_tabs(self, parent):
        style = ttk.Style()
        style.theme_use('default')
        style.configure('TNotebook', background=C_BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=C_CARD, foreground=C_TEXT, font=('Segoe UI', 9, 'bold'), padding=[12, 6])
        style.map('TNotebook.Tab', background=[('selected', C_PANEL)], foreground=[('selected', C_CYAN)])

        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Participant Enrollment
        self.tab_enroll = tk.Frame(self.notebook, bg=C_PANEL, padx=14, pady=14)
        self.notebook.add(self.tab_enroll, text="1. Participant")
        self._build_enrollment_tab(self.tab_enroll)

        # Tab 2: EEG Device & Electrodes
        self.tab_device = tk.Frame(self.notebook, bg=C_PANEL, padx=14, pady=14)
        self.notebook.add(self.tab_device, text="2. Electrodes & Check")
        self._build_device_tab(self.tab_device)

        # Tab 3: Raga Audio Slots
        self.tab_music = tk.Frame(self.notebook, bg=C_PANEL, padx=14, pady=14)
        self.notebook.add(self.tab_music, text="3. Raga Slots")
        self._build_music_tab(self.tab_music)

        # Tab 4: Protocol Execution
        self.tab_proto = tk.Frame(self.notebook, bg=C_PANEL, padx=14, pady=14)
        self.notebook.add(self.tab_proto, text="4. Protocol Runner")
        self._build_protocol_tab(self.tab_proto)

        # Tab 5: Data & CSV Export
        self.tab_data = tk.Frame(self.notebook, bg=C_PANEL, padx=14, pady=14)
        self.notebook.add(self.tab_data, text="5. CSV Deliverables")
        self._build_data_tab(self.tab_data)

    # ------------------------------------------------------------------
    # Tab 1: Participant Enrollment & Strict Eligibility Screening
    # ------------------------------------------------------------------
    def _build_enrollment_tab(self, parent):
        tk.Label(
            parent,
            text="Participant Enrollment & Eligibility Screening",
            font=("Segoe UI", 12, "bold"),
            fg=C_CYAN,
            bg=C_PANEL
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Label(
            parent,
            text="Strict Protocol Screening: Age 18–30 only. No history of head injury, brain issues, or brain medications.",
            font=("Segoe UI", 8),
            fg=C_TEXT_MUTED,
            bg=C_PANEL,
            wraplength=480,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 10))

        # Eligibility Status Banner (Red when disqualified, Green when eligible)
        self.eligibility_banner = tk.Label(
            parent,
            text="Awaiting participant screening details...",
            font=("Segoe UI", 9, "bold"),
            fg=C_TEXT_MUTED,
            bg=C_CARD,
            padx=10,
            pady=6,
            relief=tk.FLAT
        )
        self.eligibility_banner.pack(fill=tk.X, pady=(0, 10))

        form = tk.Frame(parent, bg=C_PANEL)
        form.pack(fill=tk.BOTH, expand=True)

        # Name
        tk.Label(form, text="Volunteer Full Name *", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).grid(row=0, column=0, sticky=tk.W, pady=4)
        self.ent_name = tk.Entry(form, font=("Segoe UI", 10), bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT, relief=tk.FLAT)
        self.ent_name.insert(0, "Dr. Ananya Iyer")
        self.ent_name.grid(row=0, column=1, sticky=tk.EW, pady=4, padx=8)

        # Age (18-30 only)
        tk.Label(form, text="Age (Strict 18–30 yrs) *", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).grid(row=1, column=0, sticky=tk.W, pady=4)
        self.ent_age = tk.Entry(form, font=("Segoe UI", 10), bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT, relief=tk.FLAT)
        self.ent_age.insert(0, "24")
        self.ent_age.grid(row=1, column=1, sticky=tk.EW, pady=4, padx=8)

        # Sex
        tk.Label(form, text="Sex *", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).grid(row=2, column=0, sticky=tk.W, pady=4)
        self.cmb_sex = ttk.Combobox(form, values=["Female", "Male", "Other / Non-binary"], state="readonly")
        self.cmb_sex.set("Female")
        self.cmb_sex.grid(row=2, column=1, sticky=tk.EW, pady=4, padx=8)

        # Head Injury (Yes/No)
        tk.Label(form, text="Previous Head Injury? *", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).grid(row=3, column=0, sticky=tk.W, pady=4)
        self.cmb_injury = ttk.Combobox(form, values=["No (Eligible)", "Yes (Not Eligible)"], state="readonly")
        self.cmb_injury.set("No (Eligible)")
        self.cmb_injury.grid(row=3, column=1, sticky=tk.EW, pady=4, padx=8)

        # Brain / Neurological issues (Yes/No)
        tk.Label(form, text="Brain/Neurological Issues? *", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).grid(row=4, column=0, sticky=tk.W, pady=4)
        self.cmb_brain = ttk.Combobox(form, values=["No (Eligible)", "Yes (Not Eligible)"], state="readonly")
        self.cmb_brain.set("No (Eligible)")
        self.cmb_brain.grid(row=4, column=1, sticky=tk.EW, pady=4, padx=8)

        # Brain Medications (Yes/No)
        tk.Label(form, text="Brain/Psychiatric Meds? *", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).grid(row=5, column=0, sticky=tk.W, pady=4)
        self.cmb_meds = ttk.Combobox(form, values=["No (Eligible)", "Yes (Not Eligible)"], state="readonly")
        self.cmb_meds.set("No (Eligible)")
        self.cmb_meds.grid(row=5, column=1, sticky=tk.EW, pady=4, padx=8)

        # Sleep Quality
        tk.Label(form, text="Sleep Quality (Last Night) *", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).grid(row=6, column=0, sticky=tk.W, pady=4)
        self.cmb_sleep = ttk.Combobox(form, values=["Good (7-8 hrs, normal)", "Excellent (>8 hrs, restful)", "Fair (5-6 hrs, interrupted)", "Poor (<5 hrs, fatigued)"], state="readonly")
        self.cmb_sleep.set("Good (7-8 hrs, normal)")
        self.cmb_sleep.grid(row=6, column=1, sticky=tk.EW, pady=4, padx=8)

        # Caffeine Intake
        tk.Label(form, text="Caffeine Intake (Test Day) *", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).grid(row=7, column=0, sticky=tk.W, pady=4)
        self.cmb_caffeine = ttk.Combobox(form, values=["None (Clean baseline)", "Low (1 cup >3h ago)", "Moderate (1-2 cups)", "High (>2 cups or energy drink)"], state="readonly")
        self.cmb_caffeine.set("None (Clean baseline)")
        self.cmb_caffeine.grid(row=7, column=1, sticky=tk.EW, pady=4, padx=8)

        form.columnconfigure(1, weight=1)

        # Enroll Button
        self.btn_enroll = tk.Button(
            parent,
            text="Verify Eligibility & Enroll Volunteer →",
            font=("Segoe UI", 10, "bold"),
            bg="#0072FF",
            fg="white",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            cursor="hand2",
            command=self._handle_enrollment
        )
        self.btn_enroll.pack(fill=tk.X, pady=(12, 0))

    def _handle_enrollment(self):
        name = self.ent_name.get().strip()
        age_str = self.ent_age.get().strip()
        injury = self.cmb_injury.get()
        brain = self.cmb_brain.get()
        meds = self.cmb_meds.get()

        if not name:
            messagebox.showwarning("Missing Name", "Please enter the participant's name.")
            return

        try:
            age = int(age_str)
        except ValueError:
            messagebox.showerror("Invalid Age", "Please enter a valid numeric age.")
            return

        # 1. Age Limit Check (Strictly 18–30)
        if age < 18 or age > 30:
            self.eligibility_banner.config(
                text=f"NOT ELIGIBLE: Age is {age}. Study strictly requires volunteers aged 18–30 years.",
                bg="#450A0A",
                fg=C_ROSE
            )
            messagebox.showerror(
                "Participant Not Eligible",
                f"Candidate is NOT ELIGIBLE for this study.\n\nReason: Age {age} is outside the required 18–30 limit.\nCannot proceed to data collection."
            )
            return

        # 2. Head Injury Check
        if "Yes" in injury:
            self.eligibility_banner.config(
                text="NOT ELIGIBLE: Participant reported previous head injury.",
                bg="#450A0A",
                fg=C_ROSE
            )
            messagebox.showerror(
                "Participant Not Eligible",
                "Candidate is NOT ELIGIBLE for this study.\n\nReason: History of previous head injury reported.\nCannot proceed."
            )
            return

        # 3. Brain Issues Check
        if "Yes" in brain:
            self.eligibility_banner.config(
                text="NOT ELIGIBLE: Neurological/brain disorder reported.",
                bg="#450A0A",
                fg=C_ROSE
            )
            messagebox.showerror(
                "Participant Not Eligible",
                "Candidate is NOT ELIGIBLE for this study.\n\nReason: Neurological or brain condition reported.\nCannot proceed."
            )
            return

        # 4. Brain Medications Check
        if "Yes" in meds:
            self.eligibility_banner.config(
                text="NOT ELIGIBLE: Currently taking medications for brain/neurological.",
                bg="#450A0A",
                fg=C_ROSE
            )
            messagebox.showerror(
                "Participant Not Eligible",
                "Candidate is NOT ELIGIBLE for this study.\n\nReason: Candidate is taking brain-related medication.\nCannot proceed."
            )
            return

        # All passed: Eligible!
        pid = f"NR-P{int(time.time()) % 1000:03d}"
        self.participant = {
            "participant_id": pid,
            "name": name,
            "age": age,
            "sex": self.cmb_sex.get(),
            "sleep_quality": self.cmb_sleep.get(),
            "caffeine_intake": self.cmb_caffeine.get(),
            "enrolled_at": datetime.now().isoformat()
        }

        self.eligibility_banner.config(
            text=f"ELIGIBLE: {name} (Age {age}) • Assigned ID: {pid}",
            bg="#064E3B",
            fg=C_EMERALD
        )
        messagebox.showinfo("Enrolled", f"Volunteer {name} is eligible and successfully enrolled!\nAssigned ID: {pid}\n\nProceed to Step 2: Electrodes & Connection.")
        self.notebook.select(self.tab_device)

    # ------------------------------------------------------------------
    # Tab 2: EEG Device Connection & 3-Stage Electrode Check
    # ------------------------------------------------------------------
    def _build_device_tab(self, parent):
        tk.Label(
            parent,
            text="EEG Headphone Pro & Electrode Check",
            font=("Segoe UI", 12, "bold"),
            fg=C_CYAN,
            bg=C_PANEL
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Label(
            parent,
            text="Headphone EEG configuration: 4 Active Leads (A1, A2, C3, C4), 2 Grounds, 1 Reference (Cz).",
            font=("Segoe UI", 8),
            fg=C_TEXT_MUTED,
            bg=C_PANEL
        ).pack(anchor=tk.W, pady=(0, 10))

        # Device Selection & Buttons
        dev_frame = tk.Frame(parent, bg=C_CARD, padx=12, pady=10)
        dev_frame.pack(fill=tk.X, pady=(0, 12))

        btn_row = tk.Frame(dev_frame, bg=C_CARD)
        btn_row.pack(fill=tk.X, pady=(0, 6))

        self.btn_scan = tk.Button(
            btn_row,
            text="Scan Devices",
            font=("Segoe UI", 9, "bold"),
            bg="#1E293B",
            fg=C_TEXT,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            command=self._handle_scan_devices
        )
        self.btn_scan.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_connect = tk.Button(
            btn_row,
            text="Connect Device",
            font=("Segoe UI", 9, "bold"),
            bg="#0072FF",
            fg="white",
            relief=tk.FLAT,
            padx=12,
            pady=4,
            command=self._handle_connect_device
        )
        self.btn_connect.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_disconnect = tk.Button(
            btn_row,
            text="Disconnect",
            font=("Segoe UI", 9, "bold"),
            bg=C_ROSE,
            fg="white",
            relief=tk.FLAT,
            padx=10,
            pady=4,
            command=self._handle_disconnect
        )
        self.btn_disconnect.pack(side=tk.LEFT)

        # Instructions for real hardware setup
        inst_lbl = tk.Label(
            dev_frame,
            text="Step 1: Insert USB Dongle into PC  •  Step 2: Turn ON Headphone  •  Step 3: Click 'Scan Devices'",
            font=("Segoe UI", 8, "bold"),
            fg=C_CYAN,
            bg=C_CARD
        )
        inst_lbl.pack(anchor=tk.W, pady=(0, 6))

        self.cmb_devices = ttk.Combobox(dev_frame, state="readonly", width=55)
        self.cmb_devices.pack(fill=tk.X)
        self._populate_initial_devices()

        # 3-Stage Connection Legend
        legend_frame = tk.Frame(parent, bg=C_PANEL)
        legend_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(legend_frame, text="Electrode Stages Legend:", font=("Segoe UI", 8, "bold"), fg=C_TEXT_MUTED, bg=C_PANEL).pack(side=tk.LEFT)
        tk.Label(legend_frame, text=" 🔴 Red = Not Connected (>100kΩ) ", font=("Segoe UI", 8), fg=C_ROSE, bg=C_PANEL).pack(side=tk.LEFT)
        tk.Label(legend_frame, text=" 🟠 Orange = Partially Connected ", font=("Segoe UI", 8), fg=C_ORANGE, bg=C_PANEL).pack(side=tk.LEFT)
        tk.Label(legend_frame, text=" 🟢 Green = Fully Connected (<50kΩ) ", font=("Segoe UI", 8), fg=C_EMERALD, bg=C_PANEL).pack(side=tk.LEFT)

        # 4 Electrode Cards (A1, A2, C3, C4)
        elec_grid = tk.Frame(parent, bg=C_PANEL)
        elec_grid.pack(fill=tk.BOTH, expand=True, pady=4)

        self.electrode_ui_cards = {}
        for idx, ch in enumerate(TARGET_CHANNELS):
            pos_label = "Left Mastoid" if ch == "A1" else ("Right Mastoid" if ch == "A2" else ("Left Central" if ch == "C3" else "Right Central"))
            card = tk.Frame(elec_grid, bg=C_CARD, padx=10, pady=8, relief=tk.FLAT)
            card.grid(row=idx // 2, column=idx % 2, sticky=tk.NSEW, padx=6, pady=6)
            elec_grid.columnconfigure(idx % 2, weight=1)
            elec_grid.rowconfigure(idx // 2, weight=1)

            # Top: Electrode name & Status Indicator
            top_bar = tk.Frame(card, bg=C_CARD)
            top_bar.pack(fill=tk.X)
            lbl_name = tk.Label(top_bar, text=ch, font=("Segoe UI", 12, "bold"), fg=CH_COLORS[ch], bg=C_CARD)
            lbl_name.pack(side=tk.LEFT)
            lbl_pos = tk.Label(top_bar, text=f"({pos_label})", font=("Segoe UI", 8), fg=C_TEXT_DIM, bg=C_CARD)
            lbl_pos.pack(side=tk.LEFT, padx=6)

            lbl_stage = tk.Label(
                top_bar,
                text="🔴 NOT CONNECTED",
                font=("Segoe UI", 8, "bold"),
                fg=C_ROSE,
                bg="#2A0F14",
                padx=6,
                pady=1
            )
            lbl_stage.pack(side=tk.RIGHT)

            # Impedance
            lbl_imp = tk.Label(card, text="Impedance: Disconnected", font=("Consolas", 9), fg=C_TEXT_MUTED, bg=C_CARD)
            lbl_imp.pack(anchor=tk.W, pady=(4, 1))

            # Live Dominant Frequency
            lbl_freq = tk.Label(card, text="Frequency: 0.0 Hz (—)", font=("Consolas", 9), fg=C_CYAN, bg=C_CARD)
            lbl_freq.pack(anchor=tk.W)

            self.electrode_ui_cards[ch] = {
                "card": card,
                "stage": lbl_stage,
                "impedance": lbl_imp,
                "frequency": lbl_freq
            }

        # Quality Check Status Banner
        self.signal_check_banner = tk.Label(
            parent,
            text="Waiting for device connection. Connect headphones to inspect electrodes.",
            font=("Segoe UI", 9, "bold"),
            fg=C_TEXT_MUTED,
            bg=C_CARD,
            padx=10,
            pady=8
        )
        self.signal_check_banner.pack(fill=tk.X, pady=(10, 0))

    def _populate_initial_devices(self):
        initial = [
            "[Click 'Scan Devices' after inserting USB dongle & powering ON headset]",
            "NeuroRaaga Synthetic EEG Generator (250 Hz) [Serial: SIM-NEURORAAGA-250]"
        ]
        self.cmb_devices["values"] = initial
        self.cmb_devices.current(0)

    def _handle_scan_devices(self):
        self._start_capsule_poll_thread()
        self.btn_scan.config(state=tk.DISABLED, text="Scanning... (8s)")
        self.signal_check_banner.config(
            text="Scanning Bluetooth LE via USB Dongle for nearby Capsule EEG Headphones...",
            fg=C_GOLD,
            bg="#2B210B"
        )

        def worker():
            discovered = []
            if self.locator:
                try:
                    from DeviceType import DeviceType
                    scan_done = threading.Event()
                    def on_dev(l, info, r):
                        for i in range(len(info)):
                            name_str = info[i].get_name()
                            serial_str = info[i].get_serial()
                            entry = f"{name_str} [Serial: {serial_str}]"
                            if entry not in discovered:
                                discovered.append(entry)
                        scan_done.set()

                    self.locator.set_on_devices_list(on_dev)
                    # Request Headphones first
                    self.locator.request_devices(DeviceType.Headphones, 6)
                    scan_done.wait(timeout=6.5)

                    if not discovered:
                        scan_done.clear()
                        # Request Any device type
                        self.locator.request_devices(DeviceType.Any, 2)
                        scan_done.wait(timeout=2.5)
                except Exception as e:
                    print(f"Scan error: {e}")

            all_devices = []
            if discovered:
                all_devices.extend(discovered)
            else:
                all_devices.append("[No physical EEG devices found - Plug in dongle & Turn on headset]")

            # Always offer Synthetic Simulator as explicit offline testing option
            sim_entry = "NeuroRaaga Synthetic EEG Generator (250 Hz) [Serial: SIM-NEURORAAGA-250]"
            all_devices.append(sim_entry)

            def update_ui():
                self.cmb_devices["values"] = all_devices
                self.cmb_devices.current(0)
                self.btn_scan.config(state=tk.NORMAL, text="Scan Devices")
                if discovered:
                    self.signal_check_banner.config(
                        text=f"Scan complete! Found {len(discovered)} EEG hardware device(s). Select device & click 'Connect Device'.",
                        fg=C_EMERALD,
                        bg="#064E3B"
                    )
                else:
                    self.signal_check_banner.config(
                        text="No physical EEG devices detected. Ensure USB dongle is connected, headset is powered ON, and scan again.",
                        fg=C_ROSE,
                        bg="#450A0A"
                    )

            self.ui_queue.append(update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_connect_device(self):
        sel = self.cmb_devices.get().strip()
        if not sel or "Click 'Scan Devices'" in sel or "No physical EEG devices found" in sel:
            messagebox.showwarning(
                "Device Not Selected",
                "Please insert your USB BLE dongle, turn ON your Capsule EEG Headphone, and click 'Scan Devices' first."
            )
            return

        is_sim = "SIM-NEURORAAGA-250" in sel
        serial = "SIM-NEURORAAGA-250" if is_sim else sel.split("[Serial: ")[-1].replace("]", "").strip()

        if is_sim:
            self._connect_simulation(serial)
            return

        # Native Physical Hardware Connection
        self.btn_connect.config(state=tk.DISABLED, text="Connecting...")
        self.signal_check_banner.config(
            text=f"Connecting to physical EEG Headphone ({serial})... Establishing Bluetooth link...",
            fg=C_CYAN,
            bg="#162032"
        )

        def connect_worker():
            connected_ok = False
            error_msg = ""
            try:
                from Device import Device
                self._start_capsule_poll_thread()

                self.native_device = Device(self.locator, serial, self.capsule.get_lib())
                self.native_device.set_on_connection_status_changed(self._on_native_connection_status)
                self.native_device.set_on_eeg(self._on_native_eeg)
                self.native_device.set_on_resistances(self._on_native_resistances)
                self.native_device.connect(bipolarChannels=True)
                self.native_device.start()

                connected_ok = True
            except Exception as e:
                error_msg = str(e)

            def finalize_connect():
                self.btn_connect.config(state=tk.NORMAL, text="Connect Device")
                if connected_ok:
                    self.is_connected = True
                    self.use_simulation = False
                    self.device_serial = serial
                    self.device_name = f"Capsule EEG Headphone Pro ({serial})"
                    self.lbl_hdr_conn.config(text="● CONNECTED (NATIVE HARDWARE)", fg=C_EMERALD)
                    self.lbl_hdr_serial.config(text=f"Serial: {self.device_serial}")
                    self.signal_check_banner.config(
                        text=f"Native Headphone Connected ({serial})! Adjust ear cups so all 4 leads turn GREEN.",
                        fg=C_EMERALD,
                        bg="#064E3B"
                    )
                    messagebox.showinfo("Connected", f"Connected to native EEG Headphone Pro!\nSerial/Code: {serial}\n\nLive real-time physical EEG stream is active.")
                else:
                    self.native_device = None
                    self.is_connected = False
                    self.lbl_hdr_conn.config(text="● DISCONNECTED", fg=C_ROSE)
                    self.lbl_hdr_serial.config(text="Serial: None")
                    self.signal_check_banner.config(
                        text=f"Connection failed for {serial}. Ensure dongle is plugged in & headset is powered ON.",
                        fg=C_ROSE,
                        bg="#450A0A"
                    )
                    messagebox.showerror(
                        "Hardware Connection Failed",
                        f"Could not establish physical connection to EEG device ({serial}):\n\n{error_msg}\n\n"
                        f"Troubleshooting checklist:\n"
                        f"1. Ensure the USB BLE dongle is plugged into your PC.\n"
                        f"2. Ensure the headphone power switch is ON and battery is charged.\n"
                        f"3. Ensure the headphone is within range of the PC.\n"
                        f"4. Click 'Scan Devices' to refresh discovery."
                    )

            self.ui_queue.append(finalize_connect)

        threading.Thread(target=connect_worker, daemon=True).start()

    def _connect_simulation(self, serial: str):
        self.is_connected = True
        self.use_simulation = True
        self.device_serial = serial
        self.device_name = f"NeuroRaaga EEG Headphone ({serial})" if not serial.startswith("SIM-") else "NeuroRaaga Precision EEG Simulator (250 Hz)"
        self.lbl_hdr_conn.config(text=f"● CONNECTED ({serial})", fg=C_EMERALD)
        self.lbl_hdr_serial.config(text=f"Serial: {self.device_serial}")
        self.signal_check_banner.config(
            text="Device Connected! Placing electrodes on participant... All 4 must turn GREEN.",
            fg=C_GOLD,
            bg="#2B210B"
        )
        for ch in TARGET_CHANNELS:
            self.electrode_states[ch] = "GREEN"
            self.electrode_impedances[ch] = round(14.0 + (hash(ch) % 5), 1)
        self._update_electrode_card_ui()
        messagebox.showinfo("Connected", f"Connected to {self.device_name}!\nLive real-time waveforms are now streaming on the oscilloscope.")

    def _on_native_connection_status(self, device, status):
        status_val = int(status)
        if status_val == 1:
            self.is_connected = True
        else:
            self.is_connected = False
            self._handle_disconnect()

    def _on_native_resistances(self, device, res):
        for idx in range(len(res)):
            val_kohm = res.get_value(idx) / 1000.0
            if idx < len(TARGET_CHANNELS):
                ch = TARGET_CHANNELS[idx]
                self.electrode_impedances[ch] = round(val_kohm, 1)
                if val_kohm < 50.0:
                    self.electrode_states[ch] = "GREEN"
                elif val_kohm < 100.0:
                    self.electrode_states[ch] = "ORANGE"
                else:
                    self.electrode_states[ch] = "RED"

    def _on_native_eeg(self, device, eeg):
        sample_count = eeg.get_samples_count()
        ch_count = eeg.get_channels_count()
        now_ts = time.time()

        for s in range(sample_count):
            t_ms = eeg.get_timestamp(s)
            t_sec = t_ms / 1000.0 if t_ms > 0 else now_ts

            sample_dict = {"timestamp": t_sec}
            for ch_idx, ch_name in enumerate(TARGET_CHANNELS):
                if ch_idx < ch_count:
                    raw_val = eeg.get_raw_value(ch_idx, s)
                    uV = raw_val * 1e6 if abs(raw_val) < 1.0 else raw_val
                else:
                    uV = 0.0
                sample_dict[ch_name] = round(uV, 3)
                self.wave_buffers[ch_name].append(uV)
                self.latest_uv[ch_name] = uV

            self._log_protocol_sample(sample_dict)

    def _handle_disconnect(self):
        self.is_connected = False
        if self.native_device:
            try:
                self.native_device.stop()
                self.native_device.disconnect()
            except Exception:
                pass
            self.native_device = None
        self.lbl_hdr_conn.config(text="● DISCONNECTED (BLANK WAVEFORM)", fg=C_ROSE)
        self.lbl_hdr_serial.config(text="Serial: None")
        # Blank the buffers when disconnected
        for ch in TARGET_CHANNELS:
            self.wave_buffers[ch] = collections.deque([0.0]*self.buffer_len, maxlen=self.buffer_len)
            self.electrode_states[ch] = "RED"
            self.electrode_impedances[ch] = 999.9
            self.electrode_frequencies[ch] = 0.0
            self.electrode_bands[ch] = "Disconnected"
        self._update_electrode_card_ui()

    def _update_electrode_card_ui(self):
        all_green = True
        bad_channels = []

        for ch in TARGET_CHANNELS:
            state = self.electrode_states[ch]
            imp = self.electrode_impedances[ch]
            freq = self.electrode_frequencies[ch]
            band = self.electrode_bands[ch]
            card_ui = self.electrode_ui_cards[ch]

            if state == "GREEN":
                card_ui["stage"].config(text="🟢 FULLY CONNECTED", fg=C_EMERALD, bg="#064E3B")
                card_ui["impedance"].config(text=f"Impedance: {imp} kΩ (Good)", fg=C_TEXT)
                card_ui["frequency"].config(text=f"Frequency: {freq:.1f} Hz [{band}]", fg=C_CYAN)
            elif state == "ORANGE":
                all_green = False
                bad_channels.append(f"{ch} (Partial)")
                card_ui["stage"].config(text="🟠 PARTIALLY CONNECTED", fg=C_ORANGE, bg="#431407")
                card_ui["impedance"].config(text=f"Impedance: {imp} kΩ (Fair)", fg=C_ORANGE)
                card_ui["frequency"].config(text=f"Frequency: {freq:.1f} Hz (Noisy)", fg=C_ORANGE)
            else: # RED
                all_green = False
                bad_channels.append(f"{ch} (Detached)")
                card_ui["stage"].config(text="🔴 NOT CONNECTED", fg=C_ROSE, bg="#450A0A")
                card_ui["impedance"].config(text="Impedance: >100 kΩ (Poor)", fg=C_ROSE)
                card_ui["frequency"].config(text="Frequency: 0.0 Hz (Off)", fg=C_TEXT_DIM)

        if not self.is_connected:
            self.signal_check_banner.config(
                text="Device not connected. Waveforms remain blank until connection.",
                fg=C_ROSE,
                bg="#2A0F14"
            )
        elif all_green:
            self.signal_check_banner.config(
                text="ALL 4 ELECTRODES GREEN & VALID. Ready for EEG data collection.",
                fg=C_EMERALD,
                bg="#064E3B"
            )
        else:
            self.signal_check_banner.config(
                text=f"CONNECT ELECTRODES CORRECTLY: [{', '.join(bad_channels)}] not ready. Cannot collect.",
                fg=C_ROSE,
                bg="#450A0A"
            )

    # ------------------------------------------------------------------
    # Tab 3: Raga Audio Slots Management
    # ------------------------------------------------------------------
    def _build_music_tab(self, parent):
        tk.Label(
            parent,
            text="Carnatic Music Library & Slot Mapping",
            font=("Segoe UI", 12, "bold"),
            fg=C_CYAN,
            bg=C_PANEL
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Label(
            parent,
            text="Map or replace audio tracks for the 3 experimental conditions without touching code.",
            font=("Segoe UI", 8),
            fg=C_TEXT_MUTED,
            bg=C_PANEL
        ).pack(anchor=tk.W, pady=(0, 10))

        slots = audio_manager.get_slots()
        self.raga_ui_slots = {}

        for slot_id, info in slots.items():
            slot_box = tk.Frame(parent, bg=C_CARD, padx=12, pady=10, relief=tk.FLAT)
            slot_box.pack(fill=tk.X, pady=6)

            top = tk.Frame(slot_box, bg=C_CARD)
            top.pack(fill=tk.X)
            lbl_tag = tk.Label(top, text=info["label"], font=("Segoe UI", 8, "bold"), fg=C_GOLD, bg="#2E2305", padx=6, pady=1)
            lbl_tag.pack(side=tk.LEFT)
            lbl_dur = tk.Label(top, text=f"Duration: {info['duration_sec']}s", font=("Consolas", 8), fg=C_TEXT_MUTED, bg=C_CARD)
            lbl_dur.pack(side=tk.RIGHT)

            lbl_title = tk.Label(slot_box, text=info["current_title"], font=("Segoe UI", 11, "bold"), fg=C_TEXT, bg=C_CARD)
            lbl_title.pack(anchor=tk.W, pady=(2, 0))

            lbl_mood = tk.Label(slot_box, text=info["mood_description"], font=("Segoe UI", 8), fg=C_TEXT_MUTED, bg=C_CARD)
            lbl_mood.pack(anchor=tk.W)

            btn_bar = tk.Frame(slot_box, bg=C_CARD)
            btn_bar.pack(fill=tk.X, pady=(6, 0))

            btn_prev = tk.Button(
                btn_bar,
                text="▶ Preview",
                font=("Segoe UI", 8, "bold"),
                bg="#1E293B",
                fg=C_TEXT,
                relief=tk.FLAT,
                padx=8,
                pady=2,
                command=lambda s=slot_id: self._preview_raga(s)
            )
            btn_prev.pack(side=tk.LEFT, padx=(0, 6))

            btn_upload = tk.Button(
                btn_bar,
                text="Browse & Replace...",
                font=("Segoe UI", 8),
                bg="#334155",
                fg=C_TEXT,
                relief=tk.FLAT,
                padx=8,
                pady=2,
                command=lambda s=slot_id: self._replace_raga_track(s)
            )
            btn_upload.pack(side=tk.LEFT)

            self.raga_ui_slots[slot_id] = {
                "title": lbl_title,
                "info": info
            }

    def _preview_raga(self, slot_id):
        slot = audio_manager.get_slot_info(slot_id)
        if slot and slot.get("filepath"):
            if self.audio_player.is_playing:
                self.audio_player.stop()
            else:
                self.audio_player.load_and_play(slot["filepath"])
                self.lbl_player_track.config(text=f"Playing Preview: {slot['current_title']}")

    def _replace_raga_track(self, slot_id):
        filepath = filedialog.askopenfilename(
            title=f"Select Audio Track for {slot_id.upper()}",
            filetypes=[("Audio Files", "*.wav *.mp3 *.ogg *.flac"), ("All Files", "*.*")]
        )
        if filepath:
            filename = os.path.basename(filepath)
            display_title = os.path.splitext(filename)[0]
            with open(filepath, "rb") as f:
                updated = audio_manager.save_upload(slot_id, f, filename, display_title)
            self.raga_ui_slots[slot_id]["title"].config(text=updated["current_title"])
            messagebox.showinfo("Track Updated", f"Successfully mapped '{display_title}' to {slot_id.upper()}!")

    # ------------------------------------------------------------------
    # Tab 4: Fixed Protocol Runner & Auto-Pause Watchdog
    # ------------------------------------------------------------------
    def _build_protocol_tab(self, parent):
        tk.Label(
            parent,
            text="Fixed Experimental Protocol Runner",
            font=("Segoe UI", 12, "bold"),
            fg=C_CYAN,
            bg=C_PANEL
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Label(
            parent,
            text="Strict 12-Minute Fixed Timing. All 4 electrodes must be GREEN. If any electrode turns RED/ORANGE, recording auto-pauses and resumes without modifying total valid collection time.",
            font=("Segoe UI", 8),
            fg=C_TEXT_MUTED,
            bg=C_PANEL,
            wraplength=480,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 8))

        # Timing Mode Selector (120s standard vs 15s test)
        mode_frame = tk.Frame(parent, bg=C_CARD, padx=10, pady=6)
        mode_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(mode_frame, text="Protocol Segment Duration:", font=("Segoe UI", 8, "bold"), fg=C_TEXT, bg=C_CARD).pack(side=tk.LEFT)
        self.cmb_proto_mode = ttk.Combobox(
            mode_frame,
            values=["Standard Clinical (120s per segment • 12 min total)", "Fast Test Mode (15s per segment • 90s total)"],
            state="readonly",
            width=36
        )
        self.cmb_proto_mode.set("Standard Clinical (120s per segment • 12 min total)")
        self.cmb_proto_mode.pack(side=tk.RIGHT)
        self.cmb_proto_mode.bind("<<ComboboxSelected>>", self._on_proto_mode_changed)

        # Clocks
        clocks_box = tk.Frame(parent, bg=C_PANEL)
        clocks_box.pack(fill=tk.X, pady=(0, 8))

        b1 = tk.Frame(clocks_box, bg=C_CARD, padx=12, pady=6)
        b1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        tk.Label(b1, text="STAGE REMAINING", font=("Segoe UI", 7, "bold"), fg=C_TEXT_DIM, bg=C_CARD).pack()
        self.lbl_stage_clock = tk.Label(b1, text="02:00", font=("Consolas", 16, "bold"), fg=C_CYAN, bg=C_CARD)
        self.lbl_stage_clock.pack()

        b2 = tk.Frame(clocks_box, bg=C_CARD, padx=12, pady=6)
        b2.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))
        tk.Label(b2, text="TOTAL REMAINING", font=("Segoe UI", 7, "bold"), fg=C_TEXT_DIM, bg=C_CARD).pack()
        self.lbl_total_clock = tk.Label(b2, text="12:00", font=("Consolas", 16, "bold"), fg=C_GOLD, bg=C_CARD)
        self.lbl_total_clock.pack()

        # Stages List
        self.stage_list_frame = tk.Frame(parent, bg=C_PANEL)
        self.stage_list_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        self.stage_list_labels = []

        for idx, stg in enumerate(PROTOCOL_STAGES):
            row = tk.Frame(self.stage_list_frame, bg=C_CARD, padx=10, pady=5)
            row.pack(fill=tk.X, pady=2)
            lbl_num = tk.Label(row, text=f"{idx+1}", font=("Segoe UI", 8, "bold"), fg=C_CYAN, bg=C_CARD, width=2)
            lbl_num.pack(side=tk.LEFT)
            lbl_name = tk.Label(row, text=stg["name"], font=("Segoe UI", 8, "bold"), fg=C_TEXT, bg=C_CARD)
            lbl_name.pack(side=tk.LEFT, padx=6)
            lbl_time = tk.Label(row, text="120s", font=("Consolas", 8), fg=C_TEXT_MUTED, bg=C_CARD)
            lbl_time.pack(side=tk.RIGHT)
            self.stage_list_labels.append({"frame": row, "name": lbl_name, "time": lbl_time})

        # Auto-Pause Alert Banner
        self.pause_alert_banner = tk.Label(
            parent,
            text="",
            font=("Segoe UI", 8, "bold"),
            fg=C_ROSE,
            bg=C_PANEL
        )
        self.pause_alert_banner.pack(fill=tk.X, pady=2)

        # Control Buttons (Start / Abort)
        ctrl_frame = tk.Frame(parent, bg=C_PANEL)
        ctrl_frame.pack(fill=tk.X, pady=(6, 0))

        self.btn_start_proto = tk.Button(
            ctrl_frame,
            text="▶ Start Fixed Protocol (12 Minutes)",
            font=("Segoe UI", 10, "bold"),
            bg="#0072FF",
            fg="white",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            cursor="hand2",
            command=self._start_protocol
        )
        self.btn_start_proto.pack(fill=tk.X)

        self.btn_abort_proto = tk.Button(
            ctrl_frame,
            text="■ Abort Recording Session",
            font=("Segoe UI", 9, "bold"),
            bg=C_ROSE,
            fg="white",
            relief=tk.FLAT,
            padx=16,
            pady=6,
            cursor="hand2",
            command=self._abort_protocol
        )
        # Hidden by default

    def _on_proto_mode_changed(self, event=None):
        mode = self.cmb_proto_mode.get()
        if "15s" in mode:
            self.stage_duration_sec = 15
        else:
            self.stage_duration_sec = 120
        self.total_target_samples = self.stage_duration_sec * self.sample_rate
        # Update stage list labels
        for idx, lbls in enumerate(self.stage_list_labels):
            lbls["time"].config(text=f"{self.stage_duration_sec}s")
        rem = self.stage_duration_sec
        tot = self.stage_duration_sec * len(PROTOCOL_STAGES)
        self.lbl_stage_clock.config(text=f"{rem//60:02d}:{rem%60:02d}")
        self.lbl_total_clock.config(text=f"{tot//60:02d}:{tot%60:02d}")

    def _start_protocol(self):
        # 1. Eligibility Check
        if not self.participant:
            messagebox.showwarning("Enrollment Required", "Please enroll an eligible participant in Tab 1 first.")
            self.notebook.select(self.tab_enroll)
            return

        # 2. Connection Check
        if not self.is_connected:
            messagebox.showwarning("Device Not Connected", "EEG device is not connected. Please connect in Tab 2.")
            self.notebook.select(self.tab_device)
            return

        # 3. All 4 Electrodes GREEN Check
        all_green = all(self.electrode_states[ch] == "GREEN" for ch in TARGET_CHANNELS)
        if not all_green:
            bad = [ch for ch, s in self.electrode_states.items() if s != "GREEN"]
            messagebox.showerror(
                "Electrodes Not Ready",
                f"Cannot start recording.\n\nAll 4 electrodes must be GREEN (<50 kΩ).\nCurrently not ready: {', '.join(bad)}.\n\nPlease adjust headphone contacts on participant."
            )
            self.notebook.select(self.tab_device)
            return

        # 4. Initialize Data Storage Directory & Master CSV
        pid = self.participant["participant_id"]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = RECORDINGS_DIR / f"{pid}_{ts}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        master_path = self.session_dir / f"NeuroRaaga_{pid}_master.csv"
        self.master_csv_file = open(master_path, "w", newline="", encoding="utf-8")
        self.master_writer = csv.writer(self.master_csv_file)
        self.master_writer.writerow(["Timestamp", "A1", "A2", "C3", "C4", "Segment"])

        self.generated_slices = []
        self.subjective_ratings = {}
        self.current_stage_idx = 0
        self.valid_stage_samples = 0
        self.total_session_samples = 0
        self.protocol_running = True
        self.protocol_paused = False

        self.btn_start_proto.pack_forget()
        self.btn_abort_proto.pack(fill=tk.X)
        self.cmb_proto_mode.config(state="disabled")

        self._enter_stage(0)

    def _enter_stage(self, stage_idx):
        if stage_idx >= len(PROTOCOL_STAGES):
            self._finish_protocol()
            return

        self.current_stage_idx = stage_idx
        stg = PROTOCOL_STAGES[stage_idx]
        self.valid_stage_samples = 0

        # Close old slice file if open
        if self.slice_csv_file and not self.slice_csv_file.closed:
            self.slice_csv_file.flush()
            self.slice_csv_file.close()

        # Open new slice CSV file
        pid = self.participant["participant_id"]
        slice_name = f"NeuroRaaga_{pid}_segment_{stg['id']}.csv"
        slice_path = self.session_dir / slice_name
        self.slice_csv_file = open(slice_path, "w", newline="", encoding="utf-8")
        self.slice_writer = csv.writer(self.slice_csv_file)
        self.slice_writer.writerow(["Timestamp", "A1", "A2", "C3", "C4", "Segment"])
        self.generated_slices.append(slice_name)

        # Highlight stage in list
        for i, lbls in enumerate(self.stage_list_labels):
            if i == stage_idx:
                lbls["frame"].config(bg="#1E3A5F")
                lbls["name"].config(fg=C_CYAN, bg="#1E3A5F")
            elif i < stage_idx:
                lbls["frame"].config(bg="#064E3B")
                lbls["name"].config(fg=C_EMERALD, bg="#064E3B")
            else:
                lbls["frame"].config(bg=C_CARD)
                lbls["name"].config(fg=C_TEXT, bg=C_CARD)

        self.lbl_hdr_segment.config(text=f"STAGE: {stg['id'].upper()}")

        # Audio playback for raga segments
        if stg["audio"]:
            slot = audio_manager.get_slot_info(stg["audio"])
            if slot and slot.get("filepath"):
                self.audio_player.load_and_play(slot["filepath"])
                self.lbl_player_track.config(text=f"Delivering Audio: {slot['current_title']}")
        else:
            self.audio_player.stop()
            self.lbl_player_track.config(text="Silent Recovery / Baseline (No Audio)")

    def _abort_protocol(self):
        if messagebox.askyesno("Abort Recording", "Are you sure you want to abort the current protocol? Valid samples recorded so far will be saved."):
            self.protocol_running = False
            self.audio_player.stop()
            if self.slice_csv_file and not self.slice_csv_file.closed:
                self.slice_csv_file.close()
            if self.master_csv_file and not self.master_csv_file.closed:
                self.master_csv_file.close()
            self.btn_abort_proto.pack_forget()
            self.btn_start_proto.pack(fill=tk.X)
            self.cmb_proto_mode.config(state="readonly")
            self.lbl_hdr_segment.config(text="STAGE: ABORTED")

    def _finish_protocol(self):
        self.protocol_running = False
        self.audio_player.stop()
        if self.slice_csv_file and not self.slice_csv_file.closed:
            self.slice_csv_file.close()
        if self.master_csv_file and not self.master_csv_file.closed:
            self.master_csv_file.close()

        # Prompt final rating for Raga 3
        self._prompt_subjective_rating("raga3", "Raga 3 (Mohanam)")

        # Save Metadata JSON & Ratings CSV
        self._finalize_data_deliverables()

        self.btn_abort_proto.pack_forget()
        self.btn_start_proto.pack(fill=tk.X)
        self.cmb_proto_mode.config(state="readonly")
        self.lbl_hdr_segment.config(text="STAGE: COMPLETE")

        messagebox.showinfo(
            "Protocol Complete",
            f"All 6 segments completed with identical sample duration ({self.total_target_samples} samples per segment).\n\nMaster CSV and all 6 segment slices have been generated in Step 5."
        )
        self.notebook.select(self.tab_data)
        self._refresh_data_tab()

    # ------------------------------------------------------------------
    # Subjective Ratings Dialog
    # ------------------------------------------------------------------
    def _prompt_subjective_rating(self, condition: str, title_str: str):
        dlg = tk.Toplevel(self.root)
        dlg.title(f"Subjective Ratings: {title_str}")
        dlg.geometry("480x420")
        dlg.configure(bg=C_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text=f"Subjective Ratings — {title_str}", font=("Segoe UI", 12, "bold"), fg=C_GOLD, bg=C_PANEL).pack(pady=(16, 6))
        tk.Label(dlg, text="Ask participant to rate their acute experience on a 0–10 scale:", font=("Segoe UI", 8), fg=C_TEXT_MUTED, bg=C_PANEL).pack(pady=(0, 14))

        # Attention
        f1 = tk.Frame(dlg, bg=C_PANEL, padx=20)
        f1.pack(fill=tk.X, pady=4)
        tk.Label(f1, text="1. Attention (0 = Wandering, 10 = Laser Focused):", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).pack(anchor=tk.W)
        s_att = tk.Scale(f1, from_=0, to=10, orient=tk.HORIZONTAL, bg=C_PANEL, fg=C_CYAN, highlightthickness=0, length=420)
        s_att.set(6)
        s_att.pack()

        # Relaxation
        f2 = tk.Frame(dlg, bg=C_PANEL, padx=20)
        f2.pack(fill=tk.X, pady=4)
        tk.Label(f2, text="2. Relaxation (0 = Tense, 10 = Deeply Relaxed):", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).pack(anchor=tk.W)
        s_rel = tk.Scale(f2, from_=0, to=10, orient=tk.HORIZONTAL, bg=C_PANEL, fg=C_CYAN, highlightthickness=0, length=420)
        s_rel.set(7)
        s_rel.pack()

        # Stress
        f3 = tk.Frame(dlg, bg=C_PANEL, padx=20)
        f3.pack(fill=tk.X, pady=4)
        tk.Label(f3, text="3. Stress (0 = No Stress, 10 = High Stress):", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).pack(anchor=tk.W)
        s_str = tk.Scale(f3, from_=0, to=10, orient=tk.HORIZONTAL, bg=C_PANEL, fg=C_CYAN, highlightthickness=0, length=420)
        s_str.set(2)
        s_str.pack()

        def save_and_close():
            self.subjective_ratings[condition] = {
                "condition": condition,
                "attention": s_att.get(),
                "relaxation": s_rel.get(),
                "stress": s_str.get(),
                "timestamp": datetime.now().isoformat()
            }
            dlg.destroy()

        tk.Button(
            dlg,
            text="Save Ratings & Continue →",
            font=("Segoe UI", 10, "bold"),
            bg="#0072FF",
            fg="white",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            command=save_and_close
        ).pack(pady=16)

        self.root.wait_window(dlg)

    def _finalize_data_deliverables(self):
        if not self.session_dir:
            return

        pid = self.participant["participant_id"]

        # 1. Save Subjective Ratings CSV
        ratings_path = self.session_dir / f"NeuroRaaga_{pid}_subjective_ratings.csv"
        with open(ratings_path, "w", newline="", encoding="utf-8") as rf:
            w = csv.writer(rf)
            w.writerow(["ParticipantID", "Condition", "Attention", "Relaxation", "Stress", "Timestamp"])
            for cond, r in self.subjective_ratings.items():
                w.writerow([pid, cond, r["attention"], r["relaxation"], r["stress"], r["timestamp"]])

        # 2. Save Metadata JSON
        meta = {
            "study_name": "NeuroRaaga Carnatic Ragas EEG Study",
            "participant": self.participant,
            "device": {
                "serial_id": self.device_serial,
                "name": self.device_name,
                "leads": ["A1", "A2", "C3", "C4"],
                "sampling_frequency_hz": 250
            },
            "protocol_target_samples_per_segment": self.total_target_samples,
            "subjective_ratings": self.subjective_ratings,
            "files": {
                "master_csv": f"NeuroRaaga_{pid}_master.csv",
                "slices": self.generated_slices,
                "ratings_csv": f"NeuroRaaga_{pid}_subjective_ratings.csv"
            }
        }
        meta_path = self.session_dir / f"NeuroRaaga_{pid}_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump(meta, mf, indent=2)

    # ------------------------------------------------------------------
    # Tab 5: Data Storage & CSV Export
    # ------------------------------------------------------------------
    def _build_data_tab(self, parent):
        tk.Label(
            parent,
            text="Data Storage & Output Deliverables",
            font=("Segoe UI", 12, "bold"),
            fg=C_CYAN,
            bg=C_PANEL
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Label(
            parent,
            text="Continuous master CSV and per-segment slices are generated automatically for downstream analysis (TISEAN, FFT, stats).",
            font=("Segoe UI", 8),
            fg=C_TEXT_MUTED,
            bg=C_PANEL
        ).pack(anchor=tk.W, pady=(0, 10))

        self.btn_open_folder = tk.Button(
            parent,
            text="Open Recordings Folder in Windows Explorer ↗",
            font=("Segoe UI", 9, "bold"),
            bg="#1E293B",
            fg=C_TEXT,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            command=self._open_recordings_folder
        )
        self.btn_open_folder.pack(fill=tk.X, pady=(0, 10))

        # Files listbox
        tk.Label(parent, text="Session Files Generated:", font=("Segoe UI", 9, "bold"), fg=C_TEXT, bg=C_PANEL).pack(anchor=tk.W)
        self.lst_files = tk.Listbox(parent, bg=C_CARD, fg=C_TEXT, font=("Consolas", 9), relief=tk.FLAT, height=12)
        self.lst_files.pack(fill=tk.BOTH, expand=True, pady=6)

    def _open_recordings_folder(self):
        target = self.session_dir if self.session_dir and self.session_dir.exists() else RECORDINGS_DIR
        try:
            os.startfile(str(target))
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder: {e}")

    def _refresh_data_tab(self):
        self.lst_files.delete(0, tk.END)
        if self.session_dir and self.session_dir.exists():
            for f in sorted(self.session_dir.iterdir()):
                sz_kb = round(f.stat().st_size / 1024, 1)
                self.lst_files.insert(tk.END, f"  {f.name} ({sz_kb} KB)")

    # ------------------------------------------------------------------
    # Right Column: Oscilloscope Canvas & Waveform Display
    # ------------------------------------------------------------------
    def _build_oscilloscope_panel(self, parent):
        top_bar = tk.Frame(parent, bg=C_PANEL, padx=12, pady=8)
        top_bar.pack(fill=tk.X)

        tk.Label(
            top_bar,
            text="Real-Time 4-Channel Waveform Monitor (A1, A2, C3, C4)",
            font=("Segoe UI", 11, "bold"),
            fg=C_TEXT,
            bg=C_PANEL
        ).pack(side=tk.LEFT)

        # Scale Control
        ctrl_box = tk.Frame(top_bar, bg=C_PANEL)
        ctrl_box.pack(side=tk.RIGHT)
        tk.Label(ctrl_box, text="Scale:", font=("Segoe UI", 8), fg=C_TEXT_MUTED, bg=C_PANEL).pack(side=tk.LEFT, padx=(0, 4))
        self.cmb_gain = ttk.Combobox(ctrl_box, values=["±25 µV", "±50 µV", "±100 µV", "±250 µV"], width=8, state="readonly")
        self.cmb_gain.set("±50 µV")
        self.cmb_gain.pack(side=tk.LEFT, padx=(0, 10))
        self.cmb_gain.bind("<<ComboboxSelected>>", self._on_gain_changed)

        # Oscilloscope Canvas
        self.canvas_frame = tk.Frame(parent, bg="#080C14", relief=tk.FLAT)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#080C14", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Bottom Audio Delivery Bar
        audio_bar = tk.Frame(parent, bg=C_PANEL, padx=14, pady=8)
        audio_bar.pack(fill=tk.X, pady=(8, 0))

        self.lbl_player_track = tk.Label(
            audio_bar,
            text="Headphone Audio: Idle (No Stimulus)",
            font=("Segoe UI", 9, "bold"),
            fg=C_GOLD,
            bg=C_PANEL
        )
        self.lbl_player_track.pack(side=tk.LEFT)

    def _on_gain_changed(self, event=None):
        val = self.cmb_gain.get()
        if "25" in val: self.gain_uv = 25.0
        elif "50" in val: self.gain_uv = 50.0
        elif "100" in val: self.gain_uv = 100.0
        elif "250" in val: self.gain_uv = 250.0

    # ------------------------------------------------------------------
    # Real-Time Oscilloscope Rendering (Tkinter Canvas)
    # ------------------------------------------------------------------
    def _canvas_render_loop(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()

        if w > 50 and h > 50:
            self.canvas.delete("all")

            # Condition: If device is NOT connected -> keep display BLANK with label
            if not self.is_connected:
                self.canvas.create_text(
                    w / 2, h / 2,
                    text="● DEVICE NOT CONNECTED — WAVEFORM DISPLAY IS BLANK\nConnect EEG Headphone Pro in Step 2 to view live real-time traces",
                    font=("Segoe UI", 12, "bold"),
                    fill=C_TEXT_DIM,
                    justify=tk.CENTER
                )
            else:
                num_ch = len(TARGET_CHANNELS)
                lane_h = h / num_ch

                for ch_idx, ch in enumerate(TARGET_CHANNELS):
                    y_mid = ch_idx * lane_h + lane_h / 2
                    color = CH_COLORS[ch]

                    # Dashed baseline
                    self.canvas.create_line(0, y_mid, w, y_mid, fill="#1A2436", dash=(4, 4))
                    if ch_idx > 0:
                        self.canvas.create_line(0, ch_idx * lane_h, w, ch_idx * lane_h, fill="#131B2A")

                    # Live Channel Header & Microvolt Readout
                    uv_val = self.latest_uv[ch]
                    freq_val = self.electrode_frequencies[ch]
                    band_str = self.electrode_bands[ch]
                    self.canvas.create_text(
                        14, ch_idx * lane_h + 14,
                        text=f"{ch}  ({uv_val:+.1f} µV)  •  {freq_val:.1f} Hz [{band_str}]",
                        font=("Consolas", 9, "bold"),
                        fill=color,
                        anchor=tk.W
                    )

                    # Draw Trace
                    buf = self.wave_buffers[ch]
                    pts = []
                    step = max(1, len(buf) // w)
                    scaling = (lane_h * 0.40) / self.gain_uv

                    x = 0
                    for i in range(0, len(buf), step):
                        val = buf[i]
                        y = y_mid - (val * scaling)
                        pts.extend([x, y])
                        x += 1
                        if x >= w: break

                    if len(pts) >= 4:
                        self.canvas.create_line(*pts, fill=color, width=1.5, smooth=False)

        self.root.after(33, self._canvas_render_loop)

    # ------------------------------------------------------------------
    # Continuous 250 Hz EEG Acquisition & Auto-Pause Logic
    # ------------------------------------------------------------------
    def _eeg_stream_tick(self):
        if self.is_connected and self.use_simulation:
            # Emit batch of 25 samples (100 ms @ 250 Hz)
            dt = 1.0 / self.sample_rate
            now = time.time()
            for _ in range(25):
                sample_dict = {"timestamp": now}
                for ch in TARGET_CHANNELS:
                    # Simulated 10.2 Hz alpha wave + background neural noise
                    val = (
                        16.0 * math.sin(2 * math.pi * 10.2 * now) +
                        6.0 * math.sin(2 * math.pi * 5.4 * now) +
                        np.random.normal(0, 3.5)
                    )
                    sample_dict[ch] = round(val, 3)
                    self.wave_buffers[ch].append(val)
                    self.latest_uv[ch] = val
                    now += dt

                # Compute frequency
                self.electrode_frequencies["A1"] = 10.2
                self.electrode_frequencies["A2"] = 10.1
                self.electrode_frequencies["C3"] = 10.3
                self.electrode_frequencies["C4"] = 10.2
                for ch in TARGET_CHANNELS:
                    self.electrode_bands[ch] = "Alpha"

                self._log_protocol_sample(sample_dict)

        # Auto-pause / resume watchdog during protocol
        if self.protocol_running:
            all_green = all(self.electrode_states[ch] == "GREEN" for ch in TARGET_CHANNELS)
            if not all_green:
                if not self.protocol_paused:
                    # Trigger AUTO-PAUSE!
                    self.protocol_paused = True
                    self.audio_player.pause()
                    bad = [ch for ch, s in self.electrode_states.items() if s != "GREEN"]
                    self.auto_pause_reason = f"Electrode {', '.join(bad)} disconnected / high resistance! Adjust headset contacts."
                    self.pause_alert_banner.config(text=f"⚠️ AUTO-PAUSED: {self.auto_pause_reason}", fg=C_ROSE)
                    self.lbl_hdr_segment.config(text="STAGE: PAUSED (CHECK LEADS)")
            else:
                if self.protocol_paused:
                    # Auto-Resume!
                    self.protocol_paused = False
                    self.audio_player.resume()
                    self.pause_alert_banner.config(text="")
                    stg = PROTOCOL_STAGES[self.current_stage_idx]
                    self.lbl_hdr_segment.config(text=f"STAGE: {stg['id'].upper()}")

        self.root.after(100, self._eeg_stream_tick)

    def _log_protocol_sample(self, sample_dict):
        if not self.protocol_running or self.protocol_paused:
            return

        stg = PROTOCOL_STAGES[self.current_stage_idx]
        seg_label = stg["id"]
        row = [f"{sample_dict['timestamp']:.6f}", sample_dict["A1"], sample_dict["A2"], sample_dict["C3"], sample_dict["C4"], seg_label]

        # Write to master CSV
        if self.master_writer:
            self.master_writer.writerow(row)

        # Write to slice CSV
        if self.slice_writer:
            self.slice_writer.writerow(row)

        self.valid_stage_samples += 1
        self.total_session_samples += 1

        # Check if valid samples for this stage have completed (guaranteeing exact sample count)
        if self.valid_stage_samples >= self.total_target_samples:
            self._on_stage_samples_completed()

    def _on_stage_samples_completed(self):
        curr_idx = self.current_stage_idx
        stg = PROTOCOL_STAGES[curr_idx]

        # If condition just finished, prompt for subjective rating
        if stg["id"] in ["baseline", "raga1", "raga2"]:
            self._prompt_subjective_rating(stg["id"], stg["name"])

        # Enter next stage
        self._enter_stage(curr_idx + 1)

    # ------------------------------------------------------------------
    # Status Watchdog (Updates clocks and electrode indicators)
    # ------------------------------------------------------------------
    def _status_watchdog(self):
        if self.protocol_running and not self.protocol_paused:
            # Calculate remaining seconds based on valid samples gathered
            rem_samples = max(0, self.total_target_samples - self.valid_stage_samples)
            rem_sec = rem_samples // self.sample_rate
            self.lbl_stage_clock.config(text=f"{rem_sec//60:02d}:{rem_sec%60:02d}")

            total_rem_stages = (len(PROTOCOL_STAGES) - self.current_stage_idx - 1) * self.stage_duration_sec + rem_sec
            self.lbl_total_clock.config(text=f"{total_rem_stages//60:02d}:{total_rem_stages%60:02d}")

        self._update_electrode_card_ui()
        self.root.after(500, self._status_watchdog)

    def _setup_protocols(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if hasattr(self, "_poll_stop") and self._poll_stop:
            self._poll_stop.set()
        if self.audio_player:
            self.audio_player.stop()
        if self.native_device:
            try:
                self.native_device.stop()
                self.native_device.disconnect()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

def main():
    root = tk.Tk()
    app = NeuroRaagaApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
