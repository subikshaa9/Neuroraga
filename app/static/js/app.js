/**
 * NeuroRaaga Application Controller
 * Handles UI interactions, REST API calls, WebSocket event dispatching, and state management.
 */

// Global State
const state = {
  participant: null,
  device: {
    connected: false,
    serial: null,
    name: "None",
    battery: 100,
    streaming: false,
    resistances: { A1: 18.5, A2: 17.2, C3: 16.9, C4: 19.1 },
    calibration: null
  },
  protocol: {
    is_running: false,
    stage_index: -1,
    stages: [],
    stage_elapsed: 0,
    duration_per_segment: 120,
    total_elapsed: 0
  },
  audioSlots: {},
  oscilloscope: null,
  activeTab: 'enrollment',
  pendingRating: null
};

// DOM Elements Cache
const dom = {};

document.addEventListener('DOMContentLoaded', () => {
  initDOMReferences();
  initOscilloscope();
  initAudioPlayer();
  setupEventListeners();
  initWebSocket();
  fetchInitialState();
});

function initDOMReferences() {
  // Navigation tabs
  dom.stepCards = document.querySelectorAll('.step-card');
  dom.tabPanels = document.querySelectorAll('.tab-content');

  // Header status indicators
  dom.hdrDeviceSerial = document.getElementById('hdrDeviceSerial');
  dom.hdrDeviceStatus = document.getElementById('hdrDeviceStatus');
  dom.hdrDeviceIndicator = document.getElementById('hdrDeviceIndicator');
  dom.hdrBattery = document.getElementById('hdrBattery');
  dom.hdrSessionTimer = document.getElementById('hdrSessionTimer');
  dom.hdrActiveSegment = document.getElementById('hdrActiveSegment');

  // Step 1: Enrollment
  dom.formEnrollment = document.getElementById('formEnrollment');
  dom.inputPartId = document.getElementById('partId');
  dom.inputPartName = document.getElementById('partName');
  dom.inputPartAge = document.getElementById('partAge');
  dom.selectPartSex = document.getElementById('partSex');
  dom.selectSleepQuality = document.getElementById('sleepQuality');
  dom.selectCaffeine = document.getElementById('caffeineIntake');

  // Step 2: Device & Calibration
  dom.btnScanDevices = document.getElementById('btnScanDevices');
  dom.deviceListContainer = document.getElementById('deviceListContainer');
  dom.btnConnectDevice = document.getElementById('btnConnectDevice');
  dom.btnDisconnectDevice = document.getElementById('btnDisconnectDevice');
  dom.btnCalibrate = document.getElementById('btnCalibrate');
  dom.connectedSerialDisplay = document.getElementById('connectedSerialDisplay');
  dom.calibStatusBadge = document.getElementById('calibStatusBadge');

  // Step 3: Music Library
  dom.slotsContainer = document.getElementById('slotsContainer');
  dom.fileUploadInput = document.getElementById('fileUploadInput');

  // Step 4: Protocol
  dom.protocolTimeline = document.getElementById('protocolTimeline');
  dom.btnStartProtocol = document.getElementById('btnStartProtocol');
  dom.btnAbortProtocol = document.getElementById('btnAbortProtocol');
  dom.protocolTimerDisplay = document.getElementById('protocolTimerDisplay');
  dom.segmentTimerDisplay = document.getElementById('segmentTimerDisplay');
  dom.protocolSpeedSelect = document.getElementById('protocolSpeedSelect');

  // Step 5: Data Storage
  dom.sessionSummaryCard = document.getElementById('sessionSummaryCard');
  dom.exportFilesList = document.getElementById('exportFilesList');
  dom.btnOpenFolder = document.getElementById('btnOpenFolder');
  dom.previousSessionsList = document.getElementById('previousSessionsList');

  // Subjective Rating Modal
  dom.ratingModal = document.getElementById('ratingModal');
  dom.ratingModalTitle = document.getElementById('ratingModalTitle');
  dom.ratingConditionLabel = document.getElementById('ratingConditionLabel');
  dom.sliderAttention = document.getElementById('sliderAttention');
  dom.valAttention = document.getElementById('valAttention');
  dom.sliderRelaxation = document.getElementById('sliderRelaxation');
  dom.valRelaxation = document.getElementById('valRelaxation');
  dom.sliderStress = document.getElementById('sliderStress');
  dom.valStress = document.getElementById('valStress');
  dom.inputRatingNotes = document.getElementById('ratingNotes');
  dom.btnSubmitRating = document.getElementById('btnSubmitRating');

  // Oscilloscope controls
  dom.selectGain = document.getElementById('selectGain');
  dom.selectTimeWindow = document.getElementById('selectTimeWindow');
  dom.btnPauseScope = document.getElementById('btnPauseScope');
}

function initOscilloscope() {
  const canvas = document.getElementById('eegCanvas');
  state.oscilloscope = new EEGOscilloscope(canvas);
}

function initAudioPlayer() {
  window.ragaAudio.initUI({
    title: document.getElementById('playerTrackTitle'),
    sub: document.getElementById('playerTrackSub'),
    progressFill: document.getElementById('playerProgressFill'),
    timeCur: document.getElementById('playerTimeCur'),
    timeTot: document.getElementById('playerTimeTot'),
    pulseIcon: document.getElementById('playerPulseIcon'),
    volumeSlider: document.getElementById('playerVolume')
  });
}

function setupEventListeners() {
  // Step Navigation
  dom.stepCards.forEach(card => {
    card.addEventListener('click', () => {
      const tabId = card.getAttribute('data-tab');
      switchTab(tabId);
    });
  });

  // Step 1: Form Submit
  dom.formEnrollment.addEventListener('submit', (e) => {
    e.preventDefault();
    submitEnrollment();
  });

  // Step 2: Device Controls
  dom.btnScanDevices.addEventListener('click', scanDevices);
  dom.btnConnectDevice.addEventListener('click', connectSelectedDevice);
  dom.btnDisconnectDevice.addEventListener('click', disconnectDevice);
  dom.btnCalibrate.addEventListener('click', runCalibration);

  // Step 4: Protocol Controls
  dom.btnStartProtocol.addEventListener('click', startProtocol);
  dom.btnAbortProtocol.addEventListener('click', abortProtocol);
  dom.protocolSpeedSelect.addEventListener('change', (e) => {
    const dur = parseFloat(e.target.value);
    fetch('/api/protocol/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ duration_per_segment_sec: dur })
    });
  });

  // Oscilloscope controls
  dom.selectGain.addEventListener('change', (e) => {
    state.oscilloscope.setGain(e.target.value);
  });
  dom.selectTimeWindow.addEventListener('change', (e) => {
    state.oscilloscope.setTimeWindow(e.target.value);
  });
  dom.btnPauseScope.addEventListener('click', () => {
    const isPaused = state.oscilloscope.togglePause();
    dom.btnPauseScope.textContent = isPaused ? 'Resume Scope' : 'Freeze Scope';
  });

  // Rating Sliders live badge updates
  dom.sliderAttention.addEventListener('input', (e) => {
    dom.valAttention.textContent = e.target.value;
  });
  dom.sliderRelaxation.addEventListener('input', (e) => {
    dom.valRelaxation.textContent = e.target.value;
  });
  dom.sliderStress.addEventListener('input', (e) => {
    dom.valStress.textContent = e.target.value;
  });
  dom.btnSubmitRating.addEventListener('click', submitSubjectiveRating);

  // Open recordings folder
  dom.btnOpenFolder.addEventListener('click', () => {
    const sessionDir = dom.btnOpenFolder.getAttribute('data-folder') || '';
    fetch(`/api/data/open_folder/${sessionDir}`, { method: 'POST' });
  });
}

function switchTab(tabId) {
  state.activeTab = tabId;
  dom.stepCards.forEach(c => {
    c.classList.toggle('active', c.getAttribute('data-tab') === tabId);
  });
  dom.tabPanels.forEach(p => {
    p.classList.toggle('active', p.id === `tab-${tabId}`);
  });
}

// ----------------- WebSocket Connection -----------------
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('[NeuroRaaga] WebSocket connected.');
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleWebSocketMessage(msg);
    } catch (e) {
      console.error('[NeuroRaaga] WS parse error:', e);
    }
  };

  ws.onclose = () => {
    console.warn('[NeuroRaaga] WS disconnected. Reconnecting in 2s...');
    setTimeout(initWebSocket, 2000);
  };
}

function handleWebSocketMessage(msg) {
  switch (msg.type) {
    case 'snapshot':
      updateDeviceState(msg.device);
      updateProtocolState(msg.protocol);
      if (msg.recent_buffer) {
        state.oscilloscope.loadInitialBuffer(msg.recent_buffer.channels);
      }
      if (msg.audio_slots) {
        renderAudioSlots(msg.audio_slots);
      }
      break;

    case 'eeg_data':
      if (msg.samples && state.oscilloscope) {
        state.oscilloscope.pushSamples(msg.samples);
      }
      break;

    case 'device_connected':
      state.device.connected = true;
      state.device.serial = msg.serial;
      state.device.name = msg.name;
      if (msg.resistances) state.device.resistances = msg.resistances;
      updateDeviceUI();
      break;

    case 'device_disconnected':
      state.device.connected = false;
      state.device.serial = null;
      updateDeviceUI();
      break;

    case 'calibration_finished':
      handleCalibrationResult(msg.result);
      break;

    case 'stage_changed':
      handleStageChanged(msg.data);
      break;

    case 'protocol_tick':
      handleProtocolTick(msg.data);
      break;

    case 'audio_command':
      if (msg.data.action === 'stop') {
        window.ragaAudio.stopTrack();
      }
      break;

    case 'audio_slot_updated':
      state.audioSlots[msg.slot_id] = msg.slot;
      renderAudioSlots(state.audioSlots);
      break;

    case 'request_subjective_rating':
      openSubjectiveRatingModal(msg.data);
      break;

    case 'protocol_completed':
      handleProtocolCompleted(msg.data);
      break;

    case 'protocol_aborted':
      alert('Protocol recording session was aborted.');
      state.protocol.is_running = false;
      updateProtocolUI();
      break;
  }
}

// ----------------- REST Initializer -----------------
async function fetchInitialState() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    updateDeviceState(data.device);
    updateProtocolState(data.protocol);
    state.audioSlots = data.audio_slots || {};
    renderAudioSlots(state.audioSlots);
    renderProtocolTimeline(data.protocol.stages || []);
    loadPreviousSessions();
  } catch (e) {
    console.error('Error fetching initial status:', e);
  }
}

// ----------------- Step 1: Participant Enrollment -----------------
async function submitEnrollment() {
  const reqBody = {
    participant_id: dom.inputPartId.value.trim() || undefined,
    name: dom.inputPartName.value.trim(),
    age: parseInt(dom.inputPartAge.value),
    sex: dom.selectPartSex.value,
    sleep_quality: dom.selectSleepQuality.value,
    caffeine_intake: dom.selectCaffeine.value
  };

  try {
    const res = await fetch('/api/participant/enroll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody)
    });
    const data = await res.json();
    if (data.success) {
      state.participant = data.participant;
      document.getElementById('step-enrollment').classList.add('completed');
      alert(`Participant enrolled successfully! Assigned ID: ${data.participant.participant_id}`);
      switchTab('device');
    }
  } catch (e) {
    alert(`Enrollment error: ${e.message}`);
  }
}

// ----------------- Step 2: Device & Calibration -----------------
let discoveredDevices = [];
let selectedDeviceSerial = null;

async function scanDevices() {
  dom.btnScanDevices.textContent = 'Scanning...';
  dom.btnScanDevices.disabled = true;
  dom.deviceListContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">Scanning Bluetooth and simulated devices...</div>';

  try {
    const res = await fetch('/api/device/scan');
    const data = await res.json();
    discoveredDevices = data.devices || [];
    renderDiscoveredDevices();
  } catch (e) {
    dom.deviceListContainer.innerHTML = `<div style="color: var(--rose-alert); font-size: 0.85rem;">Scan error: ${e.message}</div>`;
  } finally {
    dom.btnScanDevices.textContent = 'Scan Devices';
    dom.btnScanDevices.disabled = false;
  }
}

function renderDiscoveredDevices() {
  if (discoveredDevices.length === 0) {
    dom.deviceListContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No devices discovered. Ensure headset is powered on.</div>';
    return;
  }

  dom.deviceListContainer.innerHTML = '';
  discoveredDevices.forEach((dev, idx) => {
    const item = document.createElement('div');
    item.className = `device-item ${idx === 0 ? 'selected' : ''}`;
    item.innerHTML = `
      <div class="device-meta">
        <span class="device-name">${dev.name}</span>
        <span class="device-serial mono">Serial ID: ${dev.serial} &bull; Type: ${dev.type}</span>
      </div>
      <button class="btn btn-secondary btn-sm select-btn">Select</button>
    `;
    item.addEventListener('click', () => {
      document.querySelectorAll('.device-item').forEach(d => d.classList.remove('selected'));
      item.classList.add('selected');
      selectedDeviceSerial = dev.serial;
    });
    dom.deviceListContainer.appendChild(item);
  });
  selectedDeviceSerial = discoveredDevices[0].serial;
}

async function connectSelectedDevice() {
  if (!selectedDeviceSerial && discoveredDevices.length > 0) {
    selectedDeviceSerial = discoveredDevices[0].serial;
  }
  const isSim = selectedDeviceSerial ? selectedDeviceSerial.startsWith('SIM-') : true;
  const serial = selectedDeviceSerial || 'SIM-NEURORAAGA-250';

  dom.btnConnectDevice.textContent = 'Connecting...';
  dom.btnConnectDevice.disabled = true;

  try {
    const res = await fetch('/api/device/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial: serial, simulated: isSim })
    });
    const data = await res.json();
    if (data.connected) {
      state.device.connected = true;
      state.device.serial = data.serial;
      state.device.name = data.name;
      if (data.resistances) state.device.resistances = data.resistances;
      updateDeviceUI();
    }
  } catch (e) {
    alert(`Connection failed: ${e.message}`);
  } finally {
    dom.btnConnectDevice.textContent = 'Connect Device';
    dom.btnConnectDevice.disabled = false;
  }
}

async function disconnectDevice() {
  await fetch('/api/device/disconnect', { method: 'POST' });
  state.device.connected = false;
  state.device.serial = null;
  updateDeviceUI();
}

async function runCalibration() {
  dom.btnCalibrate.textContent = 'Checking Signals (3.5s)...';
  dom.btnCalibrate.disabled = true;
  dom.calibStatusBadge.innerHTML = '<span style="color: var(--amber-light);">Analyzing impedance & stability...</span>';

  try {
    const res = await fetch('/api/device/calibrate', { method: 'POST' });
    const result = await res.json();
    handleCalibrationResult(result);
  } catch (e) {
    alert(`Calibration error: ${e.message}`);
  } finally {
    dom.btnCalibrate.textContent = 'Run Calibration Check';
    dom.btnCalibrate.disabled = false;
  }
}

function handleCalibrationResult(result) {
  state.device.calibration = result;
  
  // Update Impedance values
  if (result.channels) {
    for (const [ch, info] of Object.entries(result.channels)) {
      const badge = document.getElementById(`badge-${ch}`);
      const valEl = document.getElementById(`val-${ch}`);
      const statEl = document.getElementById(`stat-${ch}`);
      if (badge && valEl && statEl) {
        valEl.textContent = `${info.impedance_kohm} kΩ`;
        statEl.textContent = info.status;
        badge.className = `electrode-badge ${info.status.toLowerCase()}`;
        statEl.className = `electrode-status ${info.status.toLowerCase()}`;
      }
    }
  }

  const isReady = result.ready_for_protocol;
  dom.calibStatusBadge.innerHTML = `
    <span class="status-indicator ${isReady ? 'connected' : ''}"></span>
    <span style="font-weight: 700; color: ${isReady ? 'var(--emerald-live)' : 'var(--rose-alert)'}">
      ${result.overall_status}: ${result.message}
    </span>
  `;

  if (isReady) {
    document.getElementById('step-device').classList.add('completed');
  }
}

function updateDeviceState(deviceState) {
  state.device = { ...state.device, ...deviceState };
  updateDeviceUI();
}

function updateDeviceUI() {
  const isConn = state.device.connected;
  dom.hdrDeviceIndicator.className = `status-indicator ${isConn ? 'connected pulsing' : ''}`;
  dom.hdrDeviceStatus.textContent = isConn ? 'CONNECTED' : 'DISCONNECTED';
  dom.hdrDeviceSerial.textContent = state.device.serial ? `Serial: ${state.device.serial}` : 'No Device';
  dom.connectedSerialDisplay.textContent = state.device.serial || 'None';

  dom.btnConnectDevice.style.display = isConn ? 'none' : 'inline-flex';
  dom.btnDisconnectDevice.style.display = isConn ? 'inline-flex' : 'none';
  dom.btnCalibrate.disabled = !isConn;

  // Update Impedance Display
  if (state.device.resistances) {
    for (const [ch, val] of Object.entries(state.device.resistances)) {
      const valEl = document.getElementById(`val-${ch}`);
      if (valEl) valEl.textContent = `${val} kΩ`;
    }
  }
}

// ----------------- Step 3: Music Library & Audio Slots -----------------
function renderAudioSlots(slots) {
  state.audioSlots = slots;
  dom.slotsContainer.innerHTML = '';

  const slotKeys = ['raga1', 'raga2', 'raga3'];
  slotKeys.forEach(slotId => {
    const s = slots[slotId];
    if (!s) return;

    const card = document.createElement('div');
    card.className = 'audio-slot-card';
    card.id = `card-${slotId}`;
    card.innerHTML = `
      <div class="slot-header">
        <span class="slot-tag">${s.label}</span>
        <span class="mono" style="font-size: 0.75rem; color: var(--text-muted);">${s.duration_sec}s</span>
      </div>
      <div>
        <div class="slot-title">${s.current_title}</div>
        <div class="slot-desc">${s.mood_description}</div>
        <div class="mono" style="font-size: 0.72rem; color: var(--text-dim); margin-top: 4px;">File: ${s.filename}</div>
      </div>
      <div class="slot-controls">
        <button class="btn btn-secondary btn-sm" onclick="previewTrack('${s.url}', '${s.current_title}')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Preview
        </button>
        <button class="btn btn-secondary btn-sm" onclick="triggerFileUpload('${slotId}', '${s.label}')">
          Upload / Replace
        </button>
        ${s.is_custom ? `<button class="btn btn-secondary btn-sm" onclick="resetSlot('${slotId}')">Reset</button>` : ''}
      </div>
    `;
    dom.slotsContainer.appendChild(card);
  });
  document.getElementById('step-audio').classList.add('completed');
}

window.previewTrack = function(url, title) {
  window.ragaAudio.playTrack(url, title, "Operator Preview");
};

window.resetSlot = async function(slotId) {
  await fetch(`/api/audio/reset/${slotId}`, { method: 'POST' });
};

window.triggerFileUpload = function(slotId, label) {
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = 'audio/*,.wav,.mp3,.ogg,.flac,.m4a';
  fileInput.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const customTitle = prompt(`Enter display title for ${label}:`, file.name.replace(/\.[^/.]+$/, ''));
    if (customTitle === null) return;

    const formData = new FormData();
    formData.append('slot_id', slotId);
    formData.append('display_title', customTitle.trim() || file.name);
    formData.append('audio_file', file);

    try {
      const res = await fetch('/api/audio/upload', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (data.success) {
        alert(`Uploaded and mapped track to ${label}!`);
      }
    } catch (err) {
      alert(`Upload failed: ${err.message}`);
    }
  };
  fileInput.click();
};

// ----------------- Step 4: Protocol Execution -----------------
function renderProtocolTimeline(stages) {
  state.protocol.stages = stages;
  dom.protocolTimeline.innerHTML = '';

  stages.forEach((stg, idx) => {
    const item = document.createElement('div');
    item.className = 'protocol-stage-item';
    item.id = `proto-stage-${idx}`;
    item.innerHTML = `
      <span class="stage-badge">${idx + 1}</span>
      <span class="stage-name">${stg.name}</span>
      <span class="stage-time">${stg.default_duration_sec}s</span>
    `;
    dom.protocolTimeline.appendChild(item);
  });
}

async function startProtocol() {
  if (!state.participant) {
    alert('Please enroll a participant in Step 1 before starting the recording protocol.');
    switchTab('enrollment');
    return;
  }

  if (!state.device.connected) {
    const proceed = confirm('EEG device is not connected. Connect simulated device (250 Hz) and proceed?');
    if (proceed) {
      await connectSelectedDevice();
    } else {
      return;
    }
  }

  try {
    const res = await fetch('/api/protocol/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant: state.participant })
    });
    const data = await res.json();
    if (data.status === 'started') {
      state.protocol.is_running = true;
      updateProtocolUI();
      document.getElementById('step-protocol').classList.add('active');
    }
  } catch (e) {
    alert(`Could not start protocol: ${e.message}`);
  }
}

async function abortProtocol() {
  const conf = confirm('Are you sure you want to abort the current recording protocol? Data up to this point will be saved.');
  if (conf) {
    await fetch('/api/protocol/abort', { method: 'POST' });
  }
}

function handleStageChanged(data) {
  state.protocol.stage_index = data.stage_index;
  dom.hdrActiveSegment.textContent = `SEGMENT: ${data.segment_name.toUpperCase()}`;

  // Highlight active stage in timeline
  document.querySelectorAll('.protocol-stage-item').forEach((el, idx) => {
    el.classList.remove('current');
    if (idx < data.stage_index) el.classList.add('completed');
    if (idx === data.stage_index) el.classList.add('current');
  });

  // Audio Playback Cue
  if (data.is_audio && data.audio_info) {
    window.ragaAudio.playTrack(
      data.audio_info.url,
      data.audio_info.current_title,
      `Study Audio Active (${data.segment_name})`
    );
  } else {
    window.ragaAudio.stopTrack();
  }

  // Update instructions in oscilloscope footer
  document.getElementById('protocolInstructionText').textContent = data.instructions;
}

function handleProtocolTick(data) {
  const remSec = Math.ceil(data.stage_remaining);
  const totalRemSec = Math.ceil(data.total_duration - data.total_elapsed);

  dom.segmentTimerDisplay.textContent = formatMMSS(remSec);
  dom.protocolTimerDisplay.textContent = formatMMSS(totalRemSec);
  dom.hdrSessionTimer.textContent = formatMMSS(data.total_elapsed);
}

function updateProtocolState(protocolState) {
  state.protocol = { ...state.protocol, ...protocolState };
  updateProtocolUI();
}

function updateProtocolUI() {
  const isRunning = state.protocol.is_running;
  dom.btnStartProtocol.style.display = isRunning ? 'none' : 'inline-flex';
  dom.btnAbortProtocol.style.display = isRunning ? 'inline-flex' : 'none';
  dom.protocolSpeedSelect.disabled = isRunning;
}

function formatMMSS(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m.toString().padStart(2, '0')}:${rem.toString().padStart(2, '0')}`;
}

// ----------------- Step 5: Subjective Ratings & Exports -----------------
function openSubjectiveRatingModal(data) {
  state.pendingRating = data;
  dom.ratingModalTitle.textContent = data.title;
  dom.ratingConditionLabel.textContent = `Condition: ${data.condition.toUpperCase()}`;

  // Reset sliders to default mid values
  dom.sliderAttention.value = 5;
  dom.valAttention.textContent = 5;
  dom.sliderRelaxation.value = 5;
  dom.valRelaxation.textContent = 5;
  dom.sliderStress.value = 5;
  dom.valStress.textContent = 5;
  dom.inputRatingNotes.value = '';

  dom.ratingModal.classList.add('active');
}

async function submitSubjectiveRating() {
  if (!state.pendingRating) return;

  const reqBody = {
    condition: state.pendingRating.condition,
    segment: state.pendingRating.segment,
    attention: parseFloat(dom.sliderAttention.value),
    relaxation: parseFloat(dom.sliderRelaxation.value),
    stress: parseFloat(dom.sliderStress.value),
    notes: dom.inputRatingNotes.value.trim()
  };

  try {
    await fetch('/api/protocol/rating', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody)
    });
    dom.ratingModal.classList.remove('active');
    state.pendingRating = null;
  } catch (e) {
    alert(`Error recording rating: ${e.message}`);
  }
}

function handleProtocolCompleted(data) {
  state.protocol.is_running = false;
  updateProtocolUI();
  dom.hdrActiveSegment.textContent = 'SESSION COMPLETED';
  document.getElementById('step-protocol').classList.add('completed');
  document.getElementById('step-data').classList.add('completed');

  alert('All 6 stages of the experimental protocol are complete! Generating master CSV and per-segment slices.');
  switchTab('data');
  renderSessionExports(data);
  loadPreviousSessions();
}

function renderSessionExports(sessionData) {
  dom.sessionSummaryCard.style.display = 'flex';
  const meta = sessionData.metadata || {};
  const folderName = sessionData.summary?.session_folder_name || '';
  
  dom.btnOpenFolder.setAttribute('data-folder', folderName);
  dom.exportFilesList.innerHTML = '';

  const files = meta.files || {};
  const masterFile = files.master_csv;
  const slices = files.segment_slices || [];
  const ratings = files.ratings_csv;
  const metaJson = files.metadata_json;

  // Master CSV
  if (masterFile) {
    addExportFileItem(folderName, masterFile, 'Master Continuous EEG (250 Hz)');
  }
  // Slices
  slices.forEach(sl => {
    addExportFileItem(folderName, sl, 'Segment Slice');
  });
  // Ratings
  if (ratings) {
    addExportFileItem(folderName, ratings, 'Subjective Ratings (0-10)');
  }
  // Metadata JSON
  if (metaJson) {
    addExportFileItem(folderName, metaJson, 'Session Metadata & Exact Timestamps');
  }
}

function addExportFileItem(folder, filename, label) {
  const div = document.createElement('div');
  div.className = 'export-file-item';
  div.innerHTML = `
    <div>
      <span class="file-name">${filename}</span>
      <span style="font-size: 0.72rem; color: var(--text-dim); margin-left: 8px;">(${label})</span>
    </div>
    <a href="/api/data/download/${folder}/${filename}" download class="btn btn-secondary btn-sm">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg> Download
    </a>
  `;
  dom.exportFilesList.appendChild(div);
}

async function loadPreviousSessions() {
  try {
    const res = await fetch('/api/data/sessions');
    const data = await res.json();
    const sessions = data.sessions || [];

    dom.previousSessionsList.innerHTML = '';
    if (sessions.length === 0) {
      dom.previousSessionsList.innerHTML = '<div style="color: var(--text-dim); font-size: 0.8rem;">No previous recordings found.</div>';
      return;
    }

    sessions.forEach(s => {
      const p = s.metadata?.participant || {};
      const card = document.createElement('div');
      card.className = 'device-item';
      card.innerHTML = `
        <div class="device-meta">
          <span class="device-name">${p.name || 'Volunteer'} [${p.participant_id || s.folder_name}]</span>
          <span class="device-serial mono">Recorded: ${s.created_at} &bull; ${s.files.length} files</span>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="revealFolder('${s.folder_name}')">Reveal Folder</button>
      `;
      dom.previousSessionsList.appendChild(card);
    });
  } catch (e) {
    console.error('Error fetching sessions:', e);
  }
}

window.revealFolder = function(folder) {
  fetch(`/api/data/open_folder/${folder}`, { method: 'POST' });
};
