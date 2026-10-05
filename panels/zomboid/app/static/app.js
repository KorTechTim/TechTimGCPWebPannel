'use strict';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
let statusCache = null;
let configCache = null;
let sandboxSchemaCache = null;
let discordWebhookConfigured = false;
let activeSandboxCategory = 'population';
let currentLog = 'server';
let currentPath = '';
let editingFilePath = '';
let fileEditorOriginal = '';
const commandHistory = [];
let commandHistoryIndex = 0;
const RESOURCE_REFRESH_MS = 1000;
const RESOURCE_HISTORY_WINDOW_MS = 8 * 60 * 60 * 1000;
const RESOURCE_HISTORY_STORAGE_KEY = 'techtim-zomboid-resource-history-v1';
const STOPPED_ONLY_VIEWS = new Set(['settings', 'sandbox', 'mods', 'players', 'backups', 'advanced', 'files']);
let resourceRefreshPending = false;
let resourceHistorySavedAt = 0;
let copyTooltipTimer = null;

function loadResourceHistory() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RESOURCE_HISTORY_STORAGE_KEY) || '[]');
    const cutoff = Date.now() - RESOURCE_HISTORY_WINDOW_MS;
    return Array.isArray(parsed) ? parsed.filter(point => Array.isArray(point) && point.length === 3 && Number(point[0]) >= cutoff) : [];
  } catch (_error) { return []; }
}
const resourceHistory = loadResourceHistory();

async function api(url, options = {}) {
  const response = await fetch(url, {credentials: 'same-origin', ...options});
  const type = response.headers.get('content-type') || '';
  const data = type.includes('json') ? await response.json() : await response.text();
  if (response.status === 401) { location.assign('/login'); throw new Error('로그인이 필요합니다.'); }
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : '요청을 완료하지 못했습니다.');
  return data;
}

function json(method, body) { return {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}; }
function message(text, error = false) { const box = $('#global-message'); box.textContent = text || ''; box.classList.toggle('error', error); }
async function perform(work, success) { try { message('처리 중입니다.'); const result = await work(); message(success || result?.message || '완료했습니다.'); return result; } catch (error) { message(error.message, true); throw error; } }
async function copyText(value) {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(value); return; }
  } catch (_error) { /* Public-IP HTTP access may require the legacy clipboard fallback. */ }
  const input = document.createElement('textarea');
  input.value = value;
  input.setAttribute('readonly', '');
  input.style.cssText = 'position:fixed;left:-9999px;top:0';
  document.body.append(input);
  input.select();
  const copied = document.execCommand('copy');
  input.remove();
  if (!copied) throw new Error('IP를 복사하지 못했습니다.');
}
function bytes(value) { if (value == null || !Number.isFinite(Number(value))) return '-'; let n = Number(value); const units = ['B','KB','MB','GB','TB']; let i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; } return `${n >= 10 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`; }
function lines(text) { return text.split(/\r?\n/).map(value => value.trim()).filter(Boolean); }
function setMeter(selector, value) { const element = $(selector); if (element) element.style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`; }
function syncModalState() { document.body.classList.toggle('modal-open', $$('dialog').some(dialog => dialog.open)); }
function showDialog(dialog) { dialog.showModal(); syncModalState(); }
function closeDialog(dialog, returnValue = 'cancel') { if (dialog.open) dialog.close(returnValue); }

$$('dialog').forEach(dialog => {
  dialog.addEventListener('close', syncModalState);
  dialog.addEventListener('click', event => { if (event.target === dialog && dialog.dataset.persistent !== 'true') closeDialog(dialog); });
});

const titles = {overview:'홈(HOME)',console:'관리 터미널',settings:'기본 서버 설정',sandbox:'샌드박스 배율',mods:'모드 · 워크숍',players:'사용자 관리',backups:'백업 · 복원',advanced:'샌드박스 배율 직접 수정',schedule:'예약 작업',files:'서버 폴더 탐색기',discord:'디스코드 연동'};
function serverIsRunning(status = statusCache) { return ['running', 'restarting'].includes(status?.server); }
function showServerRunningLock() {
  const dialog = $('#server-running-lock-dialog');
  if (!dialog.open) showDialog(dialog);
}
function leaveServerRunningLock() {
  closeDialog($('#server-running-lock-dialog'), 'home');
  showView('overview');
}
$('#server-running-lock-home').addEventListener('click', leaveServerRunningLock);
$('#server-running-lock-dialog').addEventListener('cancel', event => { event.preventDefault(); leaveServerRunningLock(); });
$('#confirm-engine-required').addEventListener('click', () => closeDialog($('#engine-required-dialog'), 'confirm'));
$('#engine-required-dialog').addEventListener('cancel', event => event.preventDefault());

async function showView(name) {
  if (!titles[name]) name = 'overview';
  $$('.view').forEach(view => view.classList.toggle('active', view.dataset.page === name));
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === name));
  $('#overview-status').hidden = name !== 'overview';
  $('#page-title').textContent = titles[name];
  history.replaceState(null, '', `#${name}`);
  try {
    if (STOPPED_ONLY_VIEWS.has(name)) {
      await refreshStatus();
      if (serverIsRunning()) { showServerRunningLock(); return; }
    }
    if (name === 'settings') await loadConfig();
    if (name === 'sandbox') await loadSandbox();
    if (name === 'mods') await loadMods();
    if (name === 'players') await loadPlayers();
    if (name === 'backups') await loadBackups();
    if (name === 'schedule') await loadSchedule();
    if (name === 'files') await loadFiles(currentPath);
    if (name === 'discord') await loadDiscord();
    if (name === 'advanced') await loadTextFile();
    if (name === 'console') await loadLogs();
  } catch (error) { message(error.message, true); }
}

$$('[data-view]').forEach(element => element.addEventListener('click', event => { event.preventDefault(); showView(element.dataset.view); }));

function stateLabel(state) {
  return {running:'● 서버 실행 중',restarting:'● 서버 재시작 중',exited:'● 서버 중지됨',created:'● 서버 준비됨',missing:'● 서버 미생성',unavailable:'● Docker 확인 필요'}[state] || state;
}

async function refreshStatus() {
  const status = await api('/api/status');
  statusCache = status;
  $('#engine-state').textContent = status.engine.installed ? '설치 완료' : '설치 필요';
  $('#engine-build').textContent = status.engine.installed ? `Build ${status.engine.build_id}` : 'Steam App 380870';
  $('#server-state').textContent = stateLabel(status.server);
  $('#branch-state').textContent = status.engine.branch;
  $('#panel-version').textContent = status.panel_version;
  $('#sidebar-version').textContent = `PANEL ${status.panel_version}`;
  $('#connection-endpoint').textContent = `${location.hostname} : ${status.endpoint_port}`;
  $$('[data-action]').forEach(button => {
    const action = button.dataset.action;
    button.disabled = status.busy || (action === 'start' && status.server === 'running') || (action !== 'start' && status.server !== 'running');
  });
  $('#install-engine').disabled = status.busy || status.server === 'running';
  const terminalReady = status.server === 'running' && !status.busy;
  $('#terminal-command').disabled = !terminalReady;
  $('#terminal-command-submit').disabled = !terminalReady;
  $('#terminal-command-state').textContent = terminalReady ? '● 명령 전송 가능' : '● 서버 실행 중에만 명령 전송 가능';
  const activePage = $('.view.active')?.dataset.page;
  if (STOPPED_ONLY_VIEWS.has(activePage) && serverIsRunning(status)) showServerRunningLock();
  return status;
}

function saveResourceHistory(force = false) {
  const now = Date.now();
  if (!force && now - resourceHistorySavedAt < 15000) return;
  try { localStorage.setItem(RESOURCE_HISTORY_STORAGE_KEY, JSON.stringify(resourceHistory)); resourceHistorySavedAt = now; }
  catch (_error) { /* The live chart still works when browser storage is unavailable. */ }
}

function appendResourceHistory(cpu, memory) {
  const now = Date.now();
  const cpuValue = Number.isFinite(Number(cpu)) ? Math.max(0, Math.min(100, Number(cpu))) : null;
  const memoryValue = Number.isFinite(Number(memory)) ? Math.max(0, Math.min(100, Number(memory))) : null;
  if (cpuValue == null && memoryValue == null) return;
  resourceHistory.push([now, cpuValue, memoryValue]);
  const cutoff = now - RESOURCE_HISTORY_WINDOW_MS;
  while (resourceHistory.length && resourceHistory[0][0] < cutoff) resourceHistory.shift();
  saveResourceHistory();
}

function drawResourceHistory(canvasId, valueIndex, color) {
  const canvas = $(canvasId);
  const rect = canvas.getBoundingClientRect();
  if (!rect.width) return;
  const width = Math.max(1, Math.floor(rect.width));
  const height = 68;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(width * ratio); canvas.height = Math.floor(height * ratio);
  const context = canvas.getContext('2d'); context.scale(ratio, ratio);
  const top = 5, bottom = height - 6, chartHeight = bottom - top;
  context.lineWidth = 1;
  context.strokeStyle = 'rgba(119,160,150,.18)';
  for (const percent of [0, 25, 50, 75, 100]) {
    const y = bottom - chartHeight * percent / 100;
    context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
  }
  const now = Date.now(), start = now - RESOURCE_HISTORY_WINDOW_MS;
  const samples = resourceHistory.filter(point => point[0] >= start && point[valueIndex] != null);
  if (!samples.length) return;
  const step = Math.max(1, Math.ceil(samples.length / width));
  const points = [];
  for (let index = 0; index < samples.length; index += step) {
    const bucket = samples.slice(index, index + step);
    const sample = bucket[bucket.length - 1];
    points.push([Math.min(width - 1, Math.max(0, (sample[0] - start) / RESOURCE_HISTORY_WINDOW_MS * width)), bottom - sample[valueIndex] / 100 * chartHeight]);
  }
  context.beginPath(); context.moveTo(points[0][0], bottom);
  for (const point of points) context.lineTo(point[0], point[1]);
  context.lineTo(points[points.length - 1][0], bottom); context.closePath();
  const fill = context.createLinearGradient(0, top, 0, bottom); fill.addColorStop(0, `${color}55`); fill.addColorStop(1, `${color}05`);
  context.fillStyle = fill; context.fill();
  context.beginPath(); context.moveTo(points[0][0], points[0][1]);
  for (const point of points.slice(1)) context.lineTo(point[0], point[1]);
  context.strokeStyle = color; context.lineWidth = 1.7; context.stroke();
  const latest = points[points.length - 1]; context.beginPath(); context.arc(latest[0], latest[1], 2.4, 0, Math.PI * 2); context.fillStyle = color; context.fill();
}

function renderResourceHistory() {
  drawResourceHistory('#cpu-history-chart', 1, '#56c9b4');
  drawResourceHistory('#memory-history-chart', 2, '#d2a24e');
}

async function refreshResources() {
  if (resourceRefreshPending) return;
  resourceRefreshPending = true;
  try {
    const data = await api('/api/resources');
    const cpu = data.cpu.percent;
    const mem = data.memory.percent;
    const disk = data.disk.percent;
    $('#cpu-value').textContent = cpu == null ? '수집 중' : `${cpu.toFixed(1)}%`;
    $('#memory-value').textContent = mem == null ? '-' : `${mem.toFixed(1)}%`;
    $('#disk-value').textContent = `${disk.toFixed(1)}%`;
    $('#memory-detail').textContent = `${bytes(data.memory.used)} / ${bytes(data.memory.total)} · 1초 갱신`;
    $('#disk-detail').textContent = `${bytes(data.disk.used)} / ${bytes(data.disk.total)}`;
    setMeter('#disk-meter', disk);
    appendResourceHistory(cpu, mem);
    renderResourceHistory();
    const down = `${bytes(data.network.down)}/s`, up = `${bytes(data.network.up)}/s`;
    $('#network-down').textContent = down;
    $('#network-up').textContent = up;
    $('#network-value').textContent = `${down} ↓`;
  } finally { resourceRefreshPending = false; }
}

async function loadLogs() {
  const data = await api(`/api/logs?kind=${currentLog}`);
  for (const id of ['#overview-log','#full-log']) {
    const target = $(id); if (!target) continue; target.textContent = data.log;
    if ($('#auto-scroll')?.checked) target.scrollTop = target.scrollHeight;
  }
  $('#log-pulse').textContent = statusCache?.server === 'running' ? '● 서버 로그 연결됨' : '● 저장된 로그 표시 중';
}

$$('.log-tab').forEach(button => button.addEventListener('click', () => {
  currentLog = button.dataset.log;
  $$('.log-tab').forEach(item => item.classList.toggle('active', item.dataset.log === currentLog));
  loadLogs().catch(error => message(error.message, true));
}));
$('#refresh-log').addEventListener('click', () => loadLogs().catch(error => message(error.message, true)));

const commandHelpDialog = $('#command-help-dialog');
$('#open-command-help').addEventListener('click', () => showDialog(commandHelpDialog));
$('#close-command-help').addEventListener('click', () => closeDialog(commandHelpDialog));

const textInputDialog = $('#text-input-dialog');
const textInput = $('#text-input-value');
function requestTextInput({title, description, label, placeholder = '', value = ''}) {
  $('#text-input-title').textContent = title;
  $('#text-input-description').textContent = description;
  $('#text-input-label').textContent = label;
  textInput.placeholder = placeholder;
  textInput.value = value;
  textInputDialog.returnValue = '';
  showDialog(textInputDialog);
  requestAnimationFrame(() => textInput.focus());
  return new Promise(resolve => textInputDialog.addEventListener('close', () => {
    resolve(textInputDialog.returnValue === 'submit' ? textInput.value.trim() : '');
  }, {once: true}));
}
$('#text-input-form').addEventListener('submit', event => {
  event.preventDefault();
  if (textInput.reportValidity()) closeDialog(textInputDialog, 'submit');
});
$('#close-text-input').addEventListener('click', () => closeDialog(textInputDialog));
$('#cancel-text-input').addEventListener('click', () => closeDialog(textInputDialog));

$('#terminal-command').addEventListener('keydown', event => {
  if (!['ArrowUp', 'ArrowDown'].includes(event.key) || !commandHistory.length) return;
  event.preventDefault();
  if (event.key === 'ArrowUp') commandHistoryIndex = Math.max(0, commandHistoryIndex - 1);
  else commandHistoryIndex = Math.min(commandHistory.length, commandHistoryIndex + 1);
  event.currentTarget.value = commandHistory[commandHistoryIndex] || '';
});

$('#terminal-command-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input = $('#terminal-command');
  const command = input.value.trim();
  if (!command) return;
  $('#terminal-command-state').textContent = `● ${command.split(/\s+/, 1)[0]} 전송 중`;
  try {
    const result = await api('/api/console/command', json('POST', {command}));
    if (commandHistory.at(-1) !== command) commandHistory.push(command);
    commandHistoryIndex = commandHistory.length;
    input.value = '';
    currentLog = 'server';
    $$('.log-tab').forEach(item => item.classList.toggle('active', item.dataset.log === 'server'));
    await new Promise(resolve => setTimeout(resolve, 350));
    await loadLogs();
    $('#terminal-command-state').textContent = `● ${result.message}`;
    input.focus();
  } catch (error) {
    $('#terminal-command-state').textContent = `● ${error.message}`;
  }
});

$('#install-engine').addEventListener('click', () => perform(() => api('/api/install', {method:'POST'}), '엔진 설치·업데이트를 시작했습니다.'));
$$('[data-action]').forEach(button => button.addEventListener('click', async () => {
  const action = button.dataset.action;
  if (action === 'start') {
    try {
      const status = await refreshStatus();
      if (!status.engine.installed) { showDialog($('#engine-required-dialog')); return; }
    } catch (error) { message(error.message, true); return; }
  }
  perform(() => api(`/api/server/${action}`, {method:'POST'}), '서버 작업을 시작했습니다.').catch(() => {});
}));
$('#copy-endpoint').addEventListener('click', async () => {
  try {
    await copyText(location.hostname);
    const tooltip = $('#copy-endpoint-tooltip');
    tooltip.classList.add('visible');
    clearTimeout(copyTooltipTimer);
    copyTooltipTimer = setTimeout(() => tooltip.classList.remove('visible'), 2000);
  } catch (error) { message(error.message, true); }
});

function fillForm(form, values) {
  for (const [key, value] of Object.entries(values)) {
    const field = form.elements.namedItem(key); if (!field) continue;
    if (field.type === 'checkbox') field.checked = Boolean(value); else field.value = value ?? '';
  }
}
function formData(form) {
  const result = {};
  for (const field of form.elements) {
    if (!field.name) continue;
    if (field.type === 'checkbox') result[field.name] = field.checked;
    else if (field.type === 'number') result[field.name] = Number(field.value);
    else result[field.name] = field.value;
  }
  return result;
}

async function loadConfig() { configCache = await api('/api/config'); fillForm($('#settings-form'), configCache); }
$('#save-settings').addEventListener('click', () => perform(async () => {
  const payload = formData($('#settings-form'));
  payload.workshop_items = configCache?.workshop_items || []; payload.mod_ids = configCache?.mod_ids || []; payload.map_order = configCache?.map_order || ['Muldraugh, KY'];
  configCache = await api('/api/config', json('POST', payload)); fillForm($('#settings-form'), configCache);
}, '기본 서버 설정을 저장했습니다.'));

function sandboxField(spec) {
  const wrapper = document.createElement('label');
  wrapper.className = `sandbox-field sandbox-field-${spec.type}`;
  wrapper.dataset.search = `${spec.label} ${spec.key} ${spec.help || ''}`.toLocaleLowerCase();
  const heading = document.createElement('span'); heading.className = 'sandbox-field-title'; heading.textContent = spec.label;
  const key = document.createElement('code'); key.textContent = spec.key;
  let input;
  if (spec.type === 'boolean') {
    input = document.createElement('input'); input.type = 'checkbox';
    const switcher = document.createElement('i'); switcher.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('span'); copy.className = 'sandbox-toggle-copy'; copy.append(heading, key);
    wrapper.append(input, switcher, copy);
  } else {
    wrapper.append(heading, key);
    if (spec.options?.length) {
      input = document.createElement('select');
      for (const item of spec.options) { const option = document.createElement('option'); option.value = item.value; option.textContent = `${item.value} · ${item.label}`; input.append(option); }
    } else if (spec.type === 'string' && (spec.default?.length > 60 || /List$/.test(spec.key))) {
      input = document.createElement('textarea'); input.rows = 2;
    } else {
      input = document.createElement('input'); input.type = spec.type === 'string' ? 'text' : 'number';
      if (spec.min != null) input.min = spec.min;
      if (spec.max != null) input.max = spec.max;
      if (spec.step != null) input.step = spec.step;
    }
    wrapper.append(input);
    if (spec.help) { const help = document.createElement('small'); help.textContent = spec.help; wrapper.append(help); }
  }
  input.name = spec.name;
  return wrapper;
}

function applySandboxFilters() {
  const query = $('#sandbox-search').value.trim().toLocaleLowerCase();
  let visible = 0;
  $$('.sandbox-category-panel').forEach(panel => {
    const categoryMatch = activeSandboxCategory === 'all' || panel.dataset.category === activeSandboxCategory;
    let panelVisible = 0;
    panel.querySelectorAll('.sandbox-field').forEach(field => {
      const show = categoryMatch && (!query || field.dataset.search.includes(query));
      field.hidden = !show;
      if (show) panelVisible++;
    });
    panel.hidden = panelVisible === 0;
    visible += panelVisible;
  });
  $$('.sandbox-category-button').forEach(button => button.classList.toggle('active', button.dataset.category === activeSandboxCategory));
  $('#sandbox-result-count').textContent = `${visible}개 설정`;
  $('#sandbox-empty').hidden = visible > 0;
}

function renderSandbox(schema, values) {
  const nav = $('#sandbox-categories'); nav.replaceChildren();
  const all = document.createElement('button'); all.type = 'button'; all.className = 'sandbox-category-button'; all.dataset.category = 'all'; all.innerHTML = `<strong>전체</strong><span>${schema.fields.length}</span>`; nav.append(all);
  for (const category of schema.categories) {
    const count = schema.fields.filter(field => field.category === category.id).length;
    const button = document.createElement('button'); button.type = 'button'; button.className = 'sandbox-category-button'; button.dataset.category = category.id;
    const title = document.createElement('strong'); title.textContent = category.title; const badge = document.createElement('span'); badge.textContent = count; button.append(title, badge); nav.append(button);
  }
  nav.querySelectorAll('button').forEach(button => button.addEventListener('click', () => { activeSandboxCategory = button.dataset.category; $('#sandbox-search').value = ''; applySandboxFilters(); }));

  const form = $('#sandbox-form'); form.replaceChildren();
  for (const category of schema.categories) {
    const panel = document.createElement('section'); panel.className = 'sandbox-category-panel panel'; panel.dataset.category = category.id;
    const header = document.createElement('header'); const copy = document.createElement('div'); const title = document.createElement('h3'); title.textContent = category.title;
    const description = document.createElement('p'); description.textContent = category.description; copy.append(title, description);
    const count = document.createElement('span'); count.textContent = `${schema.fields.filter(field => field.category === category.id).length} SETTINGS`; header.append(copy, count);
    const grid = document.createElement('div'); grid.className = 'sandbox-field-grid';
    schema.fields.filter(field => field.category === category.id).forEach(field => grid.append(sandboxField(field)));
    panel.append(header, grid); form.append(panel);
  }
  const empty = document.createElement('div'); empty.id = 'sandbox-empty'; empty.className = 'sandbox-empty'; empty.textContent = '검색 조건에 맞는 설정이 없습니다.'; empty.hidden = true; form.append(empty);
  fillForm(form, values);
  applySandboxFilters();
}

async function loadSandbox() {
  const [schema, values] = await Promise.all([sandboxSchemaCache || api('/api/sandbox/schema'), api('/api/sandbox')]);
  sandboxSchemaCache = schema;
  renderSandbox(schema, values);
}
$('#sandbox-search').addEventListener('input', event => { if (event.currentTarget.value.trim()) activeSandboxCategory = 'all'; applySandboxFilters(); });
$('#reset-sandbox').addEventListener('click', () => {
  if (!sandboxSchemaCache) return;
  const defaults = Object.fromEntries(sandboxSchemaCache.fields.map(spec => [spec.name, spec.default]));
  fillForm($('#sandbox-form'), defaults);
  message('모든 샌드박스 설정을 기본값으로 되돌렸습니다. 전체 설정 저장을 눌러 적용하세요.');
});
$('#save-sandbox').addEventListener('click', () => perform(() => api('/api/sandbox', json('POST', formData($('#sandbox-form')))), '샌드박스 배율을 저장했습니다.'));

async function loadMods() {
  const [workshop, config] = await Promise.all([api('/api/workshop'), api('/api/config')]); configCache = config;
  renderModPairs(workshop.workshop_items, workshop.mod_ids); $('#map-order').value = workshop.map_order.join('\n');
  $('#workshop-count').textContent = workshop.workshop_items.length; $('#mod-count').textContent = workshop.mod_ids.length; $('#installed-mod-count').textContent = workshop.installed.length;
}
function renumberModPairs() {
  $$('.mod-pair-row').forEach((row, index) => { row.querySelector('.mod-pair-index').textContent = String(index + 1).padStart(2, '0'); });
}
function updateModPairCounts() {
  $('#workshop-count').textContent = $$('.mod-pair-workshop').filter(input => input.value.trim()).length;
  $('#mod-count').textContent = $$('.mod-pair-id').filter(input => input.value.trim()).length;
}
function createModPairRow(workshopId = '', modId = '') {
  const row = document.createElement('div'); row.className = 'mod-pair-row';
  const index = document.createElement('span'); index.className = 'mod-pair-index';
  const workshop = document.createElement('input'); workshop.className = 'mod-pair-workshop'; workshop.type = 'text'; workshop.inputMode = 'numeric'; workshop.pattern = '[0-9]*'; workshop.maxLength = 20; workshop.placeholder = '예: 2392709985'; workshop.ariaLabel = 'Steam Workshop 숫자 ID'; workshop.value = workshopId;
  const mod = document.createElement('input'); mod.className = 'mod-pair-id'; mod.type = 'text'; mod.maxLength = 128; mod.placeholder = '예: ModOptions'; mod.ariaLabel = '내부 Mod ID'; mod.value = modId;
  const remove = document.createElement('button'); remove.className = 'mod-pair-remove'; remove.type = 'button'; remove.title = '이 모드 행 삭제'; remove.ariaLabel = '모드 행 삭제'; remove.textContent = '×';
  workshop.addEventListener('input', updateModPairCounts); mod.addEventListener('input', updateModPairCounts);
  remove.addEventListener('click', () => { row.remove(); if (!$('#mod-pair-list').children.length) $('#mod-pair-list').append(createModPairRow()); renumberModPairs(); updateModPairCounts(); });
  row.append(index, workshop, mod, remove); return row;
}
function renderModPairs(workshopItems = [], modIds = []) {
  const list = $('#mod-pair-list'); list.replaceChildren();
  const count = Math.max(workshopItems.length, modIds.length, 1);
  for (let index = 0; index < count; index++) list.append(createModPairRow(workshopItems[index] || '', modIds[index] || ''));
  renumberModPairs(); updateModPairCounts();
}
function collectModPairs() {
  const pairs = $$('.mod-pair-row').map(row => ({workshop: row.querySelector('.mod-pair-workshop').value.trim(), mod: row.querySelector('.mod-pair-id').value.trim()}));
  const incomplete = pairs.find(pair => Boolean(pair.workshop) !== Boolean(pair.mod));
  if (incomplete) throw new Error('각 행의 Workshop ID와 내부 Mod ID를 모두 입력해주세요.');
  const completed = pairs.filter(pair => pair.workshop && pair.mod);
  if (completed.some(pair => !/^\d{5,20}$/.test(pair.workshop))) throw new Error('Workshop ID는 5~20자리 숫자로 입력해주세요.');
  const workshopItems = completed.map(pair => pair.workshop); const modIds = completed.map(pair => pair.mod);
  if (new Set(workshopItems).size !== workshopItems.length) throw new Error('중복된 Workshop ID가 있습니다.');
  if (new Set(modIds).size !== modIds.length) throw new Error('중복된 내부 Mod ID가 있습니다.');
  return {workshopItems, modIds};
}
$('#add-mod-pair').addEventListener('click', () => { $('#mod-pair-list').append(createModPairRow()); renumberModPairs(); });
$('#save-mods').addEventListener('click', () => perform(async () => {
  const config = configCache || await api('/api/config');
  const pairs = collectModPairs(); config.workshop_items = pairs.workshopItems; config.mod_ids = pairs.modIds; config.map_order = lines($('#map-order').value);
  configCache = await api('/api/config', json('POST', config)); await loadMods();
}, '모드 구성을 저장했습니다. 다음 시작 때 적용됩니다.'));

async function updatePlayer(username, field, value) {
  await perform(() => api('/api/players', json('POST', {username, field, value})), '사용자 DB를 변경했습니다.');
  await loadPlayers();
}
async function loadPlayers() {
  const data = await api('/api/players'); $('#players-summary').textContent = data.message; const list = $('#player-list'); list.replaceChildren();
  if (!data.accounts.length) { list.textContent = data.message; return; }
  for (const account of data.accounts) {
    const row = document.createElement('article'); row.className = 'record';
    const info = document.createElement('div'); const title = document.createElement('strong'); title.textContent = account.username; const meta = document.createElement('small'); meta.textContent = `Steam ${account.steam_id || '-'} · ${account.access_level || 'none'} · ${account.whitelisted ? '화이트리스트' : '일반'}${account.banned ? ' · 차단됨' : ''}`; info.append(title, meta);
    const actions = document.createElement('div'); actions.className = 'record-actions player-actions';
    if (data.capabilities?.access_level) { const select = document.createElement('select'); for (const level of ['none','admin','moderator','overseer','gm','observer']) { const option = document.createElement('option'); option.value = level; option.textContent = level; option.selected = account.access_level === level; select.append(option); } select.addEventListener('change', () => updatePlayer(account.username, 'access_level', select.value)); actions.append(select); }
    if (data.capabilities?.whitelisted) { const white = document.createElement('button'); white.textContent = account.whitelisted ? '허용 해제' : '화이트리스트'; white.addEventListener('click', () => updatePlayer(account.username, 'whitelisted', !account.whitelisted)); actions.append(white); }
    if (data.capabilities?.banned) { const ban = document.createElement('button'); ban.textContent = account.banned ? '차단 해제' : '차단'; ban.addEventListener('click', () => updatePlayer(account.username, 'banned', !account.banned)); actions.append(ban); }
    row.append(info, actions); list.append(row);
  }
}
$('#refresh-players').addEventListener('click', () => loadPlayers().catch(error => message(error.message, true)));

async function loadSchedule() {
  const schedule = await api('/api/schedule'); const form = $('#schedule-form'); form.elements.enabled.checked = schedule.enabled;
  for (let index = 1; index <= 3; index++) form.elements[`time_${index}`].value = schedule.times[index - 1] || '';
}
$('#save-schedule').addEventListener('click', () => perform(() => {
  const form = $('#schedule-form'); const times = [1,2,3].map(index => form.elements[`time_${index}`].value).filter(Boolean);
  if (!times.length) throw new Error('재시작 시각을 하나 이상 입력해주세요.');
  return api('/api/schedule', json('POST', {enabled: form.elements.enabled.checked, times}));
}, '예약 재시작 설정을 저장했습니다.'));

async function loadBackups() {
  const data = await api('/api/backups'); const list = $('#backup-list'); list.replaceChildren();
  if (!data.backups.length) { list.textContent = '아직 생성된 백업이 없습니다.'; return; }
  for (const backup of data.backups) {
    const row = document.createElement('article'); row.className = 'record';
    const info = document.createElement('div'); const title = document.createElement('strong'); title.textContent = backup.name; const meta = document.createElement('small'); meta.textContent = `${backup.created} · ${bytes(backup.size)}`; info.append(title, meta);
    const actions = document.createElement('div'); actions.className = 'record-actions';
    const download = document.createElement('a'); download.href = `/api/backups/download?name=${encodeURIComponent(backup.name)}`; download.textContent = '다운로드';
    const restore = document.createElement('button'); restore.textContent = '복원'; restore.addEventListener('click', () => perform(() => api('/api/backups/restore', json('POST', {name: backup.name})), '백업을 복원했습니다.').then(loadBackups));
    actions.append(download, restore); row.append(info, actions); list.append(row);
  }
}
$('#create-backup').addEventListener('click', () => perform(() => api('/api/backups', {method:'POST'}), '백업을 생성했습니다.').then(loadBackups));

async function loadTextFile() { const data = await api(`/api/text-file/${$('#text-file-kind').value}`); $('#text-file-editor').value = data.content; }
$('#text-file-kind').addEventListener('change', () => loadTextFile().catch(error => message(error.message, true)));
$('#save-text-file').addEventListener('click', () => perform(() => api(`/api/text-file/${$('#text-file-kind').value}`, json('POST', {content: $('#text-file-editor').value})), '고급 설정 파일을 저장했습니다.'));

async function openFileEditor(path) {
  const dialog = $('#file-editor-dialog');
  editingFilePath = '';
  fileEditorOriginal = '';
  $('#file-editor-title').textContent = path.split('/').at(-1) || '파일 편집';
  $('#file-editor-path').textContent = `/data/${path}`;
  $('#file-editor-status').classList.remove('error');
  $('#file-editor-status').textContent = '파일을 불러오는 중입니다.';
  $('#file-editor-content').value = '';
  $('#file-editor-content').disabled = true;
  $('#save-file-editor').disabled = true;
  showDialog(dialog);
  try {
    const data = await api(`/api/files/text?path=${encodeURIComponent(path)}`);
    if (!dialog.open) return;
    editingFilePath = data.path;
    fileEditorOriginal = data.content;
    $('#file-editor-title').textContent = data.name;
    $('#file-editor-path').textContent = `/data/${data.path} · ${bytes(data.size)}`;
    $('#file-editor-content').value = data.content;
    $('#file-editor-content').disabled = false;
    $('#save-file-editor').disabled = true;
    $('#file-editor-status').textContent = '텍스트 파일을 편집할 수 있습니다. Ctrl/Cmd+S로 저장할 수 있습니다.';
    $('#file-editor-content').focus();
  } catch (error) {
    $('#file-editor-status').classList.add('error');
    $('#file-editor-status').textContent = error.message;
  }
}
function closeFileEditor() { closeDialog($('#file-editor-dialog')); }
$('#close-file-editor').addEventListener('click', closeFileEditor);
$('#cancel-file-editor').addEventListener('click', closeFileEditor);
$('#file-editor-dialog').addEventListener('close', () => { editingFilePath = ''; fileEditorOriginal = ''; });
$('#save-file-editor').addEventListener('click', async () => {
  if (!editingFilePath) return;
  const button = $('#save-file-editor');
  const status = $('#file-editor-status');
  button.disabled = true;
  status.classList.remove('error');
  status.textContent = '파일을 저장하고 있습니다.';
  try {
    const content = $('#file-editor-content').value;
    const data = await api(`/api/files/text?path=${encodeURIComponent(editingFilePath)}`, json('POST', {content}));
    fileEditorOriginal = content;
    status.textContent = `${data.message} · ${bytes(data.size)}`;
    await loadFiles(currentPath);
  } catch (error) {
    status.classList.add('error');
    status.textContent = error.message;
  } finally { button.disabled = !editingFilePath || $('#file-editor-content').value === fileEditorOriginal; }
});
$('#file-editor-content').addEventListener('input', event => {
  $('#file-editor-status').classList.remove('error');
  $('#save-file-editor').disabled = !editingFilePath || event.currentTarget.value === fileEditorOriginal;
  if (editingFilePath) $('#file-editor-status').textContent = event.currentTarget.value === fileEditorOriginal ? '저장된 내용과 같습니다.' : '저장하지 않은 변경사항이 있습니다.';
});
$('#file-editor-content').addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 's') {
    event.preventDefault();
    if (!$('#save-file-editor').disabled) $('#save-file-editor').click();
  }
});

function renderBreadcrumbs(path) {
  const target = $('#breadcrumbs'); target.replaceChildren(); const root = document.createElement('button'); root.textContent = '/data'; root.addEventListener('click', () => loadFiles('')); target.append(root);
  let accumulated = '';
  for (const part of path.split('/').filter(Boolean)) { target.append(document.createTextNode(' / ')); accumulated = accumulated ? `${accumulated}/${part}` : part; const destination = accumulated; const button = document.createElement('button'); button.textContent = part; button.addEventListener('click', () => loadFiles(destination)); target.append(button); }
}
async function loadFiles(path = '') {
  const data = await api(`/api/files?path=${encodeURIComponent(path)}`); currentPath = data.path; renderBreadcrumbs(data.path); const list = $('#file-list'); list.replaceChildren();
  for (const entry of data.entries) {
    const row = document.createElement('div'); row.className = 'file-row';
    const icon = document.createElement('img'); icon.className = 'file-entry-icon'; icon.src = entry.type === 'dir' ? '/static/zomboid-file-folder-v1.png' : '/static/zomboid-file-document-v1.png'; icon.alt = entry.type === 'dir' ? '폴더' : '파일';
    const name = document.createElement('button'); name.type = 'button'; name.className = 'file-entry-name'; name.textContent = entry.name;
    name.title = entry.type === 'dir' ? '폴더 열기' : '텍스트 편집기로 열기';
    name.addEventListener('click', () => entry.type === 'dir' ? loadFiles(entry.path) : openFileEditor(entry.path));
    const size = document.createElement('small'); size.className = 'file-size'; size.textContent = entry.type === 'file' ? bytes(entry.size) : '폴더'; const date = document.createElement('small'); date.className = 'file-date'; date.textContent = entry.modified;
    const actions = document.createElement('div');
    if (entry.type === 'file') { const download = document.createElement('a'); download.href = `/api/files/download?path=${encodeURIComponent(entry.path)}`; download.textContent = '받기'; actions.append(download); }
    const remove = document.createElement('button'); remove.textContent = '삭제'; remove.addEventListener('click', () => perform(() => api(`/api/files?path=${encodeURIComponent(entry.path)}`, {method:'DELETE'}), '삭제했습니다.').then(() => loadFiles(currentPath))); actions.append(remove);
    row.append(icon, name, size, date, actions); list.append(row);
  }
}
$('#folder-up').addEventListener('click', () => loadFiles(currentPath.split('/').slice(0,-1).join('/')).catch(error => message(error.message, true)));
$('#refresh-files').addEventListener('click', () => loadFiles(currentPath).catch(error => message(error.message, true)));
$('#new-folder').addEventListener('click', async () => {
  const name = await requestTextInput({title: '새 폴더 만들기', description: '현재 경로에 생성할 폴더 이름을 입력하세요.', label: '폴더 이름', placeholder: '예: mods-backup'});
  if (!name) return;
  await perform(() => api('/api/files/directory', json('POST', {path: currentPath, name})), '폴더를 만들었습니다.');
  await loadFiles(currentPath);
});
$('#file-upload').addEventListener('change', async event => {
  const input = event.currentTarget;
  const file = input.files[0];
  if (!file) return;
  const data = new FormData(); data.append('path', currentPath); data.append('file', file);
  try { await perform(() => api('/api/files/upload', {method:'POST', body:data}), '파일을 올렸습니다.'); await loadFiles(currentPath); }
  catch (_error) { /* perform already displays the upload error. */ }
  finally { input.value = ''; }
});
$('#folder-upload').addEventListener('change', async event => {
  const input = event.currentTarget;
  const files = [...input.files];
  if (!files.length) return;
  const data = new FormData(); data.append('path', currentPath);
  files.forEach(file => data.append('files', file, file.webkitRelativePath || file.name));
  try {
    const result = await perform(() => api('/api/files/upload-folder', {method:'POST', body:data}));
    message(result.message || `폴더의 파일 ${files.length}개를 업로드했습니다.`);
    await loadFiles(currentPath);
  } catch (_error) { /* perform already displays the upload error. */ }
  finally { input.value = ''; }
});

function renderDiscord(data) {
  const config = data.config || data;
  const form = $('#discord-form');
  discordWebhookConfigured = Boolean(config.webhook_configured);
  fillForm(form, config);
  form.elements.webhook_url.value = '';
  form.elements.webhook_url.placeholder = discordWebhookConfigured ? '새 URL을 입력하면 기존 웹훅이 교체됩니다.' : 'https://discord.com/api/webhooks/...';
  form.elements.clear_webhook.checked = false;
  form.elements.webhook_url.disabled = false;
  $('#discord-enabled-label').textContent = config.enabled ? '사용 중' : '사용 안 함';
  $('#discord-webhook-hint').textContent = discordWebhookConfigured ? config.webhook_hint : 'Discord 채널 웹훅 URL이 등록되지 않았습니다.';
  const state = $('#discord-state');
  state.textContent = config.enabled ? '연동 사용 중' : discordWebhookConfigured ? '웹훅 등록됨' : '연동 꺼짐';
  state.classList.toggle('online', Boolean(config.enabled && discordWebhookConfigured));
  $('#test-discord').disabled = !discordWebhookConfigured;
}

async function loadDiscord() {
  const data = await api('/api/discord');
  renderDiscord(data);
  const status = $('#discord-status');
  status.className = 'discord-status';
  status.textContent = discordWebhookConfigured ? '저장된 웹훅으로 Discord 알림을 전송할 수 있습니다.' : 'Discord 채널에서 생성한 웹훅 URL을 등록해주세요.';
}

$('#discord-form').elements.enabled.addEventListener('change', event => { $('#discord-enabled-label').textContent = event.target.checked ? '사용 중' : '사용 안 함'; });
$('#discord-form').elements.clear_webhook.addEventListener('change', event => { $('#discord-form').elements.webhook_url.disabled = event.target.checked; });
$('#save-discord').addEventListener('click', async () => {
  const status = $('#discord-status');
  status.className = 'discord-status'; status.textContent = 'Discord 연동 설정을 저장하고 있습니다.';
  try {
    const data = await api('/api/discord', json('POST', formData($('#discord-form'))));
    renderDiscord(data); status.className = 'discord-status success'; status.textContent = data.message;
  } catch (error) { status.className = 'discord-status error'; status.textContent = error.message; }
});
$('#test-discord').addEventListener('click', async () => {
  const status = $('#discord-status');
  status.className = 'discord-status'; status.textContent = 'Discord 테스트 메시지를 전송하고 있습니다.';
  try {
    const data = await api('/api/discord/test', {method:'POST'});
    status.className = 'discord-status success'; status.textContent = data.message;
  } catch (error) { status.className = 'discord-status error'; status.textContent = error.message; }
});

async function checkPanelUpdate(showMessage = false) {
  const data = await api('/api/panel-update');
  $('#update-dot').hidden = !data.available; $('#update-bubble').hidden = !data.available;
  $('#update-current-version').textContent = data.current_version || statusCache?.panel_version || '-';
  $('#update-image-status').textContent = data.available ? '업데이트 가능' : '최신 이미지 사용 중';
  $('#update-image-detail').textContent = data.error || (data.available ? `${data.current_image} → ${data.latest_image}` : `이미지 ${data.current_image || '-'}`);
  if (showMessage && data.error) message(`업데이트 확인 실패: ${data.error}`, true);
  return data;
}
async function openPanelUpdateDialog() {
  const dialog = $('#panel-update-dialog');
  showDialog(dialog);
  $('#update-image-status').textContent = '확인 중';
  $('#update-image-detail').textContent = '컨테이너 레지스트리를 확인합니다.';
  try { await checkPanelUpdate(); }
  catch (error) { $('#update-image-status').textContent = '확인 실패'; $('#update-image-detail').textContent = error.message; }
}
$('#panel-update-button').addEventListener('click', openPanelUpdateDialog);
$('#open-update-dialog').addEventListener('click', openPanelUpdateDialog);
$('#close-panel-update').addEventListener('click', () => closeDialog($('#panel-update-dialog')));
$('#cancel-panel-update').addEventListener('click', () => closeDialog($('#panel-update-dialog')));
$('#apply-update').addEventListener('click', async event => {
  event.currentTarget.disabled = true;
  $('#update-image-status').textContent = '업데이트 시작 중';
  $('#update-image-detail').textContent = '새 구동기 이미지를 적용하도록 요청하고 있습니다.';
  try {
    await api('/api/panel-update', {method:'POST'});
    $('#update-image-status').textContent = '업데이트 요청 완료';
    $('#update-image-detail').textContent = '새 이미지를 적용 중입니다. 잠시 후 패널이 다시 연결됩니다.';
  } catch (error) {
    $('#update-image-status').textContent = '업데이트 실패';
    $('#update-image-detail').textContent = error.message;
    event.currentTarget.disabled = false;
  }
});

$('#logout').addEventListener('click', () => {
  $('#logout-confirm-status').hidden = true;
  $('#logout-confirm-status').textContent = '';
  $('#confirm-logout').disabled = false;
  showDialog($('#logout-confirm-dialog'));
});
$('#close-logout-confirm').addEventListener('click', () => closeDialog($('#logout-confirm-dialog')));
$('#cancel-logout').addEventListener('click', () => closeDialog($('#logout-confirm-dialog')));
$('#confirm-logout').addEventListener('click', async event => {
  const status = $('#logout-confirm-status');
  event.currentTarget.disabled = true;
  status.hidden = false;
  status.classList.remove('error');
  status.textContent = '로그아웃하고 있습니다.';
  try {
    const data = await api('/api/auth/logout', {method:'POST'});
    location.assign(data.redirect);
  } catch (error) {
    status.classList.add('error');
    status.textContent = error.message;
    event.currentTarget.disabled = false;
  }
});
async function refreshAll(notify = false) {
  try { await Promise.all([refreshStatus(), refreshResources(), loadLogs()]); if (notify) message('최신 상태로 갱신했습니다.'); } catch (error) { message(error.message, true); }
}

showView(location.hash.slice(1) || 'overview');
refreshAll();
checkPanelUpdate().catch(() => {});
setInterval(() => refreshStatus().catch(() => {}), 3000);
setInterval(() => refreshResources().catch(() => {}), RESOURCE_REFRESH_MS);
setInterval(() => loadLogs().catch(() => {}), 5000);
setInterval(() => checkPanelUpdate().catch(() => {}), 300000);
window.addEventListener('resize', renderResourceHistory);
window.addEventListener('pagehide', () => saveResourceHistory(true));
