"""
Audio Generator for NeuroRaaga Carnatic Ragas
Generates high-fidelity WAV tracks for Anandabhairavi, Shubhapantuvarali, and Mohanam
with Tanpura drone and melodic phrasing.
"""
import os
import wave
import struct
import numpy as np

SAMPLE_RATE = 44100
DURATION_SEC = 125  # Just over 2 minutes (120 s)

def note_freq(tonic, semitones):
    return tonic * (2.0 ** (semitones / 12.0))

def generate_tanpura_drone(tonic, duration, sample_rate=44100):
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    drone_l = np.zeros_like(t)
    drone_r = np.zeros_like(t)
    
    # Tanpura cycle: Pa (7 semitones), Sa (12 semitones), Sa (12 semitones), Sa low (0 semitones)
    cycle_period = 4.0  # 4 seconds per cycle
    notes = [7, 12, 12, 0]
    offsets = [0.0, 1.0, 2.0, 3.0]
    
    for note, offset in zip(notes, offsets):
        freq = note_freq(tonic, note)
        # Pluck events repeat every cycle_period
        num_cycles = int(duration / cycle_period) + 2
        for c in range(num_cycles):
            t_start = c * cycle_period + offset
            if t_start >= duration:
                continue
            idx_start = int(t_start * sample_rate)
            pluck_len = int(3.5 * sample_rate)
            idx_end = min(idx_start + pluck_len, len(t))
            actual_len = idx_end - idx_start
            if actual_len <= 0:
                continue
            
            t_pluck = np.linspace(0, actual_len / sample_rate, actual_len, endpoint=False)
            decay = np.exp(-t_pluck / 1.5)
            # Rich harmonics
            sig = (
                0.35 * np.sin(2 * np.pi * freq * t_pluck) +
                0.25 * np.sin(2 * np.pi * freq * 2 * t_pluck) +
                0.18 * np.sin(2 * np.pi * freq * 3 * t_pluck) +
                0.10 * np.sin(2 * np.pi * freq * 4 * t_pluck) +
                0.05 * np.sin(2 * np.pi * freq * 5 * t_pluck)
            ) * decay
            
            # Subtle stereo spread
            pan = 0.4 if note in [7, 12] else 0.6
            drone_l[idx_start:idx_end] += sig * (1.0 - pan)
            drone_r[idx_start:idx_end] += sig * pan
            
    return drone_l, drone_r

def generate_melody(tonic, scale_semitones, duration, phrases, sample_rate=44100):
    t_total = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    melody = np.zeros_like(t_total)
    
    current_time = 2.0
    phrase_idx = 0
    
    while current_time < duration - 4.0:
        phrase = phrases[phrase_idx % len(phrases)]
        phrase_idx += 1
        
        for semitone, note_dur in phrase:
            if current_time + note_dur >= duration:
                break
            f = note_freq(tonic, semitone)
            n_samples = int(note_dur * sample_rate)
            t_note = np.linspace(0, note_dur, n_samples, endpoint=False)
            
            # Flute vibrato / gamaka (Carnatic oscillation)
            vibrato = 1.0 + 0.015 * np.sin(2 * np.pi * 5.2 * t_note)
            phase = 2 * np.pi * f * t_note * vibrato
            
            # Flute tone with warm breath and odd harmonics
            flute_tone = (
                0.60 * np.sin(phase) +
                0.25 * np.sin(2 * phase) +
                0.12 * np.sin(3 * phase) +
                0.04 * np.sin(4 * phase)
            )
            
            # Envelope (soft attack, sustained, gentle decay)
            attack_len = int(min(0.2, note_dur * 0.25) * sample_rate)
            decay_len = int(min(0.3, note_dur * 0.3) * sample_rate)
            env = np.ones(n_samples)
            if attack_len > 0:
                env[:attack_len] = np.sin(np.linspace(0, np.pi / 2, attack_len)) ** 2
            if decay_len > 0:
                env[-decay_len:] = np.cos(np.linspace(0, np.pi / 2, decay_len)) ** 2
                
            idx_start = int(current_time * sample_rate)
            idx_end = idx_start + n_samples
            melody[idx_start:idx_end] += flute_tone * env * 0.45
            
            current_time += note_dur + 0.15 # breath gap
        
        current_time += 1.5 # pause between phrases
        
    return melody

def save_wav(filename, left, right, sample_rate=44100):
    # Normalize
    max_val = max(np.max(np.abs(left)), np.max(np.abs(right)), 1e-6)
    if max_val > 0.95:
        left = left * (0.92 / max_val)
        right = right * (0.92 / max_val)
    else:
        left = left * 0.85
        right = right * 0.85
        
    int_l = np.int16(left * 32767)
    int_r = np.int16(right * 32767)
    
    interleaved = np.empty((int_l.size + int_r.size,), dtype=np.int16)
    interleaved[0::2] = int_l
    interleaved[1::2] = int_r
    
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(interleaved.tobytes())
    print(f"Generated: {filename} ({os.path.getsize(filename)} bytes)")

def main():
    out_dir = os.path.join(os.path.dirname(__file__), "app", "audio")
    os.makedirs(out_dir, exist_ok=True)
    
    tonic = 146.83 # D3 (standard Carnatic flute / vocal pitch)
    
    # 1. Anandabhairavi (Calming, devotional, soothing)
    # Scale: S(0), R2(2), G2(3), M1(5), P(7), D2(9), N2(10), S'(12)
    # Distinctive vakra phrase: S G R G M P...
    print("Generating Raga 1: Anandabhairavi...")
    drone_l, drone_r = generate_tanpura_drone(tonic, DURATION_SEC, SAMPLE_RATE)
    ananda_phrases = [
        [(0, 2.5), (3, 1.8), (2, 1.5), (3, 2.0), (5, 3.0), (7, 4.0)],
        [(7, 2.0), (9, 1.5), (7, 2.5), (5, 2.0), (3, 2.5), (2, 2.0), (0, 3.5)],
        [(0, 1.5), (2, 1.5), (3, 2.0), (5, 2.5), (7, 2.5), (10, 2.0), (12, 3.5)],
        [(12, 2.5), (10, 1.8), (9, 2.0), (7, 2.5), (5, 2.0), (3, 2.0), (2, 2.0), (0, 4.0)]
    ]
    mel_ananda = generate_melody(tonic, [0, 2, 3, 5, 7, 9, 10, 12], DURATION_SEC, ananda_phrases, SAMPLE_RATE)
    save_wav(os.path.join(out_dir, "anandabhairavi.wav"), drone_l + mel_ananda * 0.8, drone_r + mel_ananda * 0.8, SAMPLE_RATE)
    
    # 2. Shubhapantuvarali (Contemplative, profound, yearning, intense)
    # Scale: S(0), R1(1), G2(3), M2(6), P(7), D1(8), N3(11), S'(12)
    print("Generating Raga 2: Shubhapantuvarali...")
    drone_l, drone_r = generate_tanpura_drone(tonic, DURATION_SEC, SAMPLE_RATE)
    shubha_phrases = [
        [(0, 3.0), (1, 2.5), (3, 3.0), (6, 3.5), (7, 4.0)],
        [(7, 2.5), (8, 2.0), (7, 2.5), (6, 3.0), (3, 2.5), (1, 3.0), (0, 4.0)],
        [(6, 2.0), (7, 2.0), (8, 2.5), (11, 3.0), (12, 3.5), (11, 2.0), (8, 2.5), (7, 3.5)],
        [(7, 2.0), (6, 2.5), (3, 2.0), (1, 2.5), (0, 4.5)]
    ]
    mel_shubha = generate_melody(tonic, [0, 1, 3, 6, 7, 8, 11, 12], DURATION_SEC, shubha_phrases, SAMPLE_RATE)
    save_wav(os.path.join(out_dir, "shubhapantuvarali.wav"), drone_l + mel_shubha * 0.8, drone_r + mel_shubha * 0.8, SAMPLE_RATE)
    
    # 3. Mohanam (Bright, uplifting, joyous, pentatonic)
    # Scale: S(0), R2(2), G3(4), P(7), D2(9), S'(12)
    print("Generating Raga 3: Mohanam...")
    drone_l, drone_r = generate_tanpura_drone(tonic, DURATION_SEC, SAMPLE_RATE)
    mohana_phrases = [
        [(0, 2.0), (2, 2.0), (4, 2.5), (7, 3.0), (9, 2.5), (12, 3.5)],
        [(12, 2.5), (9, 2.0), (7, 2.5), (4, 2.0), (2, 2.0), (0, 3.5)],
        [(7, 2.0), (9, 2.0), (12, 2.5), (14, 2.5), (12, 3.0), (9, 2.0), (7, 3.5)],
        [(0, 1.5), (2, 1.5), (4, 2.0), (2, 1.5), (4, 2.0), (7, 3.0), (4, 2.0), (2, 2.0), (0, 4.0)]
    ]
    mel_mohana = generate_melody(tonic, [0, 2, 4, 7, 9, 12], DURATION_SEC, mohana_phrases, SAMPLE_RATE)
    save_wav(os.path.join(out_dir, "mohanam.wav"), drone_l + mel_mohana * 0.8, drone_r + mel_mohana * 0.8, SAMPLE_RATE)
    
    print("All 3 Carnatic raga default audio tracks generated successfully!")

if __name__ == "__main__":
    main()
