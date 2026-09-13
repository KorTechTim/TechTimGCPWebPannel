'use strict';
const $ = id => document.getElementById(id);
let state = null;
let uiBusy = false;
let logKind = 'server';
let permissionLists = {};
let panelUpdating = false;
let lastJob = '';
let toastTimer;
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
  button.closest('dialog').close('cancel');
}));

function writable() { return state?.docker_available && !state.busy && !uiBusy && !runningStates.has(state.server_status); }
function updateControls() {
  document.querySelectorAll('[data-writable]').forEach(element => { element.disabled = !writable(); });
  const available = state?.docker_available && !state.busy && !uiBusy;
  const running = runningStates.has(state?.server_status);
  $('start').disabled = !available || running || !state.engine.installed;
  $('stop').disabled = !available || !running;
  $('restart').disabled = !available || !running;
  $('install').disabled = !available || running;
  $('open-settings').disabled = !state;
  $('panel-update').disabled = !available || running;
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
    const host = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname) ? 'VM 공개 IP' : location.hostname;
    $('connection-address').textContent = `${host}:${state.port}`;
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
    if (panelUpdating && !state.busy && ['completed', 'failed'].includes(job.status)) {
      panelUpdating = false;
      if (job.status === 'completed') location.reload();
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
$('panel-update').onclick = () => perform('/api/panel/update', '패널 업데이트', '최신 TechTim 웹패널로 교체합니다. 잠시 연결이 끊길 수 있으며 실패하면 이전 패널로 복구를 시도합니다.');
$('logout').onclick = async () => { try { await api('/api/auth/logout', {method: 'POST'}); location.assign('/login'); } catch (error) { toast(error.message); } };
$('copy-address').onclick = async () => {
  const value = $('connection-address').textContent;
  if (value.startsWith('VM 공개 IP')) { toast('실제 VM의 공개 IP로 접속해주세요.'); return; }
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
    else { const area = document.createElement('textarea'); area.value = value; document.body.append(area); area.select(); const copied = document.execCommand('copy'); area.remove(); if (!copied) throw new Error(); }
    toast('접속 주소를 복사했습니다.');
  } catch { toast(`접속 주소: ${value}`); }
};

const integerFields = ['port', 'save_interval', 'backups', 'backup_short', 'backup_long'];
async function openSettings() {
  try {
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
    $('world-names').replaceChildren(...data.worlds.filter(w => w.complete).map(world => { const option = document.createElement('option'); option.value = world.name; return option; }));
    message('settings-message', '');
    updateControls();
    $('settings-dialog').showModal();
  } catch (error) { toast(error.message); }
}
$('open-settings').onclick = openSettings;
$('settings-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const config = Object.fromEntries(new FormData(form));
  ['crossplay', 'public'].forEach(key => { config[key] = form.elements.namedItem(key).checked; });
  integerFields.forEach(key => { config[key] = Number(config[key]); });
  if (!config.password) delete config.password;
  uiBusy = true; updateControls();
  try { await jsonPost('/api/config', config); form.elements.password.value = ''; form.elements.password.required = false; message('settings-message', '설정을 저장했습니다. 다음 서버 시작에 적용됩니다.'); await refreshStatus(); }
  catch (error) { message('settings-message', error.message, true); }
  finally { uiBusy = false; updateControls(); }
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

const loaders = {'worlds-dialog': loadWorlds, 'backups-dialog': loadBackups, 'permissions-dialog': loadPermissions, 'schedule-dialog': loadSchedule};
document.querySelectorAll('[data-open]').forEach(button => button.onclick = async () => {
  try { await loaders[button.dataset.open](); updateControls(); $(button.dataset.open).showModal(); }
  catch (error) { toast(error.message); }
});

function meter(id, used, total) { $(id).style.width = `${total > 0 ? Math.max(0, Math.min(100, used / total * 100)) : 0}%`; }
async function refreshResources() {
  if (polls.has('resources')) return;
  polls.add('resources');
  try {
    const data = await api('/api/server/resources');
    $('cpu').textContent = data.available ? `${data.cpu_percent}%` : '—';
    $('memory').textContent = data.available ? `${bytes(data.memory_used)} / ${bytes(data.memory_total)}` : '—';
    $('disk').textContent = `${bytes(data.disk_used)} / ${bytes(data.disk_total)}`;
    $('network').textContent = data.available ? `↓ ${bytes(data.network_rx)}/s · ↑ ${bytes(data.network_tx)}/s` : '—';
    meter('cpu-meter', data.cpu_percent || 0, 100); meter('memory-meter', data.memory_used || 0, data.memory_total || 0); meter('disk-meter', data.disk_used, data.disk_total);
  } catch {
    ['cpu', 'memory', 'disk', 'network'].forEach(id => { $(id).textContent = '—'; });
    ['cpu-meter', 'memory-meter', 'disk-meter'].forEach(id => meter(id, 0, 1));
  } finally { polls.delete('resources'); }
}

async function initialize() {
  await refreshStatus();
  await Promise.allSettled([refreshLogs(), refreshResources(), loadSchedule()]);
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 3000);
  setInterval(() => { if (!document.hidden) refreshLogs(); }, 2000);
  setInterval(() => { if (!document.hidden) refreshResources(); }, 5000);
}
initialize();
