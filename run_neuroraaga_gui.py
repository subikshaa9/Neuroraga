"""
NeuroRaaga — Native Desktop GUI Launcher
Starts the native Tkinter NeuroRaaga application with real-time waveform display,
strict eligibility screening, 3-stage electrode indicators, and automated protocol timing.
"""
import sys
import os

# Add workspace directory to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app.gui_dashboard import main

if __name__ == "__main__":
    print("=" * 70)
    print("  NeuroRaaga - Carnatic Ragas Acute EEG Acquisition Platform")
    print("  Native Desktop GUI (Tkinter) • 4-Channel EEG (A1, A2, C3, C4)")
    print("=" * 70)
    main()
