'use strict';
const $ = id => document.getElementById(id);
let state = null;
let uiBusy = false;
let logKind = 'server';
let connectionMode = 'invite';
let permissionLists = {};
let panelUpdating = false;
let activeDetail = null;
let lastJob = '';
let toastTimer;
let panelUpdateCheckTimer;
let serverFilesPath = '';
let serverFilesParent = '';
const selectedServerFolders = new Set();
const polls = new Set();
const runningStates = new Set(['running', 'restarting', 'paused', 'removing']);

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

function writable() { return state?.docker_available && !state.busy && !uiBusy && !runningStates.has(state.server_status); }
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
  $('panel-update-action').disabled = !available || running;
  updateServerFileControls();
  $('install-label').textContent = state?.engine.installed ? '서버 업데이트' : '엔진 설치';
  $('control-hint').textContent = !state?.docker_available ? '서버 제어를 위해 Docker 연결이 필요합니다.'
    : state.busy || uiBusy ? '현재 작업이 끝나면 다음 작업을 진행할 수 있습니다.'
    : running ? '서버가 실행 중입니다. 중지하면 월드 저장을 기다립니다.'
    : !state.engine.installed ? '엔진을 설치하고 서버 설정을 저장한 뒤 시작하세요.'
    : '시작 전에 월드 이름과 게임 접속 비밀번호를 확인하세요.';
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
  } catch (error) { toast(error.message); }
  finally { uiBusy = false; updateControls(); }
}
$('start').onclick = () => perform('/api/server/start', '서버 시작');
$('stop').onclick = () => perform('/api/server/stop', '서버 중지', '접속 중인 플레이어의 연결이 종료됩니다. 월드 저장이 끝날 때까지 기다린 뒤 서버를 중지합니다.');
$('restart').onclick = () => perform('/api/server/restart', '서버 재시작', '현재 월드를 저장하고 서버를 다시 시작합니다. 접속 중인 플레이어는 다시 접속해야 합니다.');
$('install').onclick = () => perform('/api/install', state?.engine.installed ? '서버 업데이트' : '엔진 설치', 'Steam 정식 서버를 다운로드합니다. 기존 월드가 있으면 업데이트 전에 백업을 만듭니다.');
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
  form.elements.password.value = '';
  fillWorldNames(data.worlds);
  message('quick-settings-message', config.password_set ? '접속 비밀번호가 설정되어 있습니다.' : '최초 시작 전 비밀번호를 입력해주세요.');
}

$('quick-settings-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const config = Object.fromEntries(new FormData(form));
  config.port = Number(config.port);
  ['crossplay', 'public'].forEach(key => { config[key] = form.elements.namedItem(key).checked; });
  if (!config.password) delete config.password;
  uiBusy = true; updateControls();
  try {
    await jsonPost('/api/config', config);
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
  document.querySelectorAll('.server-folder-select, .server-file-download').forEach(control => { control.disabled = !enabled; });
}

function setServerFilesMessage(text, error = false) {
  message('server-files-message', text, error);
}

function serverFileRow(entry) {
  const row = document.createElement('tr');
  const nameCell = document.createElement('td');
  const nameWrap = document.createElement('div');
  nameWrap.className = 'explorer-name-wrap';
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
    open.type = 'button'; open.className = 'explorer-name'; open.textContent = `▸ ${entry.name}`;
    open.onclick = () => loadServerFiles(entry.path);
    nameWrap.append(checkbox, open);
  } else {
    const icon = document.createElement('span');
    icon.className = 'explorer-file-name'; icon.textContent = `◇ ${entry.name}`;
    nameWrap.append(icon);
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
    $('server-files-path').textContent = `/server${serverFilesPath ? `/${serverFilesPath}` : ''}`;
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
  if (!data.worlds.length) emptyList(list, '아직 월드가 없습니다. 서버를 처음 시작하거나 기존 월드를 가져오세요.');
  for (const world of data.worlds) {
    const {row, actions} = fileRow(world.name + (world.name === data.selected ? ' · 선택됨' : ''), `${world.complete ? '월드 파일 한 쌍' : '파일 쌍이 불완전합니다'} · ${bytes(world.size)}`);
    if (world.complete) actions.append(actionButton('다운로드', () => { location.href = `/api/worlds/${encodeURIComponent(world.name)}/download`; }, true));
    list.append(row);
  }
  updateControls();
}
$('world-upload-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  data.set('overwrite', String(form.elements.overwrite.checked));
  if (form.elements.overwrite.checked && !await confirmAction('기존 월드 덮어쓰기', '같은 이름의 월드를 업로드한 파일로 교체합니다. 교체 전 현재 월드를 백업합니다.', '업로드')) return;
  uiBusy = true; updateControls(); message('worlds-message', '월드를 업로드하고 있습니다. 창을 닫지 말아주세요.');
  try { const result = await api('/api/worlds/upload', {method: 'POST', body: data}); message('worlds-message', result.message); form.reset(); await loadWorlds(); }
  catch (error) { message('worlds-message', error.message, true); }
  finally { uiBusy = false; updateControls(); }
};

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
  $('schedule-form').elements.enabled.checked = data.enabled;
  $('schedule-form').elements.times.value = data.times.join(', ');
  $('schedule-summary').textContent = data.enabled ? `${data.times.join(' · ')} KST` : '한국 시간 기준 운영';
  $('schedule-result').textContent = data.last_message || '아직 실행된 예약이 없습니다.';
}
$('schedule-form').onsubmit = async event => {
  event.preventDefault(); const form = event.currentTarget;
  const payload = {enabled: form.elements.enabled.checked, times: form.elements.times.value.split(',').map(t => t.trim()).filter(Boolean)};
  uiBusy = true; updateControls();
  try { await jsonPost('/api/restart-schedule', payload); message('schedule-message', '예약을 저장했습니다.'); await loadSchedule(); }
  catch (error) { message('schedule-message', error.message, true); }
  finally { uiBusy = false; updateControls(); }
};

const loaders = {'settings-dialog': loadSettings, 'worlds-dialog': loadWorlds, 'backups-dialog': loadBackups, 'permissions-dialog': loadPermissions,
  'schedule-dialog': loadSchedule, 'modifiers-dialog': loadModifiers, 'server-files-dialog': () => loadServerFiles(serverFilesPath), 'mods-dialog': async () => {},
  'discord-dialog': async () => {}, 'panel-update-dialog': loadPanelUpdate};
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
    meter('cpu-meter', data.cpu_percent || 0, 100); meter('memory-meter', data.memory_used || 0, data.memory_total || 0); meter('disk-meter', data.disk_used, data.disk_total);
  } catch {
    ['cpu', 'memory', 'disk', 'network-rx', 'network-tx'].forEach(id => { $(id).textContent = '—'; });
    ['cpu-meter', 'memory-meter', 'disk-meter'].forEach(id => meter(id, 0, 1));
  } finally { polls.delete('resources'); }
}

async function initialize() {
  await refreshStatus();
  await Promise.allSettled([refreshLogs(), refreshResources(), loadSchedule(), loadQuickSettings()]);
  checkPanelUpdate();
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 3000);
  setInterval(() => { if (!document.hidden) refreshLogs(); }, 2000);
  setInterval(() => { if (!document.hidden) refreshResources(); }, 5000);
}
initialize();
