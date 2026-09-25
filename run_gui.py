"""
NeuroRaaga — GUI Launcher Shortcut
Forwards execution to run_neuroraaga_gui.py
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from run_neuroraaga_gui import main

if __name__ == "__main__":
    main()
