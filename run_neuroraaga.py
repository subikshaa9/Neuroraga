"""
NeuroRaaga Data Acquisition Dashboard Launcher
Starts the FastAPI server with WebSockets on port 8000 and opens the browser.
"""
import os
import sys
import webbrowser
import threading
import time

def open_browser():
    time.sleep(1.2)
    url = "http://localhost:8000"
    print(f"\n[NeuroRaaga] Opening web browser at: {url}\n")
    webbrowser.open(url)

def main():
    print("=" * 70)
    print("  NeuroRaaga - Carnatic Ragas Acute EEG Acquisition Platform")
    print("  4-Channel EEG (A1, A2, C3, C4) @ 250 Hz Continuous Recording")
    print("=" * 70)

    try:
        import uvicorn
        import fastapi
        import websockets
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Please install requirements: pip install fastapi uvicorn websockets")
        sys.exit(1)

    # Spawn thread to open web browser
    threading.Thread(target=open_browser, daemon=True).start()

    # Run Uvicorn server
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")

if __name__ == "__main__":
    main()
