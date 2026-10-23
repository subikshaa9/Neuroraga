"""
NeuroRaaga Main Application Server
FastAPI backend with WebSockets for real-time 250 Hz EEG streaming,
REST endpoints for participant enrollment, device calibration, audio mapping, and CSV downloads.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.eeg_engine import eeg_engine, TARGET_CHANNELS
from app.audio_manager import audio_manager, AUDIO_DIR, UPLOAD_DIR
from app.protocol_manager import protocol_manager, PROTOCOL_STAGES
from app.data_exporter import RECORDINGS_DIR
from app import signal_processing

app = FastAPI(title="NeuroRaaga EEG Data Acquisition Dashboard", version="1.0.0")
APP_BUILD_ID = "o1-o2-t3-t4-impedance-20261019-1"

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def prevent_stale_frontend(request: Any, call_next):
    response = await call_next(request)
    path = request.url.path.lower()
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Connected WebSocket clients
active_websockets: list[WebSocket] = []
ws_lock = asyncio.Lock()

# Helper queue to bridge threaded EEG engine & protocol manager with asyncio WebSockets
async_event_loop: Optional[asyncio.AbstractEventLoop] = None

def broadcast_to_websockets(msg: Dict[str, Any]):
    """Thread-safe dispatch from EEG/Protocol threads into asyncio event loop."""
    if async_event_loop and async_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(_send_ws_message(msg), async_event_loop)

async def _send_ws_message(msg: Dict[str, Any]):
    global active_websockets
    if not active_websockets:
        return
    dead = []
    for ws in list(active_websockets):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in active_websockets:
            active_websockets.remove(ws)

# Register callbacks
def on_eeg_samples(batch):
    broadcast_to_websockets({
        "type": "eeg_data",
        "samples": batch,
        "resistances": eeg_engine.resistances,
                "resistance_readings": eeg_engine.get_resistance_readings()
    })

def on_protocol_event(event):
    broadcast_to_websockets(event)

eeg_engine.add_sample_listener(on_eeg_samples)
protocol_manager.register_event_listener(on_protocol_event)

@app.on_event("startup")
async def startup_event():
    global async_event_loop
    async_event_loop = asyncio.get_running_loop()
    print(
        f"[NeuroRaaga] Backend initialized. Event loop captured. "
        f"Build={APP_BUILD_ID}; app={Path(__file__).resolve()}; static={STATIC_DIR.resolve()}"
    )

# ----------------- WebSocket -----------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        # Send initial state snapshot immediately
        recent = eeg_engine.get_latest_buffer()
        cal = eeg_engine.calibration_results
        await websocket.send_json({
            "type": "snapshot",
            "device": {
                "connected": eeg_engine.is_connected,
                "serial": eeg_engine.device_serial,
                "name": eeg_engine.device_name,
                "battery": eeg_engine.battery_percent,
                "streaming": eeg_engine.is_streaming,
                "resistances": eeg_engine.resistances,
                "resistance_readings": eeg_engine.get_resistance_readings(),
                "calibration": cal
            },
            "protocol": protocol_manager.get_status(),
            "recent_buffer": recent,
            "audio_slots": audio_manager.get_slots()
        })
        while True:
            data = await websocket.receive_json()
            # Handle any client-initiated commands over WS
            action = data.get("action")
            if action == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)
    except Exception as e:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

# ----------------- REST Endpoints -----------------

@app.get("/api/status")
def get_system_status():
    return {
        "status": "online",
        "device": {
            "connected": eeg_engine.is_connected,
            "serial": eeg_engine.device_serial,
            "name": eeg_engine.device_name,
            "type": eeg_engine.device_type_name,
            "battery": eeg_engine.battery_percent,
            "streaming": eeg_engine.is_streaming,
            "resistances": eeg_engine.resistances,
                "resistance_readings": eeg_engine.get_resistance_readings(),
            "calibration": eeg_engine.calibration_results,
            "native_dll_loaded": eeg_engine.native_dll_loaded
        },
        "protocol": protocol_manager.get_status(),
        "audio_slots": audio_manager.get_slots()
    }

# --- Device Endpoints ---
@app.get("/api/device/scan")
def scan_devices():
    devices = eeg_engine.scan_devices(timeout_sec=8.0)
    return {"devices": devices, "scan_error": eeg_engine.last_scan_error}

class ConnectDeviceRequest(BaseModel):
    serial: str
    simulated: bool = False

@app.post("/api/device/connect")
def connect_device(req: ConnectDeviceRequest):
    ok = eeg_engine.connect_device(req.serial, req.simulated)
    if not ok:
        detail = eeg_engine.last_connection_error or "Failed to connect to device."
        raise HTTPException(status_code=400, detail=detail)
    # Also auto-start streaming to allow live waveform monitor right away
    if not eeg_engine.start_streaming():
        eeg_engine.disconnect()
        raise HTTPException(status_code=500, detail="Device connected, but EEG streaming could not start.")
    broadcast_to_websockets({
        "type": "device_connected",
        "serial": eeg_engine.device_serial,
        "name": eeg_engine.device_name,
        "resistances": eeg_engine.resistances,
                "resistance_readings": eeg_engine.get_resistance_readings(),
        "streaming": eeg_engine.is_streaming
    })
    return {
        "connected": True,
        "serial": eeg_engine.device_serial,
        "name": eeg_engine.device_name,
        "resistances": eeg_engine.resistances,
                "resistance_readings": eeg_engine.get_resistance_readings(),
        "streaming": eeg_engine.is_streaming
    }

@app.post("/api/device/disconnect")
def disconnect_device():
    eeg_engine.disconnect()
    broadcast_to_websockets({"type": "device_disconnected"})
    return {"connected": False}

@app.post("/api/device/calibrate")
def run_calibration():
    if not eeg_engine.is_connected:
        raise HTTPException(status_code=400, detail="Device not connected.")
    try:
        res = eeg_engine.run_calibration(duration_sec=3.5)
    except Exception as exc:
        print(f"[API] Calibration failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Calibration failed: {exc}") from exc
    broadcast_to_websockets({
        "type": "calibration_finished",
        "result": res
    })
    return res

# --- Participant Enrollment ---
class EnrollmentRequest(BaseModel):
    participant_id: Optional[str] = None
    name: str
    age: int
    sex: str
    sleep_quality: str
    caffeine_intake: str

@app.post("/api/participant/enroll")
def enroll_participant(req: EnrollmentRequest):
    pid = req.participant_id.strip() if req.participant_id and req.participant_id.strip() else f"NR-P{abs(hash(req.name + str(req.age))) % 900 + 100}"
    info = {
        "participant_id": pid,
        "name": req.name.strip(),
        "age": req.age,
        "sex": req.sex,
        "sleep_quality": req.sleep_quality,
        "caffeine_intake": req.caffeine_intake
    }
    return {"success": True, "participant": info}

# --- Audio Library Endpoints ---
@app.get("/api/audio/slots")
def get_audio_slots():
    return audio_manager.get_slots()

@app.get("/api/audio/library")
def get_audio_library():
    return audio_manager.list_available_files()

@app.post("/api/audio/upload")
async def upload_audio_track(
    slot_id: str = Form(...),
    display_title: str = Form(...),
    audio_file: UploadFile = File(...)
):
    if slot_id not in ["raga1", "raga2", "raga3"]:
        raise HTTPException(status_code=400, detail="Invalid slot_id")
    try:
        updated = audio_manager.save_upload(
            slot_id=slot_id,
            file_obj=audio_file.file,
            filename=audio_file.filename,
            display_title=display_title
        )
        broadcast_to_websockets({
            "type": "audio_slot_updated",
            "slot_id": slot_id,
            "slot": updated
        })
        return {"success": True, "slot": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/audio/reset/{slot_id}")
def reset_audio_slot(slot_id: str):
    try:
        res = audio_manager.reset_slot(slot_id)
        broadcast_to_websockets({
            "type": "audio_slot_updated",
            "slot_id": slot_id,
            "slot": res
        })
        return {"success": True, "slot": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/audio/file/{filename}")
def serve_audio_default(filename: str):
    path = AUDIO_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), media_type="audio/wav")

@app.get("/api/audio/file/uploads/{filename}")
def serve_audio_upload(filename: str):
    path = UPLOAD_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    # Guess media type
    ext = path.suffix.lower()
    media_type = "audio/wav" if ext == ".wav" else ("audio/mpeg" if ext == ".mp3" else "application/octet-stream")
    return FileResponse(str(path), media_type=media_type)

# --- Protocol Execution ---
class ProtocolConfigRequest(BaseModel):
    duration_per_segment_sec: float

@app.post("/api/protocol/config")
def config_protocol(req: ProtocolConfigRequest):
    protocol_manager.set_duration_mode(req.duration_per_segment_sec)
    return {"duration_per_segment_sec": protocol_manager.duration_per_segment_sec}

class StartProtocolRequest(BaseModel):
    participant: Dict[str, Any]

@app.post("/api/protocol/start")
def start_protocol(req: StartProtocolRequest):
    if not eeg_engine.is_connected or not eeg_engine.is_streaming or eeg_engine.use_simulation:
        raise HTTPException(status_code=400, detail="Connect and stream from the physical Headband Pro before the protocol.")
    calibration = eeg_engine.calibration_results or {}
    if not calibration.get("ready_for_protocol", False):
        detail = calibration.get("message") or "Run calibration and resolve electrode contact and signal quality issues before recording."
        raise HTTPException(status_code=400, detail=f"Calibration did not pass: {detail}")
    if any(
        eeg_engine.resistances.get(channel) is None or eeg_engine.resistances[channel] >= 500.0
        for channel in ("O1", "O2", "T3", "T4")
    ):
        raise HTTPException(status_code=400, detail="Live electrode impedance is missing or at least 500 kOhm. Refit the headband and recalibrate before recording.")

    ok = protocol_manager.start_protocol(req.participant)
    if not ok:
        raise HTTPException(status_code=400, detail="Protocol already running or failed to initialize.")
    return {"status": "started", "protocol": protocol_manager.get_status()}

@app.post("/api/protocol/abort")
def abort_protocol():
    protocol_manager.abort_protocol()
    return {"status": "aborted"}

class SubjectiveRatingRequest(BaseModel):
    condition: str
    segment: str
    attention: float
    relaxation: float
    stress: float
    notes: Optional[str] = ""

@app.post("/api/protocol/rating")
def submit_rating(req: SubjectiveRatingRequest):
    ok = protocol_manager.submit_rating(
        condition=req.condition,
        segment=req.segment,
        attention=req.attention,
        relaxation=req.relaxation,
        stress=req.stress,
        notes=req.notes or ""
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Active recording session not found to record ratings.")
    return {"status": "rating_recorded"}

class SignalProcessingRequest(BaseModel):
    session_folder: str


@app.get("/api/data/processing/inspect/{session_folder}")
def inspect_recording_for_processing(session_folder: str):
    try:
        return signal_processing.inspect_session(session_folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/data/processing/run")
def process_selected_recording(req: SignalProcessingRequest):
    try:
        return signal_processing.process_session(req.session_folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save processing outputs: {exc}") from exc


@app.get("/api/data/processing/download/{session_folder}/{processing_folder}/{filename}")
def download_processing_output(session_folder: str, processing_folder: str, filename: str):
    if (not session_folder.replace("-", "").replace("_", "").isalnum()
            or not processing_folder.startswith("signal_processing_")
            or Path(processing_folder).name != processing_folder
            or Path(filename).name != filename):
        raise HTTPException(status_code=400, detail="Invalid processing output path.")
    try:
        session = signal_processing._safe_session(session_folder)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc
    output_dir = (session / processing_folder).resolve()
    if output_dir.parent != session.resolve() or not output_dir.is_dir():
        raise HTTPException(status_code=404, detail="Processing output not found.")
    output = (output_dir / filename).resolve()
    if output.parent != output_dir or not output.is_file():
        raise HTTPException(status_code=404, detail="Processing file not found.")
    media_type = "application/json" if filename.endswith(".json") else "text/csv"
    return FileResponse(str(output), filename=filename, media_type=media_type)


@app.post("/api/data/processing/open_folder/{session_folder}/{processing_folder}")
def open_processing_output_folder(session_folder: str, processing_folder: str):
    if not processing_folder.startswith("signal_processing_") or Path(processing_folder).name != processing_folder:
        raise HTTPException(status_code=400, detail="Invalid processing folder.")
    try:
        session = signal_processing._safe_session(session_folder)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc
    target = (session / processing_folder).resolve()
    if target.parent != session.resolve() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Processing folder not found.")
    try:
        if sys.platform == "win32":
            os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)])
        else:
            subprocess.run(["xdg-open", str(target)])
        return {"opened": True, "path": str(target)}
    except Exception as exc:
        return {"opened": False, "error": str(exc), "path": str(target)}


# --- Data Storage & Export Endpoints ---
@app.get("/api/data/sessions")
def list_sessions():
    sessions = []
    if RECORDINGS_DIR.exists():
        for d in sorted(RECORDINGS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir():
                meta_file = next(d.glob("*_metadata.json"), None)
                meta_data = {}
                if meta_file and meta_file.exists():
                    try:
                        import json
                        with open(meta_file, "r", encoding="utf-8") as f:
                            meta_data = json.load(f)
                    except Exception:
                        pass
                csv_files = [f.name for f in d.glob("*.csv")]
                sessions.append({
                    "folder_name": d.name,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d.stat().st_mtime)),
                    "files": csv_files,
                    "metadata": meta_data
                })
    return {"sessions": sessions}

@app.get("/api/data/download/{session_folder}/{filename}")
def download_session_file(session_folder: str, filename: str):
    file_path = RECORDINGS_DIR / session_folder / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        str(file_path),
        filename=filename,
        media_type="text/csv" if filename.endswith(".csv") else "application/json"
    )

@app.post("/api/data/open_folder/{session_folder}")
def open_session_folder_in_explorer(session_folder: str):
    target = RECORDINGS_DIR / session_folder
    if not target.exists():
        target = RECORDINGS_DIR
    try:
        if sys.platform == "win32":
            os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)])
        else:
            subprocess.run(["xdg-open", str(target)])
        return {"opened": True, "path": str(target)}
    except Exception as e:
        return {"opened": False, "error": str(e), "path": str(target)}

# Mount static frontend
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
