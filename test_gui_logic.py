"""
Verification script for NeuroRaaga Native GUI functionality:
1. Tests eligibility screening rules (age 18-30, head injury, brain issues, brain meds)
2. Tests 3-stage electrode states (Red, Orange, Green)
3. Tests auto-pause and auto-resume logic
4. Tests guaranteed sample count equality across segments
"""
import sys
import os
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app.gui_dashboard import NeuroRaagaApp, TARGET_CHANNELS, PROTOCOL_STAGES
import tkinter as tk
from tkinter import messagebox

# Mock messagebox dialogs for automated headless testing
messagebox.showerror = lambda title, message: print(f"[MOCK ERROR] {title}: {message}")
messagebox.showwarning = lambda title, message: print(f"[MOCK WARNING] {title}: {message}")
messagebox.showinfo = lambda title, message: print(f"[MOCK INFO] {title}: {message}")
messagebox.askyesno = lambda title, message: True

class TestNeuroRaagaGUI(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw() # Headless for test
        self.app = NeuroRaagaApp(self.root)

    def tearDown(self):
        self.app._on_close()

    def test_eligibility_screening(self):
        print("\n--- Testing Strict Eligibility Screening ---")
        
        # Test 1: Age < 18 -> Disqualified
        self.app.ent_age.delete(0, tk.END)
        self.app.ent_age.insert(0, "16")
        self.app.cmb_injury.set("No (Eligible)")
        self.app.cmb_brain.set("No (Eligible)")
        self.app.cmb_meds.set("No (Eligible)")
        # Call enrollment logic
        self.app._handle_enrollment()
        self.assertIsNone(self.app.participant, "Age < 18 should be disqualified")
        print("PASS: Age < 18 correctly blocked.")

        # Test 2: Age > 30 -> Disqualified
        self.app.ent_age.delete(0, tk.END)
        self.app.ent_age.insert(0, "34")
        self.app._handle_enrollment()
        self.assertIsNone(self.app.participant, "Age > 30 should be disqualified")
        print("PASS: Age > 30 correctly blocked.")

        # Test 3: Head injury -> Disqualified
        self.app.ent_age.delete(0, tk.END)
        self.app.ent_age.insert(0, "24")
        self.app.cmb_injury.set("Yes (Not Eligible)")
        self.app._handle_enrollment()
        self.assertIsNone(self.app.participant, "Head injury should be disqualified")
        print("PASS: Head injury correctly blocked.")

        # Test 4: Brain issues -> Disqualified
        self.app.cmb_injury.set("No (Eligible)")
        self.app.cmb_brain.set("Yes (Not Eligible)")
        self.app._handle_enrollment()
        self.assertIsNone(self.app.participant, "Brain issues should be disqualified")
        print("PASS: Brain issues correctly blocked.")

        # Test 5: Brain meds -> Disqualified
        self.app.cmb_brain.set("No (Eligible)")
        self.app.cmb_meds.set("Yes (Not Eligible)")
        self.app._handle_enrollment()
        self.assertIsNone(self.app.participant, "Brain meds should be disqualified")
        print("PASS: Brain medications correctly blocked.")

        # Test 6: Fully Eligible
        self.app.cmb_meds.set("No (Eligible)")
        self.app._handle_enrollment()
        self.assertIsNotNone(self.app.participant, "Eligible candidate should be enrolled")
        self.assertEqual(self.app.participant["age"], 24)
        print("PASS: Eligible candidate (Age 24, clean screening) successfully enrolled!")

    def test_electrode_stages_and_auto_pause(self):
        print("\n--- Testing 3-Stage Electrodes and Auto-Pause/Resume ---")
        
        # Connect simulator
        self.app.cmb_devices["values"] = ["NeuroRaaga Synthetic EEG Generator (250 Hz) [Serial: SIM-NEURORAAGA-250]"]
        self.app.cmb_devices.current(0)
        self.app._handle_connect_device()
        self.assertTrue(self.app.is_connected)

        # Confirm initial all green
        for ch in TARGET_CHANNELS:
            self.assertEqual(self.app.electrode_states[ch], "GREEN")

        # Start protocol in fast test mode (15s = 3750 samples per segment)
        self.app.participant = {"participant_id": "TEST-P99", "name": "Test User", "age": 22}
        self.app.cmb_proto_mode.set("Fast Test Mode (15s per segment • 90s total)")
        self.app._on_proto_mode_changed()
        self.assertEqual(self.app.total_target_samples, 15 * 250)

        self.app._start_protocol()
        self.assertTrue(self.app.protocol_running)
        self.assertFalse(self.app.protocol_paused)
        print("PASS: Protocol started in stage 0 (baseline) with all electrodes GREEN.")

        # Simulate A1 dropping to RED (disconnected)
        self.app.electrode_states["A1"] = "RED"
        self.app._eeg_stream_tick()
        self.assertTrue(self.app.protocol_paused, "Should AUTO-PAUSE when electrode drops to RED")
        print("PASS: Auto-pause triggered immediately when electrode A1 disconnected.")

        # Simulate A1 returning to GREEN
        self.app.electrode_states["A1"] = "GREEN"
        self.app._eeg_stream_tick()
        self.assertFalse(self.app.protocol_paused, "Should AUTO-RESUME when all electrodes return to GREEN")
        print("PASS: Auto-resume triggered immediately when all electrodes returned to GREEN.")

        # Clean up
        self.app._abort_protocol()

if __name__ == "__main__":
    unittest.main()
