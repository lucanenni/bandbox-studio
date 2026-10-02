'use strict';

// Local drafts never touch the amp. Every write starts at a labeled button.
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const friendly = (value) => String(value ?? '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
const pad = (value) => typeof value === 'number' ? String(value).padStart(2, '0') : '—';
const ui = {
  token: '', catalog: { slots: [], models: [] }, controls: {}, state: {},
  focusedId: null, slotId: 3, filter: 'all', tab: 'tone', toolGroup: 'drum', busy: false,
  parameterDrafts: new Map(), modelDrafts: new Map(), toolDrafts: new Map(), readings: new Map(),
  mixerDrafts: new Map(), mixerReadings: new Map(), mixerInputs: new Map(), dialogAction: null,
};
const slotNames = { GAT: 'Gate', COM: 'Compressor', WAH: 'Drive & wah', AMP: 'Amplifier', CAB: 'Cabinet', MOD: 'Modulation', DLY: 'Delay', RVB: 'Reverb' };
const toolNames = {
  drum_enabled: 'Drum machine', drum_bpm: 'Tempo', drum_pattern: 'Pattern',
  metronome_enabled: 'Metronome', metronome_bpm: 'Tempo', metronome_meter: 'Time signature',
  tuner_enabled: 'Tuner', tuner_mode: 'String mode', tuner_instrument: 'Instrument', tuner_reference_hz: 'Reference pitch',
  tuner_tuning: 'Tuning', tuner_chromatic: 'Chromatic mode', looper_playback: 'Playback',
  looper_recording_state: 'Recording', looper_recorded_length: 'Recorded length', looper_layer_count: 'Layers',
  looper_bars: 'Bars', looper_position_ms: 'Playback position', looper_estimated_duration_ms: 'Estimated duration',
  looper_time_left_ms: 'Time remaining', looper_signal_interval: 'Signal interval',
};
const toolDescriptions = {
  drum: ['Drum machine', 'A backing beat for finding your pocket. Pick a pattern, set the tempo, and play.'],
  metronome: ['Keep good time.', 'A steady pulse, right from your amp. Choose the tempo and time signature that suit your practice.'],
  tuner: ['Get in tune.', 'Set the BandBox’s built-in tuner. Readings here are settings; use the amp’s display to tune each string.'],
  looper: ['Build something worth repeating.', 'Control playback or begin a new freehand loop. Recording keeps going until you press Stop recording.'],
};
const ampIcon = '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true"><rect x="4" y="7" width="24" height="21" rx="2"/><path d="M11 7V4h10v3M4 13h24M9 28v2m14-2v2M8 17h16M8 21h16M8 25h16"/><circle cx="9" cy="10" r=".7"/><circle cx="13" cy="10" r=".7"/><circle cx="23" cy="10" r=".7"/></svg>';

function current() {
  const source = ui.state.current;
  return source?.preset_info ?? source?.preset ?? source ?? null;
}
function presets() { return Array.isArray(ui.state.presets) ? ui.state.presets : []; }
function focused() { return presets().find((p) => p.preset_id === ui.focusedId) ?? current(); }
function currentIsFocused() { return current()?.preset_id === ui.focusedId; }
function canEdit() { return !!ui.state.editable && currentIsFocused(); }
function slotById(id) { return currentIsFocused() ? current()?.slots?.find((slot) => slot.slot_id === id) : null; }
function modelById(id) { return ui.catalog.models.find((model) => model.model_id === id); }
function slotModel(slot) { return slot ? modelById(`${slot.algorithm_id}:${slot.config_id}`) : null; }
function presetNumber(preset) { return presets().find((p) => p.preset_id === preset?.preset_id)?.display_number ?? preset?.display_number ?? '—'; }
function draftKey(parameterId) { return `${ui.focusedId}:${ui.slotId}:${parameterId}`; }
function draftCount() { return ui.parameterDrafts.size + ui.modelDrafts.size; }
function notify(message, type = '') {
  const notice = $('#notice');
  notice.textContent = message;
  notice.className = `notice ${type}`;
  notice.hidden = !message;
}
function setBusy(value, label = 'Talking to your amp…') {
  ui.busy = value;
  $('#busy-strip').hidden = !value;
  $('#busy-label').textContent = label;
  document.body.setAttribute('aria-busy', String(value));
  applyDisabledState();
}
function applyDisabledState() {
  $$('[data-request]').forEach((button) => { button.disabled = ui.busy || button.dataset.disabled === 'true'; });
  $$('[data-edit-input]').forEach((input) => { input.disabled = ui.busy || !canEdit(); });
  $$('[data-mixer], [data-tool-input], [data-preset], #looper-bars, #looper-mode').forEach((input) => { input.disabled = ui.busy; });
  $('#preset-name').disabled = ui.busy;
  $('#close-dialog').disabled = ui.busy;
  $('#cancel-dialog').disabled = ui.busy;
}
function updateState(next) {
  if (!next) return;
  ui.state = next;
  if (ui.focusedId === null || !presets().some((p) => p.preset_id === ui.focusedId)) ui.focusedId = current()?.preset_id ?? presets()[0]?.preset_id ?? null;
}
async function send(action, args = {}) {
  let response;
  try {
    response = await fetch('/api/action', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': ui.token },
      body: JSON.stringify({ action, args }),
    });
  } catch (_) { throw new Error('The local connection stopped. Your drafts are still here. Reopen BandBox Studio, then read the amp before making more changes.'); }
  const payload = await response.json().catch(() => ({ ok: false, error: 'The local bridge returned an unreadable reply.' }));
  updateState(payload.state);
  if (!response.ok || !payload.ok || payload.result?.verified === false) {
    const error = new Error(payload.error || payload.result?.error || 'The amp did not confirm the change. Read its current state before trying again.');
    error.result = payload.result;
    throw error;
  }
  return payload.result ?? {};
}
async function run(label, operation, success) {
  if (ui.busy) return;
  setBusy(true, label);
  try {
    const result = await operation();
    if (success) notify(typeof success === 'function' ? success(result) : success, 'success');
    return result;
  } catch (error) {
    notify(error.message, 'error');
    throw error;
  } finally {
    setBusy(false);
    render();
  }
}
function eventRun(label, operation, success) { void run(label, operation, success).catch(() => {}); }
function parameterValue(slot, definition) {
  const parameter = slot?.parameters?.find((p) => p.parameter_id === definition.parameter_id);
  if (!parameter || !Number.isFinite(parameter.value)) return null;
  return Number((parameter.value / (definition.wire_multiplier || 1)).toFixed(4));
}
function setFill(input) {
  const ratio = (Number(input.value) - Number(input.min)) / (Number(input.max) - Number(input.min));
  input.style.setProperty('--fill', `${Math.max(0, Math.min(100, ratio * 100))}%`);
}
function render() {
  renderHeader(); renderPresets(); renderChain(); renderEditor(); renderMixer(); renderTools();
  applyDisabledState();
}
function renderHeader() {
  const preset = focused();
  const native = current();
  const isCurrent = currentIsFocused();
  $('#connection-dot').className = `status-dot${ui.state.connected ? ' connected' : ''}`;
  $('#connection-label').textContent = ui.state.connected ? 'BandBox connected' : 'Amp not connected';
  $('#sound-name').textContent = preset?.name ?? 'Your next great sound.';
  $('#preset-number').textContent = pad(presetNumber(preset));
  $('#sound-kind').textContent = preset ? (preset.preset_id >= 51 ? 'YOUR PRESET' : 'FACTORY PRESET') : 'SAVED SOUND';
  const currentName = slotModel(native?.slots?.find((slot) => slot.slot_id === 3))?.name;
  $('#sound-subtitle').textContent = !preset ? 'Read your amp to find your tone.' : !isCurrent ? 'Choose Load saved sound to play and edit this preset.' : ui.state.editable ? `${currentName ?? 'Your sound'} · Ready to shape on your BandBox` : ui.state.dirty ? 'Unsaved sound changes remain. The editing connection needs to be renewed.' : 'Saved settings shown. Load this sound to begin editing.';
  const load = $('#load-preset');
  load.textContent = isCurrent && ui.state.editable ? 'Reload saved sound' : 'Load saved sound';
  load.dataset.disabled = String(!preset);
  $('#save-preset').dataset.disabled = String(!canEdit() || !preset || preset.preset_id < 51 || !ui.state.dirty);
  $('#save-preset').title = preset?.preset_id < 51 ? 'Use Save as a new preset to keep a factory sound.' : 'Save verified changes on the amp';
  $('#new-preset').dataset.disabled = String(!native);
  $('#copy-preset').dataset.disabled = String(!native || !isCurrent);
  $('#rename-preset').dataset.disabled = String(!preset || preset.preset_id < 51 || !isCurrent);
  $('#save-as').dataset.disabled = String(!canEdit());
  const status = $('#edit-status');
  status.textContent = draftCount() ? `${draftCount()} unapplied ${draftCount() === 1 ? 'edit' : 'edits'}` : ui.state.dirty ? 'Changes not saved' : canEdit() ? 'Sound loaded' : 'Saved settings';
  status.className = `edit-status${ui.state.dirty || draftCount() ? ' dirty' : ''}`;
}
function renderPresets() {
  const query = $('#preset-search').value.trim().toLowerCase();
  const list = presets().filter((p) => (ui.filter !== 'user' || p.preset_id >= 51) && (!query || `${p.name} ${p.display_number}`.toLowerCase().includes(query)));
  $('#preset-count').textContent = presets().length || '—';
  $('#preset-list').innerHTML = list.length ? list.map((p) => `<button class="preset-item${p.preset_id === ui.focusedId ? ' selected' : ''}" data-preset="${p.preset_id}" aria-pressed="${p.preset_id === ui.focusedId}" title="Choose ${escapeHTML(p.name)}"><span class="preset-num">${pad(p.display_number)}</span><span class="preset-text"><strong>${escapeHTML(p.name)}</strong><small>${p.preset_id >= 51 ? 'Your preset' : 'Factory sound'}</small></span>${p.preset_id === current()?.preset_id ? '<span class="preset-playing" aria-label="Selected on the amp">●</span>' : ''}</button>`).join('') : `<div class="empty-library">${presets().length ? 'No sounds match this search.' : 'Press the refresh button to read your amp.'}</div>`;
}
function renderChain() {
  $('#signal-chain').innerHTML = ui.catalog.slots.map((definition) => {
    const slot = slotById(definition.slot_id);
    const model = slotModel(slot);
    return `<button class="effect-block${definition.slot_id === ui.slotId ? ' selected' : ''}${slot?.bypass_raw !== 0 ? ' bypassed' : ''}" data-slot="${definition.slot_id}" aria-pressed="${definition.slot_id === ui.slotId}" title="${escapeHTML(slotNames[definition.key] ?? definition.key)}"><span class="block-top"><strong>${escapeHTML(definition.key)}</strong><span class="block-dot"></span></span><span class="block-name">${escapeHTML(model?.name ?? slotNames[definition.key])}</span><span class="block-state">${slot ? slot.bypass_raw === 0 ? 'Active' : 'Bypassed' : '—'}</span></button>`;
  }).join('');
}
function renderEditor() {
  const root = $('#editor');
  const slot = slotById(ui.slotId);
  const definition = ui.catalog.slots.find((s) => s.slot_id === ui.slotId);
  if (!slot || !definition) {
    root.innerHTML = '<div class="empty-state"><span class="empty-guitar" aria-hidden="true">♫</span><h3>Make room for your next sound.</h3><p>Choose a preset and press Load saved sound to start shaping it.</p></div>';
    return;
  }
  const model = slotModel(slot);
  const modelId = `${slot.algorithm_id}:${slot.config_id}`;
  const modelDraftKey = `${ui.focusedId}:${ui.slotId}`;
  const modelDraft = ui.modelDrafts.get(modelDraftKey) ?? modelId;
  const options = ui.catalog.models.filter((m) => m.slot_id === ui.slotId);
  const active = slot.bypass_raw === 0;
  const available = (model?.parameters ?? []).filter((p) => parameterValue(slot, p) !== null);
  const lockMessage = ui.state.dirty ? 'Your last sound changes are still shown. The editing session needs to be renewed; reloading will replace unsaved changes with the saved sound.' : 'These are the saved settings. Load the sound before editing; loading replaces any unsaved changes on the amp.';
  root.innerHTML = `<div class="editor-top"><div class="editor-title"><div class="editor-icon">${ampIcon}</div><div><p class="eyebrow">${escapeHTML(slotNames[definition.key] ?? definition.key).toUpperCase()} · ${escapeHTML(definition.key)}</p><h3>${escapeHTML(model?.name ?? 'Unknown model')}</h3></div></div><button class="block-power${active ? ' active' : ''}" id="effect-power" role="switch" aria-checked="${active}" data-request data-disabled="${!canEdit()}" title="${active ? 'Bypass this effect' : 'Enable this effect'}"><span>${active ? 'Active' : 'Bypassed'}</span><span class="toggle-track"></span></button></div>${!canEdit() ? `<div class="editor-lock"><span>${escapeHTML(lockMessage)}</span></div>` : ''}<div class="model-row"><label for="effect-model">Model</label><select id="effect-model" class="styled-select" data-edit-input>${!model ? `<option value="${escapeHTML(modelId)}">Current model (unlisted)</option>` : ''}${options.map((m) => `<option value="${escapeHTML(m.model_id)}"${m.model_id === modelDraft ? ' selected' : ''}>${escapeHTML(m.name)}</option>`).join('')}</select><button id="apply-model" class="button compact" data-request data-disabled="${!canEdit() || modelDraft === modelId}">Apply model</button></div><div class="parameter-grid">${available.map((p) => {
    const currentValue = parameterValue(slot, p);
    const key = draftKey(p.parameter_id);
    const value = ui.parameterDrafts.get(key) ?? currentValue;
    const dirty = ui.parameterDrafts.has(key) && value !== currentValue;
    const label = p.name || `Parameter ${p.parameter_id + 1}`;
    return `<div class="parameter-card" data-parameter-card="${p.parameter_id}"><div class="parameter-label"><label for="number-${p.parameter_id}">${escapeHTML(label)}</label><input id="number-${p.parameter_id}" class="parameter-number" data-edit-input data-parameter="${p.parameter_id}" type="number" min="${p.ui_min}" max="${p.ui_max}" step="${p.ui_step || 1}" value="${value}" aria-label="${escapeHTML(label)} value"></div><input id="range-${p.parameter_id}" class="range" data-edit-input data-parameter="${p.parameter_id}" type="range" min="${p.ui_min}" max="${p.ui_max}" step="${p.ui_step || 1}" value="${value}" aria-label="${escapeHTML(label)} slider"><div class="parameter-bottom"><span>${p.ui_min} — ${p.ui_max}${p.unit ? ` ${escapeHTML(p.unit)}` : ''}</span><button class="button compact${dirty ? ' has-draft' : ''}" data-apply-parameter="${p.parameter_id}" data-request data-disabled="${!canEdit() || !dirty}">Apply</button></div></div>`;
  }).join('')}</div>${!available.length ? '<p class="editor-note">No adjustable values were returned for this block. Choose a supported model to continue.</p>' : ''}`;
  $$('#editor .range').forEach(setFill);
}
function renderMixer() {
  $('#mixer').innerHTML = ['master', 1, 2, 3, 4].map((key) => {
    const saved = ui.mixerReadings.get(String(key));
    const draft = ui.mixerDrafts.get(String(key));
    const hasValue = draft !== undefined || Number.isFinite(saved?.value);
    const value = draft ?? saved?.value ?? 0;
    const input = ui.mixerInputs.get(String(key));
    const label = key === 'master' ? 'Master' : `Channel ${key}`;
    const detail = key === 'master' ? 'Overall amp level' : input ? input.plugged ? friendly(input.input_type_name) : 'No input connected' : key === 3 ? 'Guitar' : 'Read to check input';
    return `<article class="mixer-card${key === 'master' ? ' master' : ''}"><p class="eyebrow">${key === 'master' ? 'THE BIG PICTURE' : `CH ${key}`}</p><h3>${label}</h3><div class="mixer-input-name">${escapeHTML(detail)}</div><div class="mixer-level">${hasValue ? value : '—'}<small>/32</small></div><input class="range" data-mixer="${key}" type="range" min="0" max="32" step="1" value="${value}" aria-label="${label} level slider"><input class="parameter-number" data-mixer="${key}" type="number" min="0" max="32" step="1" value="${hasValue ? value : ''}" placeholder="—" aria-label="${label} level"><div class="mixer-actions"><button class="button subtle" data-read-mixer="${key}" data-request>Read level</button><button class="button" data-apply-mixer="${key}" data-request data-disabled="${draft === undefined}">Apply</button></div></article>`;
  }).join('');
  $$('#mixer .range').forEach(setFill);
}
function displayReading(reading) {
  if (!reading) return 'Not read yet';
  if (reading.name) return friendly(reading.name);
  if (typeof reading.value === 'boolean') return reading.value ? 'On' : 'Off';
  if (reading.unit === 'ms') return `${(reading.value / 1000).toFixed(1)} sec`;
  if (reading.value !== undefined) return `${reading.value}${reading.unit && !['not_verified', 'raw_mixer_steps'].includes(reading.unit) ? ` ${reading.unit}` : ''}`;
  if (reading.plugged !== undefined) return reading.plugged ? friendly(reading.input_type_name) : 'No input';
  return 'Read successfully';
}
function toolInput(name, schema) {
  const reading = ui.readings.get(name);
  const value = ui.toolDrafts.has(name) ? ui.toolDrafts.get(name) : schema.type === 'string' ? reading?.name : reading?.value;
  if (schema.type === 'boolean' || schema.enum) {
    const choices = schema.type === 'boolean' ? [{ value: 'true', label: 'On' }, { value: 'false', label: 'Off' }] : schema.enum.map((v) => ({ value: v, label: friendly(v) }));
    return `<select class="styled-select" data-tool-input="${name}" aria-label="${escapeHTML(toolNames[name] ?? friendly(name))}"><option value=""${value === undefined ? ' selected' : ''}>Choose…</option>${choices.map((o) => `<option value="${escapeHTML(o.value)}"${String(value) === o.value ? ' selected' : ''}>${escapeHTML(o.label)}</option>`).join('')}</select>`;
  }
  return `<input class="control-input" type="number" data-tool-input="${name}" min="${schema.minimum}" max="${schema.maximum}" step="${schema.multipleOf ?? 1}" value="${value ?? ''}" placeholder="${schema.minimum}–${schema.maximum}${schema.unit ? ` ${schema.unit}` : ''}" aria-label="${escapeHTML(toolNames[name] ?? friendly(name))}">`;
}
function toolControl(name, writable = true) {
  const schema = ui.controls.settable_controls?.[name]?.value;
  const hasDraft = ui.toolDrafts.has(name);
  return `<div class="tool-control"><div class="tool-control-head"><label>${escapeHTML(toolNames[name] ?? friendly(name))}</label><span class="read-value" data-reading="${name}">${escapeHTML(displayReading(ui.readings.get(name)))}</span></div><div class="control-actions">${writable && schema ? toolInput(name, schema) : ''}<button class="button subtle" data-read-tool="${name}" data-request>Read</button>${writable && schema ? `<button class="button" data-apply-tool="${name}" data-request data-disabled="${!hasDraft}">Apply</button>` : ''}</div></div>`;
}
function renderTools() {
  const prefix = `${ui.toolGroup}_`;
  const [title, description] = toolDescriptions[ui.toolGroup];
  const writable = Object.keys(ui.controls.settable_controls ?? {}).filter((name) => name.startsWith(prefix));
  const readOnly = Object.keys(ui.controls.readable_controls ?? {}).filter((name) => name.startsWith(prefix) && !writable.includes(name));
  const isLooper = ui.toolGroup === 'looper';
  const recording = isLooper && ui.controls.guarded_looper_actions?.actions?.includes('start_recording');
  $('#tool-panel').innerHTML = `<div class="tool-panel-heading"><div><h3>${escapeHTML(title)}</h3><p>${escapeHTML(description)}</p></div></div>${recording ? '<div class="looper-record"><button class="button record-button" data-looper="start_recording" data-request><span class="record-icon"></span>Start new recording</button><button class="button" data-looper="stop_recording" data-request>Stop recording</button><p class="looper-note">New recording needs an empty, stopped looper with drums and metronome off. Existing loops are kept.</p></div>' : ''}<div class="tool-controls">${writable.map((name) => toolControl(name)).join('')}</div>${isLooper && ui.controls.guarded_looper_actions?.actions?.includes('set_bars') ? '<div class="bars-row"><div><label class="form-label" for="looper-bars">Bars</label><select id="looper-bars" class="styled-select"><option>4</option><option>8</option><option>12</option><option>16</option><option>24</option><option>32</option><option>1</option><option>2</option></select></div><div><label class="form-label" for="looper-mode">Backing preview</label><select id="looper-mode" class="styled-select"><option value="drum">Drums</option><option value="metronome">Metronome</option></select></div><button id="apply-bars" class="button" data-request>Apply bars</button><p class="looper-note">The chosen backing preview must already be running, with no recorded loop. Drums need at least 4 bars.</p></div>' : ''}${readOnly.length ? `<details class="advanced-readings"${isLooper ? ' open' : ''}><summary>Read ${isLooper ? 'loop' : 'more'} settings</summary><div class="tool-readonly">${readOnly.map((name) => toolControl(name, false)).join('')}</div></details>` : ''}`;
}
function clearSoundDrafts() { ui.parameterDrafts.clear(); ui.modelDrafts.clear(); }
async function loadPreset(id) {
  const result = await send('select_preset', { preset_id: id });
  ui.focusedId = id;
  clearSoundDrafts();
  return result;
}
function confirmReload() {
  if (!ui.state.dirty && !draftCount()) return true;
  return window.confirm('Load the saved sound? This replaces unsaved sound changes and clears unapplied edits.');
}
function openPresetDialog(action) {
  if (ui.busy) return;
  $('#preset-menu-items').hidden = true;
  $('#preset-menu').setAttribute('aria-expanded', 'false');
  const source = current();
  if (!source) return;
  ui.dialogAction = action;
  const title = { create_preset: 'Create a new preset', save_as: 'Save a new sound', rename_preset: 'Rename your preset' }[action];
  $('#dialog-title').textContent = title;
  $('#dialog-description').textContent = action === 'rename_preset' ? 'Give this preset a new name. Its sound stays the same.' : action === 'save_as' ? `Keep your applied ${source.name} sound as a new preset. Unapplied slider edits are not included.` : `Copy the saved ${source.name} sound. Loading the new copy replaces current unsaved changes and clears unapplied edits.`;
  $('#dialog-hint').textContent = action === 'rename_preset' ? 'This changes the name stored on your amp.' : 'The amp gives your new preset the next available number.';
  $('#preset-name').value = action === 'rename_preset' ? source.name : '';
  $('#submit-dialog').textContent = action === 'rename_preset' ? 'Rename preset' : 'Create & load';
  $('#dialog-error').hidden = true;
  $('#preset-dialog').showModal();
  $('#preset-name').focus();
}
async function readTool(name, args = {}) {
  const result = await send('read_tool', { control: name, ...args });
  if (result.state) ui.readings.set(name, result.state);
  return result;
}
async function readMixer(key) {
  if (key === 'master') {
    const result = await send('read_tool', { control: 'master_volume' });
    if (result.state) ui.mixerReadings.set(key, result.state);
    return result;
  }
  const input = await send('read_tool', { control: 'channel_input', channel: Number(key) });
  if (input.state) ui.mixerInputs.set(key, input.state);
  if (!input.state?.input_type_name) throw new Error('The amp did not identify this channel input. Its level has not been changed.');
  const volume = await send('read_tool', { control: 'channel_volume', channel: Number(key), input_type: input.state.input_type_name });
  if (volume.state) ui.mixerReadings.set(key, volume.state);
  return volume;
}
function readToolDraft(name) {
  const input = $(`[data-tool-input="${name}"]`);
  const schema = ui.controls.settable_controls[name].value;
  if (!input.value) throw new Error('Choose a value first.');
  if (schema.type === 'boolean') return input.value === 'true';
  if (schema.type === 'string') return input.value;
  if (!input.checkValidity() || !Number.isFinite(Number(input.value))) throw new Error(`Choose a value from ${schema.minimum} to ${schema.maximum}.`);
  return Number(input.value);
}

$('#preset-search').addEventListener('input', renderPresets);
$('#refresh').addEventListener('click', () => eventRun('Reading your amp…', async () => {
  const result = await send('refresh');
  return result;
}, 'Amp settings read. Your local edits have been kept.'));
$('#load-preset').addEventListener('click', () => {
  if (ui.focusedId !== null && confirmReload()) eventRun('Loading your sound…', () => loadPreset(ui.focusedId), 'Sound loaded. You can now edit its amp and effects.');
});
$('#save-preset').addEventListener('click', () => eventRun('Saving your sound…', () => send('save_user_preset', { expected_preset_id: current().preset_id }), draftCount() ? 'Applied changes saved. Your unapplied slider edits are still here.' : 'Your sound is saved on the amp.'));
$('#new-preset').addEventListener('click', () => openPresetDialog('create_preset'));
$('#copy-preset').addEventListener('click', () => openPresetDialog('create_preset'));
$('#save-as').addEventListener('click', () => openPresetDialog('save_as'));
$('#rename-preset').addEventListener('click', () => openPresetDialog('rename_preset'));
$('#preset-menu').addEventListener('click', () => {
  const menu = $('#preset-menu-items');
  menu.hidden = !menu.hidden;
  $('#preset-menu').setAttribute('aria-expanded', String(!menu.hidden));
});
document.addEventListener('click', (event) => {
  if (!event.target.closest('.sound-actions')) { $('#preset-menu-items').hidden = true; $('#preset-menu').setAttribute('aria-expanded', 'false'); }
});
$('#close-dialog').addEventListener('click', () => $('#preset-dialog').close());
$('#cancel-dialog').addEventListener('click', () => $('#preset-dialog').close());
$('#preset-dialog').addEventListener('cancel', (event) => { if (ui.busy) event.preventDefault(); });
$('#preset-form').addEventListener('submit', (event) => {
  event.preventDefault();
  if (ui.busy) return;
  const name = $('#preset-name').value.trim();
  if (!name) { $('#preset-name').focus(); return; }
  const action = ui.dialogAction;
  const source = current();
  const args = action === 'rename_preset' ? { preset_id: source.preset_id, name } : action === 'create_preset' ? { source_preset_id: source.preset_id, name, genre: source.genre ?? 0 } : { expected_preset_id: source.preset_id, name, genre: source.genre ?? 0 };
  $('#dialog-error').hidden = true;
  void run(action === 'rename_preset' ? 'Renaming your preset…' : 'Creating your new sound…', async () => {
    const result = await send(action, args);
    // Once creation is confirmed, never send creation again if loading fails.
    $('#preset-dialog').close();
    if (action !== 'rename_preset') {
      const id = result.operation?.new_preset_id ?? result.new_preset_id;
      if (id === undefined) throw new Error('The preset was created, but its new number was not returned. Refresh the library to find it; do not create it again.');
      ui.focusedId = id;
      await loadPreset(id);
    }
    return result;
  }, action === 'rename_preset' ? 'Preset renamed.' : 'Your new preset is created and loaded. Make it yours.').catch((error) => {
    if ($('#preset-dialog').open) { $('#dialog-error').textContent = error.message; $('#dialog-error').hidden = false; }
  });
});

document.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  const data = button.dataset;
  if (data.filter) {
    ui.filter = data.filter;
    $$('[data-filter]').forEach((b) => { b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button)); });
    renderPresets();
  }
  if (data.preset !== undefined) { ui.focusedId = Number(data.preset); render(); }
  if (data.slot !== undefined) { ui.slotId = Number(data.slot); renderChain(); renderEditor(); applyDisabledState(); }
  if (data.tab) {
    ui.tab = data.tab;
    $$('[data-tab]').forEach((b) => { b.classList.toggle('active', b === button); b.toggleAttribute('aria-current', b === button); });
    $$('.workspace-panel').forEach((panel) => { panel.hidden = panel.id !== `tab-${ui.tab}`; });
  }
  if (data.toolGroup) {
    ui.toolGroup = data.toolGroup;
    $$('[data-tool-group]').forEach((b) => { b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button)); });
    renderTools(); applyDisabledState();
  }
  if (data.applyParameter !== undefined) {
    const id = Number(data.applyParameter);
    const key = draftKey(id);
    const input = $(`#number-${id}`);
    if (!input.checkValidity() || input.value === '') { input.reportValidity(); return; }
    const value = Number(input.value);
    eventRun('Applying your sound change…', async () => {
      const result = await send('set_effect_parameter', { expected_preset_id: current().preset_id, slot_id: ui.slotId, parameter_id: id, ui_value: value });
      ui.parameterDrafts.delete(key);
      return result;
    }, 'Applied to your sound. Save changes to keep it.');
  }
  if (button.id === 'apply-model') {
    const key = `${ui.focusedId}:${ui.slotId}`;
    const id = ui.slotId;
    eventRun('Loading the effect model…', async () => {
      const result = await send('set_effect_model', { expected_preset_id: current().preset_id, slot_id: id, model_id: $('#effect-model').value });
      ui.modelDrafts.delete(key);
      [...ui.parameterDrafts.keys()].filter((k) => k.startsWith(`${key}:`)).forEach((k) => ui.parameterDrafts.delete(k));
      return result;
    }, 'Model loaded with its amp defaults. Save changes to keep it.');
  }
  if (button.id === 'effect-power') {
    const slot = slotById(ui.slotId);
    eventRun(slot.bypass_raw === 0 ? 'Bypassing the effect…' : 'Enabling the effect…', () => send('set_effect_active', { expected_preset_id: current().preset_id, slot_id: ui.slotId, active: slot.bypass_raw !== 0 }), 'Effect updated. Save changes to keep it.');
  }
  if (data.readTool) eventRun('Reading the amp setting…', () => readTool(data.readTool));
  if (data.applyTool) {
    let value;
    try { value = readToolDraft(data.applyTool); } catch (error) { notify(error.message, 'error'); return; }
    eventRun('Updating your practice tool…', async () => {
      const result = await send('set_tool', { control: data.applyTool, value });
      if (result.state) ui.readings.set(data.applyTool, result.state);
      ui.toolDrafts.delete(data.applyTool);
      return result;
    }, 'Setting confirmed by the amp.');
  }
  if (data.readMixer) eventRun('Reading the mixer level…', () => readMixer(data.readMixer));
  if (data.applyMixer) {
    const input = $(`input[type="number"][data-mixer="${data.applyMixer}"]`);
    if (!input.checkValidity() || input.value === '') { input.reportValidity(); return; }
    const key = data.applyMixer;
    const args = { scope: key === 'master' ? 'master' : 'channel', level: Number(input.value) };
    if (key !== 'master') args.channel = Number(key);
    eventRun('Setting the mixer level…', async () => {
      const result = await send('set_mixer_volume', args);
      if (result.state) ui.mixerReadings.set(key, result.state);
      ui.mixerDrafts.delete(key);
      return result;
    }, 'Mixer level confirmed.');
  }
  if (data.looper) eventRun(data.looper === 'start_recording' ? 'Checking the looper and starting recording…' : 'Stopping recording…', () => send('control_looper', { action: data.looper }), data.looper === 'start_recording' ? 'Recording has started. Press Stop recording when you are finished.' : 'Recording stopped. Your loop has been kept.');
  if (button.id === 'apply-bars') eventRun('Checking and setting loop length…', () => send('control_looper', { action: 'set_bars', bars: Number($('#looper-bars').value), mode: $('#looper-mode').value }), 'Loop length updated.');
});

document.addEventListener('input', (event) => {
  const input = event.target;
  if (input.dataset.parameter !== undefined) {
    const id = Number(input.dataset.parameter);
    const definition = slotModel(slotById(ui.slotId))?.parameters.find((p) => p.parameter_id === id);
    if (!definition || input.value === '') return;
    const value = Number(input.value);
    if (!Number.isFinite(value)) return;
    const baseline = parameterValue(slotById(ui.slotId), definition);
    if (value === baseline) ui.parameterDrafts.delete(draftKey(id)); else ui.parameterDrafts.set(draftKey(id), value);
    const range = $(`#range-${id}`); const number = $(`#number-${id}`);
    if (input !== range) range.value = value;
    if (input !== number) number.value = value;
    setFill(range);
    const apply = $(`[data-apply-parameter="${id}"]`);
    const hasDraft = value !== baseline;
    apply.dataset.disabled = String(!canEdit() || !hasDraft || !number.checkValidity());
    apply.classList.toggle('has-draft', hasDraft);
    renderHeader(); applyDisabledState();
  }
  if (input.dataset.mixer) {
    const key = input.dataset.mixer;
    if (input.value === '') return;
    const value = Number(input.value);
    if (!Number.isFinite(value)) return;
    ui.mixerDrafts.set(key, value);
    const other = $$(`[data-mixer="${key}"]`).find((element) => element !== input);
    if (other) other.value = value;
    const range = $(`input[type="range"][data-mixer="${key}"]`); setFill(range);
    const card = input.closest('.mixer-card');
    card.querySelector('.mixer-level').innerHTML = `${escapeHTML(value)}<small>/32</small>`;
    const number = card.querySelector('input[type="number"]');
    const apply = card.querySelector('[data-apply-mixer]');
    apply.dataset.disabled = String(!number.checkValidity());
    applyDisabledState();
  }
  if (input.dataset.toolInput) {
    const name = input.dataset.toolInput;
    const schema = ui.controls.settable_controls[name].value;
    if (input.value === '') ui.toolDrafts.delete(name);
    else ui.toolDrafts.set(name, schema.type === 'boolean' ? input.value === 'true' : schema.type === 'string' ? input.value : Number(input.value));
    const apply = $(`[data-apply-tool="${name}"]`);
    apply.dataset.disabled = String(!ui.toolDrafts.has(name) || !input.checkValidity());
    applyDisabledState();
  }
});
document.addEventListener('change', (event) => {
  if (event.target.id === 'effect-model') {
    const key = `${ui.focusedId}:${ui.slotId}`;
    const model = slotModel(slotById(ui.slotId));
    if (event.target.value === model?.model_id) ui.modelDrafts.delete(key);
    else ui.modelDrafts.set(key, event.target.value);
    $('#apply-model').dataset.disabled = String(!canEdit() || !ui.modelDrafts.has(key));
    renderHeader(); applyDisabledState();
  }
});

async function bootstrap() {
  setBusy(true, 'Opening your BandBox studio…');
  try {
    const response = await fetch('/api/bootstrap', { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'BandBox Studio could not start.');
    ui.token = data.token;
    ui.catalog = data.catalog ?? { slots: [], models: [] };
    ui.controls = data.controls ?? {};
    updateState(data.state);
    if (ui.state.message) notify(ui.state.message);
  } catch (error) { notify(`Could not open the local amp connection. ${error.message}`, 'error'); }
  finally { setBusy(false); render(); }
}
void bootstrap();

// This only reads the bridge's cached state, with no Bluetooth traffic. It lets
// a changed edit session become visibly locked without discarding any drafts.
setInterval(async () => {
  if (ui.busy || !ui.token || document.hidden || $('#preset-dialog').open) return;
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.ok) return;
    const before = JSON.stringify([ui.state.editable, ui.state.connected, ui.state.current, ui.state.dirty]);
    updateState(payload.state);
    const after = JSON.stringify([ui.state.editable, ui.state.connected, ui.state.current, ui.state.dirty]);
    if (before !== after) render();
  } catch (_) { /* A failed background cache read never retries an amp action. */ }
}, 15000);
