/**
 * NeuroRaaga Audio Controller
 * Manages headphone audio playback, automated protocol sync, and preview controls.
 */
class RagaAudioController {
  constructor() {
    this.audio = new Audio();
    this.audio.preload = 'auto';
    
    this.currentTrack = null;
    this.isPlaying = false;
    this.volume = 0.85;
    this.audio.volume = this.volume;
    
    // UI Elements (populated on DOM ready)
    this.titleEl = null;
    this.subEl = null;
    this.progressFillEl = null;
    this.timeCurEl = null;
    this.timeTotEl = null;
    this.pulseIconEl = null;
    this.volumeSliderEl = null;
    
    this.setupListeners();
  }

  initUI(elements) {
    this.titleEl = elements.title;
    this.subEl = elements.sub;
    this.progressFillEl = elements.progressFill;
    this.timeCurEl = elements.timeCur;
    this.timeTotEl = elements.timeTot;
    this.pulseIconEl = elements.pulseIcon;
    this.volumeSliderEl = elements.volumeSlider;

    if (this.volumeSliderEl) {
      this.volumeSliderEl.value = this.volume * 100;
      this.volumeSliderEl.addEventListener('input', (e) => {
        this.setVolume(e.target.value / 100);
      });
    }
  }

  setupListeners() {
    this.audio.addEventListener('timeupdate', () => {
      if (this.audio.duration && this.progressFillEl) {
        const pct = (this.audio.currentTime / this.audio.duration) * 100;
        this.progressFillEl.style.width = `${pct}%`;
      }
      if (this.timeCurEl) {
        this.timeCurEl.textContent = this.formatTime(this.audio.currentTime);
      }
    });

    this.audio.addEventListener('loadedmetadata', () => {
      if (this.timeTotEl) {
        this.timeTotEl.textContent = this.formatTime(this.audio.duration);
      }
    });

    this.audio.addEventListener('play', () => {
      this.isPlaying = true;
      if (this.pulseIconEl) this.pulseIconEl.classList.add('playing');
    });

    this.audio.addEventListener('pause', () => {
      this.isPlaying = false;
      if (this.pulseIconEl) this.pulseIconEl.classList.remove('playing');
    });

    this.audio.addEventListener('ended', () => {
      this.isPlaying = false;
      if (this.pulseIconEl) this.pulseIconEl.classList.remove('playing');
    });
  }

  playTrack(url, title, subtitle = "Headphone Delivery Active") {
    if (this.audio.src !== window.location.origin + url && this.audio.src !== url) {
      this.audio.src = url;
    }
    this.currentTrack = { url, title, subtitle };
    this.audio.loop = true;
    
    if (this.titleEl) this.titleEl.textContent = title;
    if (this.subEl) this.subEl.textContent = subtitle;

    // Smooth un-mute & play
    this.audio.play().catch(err => {
      console.warn('[AudioController] Auto-play was blocked or failed:', err);
    });
  }

  stopTrack() {
    this.audio.pause();
    this.audio.currentTime = 0;
    this.audio.loop = false;
    this.isPlaying = false;
    if (this.titleEl) this.titleEl.textContent = "Silent / Idle (No Audio)";
    if (this.subEl) this.subEl.textContent = "Headphone Output Inactive";
    if (this.pulseIconEl) this.pulseIconEl.classList.remove('playing');
    if (this.progressFillEl) this.progressFillEl.style.width = "0%";
    if (this.timeCurEl) this.timeCurEl.textContent = "00:00";
  }

  pauseTrack() {
    this.audio.pause();
  }

  setVolume(vol) {
    this.volume = Math.max(0, Math.min(1, vol));
    this.audio.volume = this.volume;
  }

  formatTime(sec) {
    if (!sec || isNaN(sec)) return "00:00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
}

window.ragaAudio = new RagaAudioController();
