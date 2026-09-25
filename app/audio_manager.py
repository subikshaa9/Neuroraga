"""
NeuroRaaga Audio Manager
Manages the Carnatic Raga library, slot mapping (Raga 1, 2, 3), and file uploads.
"""
import os
import json
import shutil
import wave
from pathlib import Path
from typing import Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "audio"
UPLOAD_DIR = AUDIO_DIR / "uploads"
CONFIG_FILE = AUDIO_DIR / "slots_config.json"

DEFAULT_SLOTS = {
    "raga1": {
        "slot_id": "raga1",
        "label": "Raga 1",
        "default_title": "Anandabhairavi",
        "current_title": "Anandabhairavi",
        "filename": "anandabhairavi.wav",
        "filepath": str(AUDIO_DIR / "anandabhairavi.wav"),
        "url": "/api/audio/file/anandabhairavi.wav",
        "duration_sec": 125.0,
        "is_custom": False,
        "mood_description": "Calming, devotional, soothing vakra phrases (Natabhairavi janya)"
    },
    "raga2": {
        "slot_id": "raga2",
        "label": "Raga 2",
        "default_title": "Shubhapantuvarali",
        "current_title": "Shubhapantuvarali",
        "filename": "shubhapantuvarali.wav",
        "filepath": str(AUDIO_DIR / "shubhapantuvarali.wav"),
        "url": "/api/audio/file/shubhapantuvarali.wav",
        "duration_sec": 125.0,
        "is_custom": False,
        "mood_description": "Contemplative, profound pathos, introspective (45th Melakarta)"
    },
    "raga3": {
        "slot_id": "raga3",
        "label": "Raga 3",
        "default_title": "Mohanam",
        "current_title": "Mohanam",
        "filename": "mohanam.wav",
        "filepath": str(AUDIO_DIR / "mohanam.wav"),
        "url": "/api/audio/file/mohanam.wav",
        "duration_sec": 125.0,
        "is_custom": False,
        "mood_description": "Joyous, uplifting, bright pentatonic melody (Harikambhoji/Kalyani janya)"
    }
}

class AudioManager:
    def __init__(self):
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.slots = self._load_slots()

    def _load_slots(self) -> Dict[str, Any]:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    slots = dict(DEFAULT_SLOTS)
                    for k, v in saved.items():
                        if k in slots:
                            slots[k].update(v)
                    return slots
            except Exception:
                pass
        return dict(DEFAULT_SLOTS)

    def _save_slots(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.slots, f, indent=2)
        except Exception as e:
            print(f"Error saving audio slots config: {e}")

    def get_duration(self, filepath: str) -> float:
        try:
            if filepath.lower().endswith(".wav"):
                with wave.open(filepath, 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    if rate > 0:
                        return round(frames / float(rate), 1)
        except Exception:
            pass
        return 120.0

    def get_slots(self) -> Dict[str, Any]:
        return self.slots

    def get_slot_info(self, slot_id: str) -> Optional[Dict[str, Any]]:
        return self.slots.get(slot_id)

    def map_file_to_slot(self, slot_id: str, filename: str, title: str, is_upload: bool = True) -> Dict[str, Any]:
        if slot_id not in self.slots:
            raise ValueError(f"Invalid slot ID: {slot_id}")
        
        folder = UPLOAD_DIR if is_upload else AUDIO_DIR
        filepath = folder / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Audio file not found: {filename}")
            
        dur = self.get_duration(str(filepath))
        url_path = f"/api/audio/file/uploads/{filename}" if is_upload else f"/api/audio/file/{filename}"
        
        self.slots[slot_id].update({
            "current_title": title,
            "filename": filename,
            "filepath": str(filepath),
            "url": url_path,
            "duration_sec": dur,
            "is_custom": is_upload
        })
        self._save_slots()
        return self.slots[slot_id]

    def reset_slot(self, slot_id: str) -> Dict[str, Any]:
        if slot_id in DEFAULT_SLOTS:
            self.slots[slot_id] = dict(DEFAULT_SLOTS[slot_id])
            self._save_slots()
            return self.slots[slot_id]
        raise ValueError(f"Invalid slot ID: {slot_id}")

    def save_upload(self, slot_id: str, file_obj, filename: str, display_title: str) -> Dict[str, Any]:
        safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
        dest_path = UPLOAD_DIR / safe_filename
        
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file_obj, buffer)
            
        return self.map_file_to_slot(slot_id, safe_filename, display_title, is_upload=True)

    def list_available_files(self):
        files = []
        for p in AUDIO_DIR.glob("*.wav"):
            files.append({"filename": p.name, "type": "default", "path": str(p)})
        for p in UPLOAD_DIR.iterdir():
            if p.suffix.lower() in [".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"]:
                files.append({"filename": p.name, "type": "upload", "path": str(p)})
        return files

audio_manager = AudioManager()
