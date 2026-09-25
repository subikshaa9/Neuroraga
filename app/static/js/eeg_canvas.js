/**
 * NeuroRaaga Real-Time Multi-Channel EEG Oscilloscope
 * High-performance HTML5 Canvas rendering for A1, A2, C3, C4 electrodes at 250 Hz.
 */
class EEGOscilloscope {
  constructor(canvasElement) {
    this.canvas = canvasElement;
    this.ctx = canvasElement.getContext('2d', { alpha: false });
    
    this.channels = ['A1', 'A2', 'C3', 'C4'];
    this.channelColors = {
      'A1': '#38bdf8', // Cyan-Blue
      'A2': '#818cf8', // Indigo Periwinkle
      'C3': '#fbbf24', // Carnatic Amber
      'C4': '#34d399'  // Mint Emerald
    };
    
    this.sampleRate = 250; // 250 Hz
    this.timeWindowSec = 10.0; // 10 seconds display
    this.maxPoints = Math.round(this.sampleRate * this.timeWindowSec);
    
    // Ring buffers for each channel
    this.dataBuffers = {
      'A1': new Float32Array(this.maxPoints),
      'A2': new Float32Array(this.maxPoints),
      'C3': new Float32Array(this.maxPoints),
      'C4': new Float32Array(this.maxPoints)
    };
    this.bufferIndex = 0;
    this.totalSamplesReceived = 0;
    
    // Scale & Gain (in uV)
    this.uVRange = 50.0; // +/- 50 uV default
    this.autoScale = false;
    this.isPaused = false;
    this.channelVisible = { 'A1': true, 'A2': true, 'C3': true, 'C4': true };
    
    // Current live microvolt readings
    this.latestValues = { 'A1': 0.0, 'A2': 0.0, 'C3': 0.0, 'C4': 0.0 };
    
    this.setupResizeObserver();
    this.startRenderLoop();
  }

  setupResizeObserver() {
    const resize = () => {
      const rect = this.canvas.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = rect.width * dpr;
      this.canvas.height = rect.height * dpr;
      this.ctx.scale(dpr, dpr);
      this.width = rect.width;
      this.height = rect.height;
    };
    window.addEventListener('resize', resize);
    setTimeout(resize, 50);
  }

  setTimeWindow(sec) {
    this.timeWindowSec = parseFloat(sec);
    const newMax = Math.round(this.sampleRate * this.timeWindowSec);
    if (newMax !== this.maxPoints) {
      this.maxPoints = newMax;
      for (const ch of this.channels) {
        const oldBuf = this.dataBuffers[ch];
        this.dataBuffers[ch] = new Float32Array(this.maxPoints);
        // Copy most recent samples
        const copyLen = Math.min(oldBuf.length, this.maxPoints);
        this.dataBuffers[ch].set(oldBuf.slice(-copyLen));
      }
      this.bufferIndex = Math.min(this.bufferIndex, this.maxPoints - 1);
    }
  }

  setGain(uV) {
    if (uV === 'auto') {
      this.autoScale = true;
    } else {
      this.autoScale = false;
      this.uVRange = parseFloat(uV);
    }
  }

  togglePause() {
    this.isPaused = !this.isPaused;
    return this.isPaused;
  }

  toggleChannel(ch) {
    if (this.channelVisible[ch] !== undefined) {
      this.channelVisible[ch] = !this.channelVisible[ch];
    }
  }

  pushSamples(samples) {
    if (this.isPaused) return;
    
    for (let i = 0; i < samples.length; i++) {
      const s = samples[i];
      for (const ch of this.channels) {
        const val = s[ch] !== undefined ? s[ch] : 0.0;
        this.dataBuffers[ch][this.bufferIndex] = val;
        this.latestValues[ch] = val;
      }
      this.bufferIndex = (this.bufferIndex + 1) % this.maxPoints;
      this.totalSamplesReceived++;
    }
  }

  loadInitialBuffer(channelData) {
    for (const ch of this.channels) {
      if (channelData[ch] && channelData[ch].length > 0) {
        const src = channelData[ch];
        const len = Math.min(src.length, this.maxPoints);
        for (let i = 0; i < len; i++) {
          this.dataBuffers[ch][i] = src[src.length - len + i];
        }
        this.bufferIndex = len % this.maxPoints;
      }
    }
  }

  startRenderLoop() {
    const render = () => {
      this.draw();
      requestAnimationFrame(render);
    };
    requestAnimationFrame(render);
  }

  draw() {
    const ctx = this.ctx;
    const w = this.width || this.canvas.width;
    const h = this.height || this.canvas.height;
    if (!w || !h) return;

    // 1. Dark Oscilloscope Background
    ctx.fillStyle = '#080c14';
    ctx.fillRect(0, 0, w, h);

    const numChannels = this.channels.length;
    const channelHeight = h / numChannels;

    // 2. Draw Subtle Grid Lines & Time Divisions
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
    const numVerticalDivisions = Math.round(this.timeWindowSec);
    const xStep = w / numVerticalDivisions;
    
    for (let x = 0; x <= w; x += xStep) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }

    // Horizontal baseline dividers for channels
    for (let i = 0; i < numChannels; i++) {
      const yMid = i * channelHeight + channelHeight / 2;
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(0, yMid);
      ctx.lineTo(w, yMid);
      ctx.stroke();
      ctx.setLineDash([]);

      // Lane boundary line
      if (i > 0) {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
        ctx.beginPath();
        ctx.moveTo(0, i * channelHeight);
        ctx.lineTo(w, i * channelHeight);
        ctx.stroke();
      }
    }

    // Auto-scale computation if enabled
    let range = this.uVRange;
    if (this.autoScale) {
      let maxAbs = 10.0;
      for (const ch of this.channels) {
        if (!this.channelVisible[ch]) continue;
        const buf = this.dataBuffers[ch];
        for (let i = 0; i < this.maxPoints; i += 5) {
          const abs = Math.abs(buf[i]);
          if (abs > maxAbs) maxAbs = abs;
        }
      }
      range = Math.min(Math.max(maxAbs * 1.25, 20.0), 300.0);
    }

    // 3. Draw Channel Traces
    const currentIdx = this.bufferIndex;
    const totalPoints = this.maxPoints;

    for (let chIdx = 0; chIdx < numChannels; chIdx++) {
      const ch = this.channels[chIdx];
      if (!this.channelVisible[ch]) continue;

      const yMid = chIdx * channelHeight + channelHeight / 2;
      const buf = this.dataBuffers[ch];
      const color = this.channelColors[ch];
      const yScaling = (channelHeight * 0.42) / range;

      // Draw Trace Line
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.75;
      ctx.lineJoin = 'round';
      ctx.beginPath();

      let started = false;
      for (let i = 0; i < totalPoints; i++) {
        // Read buffer chronologically starting from currentIdx
        const readIdx = (currentIdx + i) % totalPoints;
        const val = buf[readIdx];
        const x = (i / (totalPoints - 1)) * w;
        const y = yMid - (val * yScaling);

        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();

      // 4. Draw Channel Header & Live Value Overlay
      ctx.fillStyle = color;
      ctx.font = '700 13px "Outfit", sans-serif';
      ctx.fillText(ch, 14, chIdx * channelHeight + 20);

      ctx.fillStyle = 'rgba(248, 250, 252, 0.7)';
      ctx.font = '500 11px "JetBrains Mono", monospace';
      const liveuV = this.latestValues[ch].toFixed(1);
      ctx.fillText(`${liveuV > 0 ? '+' : ''}${liveuV} µV`, 50, chIdx * channelHeight + 20);

      // Amplitude Scale Indicator (+/- uV)
      ctx.fillStyle = 'rgba(148, 163, 184, 0.4)';
      ctx.font = '400 9px "JetBrains Mono", monospace';
      ctx.fillText(`+${range.toFixed(0)}µV`, w - 46, chIdx * channelHeight + 14);
      ctx.fillText(`-${range.toFixed(0)}µV`, w - 46, (chIdx + 1) * channelHeight - 6);
    }

    // 5. Draw Real-Time Sweep Bar (Sweep Line at right edge)
    ctx.strokeStyle = 'rgba(0, 242, 254, 0.4)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(w - 1, 0);
    ctx.lineTo(w - 1, h);
    ctx.stroke();
  }
}
