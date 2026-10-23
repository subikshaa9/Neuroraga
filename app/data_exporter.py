"""
NeuroRaaga Data Exporter
Manages continuous 250 Hz CSV data streaming, per-segment CSV slicing,
metadata generation, and subjective rating logging.
"""
from __future__ import annotations

import csv
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

RECORDINGS_DIR = Path(__file__).resolve().parent / "data" / "recordings"

class SessionDataLogger:
    def __init__(
        self,
        participant_id: str,
        participant_info: Dict[str, Any],
        device_info: Dict[str, Any],
        calibration_info: Optional[Dict[str, Any]] = None
    ):
        self.lock = threading.RLock()
        self.participant_id = participant_id
        self.participant_info = participant_info
        self.device_info = device_info
        self.calibration_info = calibration_info or {}
        
        self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = RECORDINGS_DIR / f"{self.participant_id}_{self.session_timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Master CSV
        self.master_csv_name = f"NeuroRaaga_{self.participant_id}_master.csv"
        self.master_csv_path = self.session_dir / self.master_csv_name
        self.master_file = open(self.master_csv_path, "w", newline="", encoding="utf-8")
        self.master_writer = csv.writer(self.master_file)
        self.master_writer.writerow(["Timestamp", "O1_raw", "O2_raw", "T3_raw", "T4_raw", "Segment"])
        self.master_file.flush()
        
        # Segment tracking
        self.current_segment: str = "init"
        self.current_segment_writer = None
        self.current_segment_file = None
        self.current_segment_start_time: Optional[float] = None
        self.current_segment_sample_count: int = 0
        
        self.segments_metadata: Dict[str, Any] = {}
        self.generated_slices: List[str] = []
        
        # Subjective ratings
        self.subjective_ratings: Dict[str, Dict[str, Any]] = {}
        self.ratings_csv_name = f"NeuroRaaga_{self.participant_id}_subjective_ratings.csv"
        self.ratings_csv_path = self.session_dir / self.ratings_csv_name
        with open(self.ratings_csv_path, "w", newline="", encoding="utf-8") as rf:
            writer = csv.writer(rf)
            writer.writerow(["ParticipantID", "Condition", "Segment", "Attention", "Relaxation", "Stress", "SubmittedAt"])
            
        self.total_samples_logged = 0
        self.start_epoch = time.time()
        self.is_active = True

    def start_segment(self, segment_name: str, audio_track_info: Optional[Dict[str, Any]] = None):
        with self.lock:
            # Close previous segment file if open
            self.end_segment()
            
            self.current_segment = segment_name
            self.current_segment_start_time = time.time()
            self.current_segment_sample_count = 0
            
            # Open slice CSV file
            slice_filename = f"NeuroRaaga_{self.participant_id}_segment_{segment_name}.csv"
            slice_path = self.session_dir / slice_filename
            self.current_segment_file = open(slice_path, "w", newline="", encoding="utf-8")
            self.current_segment_writer = csv.writer(self.current_segment_file)
            self.current_segment_writer.writerow(["Timestamp", "O1_raw", "O2_raw", "T3_raw", "T4_raw", "Segment"])
            self.current_segment_file.flush()
            
            self.generated_slices.append(slice_filename)
            
            self.segments_metadata[segment_name] = {
                "segment": segment_name,
                "slice_filename": slice_filename,
                "start_time_iso": datetime.now().isoformat(),
                "start_timestamp_epoch": self.current_segment_start_time,
                "audio_track": audio_track_info,
                "sample_count": 0
            }
            print(f"[SessionDataLogger] Started segment: {segment_name}")

    def end_segment(self):
        with self.lock:
            if self.current_segment_file and not self.current_segment_file.closed:
                self.current_segment_file.flush()
                self.current_segment_file.close()
                
            if self.current_segment in self.segments_metadata:
                end_time = time.time()
                dur = end_time - (self.current_segment_start_time or end_time)
                self.segments_metadata[self.current_segment].update({
                    "end_time_iso": datetime.now().isoformat(),
                    "end_timestamp_epoch": end_time,
                    "duration_sec": round(dur, 2),
                    "sample_count": self.current_segment_sample_count
                })
                print(f"[SessionDataLogger] Ended segment: {self.current_segment} ({self.current_segment_sample_count} samples)")

    def log_samples(self, samples_batch: List[Dict[str, Any]]):
        with self.lock:
            if not self.is_active:
                return
            
            seg = self.current_segment
            for s in samples_batch:
                ts = s["timestamp"]
                o1 = s.get("O1", 0.0)
                o2 = s.get("O2", 0.0)
                t3 = s.get("T3", 0.0)
                t4 = s.get("T4", 0.0)
                
                row = [f"{ts:.6f}", o1, o2, t3, t4, seg]
                self.master_writer.writerow(row)
                
                if self.current_segment_writer:
                    self.current_segment_writer.writerow(row)
                    self.current_segment_sample_count += 1
                    
                self.total_samples_logged += 1
                
            self.master_file.flush()
            if self.current_segment_file and not self.current_segment_file.closed:
                self.current_segment_file.flush()

    def record_subjective_rating(
        self,
        condition: str,
        segment: str,
        attention: float,
        relaxation: float,
        stress: float,
        notes: str = ""
    ):
        with self.lock:
            submitted_at = datetime.now().isoformat()
            self.subjective_ratings[condition] = {
                "condition": condition,
                "segment": segment,
                "attention": float(attention),
                "relaxation": float(relaxation),
                "stress": float(stress),
                "notes": notes,
                "submitted_at": submitted_at
            }
            
            # Append to ratings CSV
            with open(self.ratings_csv_path, "a", newline="", encoding="utf-8") as rf:
                writer = csv.writer(rf)
                writer.writerow([
                    self.participant_id,
                    condition,
                    segment,
                    attention,
                    relaxation,
                    stress,
                    submitted_at
                ])
            print(f"[SessionDataLogger] Recorded rating for {condition}: Att={attention}, Rel={relaxation}, Str={stress}")

    def finalize_session(self) -> Dict[str, Any]:
        with self.lock:
            self.end_segment()
            self.is_active = False
            
            if self.master_file and not self.master_file.closed:
                self.master_file.flush()
                self.master_file.close()
                
            end_epoch = time.time()
            total_duration = end_epoch - self.start_epoch
            
            metadata = {
                "study_name": "NeuroRaaga Carnatic Ragas EEG Study",
                "participant": {
                    "participant_id": self.participant_id,
                    "name": self.participant_info.get("name", "Anonymous"),
                    "age": self.participant_info.get("age"),
                    "sex": self.participant_info.get("sex"),
                    "sleep_quality_previous_night": self.participant_info.get("sleep_quality"),
                    "caffeine_intake_test_day": self.participant_info.get("caffeine_intake"),
                    "enrollment_timestamp": self.participant_info.get("enrollment_timestamp")
                },
                "device": {
                    "serial_id": self.device_info.get("serial_id"),
                    "name": self.device_info.get("name"),
                    "type": self.device_info.get("type"),
                    "sampling_frequency_hz": 250.0,
                    "electrode_montage": ["O1", "O2", "T3", "T4"],
                    "reference": "Frontal reference electrodes",
                    "resistance_values": "Capsule SDK ohms converted to kOhm; stored impedance is capped at 1000 kOhm for status checks, while the UI shows finite SDK readings and OPEN for infinity.",
                    "csv_signal_values": "Unfiltered SDK raw values in native units; display filtering is not applied to CSV.",
                    "display_filter": "0.5-40 Hz bandpass with 50 Hz notch"
                },
                "calibration_quality": self.calibration_info,
                "protocol": {
                    "total_duration_sec": round(total_duration, 2),
                    "total_samples_collected": self.total_samples_logged,
                    "expected_sample_rate": 250.0,
                    "actual_sample_rate": round(self.total_samples_logged / max(total_duration, 1.0), 2),
                    "segments": self.segments_metadata
                },
                "subjective_ratings": self.subjective_ratings,
                "files": {
                    "session_folder": str(self.session_dir),
                    "master_csv": self.master_csv_name,
                    "segment_slices": self.generated_slices,
                    "ratings_csv": self.ratings_csv_name,
                    "metadata_json": f"NeuroRaaga_{self.participant_id}_metadata.json"
                }
            }
            
            metadata_path = self.session_dir / f"NeuroRaaga_{self.participant_id}_metadata.json"
            with open(metadata_path, "w", encoding="utf-8") as mf:
                json.dump(metadata, mf, indent=2)
                
            print(f"[SessionDataLogger] Session finalized for {self.participant_id}. Total samples: {self.total_samples_logged}")
            return metadata

    def get_summary(self) -> Dict[str, Any]:
        return {
            "participant_id": self.participant_id,
            "session_dir": str(self.session_dir),
            "session_folder_name": self.session_dir.name,
            "master_csv": self.master_csv_name,
            "segment_slices": self.generated_slices,
            "ratings_csv": self.ratings_csv_name,
            "total_samples": self.total_samples_logged,
            "is_active": self.is_active,
            "current_segment": self.current_segment,
            "subjective_ratings": self.subjective_ratings
        }
