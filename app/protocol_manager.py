"""
NeuroRaaga Protocol Manager
Enforces the fixed, identical 6-stage experimental sequence:
Baseline (30s) -> Raga 1 (4m) -> Rest 1 (30s) -> Raga 2 (4m) -> Rest 2 (30s) -> Raga 3 (4m)
Continuous EEG recording runs uninterrupted across all segments and gaps.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Any
from app.eeg_engine import eeg_engine
from app.data_exporter import SessionDataLogger
from app.audio_manager import audio_manager

PROTOCOL_STAGES = [
    {
        "segment_id": "baseline",
        "name": "Baseline (Eyes Closed / Rest)",
        "condition": "baseline",
        "default_duration_sec": 30,
        "is_audio": False,
        "audio_slot": None,
        "instructions": "Volunteer rests with eyes closed in a quiet posture. Establishing neural baseline."
    },
    {
        "segment_id": "raga1",
        "name": "Raga 1 (Anandabhairavi)",
        "condition": "raga1",
        "default_duration_sec": 240,
        "is_audio": True,
        "audio_slot": "raga1",
        "instructions": "Playing Raga 1 (Anandabhairavi) through headphones. Volunteer listens with closed or soft eyes."
    },
    {
        "segment_id": "rest1",
        "name": "Silence / Post-Raga 1 Rest",
        "condition": "rest1",
        "default_duration_sec": 30,
        "is_audio": False,
        "audio_slot": None,
        "instructions": "Silent recovery period following Raga 1. Collect subjective ratings for Raga 1."
    },
    {
        "segment_id": "raga2",
        "name": "Raga 2 (Shubhapantuvarali)",
        "condition": "raga2",
        "default_duration_sec": 240,
        "is_audio": True,
        "audio_slot": "raga2",
        "instructions": "Playing Raga 2 (Shubhapantuvarali) through headphones. Volunteer listens attentively."
    },
    {
        "segment_id": "rest2",
        "name": "Silence / Post-Raga 2 Rest",
        "condition": "rest2",
        "default_duration_sec": 30,
        "is_audio": False,
        "audio_slot": None,
        "instructions": "Silent recovery period following Raga 2. Collect subjective ratings for Raga 2."
    },
    {
        "segment_id": "raga3",
        "name": "Raga 3 (Mohanam)",
        "condition": "raga3",
        "default_duration_sec": 240,
        "is_audio": True,
        "audio_slot": "raga3",
        "instructions": "Playing Raga 3 (Mohanam) through headphones. Uplifting melodic sequence."
    }
]

class ProtocolManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.stage_index = -1
        self.is_running = False
        self.is_paused = False
        self.is_completed = False
        
        # Timing configuration
        self.duration_per_segment_sec = 120.0  # Base duration for baseline and rest stages.
        self.stage_start_time: Optional[float] = None
        self.stage_elapsed_sec: float = 0.0
        self.total_elapsed_sec: float = 0.0
        
        # State tracking
        self.participant_info: Dict[str, Any] = {}
        self.data_logger: Optional[SessionDataLogger] = None
        self.final_metadata: Optional[Dict[str, Any]] = None
        
        # Listeners for protocol events (WebSocket broadcast)
        self.event_listeners: List[Callable[[Dict[str, Any]], None]] = []
        
        # Worker thread
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def set_duration_mode(self, duration_sec: float):
        """Sets the base duration; raga stages last twice as long."""
        with self.lock:
            if not self.is_running:
                self.duration_per_segment_sec = float(duration_sec)
                print(f"[ProtocolManager] Segment duration set to {self.duration_per_segment_sec} seconds")

    def register_event_listener(self, listener: Callable[[Dict[str, Any]], None]):
        if listener not in self.event_listeners:
            self.event_listeners.append(listener)

    def _broadcast_event(self, event_type: str, data: Dict[str, Any]):
        msg = {
            "type": event_type,
            "timestamp": time.time(),
            "data": data
        }
        for l in list(self.event_listeners):
            try:
                l(msg)
            except Exception as e:
                print(f"[ProtocolManager] Event listener error: {e}")

    # ---------------- Session Lifecycle ----------------
    def start_protocol(self, participant_info: Dict[str, Any]) -> bool:
        with self.lock:
            if self.is_running:
                return False
                
            self.participant_info = participant_info
            pid = participant_info.get("participant_id", f"NR-P{int(time.time())%1000:03d}")
            self.participant_info["participant_id"] = pid
            self.participant_info["enrollment_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Ensure EEG engine is connected and recording
            if not eeg_engine.is_connected:
                # Default connect to simulator or available device
                eeg_engine.connect_device("SIM-NEURORAAGA-250", simulated=True)
                
            dev_info = {
                "serial_id": eeg_engine.device_serial,
                "name": eeg_engine.device_name,
                "type": eeg_engine.device_type_name
            }
            
            # Create session data logger
            self.data_logger = SessionDataLogger(
                participant_id=pid,
                participant_info=self.participant_info,
                device_info=dev_info,
                calibration_info=eeg_engine.calibration_results or {}
            )
            
            # Register data logger as sample listener
            eeg_engine.add_sample_listener(self.data_logger.log_samples)
            
            # Start streaming if not already running
            eeg_engine.start_streaming()
            
            self.stage_index = 0
            self.is_running = True
            self.is_paused = False
            self.is_completed = False
            self.total_elapsed_sec = 0.0
            self.final_metadata = None
            
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self._protocol_loop, daemon=True)
            self._worker_thread.start()
            
            self._broadcast_event("protocol_started", {
                "participant_id": pid,
                "participant_name": participant_info.get("name"),
                "total_stages": len(PROTOCOL_STAGES),
                "duration_per_segment": self.duration_per_segment_sec,
                "total_duration": self._total_duration()
            })
            return True

    def _protocol_loop(self):
        while self.is_running and not self._stop_event.is_set():
            if self.stage_index >= len(PROTOCOL_STAGES):
                # Protocol finished!
                self._finish_protocol()
                break
                
            stage = PROTOCOL_STAGES[self.stage_index]
            self.stage_start_time = time.time()
            self.stage_elapsed_sec = 0.0
            
            # Setup audio info if audio stage
            audio_info = None
            stage_duration_sec = self._stage_duration(stage)
            if stage["is_audio"] and stage["audio_slot"]:
                audio_info = audio_manager.get_slot_info(stage["audio_slot"])
                
            # Tell data logger to start new segment slice
            if self.data_logger:
                self.data_logger.start_segment(stage["segment_id"], audio_info)
                
            # Broadcast stage enter event (including audio command)
            self._broadcast_event("stage_changed", {
                "stage_index": self.stage_index,
                "segment_id": stage["segment_id"],
                "segment_name": stage["name"],
                "condition": stage["condition"],
                "duration_sec": stage_duration_sec,
                "is_audio": stage["is_audio"],
                "audio_info": audio_info,
                "instructions": stage["instructions"],
                "rating_prompt": self._get_pending_rating_prompt()
            })
            
            # Progress loop for current stage
            while self.stage_elapsed_sec < stage_duration_sec and not self._stop_event.is_set():
                time.sleep(0.5)
                if not self.is_paused:
                    self.stage_elapsed_sec = time.time() - self.stage_start_time
                    self.total_elapsed_sec += 0.5
                    
                    self._broadcast_event("protocol_tick", {
                        "stage_index": self.stage_index,
                        "segment_id": stage["segment_id"],
                        "stage_elapsed": min(self.stage_elapsed_sec, stage_duration_sec),
                        "stage_remaining": max(0.0, stage_duration_sec - self.stage_elapsed_sec),
                        "stage_duration": stage_duration_sec,
                        "total_elapsed": self.total_elapsed_sec,
                        "total_duration": self._total_duration()
                    })
                    
            if self._stop_event.is_set():
                break
                
            # Stage completed! Stop audio if was playing
            if stage["is_audio"]:
                self._broadcast_event("audio_command", {"action": "stop"})
                
            # Trigger subjective rating popup prompt if condition just ended
            # (Baseline ended, or Ragas ended)
            self._broadcast_event("request_subjective_rating", {
                "condition": stage["condition"],
                "segment": stage["segment_id"],
                "title": f"Subjective Ratings: {stage['name']}"
            })
            
            self.stage_index += 1

    def _get_pending_rating_prompt(self) -> Optional[str]:
        # Return what rating is expected during this rest/gap
        if self.stage_index == 2:  # rest1 -> rate raga1
            return "raga1"
        elif self.stage_index == 4: # rest2 -> rate raga2
            return "raga2"
        return None

    def _stage_duration(self, stage: Dict[str, Any]) -> float:
        # 120 seconds selects the standard schedule: 30-second rests and 4-minute ragas.
        if self.duration_per_segment_sec == 120.0:
            return float(stage['default_duration_sec'])
        return self.duration_per_segment_sec * (2 if stage['is_audio'] else 1)

    def _total_duration(self) -> float:
        return sum(self._stage_duration(stage) for stage in PROTOCOL_STAGES)

    def _finish_protocol(self):
        with self.lock:
            self.is_running = False
            self.is_completed = True
            
            # Broadcast audio stop
            self._broadcast_event("audio_command", {"action": "stop"})
            
            # Request final rating for Raga 3
            self._broadcast_event("request_subjective_rating", {
                "condition": "raga3",
                "segment": "raga3",
                "title": "Subjective Ratings: Raga 3 (Mohanam)"
            })
            
            # Remove data logger from EEG engine listeners
            if self.data_logger:
                eeg_engine.remove_sample_listener(self.data_logger.log_samples)
                self.final_metadata = self.data_logger.finalize_session()
                
            self._broadcast_event("protocol_completed", {
                "participant_id": self.participant_info.get("participant_id"),
                "total_duration": self.total_elapsed_sec,
                "metadata": self.final_metadata,
                "summary": self.data_logger.get_summary() if self.data_logger else {}
            })
            print(f"[ProtocolManager] Protocol execution completed successfully!")

    def submit_rating(
        self,
        condition: str,
        segment: str,
        attention: float,
        relaxation: float,
        stress: float,
        notes: str = ""
    ) -> bool:
        with self.lock:
            if self.data_logger:
                self.data_logger.record_subjective_rating(
                    condition=condition,
                    segment=segment,
                    attention=attention,
                    relaxation=relaxation,
                    stress=stress,
                    notes=notes
                )
                self._broadcast_event("rating_recorded", {
                    "condition": condition,
                    "segment": segment,
                    "attention": attention,
                    "relaxation": relaxation,
                    "stress": stress
                })
                return True
            return False

    def abort_protocol(self):
        with self.lock:
            if not self.is_running:
                return
            self._stop_event.set()
            self.is_running = False
            self.is_paused = False
            
            if self.data_logger:
                eeg_engine.remove_sample_listener(self.data_logger.log_samples)
                self.final_metadata = self.data_logger.finalize_session()
                
            self._broadcast_event("protocol_aborted", {
                "stage_index": self.stage_index,
                "total_elapsed": self.total_elapsed_sec
            })

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            current_stage = PROTOCOL_STAGES[self.stage_index] if 0 <= self.stage_index < len(PROTOCOL_STAGES) else None
            return {
                "is_running": self.is_running,
                "is_paused": self.is_paused,
                "is_completed": self.is_completed,
                "stage_index": self.stage_index,
                "total_stages": len(PROTOCOL_STAGES),
                "current_stage": current_stage,
                "stage_elapsed_sec": round(self.stage_elapsed_sec, 1),
                "duration_per_segment_sec": self.duration_per_segment_sec,
                "total_elapsed_sec": round(self.total_elapsed_sec, 1),
                "total_expected_duration_sec": self._total_duration(),
                "participant": self.participant_info,
                "data_logger": self.data_logger.get_summary() if self.data_logger else None,
                "stages": PROTOCOL_STAGES
            }

protocol_manager = ProtocolManager()
