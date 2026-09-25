"""
Automated end-to-end test script for NeuroRaaga pipeline:
1. Tests device scan & connect
2. Tests 4-channel impedance & calibration check
3. Tests participant enrollment
4. Tests WebSocket live streaming
5. Tests fast-mode protocol run (Baseline -> Raga1 -> Rest1 -> Raga2 -> Rest2 -> Raga3)
6. Submits subjective ratings for conditions
7. Verifies generated master continuous CSV, 6 segment slices, ratings CSV, and metadata JSON.
"""
import asyncio
import json
import time
import urllib.request
import websockets
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

def post_json(path, data):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(path):
    with urllib.request.urlopen(f"{BASE_URL}{path}") as resp:
        return json.loads(resp.read().decode("utf-8"))

async def test_websocket_stream():
    print("\n--- Testing WebSocket Streaming ---")
    uri = "ws://127.0.0.1:8000/ws"
    async with websockets.connect(uri) as ws:
        # First message should be snapshot
        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        data = json.loads(msg)
        print("Received initial snapshot:", data["type"])
        assert data["type"] == "snapshot"

        # Wait for eeg_data packets
        packets = 0
        samples_count = 0
        for _ in range(10):
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            pkt = json.loads(msg)
            if pkt.get("type") == "eeg_data":
                packets += 1
                samples_count += len(pkt.get("samples", []))
                if packets == 1:
                    s0 = pkt["samples"][0]
                    print("Sample 0 structure:", s0)
                    assert "A1" in s0 and "A2" in s0 and "C3" in s0 and "C4" in s0
        print(f"Verified live WebSocket EEG stream: {packets} packets, {samples_count} total samples.")

def main():
    print("=" * 60)
    print("  NeuroRaaga End-to-End Test Suite")
    print("=" * 60)

    # 1. Device Scan
    print("\n1. Scanning devices...")
    scan_res = get_json("/api/device/scan")
    print("Scan results:", scan_res)
    assert len(scan_res["devices"]) > 0

    # 2. Connect Device
    print("\n2. Connecting to NeuroRaaga Synthetic EEG Generator...")
    conn_res = post_json("/api/device/connect", {"serial": "SIM-NEURORAAGA-250", "simulated": True})
    print("Connect response:", conn_res)
    assert conn_res["connected"] is True

    # 3. Calibration Check
    print("\n3. Running Signal Quality & Calibration Check...")
    cal_res = post_json("/api/device/calibrate", {})
    print("Calibration overall status:", cal_res["overall_status"])
    print("Channel impedances (kOhm):", {ch: info["impedance_kohm"] for ch, info in cal_res["channels"].items()})
    assert cal_res["ready_for_protocol"] is True

    # 4. WebSocket Test
    asyncio.run(test_websocket_stream())

    # 5. Participant Enrollment
    print("\n5. Enrolling test volunteer...")
    part_res = post_json("/api/participant/enroll", {
        "participant_id": "TEST-VOLUNTEER-01",
        "name": "Dr. Ananya Iyer",
        "age": 29,
        "sex": "Female",
        "sleep_quality": "Good (7-8 hrs, normal)",
        "caffeine_intake": "None"
    })
    print("Enrolled:", part_res)
    assert part_res["success"] is True

    # 6. Configure Protocol Duration (Fast 5s per segment for test)
    print("\n6. Configuring test protocol duration: 4s per segment...")
    conf_res = post_json("/api/protocol/config", {"duration_per_segment_sec": 4.0})
    print("Config response:", conf_res)

    # 7. Start Protocol
    print("\n7. Starting experimental protocol...")
    start_res = post_json("/api/protocol/start", {"participant": part_res["participant"]})
    print("Start protocol response:", start_res)
    assert start_res["status"] == "started"

    # Monitor protocol stages
    print("\nMonitoring protocol execution across all 6 stages...")
    completed = False
    for step in range(35):
        time.sleep(1.0)
        status = get_json("/api/status")["protocol"]
        stg_idx = status["stage_index"]
        cur_stg = status.get("current_stage")
        stg_name = cur_stg["name"] if cur_stg else "None"
        el = status["stage_elapsed_sec"]
        tot = status["total_elapsed_sec"]
        print(f"[{tot:.1f}s] Stage {stg_idx+1}/6: {stg_name} (Elapsed: {el:.1f}s)")

        # Periodically submit subjective ratings
        if stg_idx == 1 and el >= 2.0: # Baseline finished
            post_json("/api/protocol/rating", {
                "condition": "baseline",
                "segment": "baseline",
                "attention": 6.0,
                "relaxation": 8.0,
                "stress": 2.0,
                "notes": "Baseline rest feels calm"
            })
        elif stg_idx == 2 and el >= 2.0: # Raga 1 finished
            post_json("/api/protocol/rating", {
                "condition": "raga1",
                "segment": "raga1",
                "attention": 8.0,
                "relaxation": 9.0,
                "stress": 1.0,
                "notes": "Anandabhairavi evokes deep tranquility"
            })
        elif stg_idx == 4 and el >= 2.0: # Raga 2 finished
            post_json("/api/protocol/rating", {
                "condition": "raga2",
                "segment": "raga2",
                "attention": 9.0,
                "relaxation": 4.0,
                "stress": 5.0,
                "notes": "Shubhapantuvarali feels introspective and emotionally intense"
            })

        if status.get("is_completed"):
            completed = True
            print("\nProtocol execution completed!")
            break

    assert completed, "Protocol did not complete within expected time"

    # Submit final rating for Raga 3
    post_json("/api/protocol/rating", {
        "condition": "raga3",
        "segment": "raga3",
        "attention": 8.5,
        "relaxation": 8.5,
        "stress": 1.5,
        "notes": "Mohanam was joyous and uplifting"
    })

    # 8. Verify Generated Files
    print("\n8. Verifying Generated Files in Recordings Directory...")
    sessions_res = get_json("/api/data/sessions")
    print(f"Total recorded sessions found: {len(sessions_res['sessions'])}")
    latest_session = sessions_res["sessions"][0]
    folder = latest_session["folder_name"]
    files = latest_session["files"]
    print(f"Latest Session Folder: {folder}")
    print("Files in session folder:", files)

    # Check Master CSV
    master_csv = [f for f in files if "master.csv" in f]
    assert len(master_csv) == 1, "Master CSV missing!"
    print(f"Master CSV confirmed: {master_csv[0]}")

    # Check all 6 Segment Slices
    expected_segments = ["baseline", "raga1", "rest1", "raga2", "rest2", "raga3"]
    for seg in expected_segments:
        slice_match = [f for f in files if f"segment_{seg}.csv" in f]
        assert len(slice_match) == 1, f"Missing segment slice for: {seg}"
        print(f"Segment slice confirmed: {slice_match[0]}")

    # Check Subjective Ratings CSV
    ratings_csv = [f for f in files if "subjective_ratings.csv" in f]
    assert len(ratings_csv) == 1, "Subjective ratings CSV missing!"
    print(f"Subjective ratings CSV confirmed: {ratings_csv[0]}")

    # Check Metadata JSON
    meta = latest_session.get("metadata", {})
    assert "participant" in meta, "Metadata participant info missing!"
    assert "device" in meta, "Metadata device info missing!"
    assert "protocol" in meta, "Metadata protocol info missing!"
    assert "subjective_ratings" in meta, "Metadata ratings missing!"
    print("Metadata JSON structure verified!")

    # Check Master CSV Content Lines
    rec_path = Path("app/data/recordings") / folder / master_csv[0]
    with open(rec_path, "r", encoding="utf-8") as f:
        header = f.readline().strip()
        print("Master CSV Header:", header)
        assert header == "Timestamp,A1,A2,C3,C4,Segment"
        lines = f.readlines()
        print(f"Total data rows in master CSV: {len(lines)}")
        assert len(lines) > 500, "Too few rows recorded in master CSV!"
        # Check first and last sample
        print("First sample row:", lines[0].strip())
        print("Last sample row:", lines[-1].strip())

    # Restore default 120s duration for clinical use
    post_json("/api/protocol/config", {"duration_per_segment_sec": 120.0})
    print("\nRestored default protocol duration to standard 120s (clinical mode).")

    print("\nALL TEST ASSERTIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
