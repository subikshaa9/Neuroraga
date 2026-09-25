"""
Audio player using Windows Multimedia MCI API (winmm.dll).
Supports play, pause, resume, stop, and volume on Windows with zero external packages.
"""
import ctypes
import os
import time

class MCIAudioPlayer:
    def __init__(self):
        self._winmm = ctypes.windll.winmm
        self._is_playing = False
        self._is_paused = False
        self._current_file = None
        self._alias = "neuroraaga_audio"

    def _send_command(self, cmd: str) -> int:
        return self._winmm.mciSendStringW(cmd, None, 0, None)

    def load_and_play(self, filepath: str):
        self.stop()
        abs_path = os.path.abspath(filepath).replace("/", "\\")
        if not os.path.exists(abs_path):
            print(f"[MCIAudioPlayer] File not found: {abs_path}")
            return False
            
        self._current_file = abs_path
        self._send_command(f'open "{abs_path}" type waveaudio alias {self._alias}')
        ret = self._send_command(f'play {self._alias}')
        self._is_playing = (ret == 0)
        self._is_paused = False
        return self._is_playing

    def pause(self):
        if self._is_playing and not self._is_paused:
            self._send_command(f'pause {self._alias}')
            self._is_paused = True

    def resume(self):
        if self._is_playing and self._is_paused:
            self._send_command(f'resume {self._alias}')
            self._is_paused = False

    def stop(self):
        if self._current_file:
            self._send_command(f'stop {self._alias}')
            self._send_command(f'close {self._alias}')
        self._is_playing = False
        self._is_paused = False
        self._current_file = None

    @property
    def is_playing(self):
        return self._is_playing and not self._is_paused

    @property
    def is_paused(self):
        return self._is_paused

if __name__ == "__main__":
    player = MCIAudioPlayer()
    path = os.path.join("app", "audio", "anandabhairavi.wav")
    print("Testing play...")
    player.load_and_play(path)
    time.sleep(1.0)
    print("Testing pause...")
    player.pause()
    time.sleep(0.5)
    print("Testing resume...")
    player.resume()
    time.sleep(0.5)
    print("Testing stop...")
    player.stop()
    print("MCI Audio Player verified!")
