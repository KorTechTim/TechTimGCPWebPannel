'use strict';
const $ = id => document.getElementById(id);
let state = null;
let uiBusy = false;
let logKind = 'server';
let connectionMode = 'invite';
let permissionLists = {};
let panelUpdating = false;
let serverStartRequested = false;
let gamePasswordSet = null;
let activeDetail = null;
let lastJob = '';
let toastTimer;
let panelUpdateCheckTimer;
let serverFilesPath = '';
let serverFilesParent = '';
let serverFileEditorPath = '';
let serverFileEditorOriginal = '';
let modPackages = [];
let modUpdateTarget = '';
let modLoaderReady = false;
let steamIdPopup = null;
let discordBusy = false;
let discordWebhookConfigured = false;
let worldNames = new Set();
const selectedServerFolders = new Set();
const polls = new Set();
const runningStates = new Set(['running', 'restarting', 'paused', 'removing']);
const RESOURCE_REFRESH_MS = 1000;
const RESOURCE_HISTORY_WINDOW_MS = 24 * 60 * 60 * 1000;
const RESOURCE_HISTORY_STORAGE_KEY = 'techtim-valheim-resource-history-v1';
let resourceHistorySavedAt = 0;

function loadResourceHistory() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RESOURCE_HISTORY_STORAGE_KEY) || '[]');
    const cutoff = Date.now() - RESOURCE_HISTORY_WINDOW_MS;
    return Array.isArray(parsed)
      ? parsed.filter(point => Array.isArray(point) && point.length === 3 && Number(point[0]) >= cutoff)
      : [];
  } catch (_error) { return []; }
}
const resourceHistory = loadResourceHistory();

async function api(url, options = {}) {
  const response = await fetch(url, {cache: 'no-store', ...options});
  const data = await response.json();
  if (response.status === 401) { location.assign('/login'); throw new Error('로그인이 필요합니다.'); }
  if (response.status === 403 && data.detail === '최초 비밀번호를 변경해주세요.') location.assign('/change-password');
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '입력한 내용을 확인해주세요.');
  return data;
}

function jsonPost(url, data, method = 'POST') {
  return api(url, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
}

function toast(text) {
  clearTimeout(toastTimer);
  $('toast').textContent = text;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500);
}

function showNotice(title, text) {
  const dialog = $('notice-dialog');
  $('notice-title').textContent = title;
  $('notice-text').textContent = text;
  if (!dialog.open) dialog.showModal();
  $('notice-ok').focus();
}
$('notice-ok').onclick = () => $('notice-dialog').close();

function message(id, text, error = false) {
  $(id).textContent = text;
  $(id).classList.toggle('error-text', error);
}

function bytes(value) {
  if (!Number.isFinite(value)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value.toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

function connectionDetails() {
  const host = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname) ? 'VM 공개 IP' : location.hostname;
  if (connectionMode === 'ip') {
    return {label: 'IP ADDRESS', value: `${host}:${state?.port || 2456}`, note: '직접 접속할 때 사용하는 공개 IP 주소입니다.', copy: 'IP 주소 복사', ready: host !== 'VM 공개 IP'};
  }
  if (!state?.crossplay) {
    return {label: 'INVITE CODE', value: '크로스플레이 필요', note: '서버 설정에서 크로스플레이를 켜면 초대 코드가 발급됩니다.', copy: '초대 코드 복사', ready: false};
  }
  if (state?.join_code) {
    return {label: 'INVITE CODE', value: state.join_code, note: '게임의 참가 코드 입력란에 사용하세요.', copy: '초대 코드 복사', ready: true};
  }
  const running = runningStates.has(state?.server_status);
  return {label: 'INVITE CODE', value: running ? '초대 코드 준비 중' : '서버 시작 후 표시', note: running ? 'PlayFab에서 코드를 발급받고 있습니다.' : '서버가 실행되면 초대 코드가 표시됩니다.', copy: '초대 코드 복사', ready: false};
}

function renderConnection() {
  const details = connectionDetails();
  $('connection-invite').setAttribute('aria-selected', String(connectionMode === 'invite'));
  $('connection-ip').setAttribute('aria-selected', String(connectionMode === 'ip'));
  $('connection-label').textContent = details.label;
  $('connection-address').textContent = details.value;
  $('connection-note').textContent = details.note;
  $('copy-address').firstChild.textContent = `${details.copy} `;
  $('copy-address').disabled = !details.ready;
}

function confirmAction(title, text, button = '진행') {
  const dialog = $('confirm-dialog');
  $('confirm-title').textContent = title;
  $('confirm-text').textContent = text;
  $('confirm-ok').textContent = button;
  dialog.returnValue = '';
  dialog.showModal();
  return new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'yes'), {once: true}));
}
$('confirm-ok').onclick = () => $('confirm-dialog').close('yes');
$('confirm-cancel').onclick = () => $('confirm-dialog').close('cancel');
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', event => {
  event.preventDefault();
  const dialog = button.closest('dialog');
  if (dialog?.classList.contains('detail-page')) closeDetail();
  else dialog?.close('cancel');
}));

function setSidebarCurrent(item) {
  document.querySelectorAll('[data-open]').forEach(link => link.removeAttribute('aria-current'));
  if (item) item.setAttribute('aria-current', 'page');
}

function parkActiveDetail() {
  if (!activeDetail) return;
  const dialog = activeDetail;
  activeDetail = null;
  if (dialog.open) dialog.close('cancel');
  dialog.classList.remove('detail-page');
  document.body.append(dialog);
}

function closeDetail(scroll = true) {
  if (!activeDetail) return;
  parkActiveDetail();
  $('detail-view').hidden = true;
  $('dashboard-view').hidden = false;
  $('topbar-page-title').textContent = '서버 관리';
  setSidebarCurrent(null);
  if (scroll) window.scrollTo({top: 0, behavior: 'smooth'});
}

async function openDetail(id, loader) {
  try {
    if (loader) await loader();
    parkActiveDetail();
    const dialog = $(id);
    $('dashboard-view').hidden = true;
    $('detail-view').hidden = false;
    dialog.classList.add('detail-page');
    $('detail-content').replaceChildren(dialog);
    dialog.show();
    activeDetail = dialog;
    $('topbar-page-title').textContent = dialog.querySelector('.dialog-head h2')?.textContent || '상세 관리';
    const menu = id === 'settings-dialog' ? $('sidebar-settings') : document.querySelector(`[data-open="${id}"]`);
    setSidebarCurrent(menu);
    updateControls();
    window.scrollTo({top: 0, behavior: 'smooth'});
  } catch (error) { toast(error.message); }
}

$('detail-back').onclick = () => closeDetail();
document.querySelectorAll('.brand').forEach(link => link.addEventListener('click', () => closeDetail(false)));

function serverConfigurationLocked() { return serverStartRequested || runningStates.has(state?.server_status); }
function writable() { return state?.docker_available && !state.busy && !uiBusy && !serverConfigurationLocked(); }
function updateRunningLocks() {
  const locked = serverConfigurationLocked();
  document.querySelectorAll('[data-running-lock]').forEach(element => {
    element.classList.toggle('is-running-locked', locked);
    element.setAttribute('aria-disabled', String(locked));
    if (locked) element.title = '서버 실행 중에는 조작할 수 없습니다. 서버를 중지해주세요.';
    else element.removeAttribute('title');
  });
}
function updateControls() {
  const disabled = !writable();
  document.querySelectorAll('[data-writable]').forEach(element => {
    if (element.matches('form')) element.querySelectorAll('input,select,textarea,button').forEach(control => { control.disabled = disabled; });
    else element.disabled = disabled;
  });
  const available = state?.docker_available && !state.busy && !uiBusy;
  const running = runningStates.has(state?.server_status);
  $('start').disabled = !available || running || !state.engine.installed;
  $('stop').disabled = !available || !running;
  $('restart').disabled = !available || !running;
  $('install').disabled = !available || running;
  $('sidebar-settings').disabled = !state;
  $('panel-update-action').disabled = !available;
  updateRunningLocks();
  updateServerFileControls();
  updateModControls();
  $('install-label').textContent = state?.engine.installed ? '서버 업데이트' : '엔진 설치';
}

async function refreshStatus() {
  if (polls.has('status')) return;
  polls.add('status');
  try {
    state = await api('/api/server/status');
    const names = {missing: '서버 미생성', running: state.ready ? '서버 실행 중' : '연결 준비 중',
      exited: '서버 중지됨', dead: '프로세스 종료', restarting: '재시작 중', paused: '일시 중지', unavailable: 'Docker 연결 필요', created: '시작 대기'};
    const status = $('server-status');
    status.replaceChildren();
    const dot = document.createElement('span');
    dot.className = `dot ${state.ready ? 'online' : state.busy ? 'busy' : ''}`;
    status.append(dot, document.createTextNode(names[state.server_status] || state.server_status));
    $('current-world').textContent = state.world;
    $('engine-status').textContent = state.engine.installed ? `설치 완료${state.engine.build_id ? ' · '+state.engine.build_id : ''}` : '설치 필요';
    $('panel-version').textContent = state.panel_version;
    $('hero-crossplay').textContent = state.crossplay ? '크로스플레이 ON' : 'Steam 전용';
    renderConnection();
    if ($('panel-update-dialog').open) await loadPanelUpdate();
    $('connection-error').hidden = state.docker_available;
    $('connection-error').textContent = 'Docker에 연결할 수 없습니다. VM의 Docker 서비스와 패널 연결 설정을 확인해주세요.';
    const job = state.operation;
    if (serverStartRequested && (runningStates.has(state.server_status) || ['completed', 'failed'].includes(job.status))) {
      serverStartRequested = false;
    }
    const banner = $('operation-banner');
    banner.hidden = !job.message;
    banner.dataset.status = job.status;
    banner.textContent = job.message || '';
    if (state.oom_killed) {
      banner.hidden = false; banner.dataset.status = 'failed';
      banner.textContent = '메모리 부족으로 서버가 종료되었습니다. 서버 로그와 VM 메모리를 확인해주세요.';
    }
    if (job.updated_at !== lastJob && ['completed', 'failed'].includes(job.status)) {
      lastJob = job.updated_at;
      if ($('backups-dialog').open) await loadBackups();
      if ($('worlds-dialog').open) await loadWorlds();
    }
    if (panelUpdating) {
      const update = await loadPanelUpdate();
      if (['completed', 'failed'].includes(update.status)) {
        panelUpdating = false;
        if (update.status === 'completed') location.reload();
      }
    }
  } catch (error) {
    $('connection-error').hidden = false;
    $('connection-error').textContent = panelUpdating ? '웹패널을 교체하고 있습니다. 다시 연결될 때까지 기다려주세요.' : error.message;
    if (state) state.docker_available = false;
  } finally { updateControls(); polls.delete('status'); }
}

async function refreshLogs() {
  if (polls.has('logs')) return;
  polls.add('logs');
  const requestedKind = logKind;
  try {
    const data = await api(`/api/logs?kind=${requestedKind}`);
    if (requestedKind === logKind) {
      $('terminal').textContent = data.log;
      if ($('auto-scroll').checked) $('terminal').scrollTop = $('terminal').scrollHeight;
    }
  } catch (error) { $('terminal').textContent = error.message; }
  finally { polls.delete('logs'); }
}

function selectLog(kind) {
  logKind = kind;
  document.querySelectorAll('[data-log]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.log === kind)));
  refreshLogs();
}
document.querySelectorAll('[data-log]').forEach(button => button.onclick = () => selectLog(button.dataset.log));

async function perform(url, title, text, options = {method: 'POST'}) {
  if (text && !await confirmAction(title, text, title)) return;
  uiBusy = true; updateControls();
  try {
    const data = await api(url, options);
    toast(data.message || `${title} 요청 완료`);
    if (url === '/api/install') selectLog('install');
    if (url.startsWith('/api/server/')) selectLog('server');
    if (url === '/api/panel/update') panelUpdating = true;
    await refreshStatus();
  } catch (error) {
    if (url === '/api/server/start' && error.message.includes('게임 접속 비밀번호')) {
      showNotice('게임 접속 비밀번호 설정', error.message);
    } else toast(error.message);
  }
  finally { uiBusy = false; updateControls(); }
}
$('start').onclick = async () => {
  if (gamePasswordSet === false) {
    showNotice('게임 접속 비밀번호 설정', '서버 설정에서 게임 접속 비밀번호를 먼저 저장해주세요.');
    return;
  }
  serverStartRequested = true;
  updateControls();
  await perform('/api/server/start', '서버 시작');
  if (!state?.busy && !runningStates.has(state?.server_status)) serverStartRequested = false;
  updateControls();
};
$('stop').onclick = () => perform('/api/server/stop', '서버 중지', '접속 중인 플레이어의 연결이 종료됩니다. 월드 저장이 끝날 때까지 기다린 뒤 서버를 중지합니다.');
$('restart').onclick = () => perform('/api/server/restart', '서버 재시작', '현재 월드를 저장하고 서버를 다시 시작합니다. 접속 중인 플레이어는 다시 접속해야 합니다.');
$('install').onclick = async () => {
  const title = state?.engine.installed ? '서버 업데이트' : '엔진 설치';
  const text = 'Steam 정식 서버를 다운로드합니다. 기존 월드가 있으면 업데이트 전에 백업을 만듭니다.';
  uiBusy = true; updateControls();
  let update;
  try {
    update = await api('/api/install/check');
  } catch (error) { toast(error.message); return; }
  finally { uiBusy = false; updateControls(); }
  if (update.installed && update.update_available === false) {
    showNotice('서버 업데이트', '이미 엔진이 최신 버전입니다');
    return;
  }
  await perform('/api/install', title, text);
};
$('logout').onclick = async () => { try { await api('/api/auth/logout', {method: 'POST'}); location.assign('/login'); } catch (error) { toast(error.message); } };
$('connection-invite').onclick = () => { connectionMode = 'invite'; renderConnection(); };
$('connection-ip').onclick = () => { connectionMode = 'ip'; renderConnection(); };
$('sidebar-connection').onclick = () => { connectionMode = 'invite'; renderConnection(); };
$('copy-address').onclick = async () => {
  const details = connectionDetails();
  if (!details.ready) { toast(details.note); return; }
  const value = details.value;
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
    else { const area = document.createElement('textarea'); area.value = value; document.body.append(area); area.select(); const copied = document.execCommand('copy'); area.remove(); if (!copied) throw new Error(); }
    toast(connectionMode === 'invite' ? '초대 코드를 복사했습니다.' : 'IP 주소를 복사했습니다.');
  } catch { toast(`${connectionMode === 'invite' ? '초대 코드' : 'IP 주소'}: ${value}`); }
};

const integerFields = ['port', 'save_interval', 'backups', 'backup_short', 'backup_long'];
function fillWorldNames(worlds) {
  $('world-names').replaceChildren(...worlds.filter(world => world.complete).map(world => {
    const option = document.createElement('option'); option.value = world.name; return option;
  }));
}

async function loadQuickSettings() {
  const [config, data] = await Promise.all([api('/api/config'), api('/api/worlds')]);
  const form = $('quick-settings-form');
  ['server_name', 'world', 'port'].forEach(key => { form.elements.namedItem(key).value = config[key] ?? ''; });
  ['crossplay', 'public'].forEach(key => { form.elements.namedItem(key).checked = Boolean(config[key]); });
  gamePasswordSet = Boolean(config.password_set);
  form.elements.password.value = '';
  fillWorldNames(data.worlds);
  message('quick-settings-message', config.password_set ? '접속 비밀번호가 설정되어 있습니다.' : '최초 시작 전 비밀번호를 입력해주세요.');
}

$('quick-settings-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const config = Object.fromEntries(new FormData(form));
  const passwordProvided = Boolean(config.password);
  config.port = Number(config.port);
  ['crossplay', 'public'].forEach(key => { config[key] = form.elements.namedItem(key).checked; });
  if (!config.password) delete config.password;
  uiBusy = true; updateControls();
  try {
    await jsonPost('/api/config', config);
    if (passwordProvided) gamePasswordSet = true;
    form.elements.password.value = '';
    message('quick-settings-message', '기본 설정을 저장했습니다. 다음 서버 시작에 적용됩니다.');
    await refreshStatus();
  } catch (error) { message('quick-settings-message', error.message, true); }
  finally { uiBusy = false; updateControls(); }
};

async function loadSettings() {
  const [config, data] = await Promise.all([api('/api/config'), api('/api/worlds')]);
  const form = $('settings-form');
  for (const [key, value] of Object.entries(config)) {
    const field = form.elements.namedItem(key);
    if (!field) continue;
    if (field.type === 'checkbox') field.checked = value; else field.value = value;
  }
  form.elements.password.value = '';
  form.elements.password.required = !config.password_set;
  $('password-hint').textContent = config.password_set ? '변경할 때만 입력하세요. 비우면 기존 비밀번호를 유지합니다.' : '최초 시작 전 5자 이상으로 설정해주세요.';
  fillWorldNames(data.worlds);
  message('settings-message', '');
}
$('sidebar-settings').onclick = () => openDetail('settings-dialog', loadSettings);
$('settings-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const config = Object.fromEntries(new FormData(form));
  ['crossplay', 'public'].forEach(key => { config[key] = form.elements.namedItem(key).checked; });
  integerFields.forEach(key => { config[key] = Number(config[key]); });
  if (!config.password) delete config.password;
  uiBusy = true; updateControls();
  try { await jsonPost('/api/config', config); form.elements.password.value = ''; form.elements.password.required = false; message('settings-message', '설정을 저장했습니다. 다음 서버 시작에 적용됩니다.'); await Promise.all([refreshStatus(), loadQuickSettings()]); }
  catch (error) { message('settings-message', error.message, true); }
  finally { uiBusy = false; updateControls(); }
};

const modifierFields = ['preset', 'combat', 'death_penalty', 'resources', 'raids', 'portals'];
const modifierFlags = ['no_build_cost', 'player_events', 'passive_mobs', 'no_map'];
async function loadModifiers() {
  const config = await api('/api/config');
  const form = $('modifiers-form');
  modifierFields.forEach(key => { form.elements.namedItem(key).value = config[key] || ''; });
  modifierFlags.forEach(key => { form.elements.namedItem(key).checked = Boolean(config[key]); });
  message('modifiers-message', '');
}
$('modifiers-reset').onclick = () => {
  const form = $('modifiers-form');
  modifierFields.forEach(key => { form.elements.namedItem(key).value = ''; });
  modifierFlags.forEach(key => { form.elements.namedItem(key).checked = false; });
  message('modifiers-message', '공식 기본값으로 되돌렸습니다. 저장하면 다음 서버 시작에 적용됩니다.');
};
$('modifiers-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const config = Object.fromEntries(new FormData(form));
  modifierFlags.forEach(key => { config[key] = form.elements.namedItem(key).checked; });
  uiBusy = true; updateControls();
  try { await jsonPost('/api/config', config); message('modifiers-message', '월드 배율과 플레이 규칙을 저장했습니다. 다음 서버 시작에 적용됩니다.'); await refreshStatus(); }
  catch (error) { message('modifiers-message', error.message, true); }
  finally { uiBusy = false; updateControls(); }
};

function renderPanelUpdate(info = {status: 'idle'}) {
  const running = info.status === 'running' || panelUpdating;
  $('panel-update-current').textContent = state?.panel_version || '확인 대기';
  $('panel-update-progress').dataset.status = running ? 'running' : info.status || 'idle';
  $('panel-update-message').textContent = info.message || (running ? '최신 구동기 이미지를 확인하고 있습니다.' : '업데이트 확인을 누르면 최신 버전을 확인합니다.');
}

function setPanelUpdateNotice(available) {
  const notice = $('panel-update-notice');
  const button = $('panel-update-button');
  notice.classList.toggle('show', available);
  button.classList.toggle('update-available', available);
  button.title = available ? '업데이트가 있습니다. 웹패널을 업그레이드하세요' : '패널 업데이트';
  button.setAttribute('aria-label', available ? '패널 업데이트 있음' : '패널 업데이트');
}

function schedulePanelUpdateCheck(delay) {
  clearTimeout(panelUpdateCheckTimer);
  panelUpdateCheckTimer = setTimeout(() => checkPanelUpdate(true), delay);
}

async function checkPanelUpdate(force = false) {
  try {
    const info = await api(`/api/panel/update/check${force ? '?force=true' : ''}`);
    if (info.status !== 'ok') throw new Error(info.message || '업데이트 정보를 확인할 수 없습니다.');
    setPanelUpdateNotice(Boolean(info.update_available));
    schedulePanelUpdateCheck(5 * 60 * 1000);
  } catch {
    setPanelUpdateNotice(false);
    schedulePanelUpdateCheck(60 * 1000);
  }
}

async function loadPanelUpdate() {
  setPanelUpdateNotice(false);
  try {
    const info = await api('/api/panel/update/status');
    renderPanelUpdate(info);
    return info;
  } catch (error) {
    const info = {status: 'idle', message: error.message};
    renderPanelUpdate(info);
    return info;
  }
}
$('panel-update-action').onclick = async () => {
  setPanelUpdateNotice(false);
  renderPanelUpdate({status: 'running', message: '업데이트 요청을 준비하고 있습니다.'});
  await perform('/api/panel/update', '구동기 업데이트', '최신 TechTim GCP 웹 구동기로 교체합니다. 잠시 연결이 끊길 수 있으며 실패하면 이전 버전으로 복구를 시도합니다.');
  if (!panelUpdating) await loadPanelUpdate();
};

function emptyList(root, text) { const empty = document.createElement('p'); empty.className = 'empty-state'; empty.textContent = text; root.replaceChildren(empty); }
function fileRow(name, detail) {
  const row = document.createElement('div'); row.className = 'file-row';
  const info = document.createElement('div'); const title = document.createElement('strong'); const subtitle = document.createElement('small');
  title.textContent = name; subtitle.textContent = detail; info.append(title, subtitle);
  const actions = document.createElement('div'); actions.className = 'file-actions'; row.append(info, actions);
  return {row, actions};
}
function actionButton(label, handler, write = false) {
  const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.onclick = handler;
  if (write) button.setAttribute('data-writable', '');
  return button;
}
function downloadLink(label, url) { const link = document.createElement('a'); link.textContent = label; link.href = url; link.setAttribute('download', ''); return link; }

function updateServerFileControls() {
  const enabled = writable();
  ['server-files-refresh', 'server-files-up', 'server-files-upload', 'server-files-upload-folder'].forEach(id => {
    const control = $(id);
    if (control) control.disabled = !enabled || (id === 'server-files-up' && !serverFilesPath);
  });
  const folderForm = $('server-files-new-folder');
  if (folderForm) folderForm.querySelectorAll('input,button').forEach(control => { control.disabled = !enabled; });
  const folderDownload = $('server-files-download-folders');
  if (folderDownload) folderDownload.disabled = !enabled || selectedServerFolders.size === 0;
  document.querySelectorAll('#server-files-path button').forEach(control => { control.disabled = !enabled; });
  document.querySelectorAll('.server-folder-select, .server-file-download, .explorer-editable-file').forEach(control => { control.disabled = !enabled; });
  const editor = $('server-file-editor-content');
  const save = $('server-file-editor-save');
  if (editor) editor.disabled = !enabled || !serverFileEditorPath;
  if (save) save.disabled = !enabled || !serverFileEditorPath || editor.value === serverFileEditorOriginal;
}

function setServerFilesMessage(text, error = false) {
  message('server-files-message', text, error);
}

function renderServerFilesPath(path) {
  const breadcrumb = $('server-files-path');
  breadcrumb.replaceChildren();
  const segments = String(path || '').split('/').filter(Boolean);
  const locations = [{label: '/server', path: ''}];
  let current = '';
  for (const segment of segments) {
    current = current ? `${current}/${segment}` : segment;
    locations.push({label: segment, path: current});
  }
  locations.forEach((location, index) => {
    if (index) {
      const separator = document.createElement('span');
      separator.className = 'explorer-path-separator'; separator.textContent = '/'; separator.setAttribute('aria-hidden', 'true');
      breadcrumb.append(separator);
    }
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = location.label; button.title = `${location.label} 폴더로 이동`;
    button.dataset.path = location.path;
    if (index === locations.length - 1) button.setAttribute('aria-current', 'location');
    button.onclick = () => loadServerFiles(location.path);
    breadcrumb.append(button);
  });
}

function serverFileRow(entry) {
  const row = document.createElement('tr');
  const nameCell = document.createElement('td');
  const nameWrap = document.createElement('div');
  nameWrap.className = 'explorer-name-wrap';
  const icon = document.createElement('img');
  icon.className = 'explorer-entry-icon';
  icon.src = entry.type === 'dir' ? '/static/valheim-file-folder-v1.svg' : '/static/valheim-file-document-v1.svg';
  icon.alt = entry.type === 'dir' ? '폴더' : '파일';
  if (entry.type === 'dir') {
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'server-folder-select';
    checkbox.checked = selectedServerFolders.has(entry.path);
    checkbox.setAttribute('aria-label', `${entry.name} 폴더 선택`);
    checkbox.onchange = () => {
      if (checkbox.checked) selectedServerFolders.add(entry.path); else selectedServerFolders.delete(entry.path);
      updateServerFileControls();
    };
    const open = document.createElement('button');
    open.type = 'button'; open.className = 'explorer-name'; open.textContent = entry.name;
    open.onclick = () => loadServerFiles(entry.path);
    nameWrap.append(checkbox, icon, open);
  } else {
    if (entry.editable) {
      const edit = document.createElement('button');
      edit.type = 'button'; edit.className = 'explorer-file-name explorer-editable-file'; edit.textContent = entry.name;
      edit.title = '텍스트 편집기로 열기'; edit.onclick = () => openServerFileEditor(entry.path);
      nameWrap.append(icon, edit);
    } else {
      const name = document.createElement('span');
      name.className = 'explorer-file-name'; name.textContent = entry.name;
      nameWrap.append(icon, name);
    }
  }
  nameCell.append(nameWrap);
  const typeCell = document.createElement('td'); typeCell.textContent = entry.type === 'dir' ? '폴더' : '파일';
  const sizeCell = document.createElement('td'); sizeCell.textContent = entry.type === 'file' ? bytes(entry.size) : '—';
  const modifiedCell = document.createElement('td'); modifiedCell.textContent = String(entry.modified || '').replace('T', ' ');
  const actionCell = document.createElement('td'); actionCell.className = 'explorer-row-actions';
  if (entry.type === 'file') {
    const download = document.createElement('button');
    download.type = 'button'; download.className = 'server-file-download'; download.textContent = '다운로드';
    download.onclick = () => downloadServerFile(entry.path);
    actionCell.append(download);
  }
  row.append(nameCell, typeCell, sizeCell, modifiedCell, actionCell);
  return row;
}

async function openServerFileEditor(path) {
  const dialog = $('server-file-editor-dialog');
  serverFileEditorPath = '';
  serverFileEditorOriginal = '';
  $('server-file-editor-title').textContent = path.split('/').at(-1) || '파일 편집';
  $('server-file-editor-path').textContent = `/server/${path}`;
  $('server-file-editor-status').classList.remove('error-text');
  $('server-file-editor-status').textContent = '파일을 불러오는 중입니다.';
  $('server-file-editor-content').value = '';
  $('server-file-editor-content').disabled = true;
  $('server-file-editor-save').disabled = true;
  if (!dialog.open) dialog.showModal();
  try {
    const data = await api(`/api/server-files/text?path=${encodeURIComponent(path)}`);
    if (!dialog.open) return;
    serverFileEditorPath = data.path;
    serverFileEditorOriginal = data.content;
    $('server-file-editor-title').textContent = data.name;
    $('server-file-editor-path').textContent = `/server/${data.path} · ${bytes(data.size)}`;
    $('server-file-editor-content').value = data.content;
    $('server-file-editor-content').disabled = false;
    $('server-file-editor-status').textContent = '텍스트 파일을 편집할 수 있습니다. Ctrl/Cmd+S로 저장할 수 있습니다.';
    $('server-file-editor-content').focus();
  } catch (error) {
    $('server-file-editor-status').classList.add('error-text');
    $('server-file-editor-status').textContent = error.message;
  }
}

$('server-file-editor-dialog').addEventListener('close', () => {
  serverFileEditorPath = '';
  serverFileEditorOriginal = '';
});
$('server-file-editor-save').onclick = async () => {
  if (!serverFileEditorPath) return;
  const button = $('server-file-editor-save');
  const status = $('server-file-editor-status');
  button.disabled = true;
  status.classList.remove('error-text');
  status.textContent = '파일을 저장하고 있습니다.';
  try {
    const content = $('server-file-editor-content').value;
    const data = await jsonPost(`/api/server-files/text?path=${encodeURIComponent(serverFileEditorPath)}`, {content}, 'PUT');
    serverFileEditorOriginal = content;
    status.textContent = `${data.message} · ${bytes(data.size)}`;
    await loadServerFiles(serverFilesPath);
  } catch (error) {
    status.classList.add('error-text');
    status.textContent = error.message;
  } finally {
    button.disabled = !serverFileEditorPath || $('server-file-editor-content').value === serverFileEditorOriginal;
  }
};
$('server-file-editor-content').oninput = event => {
  const unchanged = event.currentTarget.value === serverFileEditorOriginal;
  $('server-file-editor-status').classList.remove('error-text');
  $('server-file-editor-save').disabled = !serverFileEditorPath || unchanged;
  if (serverFileEditorPath) $('server-file-editor-status').textContent = unchanged ? '저장된 내용과 같습니다.' : '저장하지 않은 변경사항이 있습니다.';
};
$('server-file-editor-content').onkeydown = event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 's') {
    event.preventDefault();
    if (!$('server-file-editor-save').disabled) $('server-file-editor-save').click();
  }
};

async function loadServerFiles(path = serverFilesPath) {
  const body = $('server-files-body');
  body.replaceChildren();
  const loading = document.createElement('tr');
  const loadingCell = document.createElement('td'); loadingCell.colSpan = 5; loadingCell.textContent = '서버 폴더를 불러오고 있습니다.';
  loading.append(loadingCell); body.append(loading);
  selectedServerFolders.clear();
  try {
    const data = await api(`/api/server-files?path=${encodeURIComponent(path || '')}`);
    serverFilesPath = data.path || '';
    serverFilesParent = data.parent || '';
    renderServerFilesPath(serverFilesPath);
    body.replaceChildren();
    if (!data.entries.length) {
      const row = document.createElement('tr'); const cell = document.createElement('td');
      cell.colSpan = 5; cell.textContent = '이 폴더는 비어 있습니다.'; row.append(cell); body.append(row);
    } else {
      body.append(...data.entries.map(serverFileRow));
    }
    setServerFilesMessage('서버 폴더 목록을 불러왔습니다.');
  } catch (error) {
    body.replaceChildren();
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 5; cell.textContent = error.message; row.append(cell); body.append(row);
    setServerFilesMessage(error.message, true);
  }
  updateServerFileControls();
}

function downloadServerFile(path) {
  const link = document.createElement('a');
  link.href = `/api/server-files/download?path=${encodeURIComponent(path)}`;
  link.setAttribute('download', ''); document.body.append(link); link.click(); link.remove();
}

async function downloadSelectedServerFolders() {
  if (!selectedServerFolders.size) return;
  setServerFilesMessage('선택한 폴더를 ZIP으로 준비하고 있습니다.');
  try {
    const response = await fetch('/api/server-files/download-folders', {
      method: 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({paths: [...selectedServerFolders]}),
    });
    if (!response.ok) {
      const data = await response.json(); throw new Error(data.detail || '폴더 다운로드를 준비하지 못했습니다.');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = match ? match[1] : 'valheim-server-folders.zip';
    document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    setServerFilesMessage('선택한 폴더 다운로드를 시작했습니다.');
  } catch (error) { setServerFilesMessage(error.message, true); }
}

async function uploadServerFile(file, overwrite = false) {
  const form = new FormData(); form.append('file', file); form.append('overwrite', String(overwrite));
  const response = await fetch(`/api/server-files/upload?path=${encodeURIComponent(serverFilesPath)}`, {method: 'POST', cache: 'no-store', body: form});
  const data = await response.json();
  if (response.status === 409 && !overwrite) {
    if (await confirmAction('파일 덮어쓰기', `${file.name} 파일이 이미 있습니다. 기존 파일을 교체할까요?`, '덮어쓰기')) return uploadServerFile(file, true);
    return;
  }
  if (!response.ok) throw new Error(data.detail || '파일 업로드에 실패했습니다.');
  setServerFilesMessage(data.message); await loadServerFiles(serverFilesPath);
}

async function uploadServerFolder(files, overwrite = false) {
  const form = new FormData();
  files.forEach(file => { form.append('files', file, file.name); form.append('relative_paths', file.webkitRelativePath || file.name); });
  form.append('overwrite', String(overwrite));
  const response = await fetch(`/api/server-files/upload-folder?path=${encodeURIComponent(serverFilesPath)}`, {method: 'POST', cache: 'no-store', body: form});
  const data = await response.json();
  if (response.status === 409 && !overwrite) {
    if (await confirmAction('폴더 덮어쓰기', '같은 경로의 파일이 있습니다. 기존 파일을 교체할까요?', '덮어쓰기')) return uploadServerFolder(files, true);
    return;
  }
  if (!response.ok) throw new Error(data.detail || '폴더 업로드에 실패했습니다.');
  setServerFilesMessage(data.message); await loadServerFiles(serverFilesPath);
}

$('server-files-refresh').onclick = () => loadServerFiles(serverFilesPath);
$('server-files-up').onclick = () => loadServerFiles(serverFilesParent);
$('server-files-download-folders').onclick = downloadSelectedServerFolders;
$('server-files-upload').onclick = () => $('server-files-upload-input').click();
$('server-files-upload-folder').onclick = () => $('server-files-folder-input').click();
$('server-files-upload-input').onchange = async event => {
  const file = event.currentTarget.files?.[0];
  if (!file) return;
  try { setServerFilesMessage(`${file.name} 업로드 중입니다.`); await uploadServerFile(file); }
  catch (error) { setServerFilesMessage(error.message, true); }
  finally { event.currentTarget.value = ''; }
};
$('server-files-folder-input').onchange = async event => {
  const files = [...(event.currentTarget.files || [])];
  if (!files.length) return;
  try { setServerFilesMessage(`${files.length}개 파일을 업로드하고 있습니다.`); await uploadServerFolder(files); }
  catch (error) { setServerFilesMessage(error.message, true); }
  finally { event.currentTarget.value = ''; }
};
$('server-files-new-folder').onsubmit = async event => {
  event.preventDefault(); const input = event.currentTarget.elements.name;
  try {
    const data = await jsonPost('/api/server-files/mkdir', {path: serverFilesPath, name: input.value});
    input.value = ''; setServerFilesMessage(data.message); await loadServerFiles(serverFilesPath);
  } catch (error) { setServerFilesMessage(error.message, true); }
};

async function loadWorlds() {
  const data = await api('/api/worlds');
  const list = $('world-list'); list.replaceChildren();
  worldNames = new Set(data.worlds.map(world => world.name));
  const dropPrompt = document.createElement('div');
  dropPrompt.className = `world-drop-prompt${data.worlds.length ? '' : ' is-empty'}`;
  const dropIcon = document.createElement('span'); dropIcon.className = 'world-drop-icon'; dropIcon.setAttribute('aria-hidden', 'true'); dropIcon.textContent = '↑';
  const dropCopy = document.createElement('div'); const dropTitle = document.createElement('strong'); const dropText = document.createElement('small');
  dropTitle.textContent = data.worlds.length ? '다른 월드 파일 추가' : '월드 파일을 여기에 놓으세요';
  dropText.textContent = '이름이 같은 .db와 .fwl 파일을 함께 드래그 앤 드롭하세요.';
  dropCopy.append(dropTitle, dropText); dropPrompt.append(dropIcon, dropCopy); list.append(dropPrompt);
  for (const world of data.worlds) {
    const {row, actions} = fileRow(world.name + (world.name === data.selected ? ' · 선택됨' : ''), `${world.complete ? '월드 파일 한 쌍' : '파일 쌍이 불완전합니다'} · ${bytes(world.size)}`);
    if (world.complete) actions.append(actionButton('다운로드', () => { location.href = `/api/worlds/${encodeURIComponent(world.name)}/download`; }, true));
    list.append(row);
  }
  updateControls();
}

async function uploadWorldPair(db, fwl, overwrite) {
  if (!db || !fwl) throw new Error('이름이 같은 .db와 .fwl 파일을 함께 선택해주세요.');
  const dbName = db.name.toLowerCase().endsWith('.db') ? db.name.slice(0, -3) : '';
  const fwlName = fwl.name.toLowerCase().endsWith('.fwl') ? fwl.name.slice(0, -4) : '';
  if (!dbName || !fwlName || dbName !== fwlName) throw new Error('이름이 같은 .db와 .fwl 파일을 함께 선택해주세요.');
  if (overwrite && !await confirmAction('기존 월드 덮어쓰기', '같은 이름의 월드를 업로드한 파일로 교체합니다. 교체 전 현재 월드를 백업합니다.', '업로드')) return false;
  const data = new FormData(); data.append('db', db); data.append('fwl', fwl); data.append('overwrite', String(overwrite));
  uiBusy = true; updateControls(); message('worlds-message', `${dbName} 월드를 업로드하고 있습니다. 창을 닫지 말아주세요.`);
  try {
    const result = await api('/api/worlds/upload', {method: 'POST', body: data});
    message('worlds-message', result.message); await loadWorlds(); return true;
  } catch (error) { message('worlds-message', error.message, true); return false; }
  finally { uiBusy = false; updateControls(); }
}

$('world-upload-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  if (await uploadWorldPair(form.elements.db.files?.[0], form.elements.fwl.files?.[0], form.elements.overwrite.checked)) form.reset();
};

const worldDropZone = $('world-list');
worldDropZone.addEventListener('dragenter', event => {
  event.preventDefault();
  if (writable()) worldDropZone.classList.add('is-dragging');
});
worldDropZone.addEventListener('dragover', event => {
  event.preventDefault();
  event.dataTransfer.dropEffect = writable() ? 'copy' : 'none';
});
worldDropZone.addEventListener('dragleave', event => {
  if (!worldDropZone.contains(event.relatedTarget)) worldDropZone.classList.remove('is-dragging');
});
worldDropZone.addEventListener('drop', async event => {
  event.preventDefault(); worldDropZone.classList.remove('is-dragging');
  if (!writable()) { message('worlds-message', '서버 실행 중이거나 다른 작업이 진행 중일 때는 월드 파일을 업로드할 수 없습니다.', true); return; }
  const files = [...(event.dataTransfer.files || [])];
  const dbFiles = files.filter(file => file.name.toLowerCase().endsWith('.db'));
  const fwlFiles = files.filter(file => file.name.toLowerCase().endsWith('.fwl'));
  if (files.length !== 2 || dbFiles.length !== 1 || fwlFiles.length !== 1) {
    message('worlds-message', '.db 파일 1개와 .fwl 파일 1개를 함께 놓아주세요.', true); return;
  }
  const name = dbFiles[0].name.slice(0, -3);
  await uploadWorldPair(dbFiles[0], fwlFiles[0], worldNames.has(name));
});

async function loadBackups() {
  const data = await api('/api/backups');
  const list = $('backup-list'); list.replaceChildren();
  if (!data.backups.length) emptyList(list, '아직 ZIP 백업이 없습니다. 서버를 중지한 뒤 첫 백업을 만들어보세요.');
  for (const backup of data.backups) {
    const when = new Date(backup.modified_at * 1000).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul'});
    const {row, actions} = fileRow(backup.name, `${bytes(backup.size)} · ${when} KST`);
    const url = `/api/backups/${encodeURIComponent(backup.name)}`;
    actions.append(downloadLink('다운로드', `${url}/download`));
    actions.append(actionButton('복원', () => perform(`${url}/restore`, '월드 복원', '현재 월드와 권한 목록을 이 백업으로 교체합니다. 복원 전 현재 월드를 백업합니다.'), true));
    const remove = actionButton('삭제', async () => { await perform(url, '백업 삭제', '이 ZIP 백업 파일을 삭제합니다. 삭제한 백업은 복구할 수 없습니다.', {method: 'DELETE'}); await loadBackups(); }, true);
    remove.classList.add('danger'); actions.append(remove); list.append(row);
  }
  updateControls();
}
$('backup-now').onclick = () => perform('/api/backups', '월드 백업');

function fillPermissions() {
  const kind = $('permission-kind').value;
  $('permission-ids').value = (permissionLists[kind] || []).join('\n');
  $('permission-warning').hidden = kind !== 'permitted';
  message('permissions-message', '');
}
$('permission-kind').onchange = fillPermissions;
async function loadPermissions() { permissionLists = await api('/api/permissions'); fillPermissions(); }
$('steam-id-check').onclick = async () => {
  const popup = window.open('', 'techtim-steam-id', 'popup,width=520,height=680');
  if (!popup) { showNotice('SteamID 확인', '브라우저에서 팝업을 허용한 뒤 다시 시도해주세요.'); return; }
  steamIdPopup = popup;
  popup.document.title = 'Steam 연결 중';
  popup.document.body.textContent = 'Steam 로그인 페이지를 여는 중입니다.';
  try {
    const data = await api('/api/steam/openid/start');
    if (!popup.closed) popup.location.replace(data.auth_url);
  } catch (error) {
    if (!popup.closed) popup.close();
    steamIdPopup = null;
    showNotice('SteamID 확인', error.message);
  }
};
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== steamIdPopup
      || event.data?.type !== 'techtim-steam-id' || !/^Steam_\d{17}$/.test(event.data.platformId || '')) return;
  $('steam-platform-id').textContent = event.data.platformId;
  $('steam-id-64').textContent = event.data.steamId;
  if (!steamIdPopup.closed) steamIdPopup.close();
  steamIdPopup = null;
  $('steam-id-dialog').showModal();
});
$('steam-id-copy').onclick = async () => {
  const value = $('steam-platform-id').textContent;
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
    else { const area = document.createElement('textarea'); area.value = value; document.body.append(area); area.select(); const copied = document.execCommand('copy'); area.remove(); if (!copied) throw new Error(); }
    toast('Steam 플랫폼 사용자 ID를 복사했습니다.');
  } catch { toast(`Steam 플랫폼 사용자 ID: ${value}`); }
};
$('permissions-form').onsubmit = async event => {
  event.preventDefault();
  const kind = $('permission-kind').value;
  const ids = $('permission-ids').value.split('\n').map(line => line.trim()).filter(Boolean);
  if (kind === 'permitted' && ids.length && !await confirmAction('접속 허용 목록 저장', '목록에 없는 모든 플레이어의 접속이 차단됩니다. 이 허용 목록을 적용할까요?', '목록 저장')) return;
  uiBusy = true; updateControls();
  try { await jsonPost('/api/permissions', {kind, ids}); permissionLists[kind] = ids; message('permissions-message', '권한 목록을 저장했습니다.'); }
  catch (error) { message('permissions-message', error.message, true); }
  finally { uiBusy = false; updateControls(); }
};

async function loadSchedule() {
  const data = await api('/api/restart-schedule');
  const defaults = ['04:00', '12:00', '20:00'];
  document.querySelectorAll('[data-schedule-slot]').forEach((slot, index) => {
    const time = data.times[index] || defaults[index];
    const [hour, minute] = time.split(':');
    slot.querySelector('[data-schedule-enabled]').checked = Boolean(data.enabled && data.times[index]);
    slot.querySelector('[data-schedule-hour]').value = String(Number(hour));
    slot.querySelector('[data-schedule-minute]').value = String(Number(minute));
  });
  syncScheduleSlots();
  $('schedule-summary').textContent = data.enabled ? `${data.times.join(' · ')} KST` : '한국 시간 기준 운영';
  $('schedule-result').textContent = data.last_message || '아직 실행된 예약이 없습니다.';
}
function syncScheduleSlots() {
  document.querySelectorAll('[data-schedule-slot]').forEach(slot => {
    const enabled = slot.querySelector('[data-schedule-enabled]').checked;
    slot.classList.toggle('is-enabled', enabled);
    slot.querySelectorAll('[data-schedule-hour], [data-schedule-minute]').forEach(input => { input.disabled = !enabled; });
  });
}
document.querySelectorAll('[data-schedule-enabled]').forEach(toggle => toggle.addEventListener('change', syncScheduleSlots));
$('schedule-form').onsubmit = async event => {
  event.preventDefault();
  const times = [];
  for (const slot of document.querySelectorAll('[data-schedule-slot]')) {
    if (!slot.querySelector('[data-schedule-enabled]').checked) continue;
    const hour = Number(slot.querySelector('[data-schedule-hour]').value);
    const minute = Number(slot.querySelector('[data-schedule-minute]').value);
    if (!Number.isInteger(hour) || hour < 0 || hour > 23 || !Number.isInteger(minute) || minute < 0 || minute > 59) {
      message('schedule-message', '시는 0~23, 분은 0~59 사이로 입력해주세요.', true); return;
    }
    times.push(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`);
  }
  const payload = {enabled: times.length > 0, times};
  uiBusy = true; updateControls();
  try { await jsonPost('/api/restart-schedule', payload); message('schedule-message', '예약을 저장했습니다.'); await loadSchedule(); }
  catch (error) { message('schedule-message', error.message, true); }
  finally { uiBusy = false; updateControls(); }
};

function setModsMessage(text, error = false) { message('mods-message', text, error); }

function updateModControls() {
  const enabled = writable();
  ['mods-install-essential', 'mods-install', 'mods-import', 'mods-export', 'mods-disable-all', 'mods-cleanup', 'mods-config-save'].forEach(id => {
    const control = $(id); if (control) control.disabled = !enabled || (id === 'mods-config-save' && !$('mods-config-select')?.value);
  });
  if ($('mods-install-essential')) $('mods-install-essential').disabled = !enabled || modLoaderReady;
  document.querySelectorAll('.mod-write-action').forEach(control => { control.disabled = !enabled; });
}

function modButton(label, className, handler) {
  const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
  button.className = className; button.onclick = handler; return button;
}

function renderModPackages() {
  const list = $('mods-list'); list.replaceChildren();
  const query = $('mods-search').value.trim().toLocaleLowerCase('ko-KR');
  const filter = $('mods-filter').value;
  const visible = modPackages.filter(item => item.name.toLocaleLowerCase('ko-KR').includes(query)
    && (filter === 'all' || (filter === 'enabled' && item.enabled) || (filter === 'disabled' && !item.enabled && !item.issue)
      || (filter === 'issue' && Boolean(item.issue))));
  if (!visible.length) { emptyList(list, modPackages.length ? '조건에 맞는 모드가 없습니다.' : '등록된 모드가 없습니다. Linux BepInEx와 서버 모드를 추가하세요.'); return; }
  visible.forEach(item => {
    const row = document.createElement('article'); row.className = 'mod-package-row';
    const info = document.createElement('div'); info.className = 'mod-package-info';
    const title = document.createElement('div'); title.className = 'mod-package-title';
    const name = document.createElement('strong'); name.textContent = item.name;
    const badge = document.createElement('span'); badge.className = `mod-state ${item.enabled ? 'enabled' : item.issue ? 'issue' : ''}`;
    badge.textContent = item.enabled ? '켜짐' : item.issue ? '준비 필요' : '꺼짐'; title.append(name, badge);
    const meta = document.createElement('small');
    meta.textContent = `${item.is_loader ? 'Linux BepInEx 로더' : '서버 모드'}${item.version ? ` · v${item.version}` : ''} · 파일 ${item.file_count}개`;
    info.append(title, meta);
    if (item.dependencies.length) {
      const dependencies = document.createElement('small'); dependencies.className = 'mod-dependencies';
      dependencies.textContent = `필요 모드: ${item.dependencies.join(', ')}`; info.append(dependencies);
    }
    if (item.issue) { const issue = document.createElement('p'); issue.className = 'mod-issue'; issue.textContent = item.issue; info.append(issue); }
    const actions = document.createElement('div'); actions.className = 'mod-package-actions'; actions.setAttribute('data-running-lock', '');
    if (!item.enabled && item.issue) {
      actions.append(modButton('해결 방법', '', () => setModsMessage(item.issue, true)));
    } else {
      actions.append(modButton(item.enabled ? '끄기' : '켜기', 'mod-write-action', async () => {
        const verb = item.enabled ? '끄기' : '켜기';
        if (!await confirmAction(`모드 ${verb}`, `${item.name} 모드를 ${verb} 상태로 변경할까요? 변경 사항은 다음 서버 시작부터 적용됩니다.`, verb)) return;
        try { const data = await jsonPost(`/api/mods/${item.id}/toggle`, {enabled: !item.enabled}); await loadMods(); setModsMessage(data.message); }
        catch (error) { setModsMessage(error.message, true); }
      }));
    }
    actions.append(modButton('업데이트', 'mod-write-action', () => { modUpdateTarget = item.id; $('mods-update-input').click(); }));
    const remove = modButton('삭제', 'mod-write-action danger', async () => {
      if (!await confirmAction('모드 삭제', `${item.name} 모드를 끄고 목록에서 제거합니다. 등록 파일은 서버 보관함으로 이동합니다.`, '삭제')) return;
      try { const data = await api(`/api/mods/${item.id}`, {method: 'DELETE'}); await loadMods(); setModsMessage(data.message); }
      catch (error) { setModsMessage(error.message, true); }
    });
    actions.append(remove); row.append(info, actions); list.append(row);
  });
  updateModControls();
}

async function loadModConfigurations() {
  const data = await api('/api/mods/configs'); const select = $('mods-config-select'); const current = select.value;
  select.replaceChildren(new Option('설정 파일 선택', ''));
  data.files.forEach(file => select.append(new Option(`${file.path} · ${bytes(file.size)}`, file.path)));
  if (data.files.some(file => file.path === current)) select.value = current;
  $('mods-config-count').textContent = `${data.files.length}개`;
  $('mods-config-editor').disabled = !select.value;
}

async function loadMods() {
  setModsMessage('모드 구성을 불러오고 있습니다.');
  const data = await api('/api/mods'); modPackages = data.packages;
  modLoaderReady = data.loader_ready;
  $('mods-loader-status').textContent = data.loader_ready ? '준비됨' : '설치 필요';
  $('mods-loader-hint').textContent = data.loader_ready ? 'Linux BepInEx 활성화' : 'Linux BepInEx ZIP 필요';
  $('mods-install-essential').textContent = data.loader_ready ? '설치 완료' : '필수 모드 설치';
  $('mods-enabled-count').textContent = `${data.enabled_count}개`;
  $('mods-registered-count').textContent = `${data.registered_count}개`;
  renderModPackages(); await loadModConfigurations(); setModsMessage('모드 구성을 확인했습니다.'); updateControls();
}

async function uploadMods(files) {
  const form = new FormData(); files.forEach(file => form.append('files', file, file.name));
  uiBusy = true; updateControls(); setModsMessage(`${files.length}개 모드 파일을 확인하고 있습니다.`);
  try {
    const data = await api('/api/mods/install', {method: 'POST', body: form});
    const failed = data.results.filter(item => !item.enabled);
    const summary = data.results.map(item => `${item.name}: ${item.message}`).join(' / ');
    await loadMods(); setModsMessage(summary, failed.length > 0);
  } catch (error) { setModsMessage(error.message, true); }
  finally { uiBusy = false; updateControls(); }
}

$('mods-search').oninput = renderModPackages;
$('mods-filter').onchange = renderModPackages;
$('mods-refresh').onclick = loadMods;
$('mods-install-essential').onclick = async () => {
  uiBusy = true; updateControls(); setModsMessage('최신 BepInEx 필수 모드를 확인하고 설치하고 있습니다.');
  try { const data = await api('/api/mods/recommended/bepinex', {method: 'POST'}); await loadMods(); setModsMessage(data.message); }
  catch (error) { setModsMessage(error.message, true); }
  finally { uiBusy = false; updateControls(); }
};
$('mods-install').onclick = () => $('mods-install-input').click();
$('mods-install-input').onchange = async event => {
  const files = [...(event.currentTarget.files || [])]; event.currentTarget.value = '';
  if (files.length) await uploadMods(files);
};
$('mods-update-input').onchange = async event => {
  const file = event.currentTarget.files?.[0]; event.currentTarget.value = '';
  if (!file || !modUpdateTarget) return;
  const form = new FormData(); form.append('file', file, file.name);
  uiBusy = true; updateControls(); setModsMessage(`${file.name} 파일로 업데이트하고 있습니다.`);
  try { const data = await api(`/api/mods/${modUpdateTarget}/update`, {method: 'POST', body: form}); await loadMods(); setModsMessage(data.message); }
  catch (error) { setModsMessage(error.message, true); }
  finally { modUpdateTarget = ''; uiBusy = false; updateControls(); }
};
$('mods-config-load').onclick = async () => {
  const path = $('mods-config-select').value; if (!path) return;
  try { const data = await api(`/api/mods/config?path=${encodeURIComponent(path)}`); $('mods-config-editor').value = data.content; $('mods-config-editor').disabled = false; updateModControls(); }
  catch (error) { setModsMessage(error.message, true); }
};
$('mods-config-select').onchange = () => { $('mods-config-editor').value = ''; $('mods-config-editor').disabled = !$('mods-config-select').value; updateModControls(); };
$('mods-config-save').onclick = async () => {
  const path = $('mods-config-select').value; if (!path) return;
  try { const data = await jsonPost('/api/mods/config', {path, content: $('mods-config-editor').value}, 'PUT'); setModsMessage(data.message); await loadModConfigurations(); }
  catch (error) { setModsMessage(error.message, true); }
};
$('mods-export').onclick = () => { location.href = '/api/mods/export'; };
$('mods-import').onclick = () => $('mods-import-input').click();
$('mods-import-input').onchange = async event => {
  const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; if (!file) return;
  const form = new FormData(); form.append('file', file, file.name);
  try { const data = await api('/api/mods/import', {method: 'POST', body: form}); await loadMods(); setModsMessage(data.message); }
  catch (error) { setModsMessage(error.message, true); }
};
$('mods-disable-all').onclick = async () => {
  if (!await confirmAction('모드 모두 끄기', 'BepInEx와 등록된 모든 모드를 끕니다. 파일과 설정은 보관됩니다.', '모두 끄기')) return;
  try { const data = await api('/api/mods/disable-all', {method: 'POST'}); await loadMods(); setModsMessage(data.message); }
  catch (error) { setModsMessage(error.message, true); }
};
$('mods-cleanup').onclick = async () => {
  try {
    const plan = await api('/api/mods/cleanup');
    if (!plan.entries.length) { setModsMessage('정리할 기존 BepInEx 또는 모드 파일이 없습니다.'); return; }
    const targets = plan.entries.map(item => `· ${item.path}`).join('\n');
    const text = `BepInEx와 모든 모드·설정·등록 목록을 초기화합니다.\n정리 대상: 파일 ${plan.file_count}개 · ${bytes(plan.bytes)}\n${targets}\n\n월드·백업·서버 엔진은 유지되며 원본은 서버 폴더 안에 보관됩니다.`;
    if (!await confirmAction('기존 BepInEx·모드 정리', text, '원본 보관 후 정리')) return;
    uiBusy = true; updateControls(); setModsMessage('기존 모드 파일을 원본 보관 폴더로 이동하고 있습니다.');
    const data = await jsonPost('/api/mods/cleanup', {token: plan.token});
    await loadMods(); setModsMessage(`${data.message} 보관 위치: ${data.archive}`);
  } catch (error) { setModsMessage(error.message, true); }
  finally { uiBusy = false; updateControls(); }
};
$('mods-diagnose').onclick = async () => {
  try { const data = await api('/api/mods/diagnose'); $('mods-diagnosis').textContent = data.report; $('mods-diagnosis').hidden = false; }
  catch (error) { setModsMessage(error.message, true); }
};

function setDiscordControlsDisabled(disabled) {
  $('discord-form').querySelectorAll('input,button').forEach(control => {
    if (!control.hasAttribute('data-close')) control.disabled = disabled;
  });
  $('discord-webhook-url').disabled = disabled || $('discord-clear-webhook').checked;
  if (!disabled) $('discord-test').disabled = !discordWebhookConfigured;
}

function renderDiscord(data) {
  const config = data.config || {};
  discordWebhookConfigured = Boolean(config.webhook_configured);
  $('discord-enabled').checked = Boolean(config.enabled);
  $('discord-username').value = config.username || 'TechTim Valheim Server';
  $('discord-webhook-url').value = '';
  $('discord-webhook-url').placeholder = discordWebhookConfigured
    ? '새 URL을 입력하면 기존 Webhook이 교체됩니다.'
    : 'https://discord.com/api/webhooks/...';
  $('discord-clear-webhook').checked = false;
  $('discord-notify-start').checked = Boolean(config.notify_server_start);
  $('discord-notify-stop').checked = Boolean(config.notify_server_stop);
  $('discord-notify-restart').checked = Boolean(config.notify_server_restart);
  $('discord-notify-backup').checked = Boolean(config.notify_backup);
  $('discord-notify-errors').checked = Boolean(config.notify_errors);
  $('discord-state').textContent = config.enabled ? '연동 사용 중' : discordWebhookConfigured ? 'Webhook 등록됨' : '연동 안 됨';
  $('discord-webhook-hint').textContent = discordWebhookConfigured
    ? config.webhook_hint
    : 'Discord 채널 Webhook URL이 등록되지 않았습니다.';
  $('discord-state').classList.toggle('online', Boolean(config.enabled && discordWebhookConfigured));
  setDiscordControlsDisabled(discordBusy);
}

async function loadDiscord() {
  try {
    const data = await api('/api/discord');
    renderDiscord(data);
    message('discord-message', discordWebhookConfigured
      ? '저장된 Webhook으로 Discord 알림을 전송할 수 있습니다.'
      : 'Discord 채널에서 생성한 Webhook URL을 등록해주세요.');
  } catch (error) { message('discord-message', error.message, true); }
}

$('discord-clear-webhook').onchange = event => {
  $('discord-webhook-url').disabled = event.target.checked || discordBusy;
};

$('discord-form').onsubmit = async event => {
  event.preventDefault();
  if (discordBusy) return;
  discordBusy = true; setDiscordControlsDisabled(true);
  message('discord-message', 'Discord 연동 설정을 저장하고 있습니다.');
  try {
    const data = await jsonPost('/api/discord', {
      enabled: $('discord-enabled').checked,
      webhook_url: $('discord-webhook-url').value.trim(),
      clear_webhook: $('discord-clear-webhook').checked,
      username: $('discord-username').value.trim() || 'TechTim Valheim Server',
      notify_server_start: $('discord-notify-start').checked,
      notify_server_stop: $('discord-notify-stop').checked,
      notify_server_restart: $('discord-notify-restart').checked,
      notify_backup: $('discord-notify-backup').checked,
      notify_errors: $('discord-notify-errors').checked
    });
    renderDiscord(data);
    message('discord-message', data.message || 'Discord 연동 설정을 저장했습니다.');
  } catch (error) { message('discord-message', error.message, true); }
  finally { discordBusy = false; setDiscordControlsDisabled(false); }
};

$('discord-test').onclick = async () => {
  if (discordBusy || !discordWebhookConfigured) return;
  discordBusy = true; setDiscordControlsDisabled(true);
  message('discord-message', 'Discord 테스트 메시지를 전송하고 있습니다.');
  try {
    const data = await api('/api/discord/test', {method: 'POST'});
    message('discord-message', data.message || 'Discord 테스트 메시지를 전송했습니다.');
  } catch (error) { message('discord-message', error.message, true); }
  finally { discordBusy = false; setDiscordControlsDisabled(false); }
};

const loaders = {'settings-dialog': loadSettings, 'worlds-dialog': loadWorlds, 'backups-dialog': loadBackups, 'permissions-dialog': loadPermissions,
  'schedule-dialog': loadSchedule, 'modifiers-dialog': loadModifiers,
  'server-files-dialog': () => serverConfigurationLocked() ? Promise.resolve() : loadServerFiles(serverFilesPath), 'mods-dialog': loadMods,
  'discord-dialog': loadDiscord, 'panel-update-dialog': loadPanelUpdate};
document.querySelectorAll('[data-open]').forEach(button => button.onclick = async () => {
  await openDetail(button.dataset.open, loaders[button.dataset.open]);
});

const sidebarMenuItems = [...document.querySelectorAll('[data-open]')];
sidebarMenuItems.forEach(item => item.addEventListener('click', () => {
  sidebarMenuItems.forEach(link => link.removeAttribute('aria-current'));
  item.setAttribute('aria-current', 'page');
}));

function meter(id, used, total) {
  const percent = total > 0 ? Math.max(0, Math.min(100, used / total * 100)) : 0;
  const bar = $(id);
  bar.style.width = `${percent}%`;
  const panel = bar.closest('.resource');
  panel.dataset.level = percent >= 90 ? 'critical' : percent >= 75 ? 'warning' : 'normal';
}

function saveResourceHistory(force = false) {
  const now = Date.now();
  if (!force && now - resourceHistorySavedAt < 15000) return;
  try {
    localStorage.setItem(RESOURCE_HISTORY_STORAGE_KEY, JSON.stringify(resourceHistory));
    resourceHistorySavedAt = now;
  } catch (_error) { /* Live graphs continue when browser storage is unavailable. */ }
}

function appendResourceHistory(cpu, memory) {
  const now = Date.now();
  const normalize = value => Number.isFinite(Number(value)) ? Math.max(0, Math.min(100, Number(value))) : null;
  const cpuValue = normalize(cpu);
  const memoryValue = normalize(memory);
  if (cpuValue == null && memoryValue == null) return;
  resourceHistory.push([now, cpuValue, memoryValue]);
  const cutoff = now - RESOURCE_HISTORY_WINDOW_MS;
  while (resourceHistory.length && resourceHistory[0][0] < cutoff) resourceHistory.shift();
  saveResourceHistory();
}

function drawResourceHistory(canvasId, valueIndex, color) {
  const canvas = $(canvasId);
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width) return;
  const width = Math.max(1, Math.floor(rect.width));
  const height = 56;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  const top = 4, bottom = height - 5, chartHeight = bottom - top;
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
    points.push([
      Math.min(width - 1, Math.max(0, (sample[0] - start) / RESOURCE_HISTORY_WINDOW_MS * width)),
      bottom - sample[valueIndex] / 100 * chartHeight,
    ]);
  }
  context.beginPath(); context.moveTo(points[0][0], bottom);
  for (const point of points) context.lineTo(point[0], point[1]);
  context.lineTo(points[points.length - 1][0], bottom); context.closePath();
  const fill = context.createLinearGradient(0, top, 0, bottom);
  fill.addColorStop(0, `${color}55`); fill.addColorStop(1, `${color}05`);
  context.fillStyle = fill; context.fill();
  context.beginPath(); context.moveTo(points[0][0], points[0][1]);
  for (const point of points.slice(1)) context.lineTo(point[0], point[1]);
  context.strokeStyle = color; context.lineWidth = 1.7; context.stroke();
  const latest = points[points.length - 1];
  context.beginPath(); context.arc(latest[0], latest[1], 2.3, 0, Math.PI * 2); context.fillStyle = color; context.fill();
}

function renderResourceHistory() {
  drawResourceHistory('cpu-history-chart', 1, '#55d5b1');
  drawResourceHistory('memory-history-chart', 2, '#d8a84d');
}

async function refreshResources() {
  if (polls.has('resources')) return;
  polls.add('resources');
  try {
    const data = await api('/api/server/resources');
    $('cpu').textContent = data.available ? `${data.cpu_percent}%` : '—';
    $('memory').textContent = data.available ? `${bytes(data.memory_used)} / ${bytes(data.memory_total)}` : '—';
    $('disk').textContent = `${bytes(data.disk_used)} / ${bytes(data.disk_total)}`;
    $('network-rx').textContent = data.available ? `${bytes(data.network_rx)}/s` : '—';
    $('network-tx').textContent = data.available ? `${bytes(data.network_tx)}/s` : '—';
    meter('disk-meter', data.disk_used, data.disk_total);
    const memoryPercent = data.available && data.memory_total > 0 ? data.memory_used / data.memory_total * 100 : null;
    appendResourceHistory(data.available ? data.cpu_percent : null, memoryPercent);
    renderResourceHistory();
  } catch {
    ['cpu', 'memory', 'disk', 'network-rx', 'network-tx'].forEach(id => { $(id).textContent = '—'; });
    meter('disk-meter', 0, 1);
  } finally { polls.delete('resources'); }
}

async function initialize() {
  await refreshStatus();
  await Promise.allSettled([refreshLogs(), refreshResources(), loadSchedule(), loadQuickSettings()]);
  checkPanelUpdate();
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 3000);
  setInterval(() => { if (!document.hidden) refreshLogs(); }, 2000);
  setInterval(() => { if (!document.hidden) refreshResources(); }, RESOURCE_REFRESH_MS);
}
initialize();
window.addEventListener('resize', renderResourceHistory);
window.addEventListener('pagehide', () => saveResourceHistory(true));
