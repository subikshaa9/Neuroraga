# NeuroRaaga — Carnatic Ragas Acute EEG Acquisition Platform

NeuroRaaga is a data acquisition dashboard designed for a scientific study investigating the acute neurophysiological effects of three classical Carnatic ragas (**Anandabhairavi**, **Shubhapantuvarali**, and **Mohanam**) on 4-channel EEG (**A1, A2, C3, C4**).

The system outputs raw, segment-labeled CSV datasets ready for nonlinear and spectral analysis pipelines (such as TISEAN, FFT power spectral density, Lyapunov exponents, and statistical modeling).

---

## Quick Start: Launch the Native Desktop GUI

To launch the **Native Desktop GUI**:
```bash
python run_neuroraaga_gui.py
```
*(No browser required. Runs directly as a native Windows desktop application with Tkinter).*

---

## Key Experimental Rules & Features

1. **Participant Enrollment & Strict Eligibility Screening**
   - **Age Restriction**: Strictly **18–30 years** (outside this range is blocked and flagged as "Not Eligible").
   - **Medical / Neurological Disqualifiers**:
     - Previous head injuries (Yes &rarr; Disqualified)
     - History of brain or neurological disorders (Yes &rarr; Disqualified)
     - Taking brain or psychoactive medications (Yes &rarr; Disqualified)
   - Candidates with any positive screening condition are **blocked from proceeding** to data acquisition.
   - Captures volunteer profile: Name, Age, Sex, Sleep quality, and Caffeine intake.

2. **EEG Device Connection & 3-Stage Electrode Check**
   - **Headphone EEG Configuration**: 4 Active Leads (**A1, A2, C3, C4**), 2 Grounds, and 1 Reference (**Cz**).
   - **Blank Waveform When Disconnected**: If the device is not connected, the oscilloscope remains completely blank. Waveforms only stream live once the device is connected.
   - **3-Stage Electrode Connection States**:
     - 🔴 **RED**: Not Connected (Impedance > 100 kΩ or detached lead)
     - 🟠 **ORANGE**: Partially Connected (Impedance 50–100 kΩ, suboptimal signal)
     - 🟢 **GREEN**: Fully Connected (Impedance < 50 kΩ, stable EEG signal in valid frequency range)
   - **Dominant Frequency Readouts**: Displays live frequency in Hz (e.g. `10.2 Hz [Alpha]`) for each channel on the dashboard during collection.
   - **Signal Gating**: **All 4 electrodes must be GREEN** to start recording. If not, the system warns: *"Connect electrodes correctly: [Channels] not ready"*.

3. **Auto-Pause & Auto-Resume with Guaranteed Zero Duration Variation**
   - In the middle of data collection, if any electrode slips from GREEN to RED or ORANGE:
     - The system **automatically pauses** the countdown timer immediately.
     - Headphone audio playback is **automatically paused**.
     - An alert is displayed: *"⚠️ AUTO-PAUSED: Electrode [A1/A2/C3/C4] disconnected / high resistance! Adjust headset contacts."*
     - Once all 4 electrodes return to 🟢 **GREEN**, the system **automatically resumes** audio and data logging!
     - **Guaranteed Identical Sample Count**: Only valid data recorded while all 4 electrodes are GREEN counts toward the segment duration. Every segment slice contains the **exact same valid duration** (120 seconds = exactly 30,000 samples @ 250 Hz), with **zero variation** across participants!

3. **Real-Time 4-Channel Waveform Display**
   - Continuous, scrolling HTML5 Canvas oscilloscope showing live traces for all 4 electrodes (**A1, A2, C3, C4**) simultaneously.
   - Live microvolt readouts, amplitude scale adjustment (±25 µV, ±50 µV, ±100 µV, ±250 µV, Auto), time window selector (5s, 10s, 15s), and freeze inspection.
   - Uninterrupted recording and visualization throughout all protocol stages (baseline, ragas, and silent recovery intervals alike).

4. **Music Library & Upload Option**
   - Dedicated dashboard section with slots for **Raga 1**, **Raga 2**, and **Raga 3**.
   - Pre-loaded with high-fidelity 44.1 kHz stereo Carnatic audio recordings for Anandabhairavi, Shubhapantuvarali, and Mohanam.
   - Direct drag-and-drop / upload file input to load or replace any slot with custom audio files (`.wav`, `.mp3`, `.ogg`, `.flac`, `.m4a`) without touching code.
   - Built-in operator preview controls with headphone channel routing.

5. **Fixed Experimental Protocol (Strict 12-Minute Sequence)**
   - **Baseline (Eyes closed / rest)**: 2 minutes (120 s)
   - **Raga 1 (Anandabhairavi)**: 2 minutes (120 s) — audio delivered through headphones
   - **Silence / Rest 1**: 2 minutes (120 s) — silent neural recovery
   - **Raga 2 (Shubhapantuvarali)**: 2 minutes (120 s) — audio delivered through headphones
   - **Silence / Rest 2**: 2 minutes (120 s) — silent neural recovery
   - **Raga 3 (Mohanam)**: 2 minutes (120 s) — audio delivered through headphones
   - *Total duration*: 12 minutes (720 seconds) continuous 250 Hz EEG recording.
   - *Accelerated / Demo Mode option*: Accessible via timing mode dropdown (e.g. 15s per segment) for swift dry-run verification.

6. **Post-Session Subjective Ratings**
   - After each condition (Baseline + each Raga), a non-intrusive rating interface captures:
     - **Attention** (0 to 10 scale)
     - **Relaxation** (0 to 10 scale)
     - **Stress** (0 to 10 scale)
     - Optional qualitative notes/sensations.
   - Recorded without halting or interrupting the continuous EEG data stream.

7. **Data Storage & Deliverables**
   - **Master Continuous CSV**: `NeuroRaaga_{ParticipantID}_master.csv`
     - Columns: `Timestamp, A1, A2, C3, C4, Segment`
     - Microsecond-precision epoch timestamp, microvolt electrode potentials, and synchronized segment label (`baseline`, `raga1`, `rest1`, `raga2`, `rest2`, `raga3`).
   - **Per-Segment CSV Slices**:
     - `NeuroRaaga_{ParticipantID}_segment_baseline.csv`
     - `NeuroRaaga_{ParticipantID}_segment_raga1.csv`
     - `NeuroRaaga_{ParticipantID}_segment_rest1.csv`
     - `NeuroRaaga_{ParticipantID}_segment_raga2.csv`
     - `NeuroRaaga_{ParticipantID}_segment_rest2.csv`
     - `NeuroRaaga_{ParticipantID}_segment_raga3.csv`
   - **Subjective Ratings CSV**:
     - `NeuroRaaga_{ParticipantID}_subjective_ratings.csv`
     - Columns: `ParticipantID, Condition, Segment, Attention, Relaxation, Stress, SubmittedAt`
   - **Session Metadata JSON**:
     - `NeuroRaaga_{ParticipantID}_metadata.json`
     - Contains volunteer profile, device serial ID, sampling frequency (250 Hz), initial calibration impedance, exact start/end timestamps and sample counts per segment, and file manifest.

---

## Directory Structure

```text
Neuroraga/
├── app/
│   ├── audio/                     # Preloaded Carnatic raga audio files
│   │   ├── anandabhairavi.wav
│   │   ├── shubhapantuvarali.wav
│   │   ├── mohanam.wav
│   │   └── uploads/               # Operator-uploaded custom raga tracks
│   ├── data/
│   │   └── recordings/            # Output folder for volunteer datasets
│   ├── static/                    # Frontend assets
│   │   ├── css/
│   │   │   └── style.css          # Glassmorphic dark theme & layout
│   │   ├── js/
│   │   │   ├── app.js             # State management & event handling
│   │   │   ├── audio_player.js    # Web Audio headphone playback engine
│   │   │   └── eeg_canvas.js      # 4-channel 250 Hz Canvas oscilloscope
│   │   └── index.html             # Dashboard single-page application
│   ├── audio_manager.py           # Slot management and multipart file upload
│   ├── data_exporter.py           # Continuous CSV logger and segment slicer
│   ├── eeg_engine.py              # Capsule SDK connector & 250 Hz EEG generator
│   ├── protocol_manager.py        # 12-minute 6-stage protocol coordinator
│   └── main.py                    # FastAPI server & WebSocket endpoints
├── Capsule_2.0.72/                 # Native Capsule SDK
├── create_default_audio.py        # Audio synthesis script for default tracks
├── run_neuroraaga.py              # Single-click launcher
└── README.md                      # This documentation
```

---

## Quick Start Guide

### 1. Launch the Application
Run the launcher from terminal or command prompt:
```bash
python run_neuroraaga.py
```
This automatically starts the local backend server on `http://localhost:8000` and opens your default browser.

### 2. Experimental Workflow (Step-by-Step)

1. **Step 1: Participant Enrollment**
   - Enter volunteer details: Name, Age, Sex, Sleep quality, and Caffeine intake.
   - Click **Enroll Participant & Proceed to Device Setup**.

2. **Step 2: Device Connection & Calibration**
   - Click **Scan Devices** to find nearby Capsule EEG hardware or choose the **NeuroRaaga Synthetic EEG Generator**.
   - Click **Connect Device** (confirm the Serial ID matches the physical unit).
   - Click **Run Signal Quality & Calibration Check**: Confirm all 4 electrodes (**A1, A2, C3, C4**) have low impedance (< 50 kΩ) and good baseline stability.

3. **Step 3: Music Library / Raga Mapping**
   - Verify the three raga slots:
     - **Slot 1 (Raga 1)**: Anandabhairavi
     - **Slot 2 (Raga 2)**: Shubhapantuvarali
     - **Slot 3 (Raga 3)**: Mohanam
   - Click **Preview** to test headphone audio level.
   - If desired, click **Upload / Replace** to load any custom high-resolution audio recording.

4. **Step 4: Start Protocol**
   - Ensure the volunteer is wearing the EEG headphones comfortably with eyes closed.
   - Click **Start Continuous 12-Minute Protocol**.
   - The system transitions smoothly through all 6 segments while live waveforms scroll across the oscilloscope.
   - Provide subjective ratings when prompted at the end of conditions.

5. **Step 5: Data Storage & CSV Export**
   - When the session finishes, the dashboard automatically generates the Master CSV, per-segment slice CSVs, Subjective Ratings CSV, and Metadata JSON.
   - Click **Download** for individual files or click **Open in Windows Explorer** to access the session directory directly.
