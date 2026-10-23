/**
 * NeuroRaaga Application Controller
 * Handles UI interactions, REST API calls, WebSocket event dispatching, and state management.
 */

// Global State
console.info(`[NeuroRaaga UI] Build ${document.querySelector('meta[name="neuroraaga-build"]')?.content || 'unknown'}`);
const state = {
  participant: null,
  device: {
    connected: false,
    serial: null,
    name: "None",
    battery: 100,
    streaming: false,
    resistances: { O1: null, O2: null, T3: null, T4: null },
    resistance_readings: { O1: null, O2: null, T3: null, T4: null },
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
  oscilloscope: null,
  activeTab: 'enrollment',
  pendingRating: null,
  processingSession: null,
  processingInspectedSession: null,
  processingSessions: []
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

  // Step 3: Protocol
  dom.protocolTimeline = document.getElementById('protocolTimeline');
  dom.btnStartProtocol = document.getElementById('btnStartProtocol');
  dom.btnAbortProtocol = document.getElementById('btnAbortProtocol');
  dom.protocolTimerDisplay = document.getElementById('protocolTimerDisplay');
  dom.segmentTimerDisplay = document.getElementById('segmentTimerDisplay');
  dom.protocolSpeedSelect = document.getElementById('protocolSpeedSelect');

  // Step 4: Data Storage
  dom.sessionSummaryCard = document.getElementById('sessionSummaryCard');
  dom.exportFilesList = document.getElementById('exportFilesList');
  dom.btnOpenFolder = document.getElementById('btnOpenFolder');
  dom.previousSessionsList = document.getElementById('previousSessionsList');

  // Step 5: Non-destructive offline processing
  dom.processingSessionList = document.getElementById('processingSessionList');
  dom.btnInspectProcessing = document.getElementById('btnInspectProcessing');
  dom.btnRunProcessing = document.getElementById('btnRunProcessing');
  dom.processingStatus = document.getElementById('processingStatus');
  dom.processingValidation = document.getElementById('processingValidation');
  dom.processingResults = document.getElementById('processingResults');
  dom.processingPreviewWrap = document.getElementById('processingPreviewWrap');
  dom.processingPreview = document.getElementById('processingPreview');
  dom.processingUnitAcknowledged = document.getElementById('processingUnitAcknowledged');
  dom.workspaceGrid = document.getElementById('workspaceGrid');
  dom.rightWorkspace = document.querySelector('.right-workspace');

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

  // Step 3: Protocol Controls
  dom.btnStartProtocol.addEventListener('click', startProtocol);
  dom.btnAbortProtocol.addEventListener('click', abortProtocol);
  dom.protocolSpeedSelect.addEventListener('change', async (e) => {
    const duration = parseFloat(e.target.value);
    const response = await fetch('/api/protocol/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ duration_per_segment_sec: duration })
    });
    const result = await response.json();
    state.protocol.duration_per_segment = result.duration_per_segment_sec;
    renderProtocolTimeline(state.protocol.stages);
    dom.protocolTimerDisplay.textContent = formatMMSS(getProtocolDuration(state.protocol.stages));
  });
  // Oscilloscope controls
  dom.selectGain.addEventListener('change', (e) => {
    state.oscilloscope.setGain(e.target.value);
  });
  document.getElementById('btnZoomIn').addEventListener('click', () => state.oscilloscope.zoomIn());
  document.getElementById('btnZoomOut').addEventListener('click', () => state.oscilloscope.zoomOut());
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

  dom.btnInspectProcessing.addEventListener('click', inspectSelectedRecording);
  dom.btnRunProcessing.addEventListener('click', processSelectedRecording);
  dom.processingUnitAcknowledged.addEventListener('change', () => {
    dom.btnRunProcessing.disabled = !dom.processingUnitAcknowledged.checked
      || state.processingInspectedSession !== state.processingSession;
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
  const processingMode = tabId === 'processing';
  dom.workspaceGrid.classList.toggle('processing-mode', processingMode);
  dom.rightWorkspace.style.display = processingMode ? 'none' : 'flex';
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
      break;

    case 'eeg_data':
      if (msg.samples && state.oscilloscope) {
        state.oscilloscope.pushSamples(msg.samples);
        const liveBadge = document.querySelector('.watermark-hz');
        if (liveBadge) liveBadge.textContent = '250 Hz LIVE';
      }
      if (msg.resistances) state.device.resistances = msg.resistances;
      if (msg.resistance_readings) state.device.resistance_readings = msg.resistance_readings;
      if (msg.resistances) {
        for (const [channel, value] of Object.entries(msg.resistances)) {
          renderImpedanceCard(channel, value, state.device.resistance_readings[channel]);
        }
      }
      break;

    case 'device_connected':
      state.oscilloscope.clear();
      document.querySelector('.watermark-hz').textContent = 'WAITING FOR EEG';
      state.device.connected = true;
      state.device.streaming = msg.streaming;
      state.device.serial = msg.serial;
      state.device.name = msg.name;
      if (msg.resistances) state.device.resistances = msg.resistances;
      if (msg.resistance_readings) state.device.resistance_readings = msg.resistance_readings;
      updateDeviceUI();
      break;

    case 'device_disconnected':
      state.oscilloscope.clear();
      state.device.connected = false;
      state.device.streaming = false;
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
    dom.protocolSpeedSelect.value = String(data.protocol.duration_per_segment_sec || 120);
    renderProtocolTimeline(data.protocol.stages || []);
    dom.protocolTimerDisplay.textContent = formatMMSS(getProtocolDuration(data.protocol.stages || []));
    dom.segmentTimerDisplay.textContent = formatMMSS(getStageDuration((data.protocol.stages || [])[0]));
    loadPreviousSessions();
    loadProcessingSessions();
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
let deviceScanError = null;

async function scanDevices() {
  selectedDeviceSerial = null;
  dom.btnScanDevices.textContent = 'Scanning...';
  dom.btnScanDevices.disabled = true;
  dom.deviceListContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">Scanning for Headband Pro devices...</div>';

  try {
    const res = await fetch('/api/device/scan');
    const data = await res.json();
    discoveredDevices = data.devices || [];
    deviceScanError = data.scan_error || null;
    renderDiscoveredDevices();
  } catch (e) {
    dom.deviceListContainer.innerHTML = `<div style="color: var(--rose-alert); font-size: 0.85rem;">Scan error: ${e.message}</div>`;
  } finally {
    dom.btnScanDevices.textContent = 'Scan Devices';
    dom.btnScanDevices.disabled = false;
  }
}

function renderDiscoveredDevices() {
  dom.deviceListContainer.innerHTML = deviceScanError
    ? `<div style="color: var(--rose-alert); font-size: 0.85rem; margin-bottom: 8px;">${deviceScanError}</div>`
    : '';
  if (discoveredDevices.length === 0) {
    dom.deviceListContainer.innerHTML += '<div style="color: var(--text-muted); font-size: 0.85rem;">No Capsule Band device found. Turn on the Headband Pro and scan again.</div>';
    return;
  }

  const preferredIndex = discoveredDevices.findIndex(dev => dev.serial === '820712');
  const selectedIndex = preferredIndex >= 0 ? preferredIndex : 0;
  discoveredDevices.forEach((dev, idx) => {
    const item = document.createElement('div');
    item.className = `device-item ${idx === selectedIndex ? 'selected' : ''}`;
    item.innerHTML = `
      <div class="device-meta">
        <span class="device-name">${dev.name}</span>
        <span class="device-serial mono">SN: ${dev.serial} &bull; ${dev.type}</span>
      </div>
      <button class="btn btn-secondary btn-sm select-btn">Connect</button>
    `;
    item.addEventListener('click', () => {
      document.querySelectorAll('.device-item').forEach(d => d.classList.remove('selected'));
      item.classList.add('selected');
      selectedDeviceSerial = dev.serial;
    });
    item.querySelector('.select-btn').addEventListener('click', (event) => {
      event.stopPropagation();
      document.querySelectorAll('.device-item').forEach(d => d.classList.remove('selected'));
      item.classList.add('selected');
      selectedDeviceSerial = dev.serial;
      connectSelectedDevice();
    });
    dom.deviceListContainer.appendChild(item);
  });
  selectedDeviceSerial = discoveredDevices[selectedIndex].serial;
}

async function connectSelectedDevice() {
  if (!selectedDeviceSerial && discoveredDevices.length > 0) {
    selectedDeviceSerial = discoveredDevices[0].serial;
  }
  if (!selectedDeviceSerial) {
    alert('Scan for a Headband Pro and select it before connecting.');
    return;
  }
  const isSim = selectedDeviceSerial.startsWith('SIM-');
  const serial = selectedDeviceSerial;

  dom.btnConnectDevice.textContent = 'Connecting...';
  dom.btnConnectDevice.disabled = true;

  try {
    const res = await fetch('/api/device/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial: serial, simulated: isSim })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Device connection failed.');
    if (data.connected) {
      state.device.connected = true;
      state.device.serial = data.serial;
      state.device.name = data.name;
      if (data.resistances) state.device.resistances = data.resistances;
      if (data.resistance_readings) state.device.resistance_readings = data.resistance_readings;
      state.device.streaming = data.streaming;
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
  state.oscilloscope.clear();
  state.device.connected = false;
  state.device.streaming = false;
  state.device.serial = null;
  updateDeviceUI();
}

async function runCalibration() {
  dom.btnCalibrate.textContent = 'Checking Signals (3.5s)...';
  dom.btnCalibrate.disabled = true;
  dom.calibStatusBadge.innerHTML = '<span style="color: var(--amber-light);">Analyzing impedance & stability...</span>';

  try {
    const res = await fetch('/api/device/calibrate', { method: 'POST' });
    const responseText = await res.text();
    let result = {};
    try {
      result = responseText ? JSON.parse(responseText) : {};
    } catch {
      if (!res.ok) throw new Error(responseText || `Calibration request failed (${res.status}).`);
      throw new Error('The server returned an unreadable calibration response.');
    }
    if (!res.ok) throw new Error(result.detail || result.message || `Calibration request failed (${res.status}).`);
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
        const measured = info.open_circuit ? 'OPEN (>1000 kΩ)' : info.measured_impedance_kohm;
        valEl.textContent = measured === 'OPEN (>1000 kΩ)' ? measured : measured == null ? (info.impedance_kohm == null ? 'No reading' : `${info.impedance_kohm} kΩ`) : `${Number(measured).toFixed(1)} kΩ`;
        statEl.textContent = info.status === 'NO READING' && info.signal_quality
          ? `NO IMPEDANCE · SIGNAL ${info.signal_quality}` : info.status;
        const statusClass = info.status === 'GREEN' ? 'good' : info.status === 'ORANGE' ? 'fair' : 'poor';
        badge.className = `electrode-badge ${statusClass}`;
        statEl.className = `electrode-status ${statusClass}`;
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
  if (deviceState.streaming && state.oscilloscope && state.oscilloscope.totalSamplesReceived === 0) {
    const liveBadge = document.querySelector('.watermark-hz');
    if (liveBadge) liveBadge.textContent = 'WAITING FOR EEG';
  }
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
  if (!isConn) {
    dom.calibStatusBadge.innerHTML = '<span style="font-size: 0.8rem;">Device not connected. Connect Headband Pro to inspect electrodes.</span>';
  } else if (!state.device.calibration && !dom.btnCalibrate.disabled) {
    dom.calibStatusBadge.innerHTML = '<span style="font-size: 0.8rem;">Headband connected. Run calibration to inspect electrode contact and signal quality.</span>';
  }

  // Update Impedance Display
  if (state.device.resistances) {
    for (const [ch, val] of Object.entries(state.device.resistances)) {
      renderImpedanceCard(ch, val, state.device.resistance_readings?.[ch]);
    }
  }
}

function renderImpedanceCard(channel, valueKohm, measuredKohm) {
  const badge = document.getElementById(`badge-${channel}`);
  const valEl = document.getElementById(`val-${channel}`);
  const statEl = document.getElementById(`stat-${channel}`);
  if (!badge || !valEl || !statEl) return;

  const value = Number(valueKohm);
  const valid = valueKohm !== null && valueKohm !== undefined && Number.isFinite(value) && value >= 0;
  const status = valid ? (value >= 1000 ? 'POOR' : value >= 500 ? 'ORANGE' : 'GREEN') : 'NO READING';
  const colorClass = status === 'GREEN' ? 'good' : status === 'ORANGE' ? 'fair' : 'poor';
  const measured = Number(measuredKohm);
  const hasMeasured = measuredKohm !== null && measuredKohm !== undefined && Number.isFinite(measured) && measured >= 0;
  valEl.textContent = measuredKohm === 'OPEN'
    ? 'OPEN (>1000 kΩ)'
    : hasMeasured
      ? `${measured.toFixed(1)} kΩ`
      : valid ? `${Math.min(value, 1000).toFixed(1)} kΩ` : 'No reading';
  statEl.textContent = status;
  badge.className = `electrode-badge ${colorClass}`;
  statEl.className = `electrode-status ${colorClass}`;
}

// ----------------- Step 3: Protocol Execution -----------------
function getStageDuration(stage) {
  if (!stage) return 30;
  if (state.protocol.duration_per_segment === 120) return Number(stage.default_duration_sec || 30);
  return state.protocol.duration_per_segment * (stage.is_audio ? 2 : 1);
}

function getProtocolDuration(stages) {
  return (stages || []).reduce((total, stage) => total + getStageDuration(stage), 0);
}

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
      <span class="stage-time">${formatMMSS(getStageDuration(stg))}</span>
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

  if (!state.device.connected || !state.device.streaming || (state.device.serial || '').startsWith('SIM-')) {
    alert('Connect the physical Headband Pro and confirm EEG streaming is active before starting.');
    switchTab('device');
    return;
  }

  try {
    const res = await fetch('/api/protocol/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant: state.participant })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Protocol could not start.');
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

async function loadProcessingSessions() {
  try {
    const response = await fetch('/api/data/sessions');
    const data = await response.json();
    state.processingSessions = (data.sessions || []).filter(session =>
      (session.files || []).some(name => /_master\.csv$/i.test(name) || /_segment_.*\.csv$/i.test(name))
    );
    dom.processingSessionList.innerHTML = '';
    if (!state.processingSessions.length) {
      dom.processingSessionList.textContent = 'No EEG recordings are available for processing.';
      return;
    }

    state.processingSessions.forEach((session, index) => {
      const participant = session.metadata?.participant || {};
      const label = document.createElement('label');
      label.className = 'device-item';
      label.style.cursor = 'pointer';
      label.style.alignItems = 'flex-start';
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'processingSession';
      radio.value = session.folder_name;
      radio.style.marginTop = '4px';
      radio.addEventListener('change', () => {
        state.processingSession = session.folder_name;
        state.processingInspectedSession = null;
        dom.processingUnitAcknowledged.checked = false;
        dom.btnInspectProcessing.disabled = false;
        dom.btnRunProcessing.disabled = true;
        dom.processingValidation.innerHTML = '';
        dom.processingResults.innerHTML = '';
        dom.processingStatus.textContent = '';
        dom.processingPreviewWrap.style.display = 'none';
      });
      const details = document.createElement('span');
      details.style.display = 'flex';
      details.style.flexDirection = 'column';
      const title = document.createElement('strong');
      title.textContent = `${participant.name || 'Volunteer'} (${participant.participant_id || session.folder_name})`;
      const sub = document.createElement('span');
      sub.className = 'device-serial mono';
      sub.textContent = `Recorded ${session.created_at} · ${(session.files || []).filter(name => /_master\.csv$|_segment_.*\.csv$/i.test(name)).length} EEG CSVs`;
      details.append(title, sub);
      label.append(radio, details);
      dom.processingSessionList.appendChild(label);
      if (index === 0) radio.checked = false;
    });
    state.processingSession = null;
    dom.btnInspectProcessing.disabled = true;
  } catch (error) {
    dom.processingSessionList.textContent = `Could not load recordings: ${error.message}`;
  }
}

async function inspectSelectedRecording() {
  if (!state.processingSession) return;
  dom.btnInspectProcessing.disabled = true;
  dom.btnRunProcessing.disabled = true;
  dom.processingStatus.textContent = 'Checking timestamps, sample rate, channel labels, missing values, and EEG files…';
  dom.processingValidation.innerHTML = '';
  dom.processingResults.innerHTML = '';
  dom.processingPreviewWrap.style.display = 'none';
  try {
    const response = await fetch(`/api/data/processing/inspect/${encodeURIComponent(state.processingSession)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Recording inspection failed.');
    renderProcessingInspection(result);
    state.processingInspectedSession = state.processingSession;
    const responseStatus = result.filter_response_validation?.passed ? 'filter response passed' : 'filter response failed';
    dom.processingStatus.textContent = `Inspected ${result.file_count} EEG CSV file(s); ${responseStatus}. Unit status: UNCONFIRMED. Acknowledge this before creating outputs.`;
    dom.btnRunProcessing.disabled = !dom.processingUnitAcknowledged.checked;
  } catch (error) {
    dom.processingStatus.textContent = error.message;
  } finally {
    dom.btnInspectProcessing.disabled = false;
  }
}

function renderProcessingInspection(result) {
  const heading = document.createElement('div');
  heading.className = 'form-label';
  heading.textContent = `Recording checks · ${result.folder_name}`;
  dom.processingValidation.appendChild(heading);
  let preview = null;
  result.files.forEach(file => {
    const card = document.createElement('div');
    card.className = 'device-select-box';
    card.style.marginTop = '8px';
    const title = document.createElement('strong');
    title.textContent = file.filename;
    card.appendChild(title);
    if (file.error) {
      const error = document.createElement('div');
      error.style.color = 'var(--rose-alert)';
      error.textContent = file.error;
      card.appendChild(error);
    } else {
      const sampling = file.sampling || {};
      const info = document.createElement('div');
      info.style.fontSize = '0.78rem';
      info.style.color = 'var(--text-muted)';
      const missingTotal = Object.values(file.missing_values_by_channel || {}).reduce((sum, count) => sum + count, 0);
      info.textContent = `${sampling.rows} rows · ${sampling.sampling_rate_hz ?? 'unknown'} Hz (target 250) · ${sampling.duration_sec}s · Channels: ${(file.channel_names || []).join(', ')} · Missing EEG values: ${missingTotal} · Timestamp gaps >6 ms: ${sampling.gaps_over_6ms}`;
      card.appendChild(info);
      const screen = file.artifact_screen || {};
      const artifactInfo = document.createElement('div');
      artifactInfo.style.fontSize = '0.76rem';
      artifactInfo.style.color = 'var(--amber-light)';
      const perChannel = Object.entries(screen.by_channel || {}).map(([channel, stats]) => `${channel}: ${stats.flagged_percent}% (${stats.flagged_samples} samples)`).join(' · ');
      artifactInfo.textContent = `Rule-based screen (review required): ${perChannel || `${screen.flagged_percent || 0}% overall`}. Per-channel rule counts are in the report.`;
      card.appendChild(artifactInfo);
      const intervalMap = screen.longest_intervals_by_channel || {};
      const t4Intervals = intervalMap.T4 || intervalMap.t4 || [];
      if (t4Intervals.length) {
        const intervalBox = document.createElement('div');
        intervalBox.style.cssText = 'font-size:0.76rem;color:var(--text-muted);margin-top:6px;line-height:1.45';
        intervalBox.textContent = `T4 longest flagged intervals (seconds from file start): ${t4Intervals.slice(0, 5).map(item => `${item.start_sec}–${item.end_sec}s (${item.duration_sec}s; ${(item.reasons || []).join(', ')})`).join(' · ')}`;
        card.appendChild(intervalBox);
      }
      (file.warnings || []).forEach(warning => {
        const line = document.createElement('div');
        line.style.color = 'var(--amber-light)';
        line.style.fontSize = '0.76rem';
        line.textContent = `Check: ${warning}`;
        card.appendChild(line);
      });
      if (!preview && file.preview && /_master\.csv$/i.test(file.filename)) preview = file.preview;
    }
    dom.processingValidation.appendChild(card);
  });
  const validation = result.filter_response_validation;
  if (validation) {
    const validationCard = document.createElement('div');
    validationCard.className = 'device-select-box';
    validationCard.style.marginTop = '10px';
    const title = document.createElement('strong');
    title.textContent = `Filter response validation: ${validation.passed ? 'PASS' : 'FAIL'} (maximum gain error ${validation.max_absolute_error})`;
    validationCard.appendChild(title);
    const responseList = document.createElement('div');
    responseList.style.cssText = 'font-size:0.75rem;color:var(--text-muted);margin-top:6px';
    responseList.textContent = (validation.points || []).map(point => `${point.frequency_hz} Hz: expected ${point.expected_gain}, measured ${point.measured_gain}`).join(' · ');
    validationCard.appendChild(responseList);
    dom.processingValidation.appendChild(validationCard);
  }
  const units = document.createElement('div');
  units.style.cssText = 'margin-top:8px;color:var(--rose-alert);font-size:0.8rem';
  units.textContent = `Physical units: ${result.signal_units?.status || 'UNCONFIRMED'} — ${result.signal_units?.label || 'raw SDK units; do not label as microvolts.'}`;
  dom.processingValidation.appendChild(units);

  const previous = result.previous_processing;
  if (previous) {
    const priorCard = document.createElement('div');
    priorCard.className = 'device-select-box';
    priorCard.style.marginTop = '10px';
    const priorText = document.createElement('div');
    priorText.textContent = `Existing processed output: ${previous.folder_name}. This is the existing filtered file preview. Its report ${previous.has_filter_validation ? 'contains' : 'does not contain'} a measured response validation; unit status is ${previous.unit_status}.`;
    const reveal = document.createElement('button');
    reveal.className = 'btn btn-secondary btn-sm';
    reveal.textContent = 'Reveal Existing Output Folder';
    reveal.addEventListener('click', () => revealProcessingFolder(result.folder_name, previous.folder_name));
    priorCard.append(priorText, reveal);
    dom.processingValidation.appendChild(priorCard);
    if (previous.preview) preview = previous.preview;
  }
  if (preview) {
    dom.processingPreviewWrap.style.display = 'block';
    drawProcessingPreview(preview);
  }
}

async function processSelectedRecording() {
  if (!state.processingSession || !dom.processingUnitAcknowledged.checked
      || state.processingInspectedSession !== state.processingSession) return;
  const proceed = window.confirm(`Create new column-wise 0.5–40 Hz outputs for ${state.processingSession}? Physical units are unconfirmed, and outputs will not be approved for segmentation. Original CSVs remain unchanged.`);
  if (!proceed) return;
  dom.btnRunProcessing.disabled = true;
  dom.btnInspectProcessing.disabled = true;
  dom.processingStatus.textContent = 'Filtering the selected recording and writing new output files…';
  try {
    const response = await fetch('/api/data/processing/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_folder: state.processingSession })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Signal processing failed.');
    renderProcessingResults(result);
    if (result.preview) {
      dom.processingPreviewWrap.style.display = 'block';
      drawProcessingPreview(result.preview);
    }
    dom.processingStatus.textContent = `Finished. New files are in ${result.source_folder}/${result.processing_folder}. Filter response: PASS. Physical unit: UNCONFIRMED. This output is not approved for segmentation.`;
  } catch (error) {
    dom.processingStatus.textContent = error.message;
  } finally {
    dom.btnRunProcessing.disabled = !dom.processingUnitAcknowledged.checked
      || state.processingInspectedSession !== state.processingSession;
    dom.btnInspectProcessing.disabled = false;
  }
}

function renderProcessingResults(result) {
  dom.processingResults.innerHTML = '';
  const title = document.createElement('div');
  title.className = 'form-label';
  title.textContent = 'New processing outputs';
  dom.processingResults.appendChild(title);
  const addDownload = (filename, label) => {
    const row = document.createElement('div');
    row.className = 'export-file-item';
    const name = document.createElement('span');
    name.className = 'file-name';
    name.textContent = `${filename} · ${label}`;
    const link = document.createElement('a');
    link.className = 'btn btn-secondary btn-sm';
    link.textContent = 'Download';
    link.href = `/api/data/processing/download/${encodeURIComponent(result.source_folder)}/${encodeURIComponent(result.processing_folder)}/${encodeURIComponent(filename)}`;
    link.download = filename;
    row.append(name, link);
    dom.processingResults.appendChild(row);
  };
  result.files.forEach(file => {
    const cleanPercent = file.rows ? (100 * file.clean_rows / file.rows).toFixed(1) : '0.0';
    const summary = document.createElement('div');
    summary.style.cssText = 'font-size:0.78rem;color:var(--text-muted);margin:8px 0 4px';
    const perChannel = Object.entries(file.clean_samples_by_channel || {}).map(([channel, count]) => `${channel} ${count} valid`).join(' · ');
    summary.textContent = `${file.source_file}: ${file.sampling?.sampling_rate_hz ?? ''} Hz · all ${file.rows} timestamps retained · ${file.flagged_rows} rows have ≥1 flagged channel · ${file.clean_rows} rows have no flags on any channel (${cleanPercent}%) · usable samples by channel: ${perChannel}`;
    dom.processingResults.appendChild(summary);
    addDownload(file.filtered_file, 'filtered, all rows + flags');
    addDownload(file.clean_file, 'filtered, all timestamps; flagged channel values blank');
  });
  (result.skipped_files || []).forEach(file => {
    const skipped = document.createElement('div');
    skipped.style.color = 'var(--rose-alert)';
    skipped.textContent = `Skipped ${file.filename}: ${file.error}`;
    dom.processingResults.appendChild(skipped);
  });
  addDownload('processing_report.json', 'settings and quality report');
  const reveal = document.createElement('button');
  reveal.className = 'btn btn-secondary btn-sm';
  reveal.textContent = 'Reveal Output Folder';
  reveal.addEventListener('click', () => revealProcessingFolder(result.source_folder, result.processing_folder));
  dom.processingResults.appendChild(reveal);
}

function revealProcessingFolder(sessionFolder, processingFolder) {
  fetch(`/api/data/processing/open_folder/${encodeURIComponent(sessionFolder)}/${encodeURIComponent(processingFolder)}`, { method: 'POST' })
    .then(async response => {
      const result = await response.json();
      if (!response.ok || !result.opened) throw new Error(result.error || 'Could not open output folder.');
      dom.processingStatus.textContent = `Opened ${result.path}`;
    })
    .catch(error => { dom.processingStatus.textContent = error.message; });
}

function drawProcessingPreview(preview) {
  const canvas = dom.processingPreview;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width) return;
  const dpr = window.devicePixelRatio || 1;
  const height = 360;
  canvas.width = Math.floor(rect.width * dpr);
  canvas.height = Math.floor(height * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, height);
  const channels = Object.entries(preview.channels || {});
  if (!channels.length) return;
  const previewTitle = document.getElementById('processingPreviewTitle');
  if (previewTitle) {
    const start = Number.isFinite(preview.start_sec) ? ` · focused window starts at ${preview.start_sec}s` : '';
    previewTitle.textContent = `Raw vs filtered · ${preview.seconds || 5}-second diagnostic window${start}`;
  }
  const top = 8;
  const left = 48;
  const right = 8;
  const plotWidth = rect.width - left - right;
  const laneHeight = (height - top - 8) / channels.length;
  channels.forEach(([name, series], lane) => {
    const yTop = top + lane * laneHeight;
    const center = yTop + laneHeight / 2;
    const raw = series.raw || [];
    const filtered = series.filtered || [];
    const centerOf = values => {
      const finite = values.filter(Number.isFinite).sort((a, b) => a - b);
      return finite.length ? finite[Math.floor(finite.length / 2)] : 0;
    };
    const rawCenter = centerOf(raw);
    const filteredCenter = centerOf(filtered);
    const deviations = raw.map(value => Number.isFinite(value) ? Math.abs(value - rawCenter) : NaN)
      .concat(filtered.map(value => Number.isFinite(value) ? Math.abs(value - filteredCenter) : NaN))
      .filter(Number.isFinite).sort((a, b) => a - b);
    const scale = Math.max(1e-12, deviations[Math.min(deviations.length - 1, Math.floor(deviations.length * 0.98))] || 0) * 1.15;
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.22)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, center);
    ctx.lineTo(rect.width - right, center);
    ctx.stroke();
    ctx.fillStyle = '#e2e8f0';
    ctx.font = '12px monospace';
    ctx.fillText(name, 8, center - 3);
    const flagged = series.flagged || [];
    ctx.fillStyle = 'rgba(244, 63, 94, 0.2)';
    flagged.forEach((isFlagged, index) => {
      if (!isFlagged) return;
      const x = left + (flagged.length <= 1 ? 0 : index / (flagged.length - 1) * plotWidth);
      ctx.fillRect(x, yTop + 1, Math.max(1, plotWidth / flagged.length), laneHeight - 2);
    });
    const drawLine = (values, centerValue, color, lineWidth) => {
      ctx.beginPath();
      let drawing = false;
      values.forEach((value, index) => {
        if (!Number.isFinite(value)) { drawing = false; return; }
        const x = left + (values.length <= 1 ? 0 : index / (values.length - 1) * plotWidth);
        const deviation = Math.max(-scale, Math.min(scale, value - centerValue));
        const y = center - (deviation / scale) * (laneHeight * 0.42);
        if (!drawing) { ctx.moveTo(x, y); drawing = true; }
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      ctx.stroke();
    };
    drawLine(raw, rawCenter, 'rgba(203, 213, 225, 0.65)', 1);
    drawLine(filtered, filteredCenter, '#22d3ee', 1.4);
  });
}

window.revealFolder = function(folder) {
  fetch(`/api/data/open_folder/${folder}`, { method: 'POST' });
};
