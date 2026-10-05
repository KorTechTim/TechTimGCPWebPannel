'use strict';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
let statusCache = null;
let configCache = null;
let currentLog = 'server';
let currentPath = '';

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
function bytes(value) { if (value == null || !Number.isFinite(Number(value))) return '-'; let n = Number(value); const units = ['B','KB','MB','GB','TB']; let i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; } return `${n >= 10 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`; }
function lines(text) { return text.split(/\r?\n/).map(value => value.trim()).filter(Boolean); }
function setMeter(selector, value) { const element = $(selector); if (element) element.style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`; }

const titles = {overview:'서버 개요',console:'실시간 로그',settings:'기본 서버 설정',sandbox:'샌드박스 배율',mods:'모드 · 워크숍',players:'사용자 관리',backups:'백업 · 복원',advanced:'고급 파일 설정',schedule:'예약 작업',files:'서버 폴더 탐색기',monitor:'VM 모니터링','panel-update':'구동기 업데이트'};
async function showView(name) {
  if (!titles[name]) name = 'overview';
  $$('.view').forEach(view => view.classList.toggle('active', view.dataset.page === name));
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === name));
  $('#page-title').textContent = titles[name];
  history.replaceState(null, '', `#${name}`);
  try {
    if (name === 'settings') await loadConfig();
    if (name === 'sandbox') await loadSandbox();
    if (name === 'mods') await loadMods();
    if (name === 'players') await loadPlayers();
    if (name === 'backups') await loadBackups();
    if (name === 'schedule') await loadSchedule();
    if (name === 'files') await loadFiles(currentPath);
    if (name === 'advanced') await loadTextFile();
    if (name === 'console') await loadLogs();
    if (name === 'panel-update') await checkPanelUpdate(true);
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
  $('#operation-name').textContent = status.operation.name;
  $('#operation-message').textContent = status.operation.message;
  $('#connection-endpoint').textContent = `${location.hostname} : ${status.endpoint_port}`;
  $$('[data-action]').forEach(button => {
    const action = button.dataset.action;
    button.disabled = status.busy || (action === 'start' && status.server === 'running') || (action !== 'start' && status.server !== 'running');
  });
  $('#install-engine').disabled = status.busy || status.server === 'running';
  return status;
}

async function refreshResources() {
  const data = await api('/api/resources');
  const cpu = data.cpu.percent;
  const mem = data.memory.percent;
  const disk = data.disk.percent;
  ['#cpu-value','#cpu-value-2'].forEach(id => $(id).textContent = cpu == null ? '수집 중' : `${cpu.toFixed(1)}%`);
  ['#memory-value','#memory-value-2'].forEach(id => $(id).textContent = mem == null ? '-' : `${mem.toFixed(1)}%`);
  ['#disk-value','#disk-value-2'].forEach(id => $(id).textContent = `${disk.toFixed(1)}%`);
  ['#memory-detail','#memory-detail-2'].forEach(id => $(id).textContent = `${bytes(data.memory.used)} / ${bytes(data.memory.total)}`);
  ['#disk-detail','#disk-detail-2'].forEach(id => $(id).textContent = `${bytes(data.disk.used)} / ${bytes(data.disk.total)}`);
  ['#cpu-meter','#cpu-meter-2'].forEach(id => setMeter(id, cpu));
  ['#memory-meter','#memory-meter-2'].forEach(id => setMeter(id, mem));
  ['#disk-meter','#disk-meter-2'].forEach(id => setMeter(id, disk));
  const down = `${bytes(data.network.down)}/s`, up = `${bytes(data.network.up)}/s`;
  ['#network-down','#network-down-2'].forEach(id => $(id).textContent = down);
  ['#network-up','#network-up-2'].forEach(id => $(id).textContent = up);
  ['#network-value','#network-value-2'].forEach(id => $(id).textContent = `${down} ↓`);
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

$('#install-engine').addEventListener('click', () => perform(() => api('/api/install', {method:'POST'}), '엔진 설치·업데이트를 시작했습니다.'));
$$('[data-action]').forEach(button => button.addEventListener('click', () => perform(() => api(`/api/server/${button.dataset.action}`, {method:'POST'}), '서버 작업을 시작했습니다.')));
$('#copy-endpoint').addEventListener('click', async () => { await navigator.clipboard.writeText(`${location.hostname}:${statusCache?.endpoint_port || 16261}`); message('서버 주소를 복사했습니다.'); });

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

async function loadSandbox() { fillForm($('#sandbox-form'), await api('/api/sandbox')); }
$('#save-sandbox').addEventListener('click', () => perform(() => api('/api/sandbox', json('POST', formData($('#sandbox-form')))), '샌드박스 배율을 저장했습니다.'));

async function loadMods() {
  const [workshop, config] = await Promise.all([api('/api/workshop'), api('/api/config')]); configCache = config;
  $('#workshop-items').value = workshop.workshop_items.join('\n'); $('#mod-ids').value = workshop.mod_ids.join('\n'); $('#map-order').value = workshop.map_order.join('\n');
  $('#workshop-count').textContent = workshop.workshop_items.length; $('#mod-count').textContent = workshop.mod_ids.length; $('#installed-mod-count').textContent = workshop.installed.length;
}
$('#save-mods').addEventListener('click', () => perform(async () => {
  const config = configCache || await api('/api/config');
  config.workshop_items = lines($('#workshop-items').value); config.mod_ids = lines($('#mod-ids').value); config.map_order = lines($('#map-order').value);
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

function renderBreadcrumbs(path) {
  const target = $('#breadcrumbs'); target.replaceChildren(); const root = document.createElement('button'); root.textContent = '/data'; root.addEventListener('click', () => loadFiles('')); target.append(root);
  let accumulated = '';
  for (const part of path.split('/').filter(Boolean)) { target.append(document.createTextNode(' / ')); accumulated = accumulated ? `${accumulated}/${part}` : part; const destination = accumulated; const button = document.createElement('button'); button.textContent = part; button.addEventListener('click', () => loadFiles(destination)); target.append(button); }
}
async function loadFiles(path = '') {
  const data = await api(`/api/files?path=${encodeURIComponent(path)}`); currentPath = data.path; renderBreadcrumbs(data.path); const list = $('#file-list'); list.replaceChildren();
  for (const entry of data.entries) {
    const row = document.createElement('div'); row.className = 'file-row';
    const icon = document.createElement('b'); icon.textContent = entry.type === 'dir' ? '▣' : '▤'; const name = document.createElement('strong'); name.textContent = entry.name;
    if (entry.type === 'dir') { name.style.cursor = 'pointer'; name.addEventListener('click', () => loadFiles(entry.path)); }
    const size = document.createElement('small'); size.className = 'file-size'; size.textContent = entry.type === 'file' ? bytes(entry.size) : '폴더'; const date = document.createElement('small'); date.className = 'file-date'; date.textContent = entry.modified;
    const actions = document.createElement('div');
    if (entry.type === 'file') { const download = document.createElement('a'); download.href = `/api/files/download?path=${encodeURIComponent(entry.path)}`; download.textContent = '받기'; actions.append(download); }
    const remove = document.createElement('button'); remove.textContent = '삭제'; remove.addEventListener('click', () => perform(() => api(`/api/files?path=${encodeURIComponent(entry.path)}`, {method:'DELETE'}), '삭제했습니다.').then(() => loadFiles(currentPath))); actions.append(remove);
    row.append(icon, name, size, date, actions); list.append(row);
  }
}
$('#folder-up').addEventListener('click', () => loadFiles(currentPath.split('/').slice(0,-1).join('/')).catch(error => message(error.message, true)));
$('#refresh-files').addEventListener('click', () => loadFiles(currentPath).catch(error => message(error.message, true)));
$('#new-folder').addEventListener('click', async () => { const name = window.prompt('새 폴더 이름'); if (!name) return; await perform(() => api('/api/files/directory', json('POST', {path: currentPath, name})), '폴더를 만들었습니다.'); await loadFiles(currentPath); });
$('#file-upload').addEventListener('change', async event => { const file = event.target.files[0]; if (!file) return; const data = new FormData(); data.append('path', currentPath); data.append('file', file); await perform(() => api('/api/files/upload', {method:'POST', body:data}), '파일을 올렸습니다.'); event.target.value = ''; await loadFiles(currentPath); });

async function checkPanelUpdate(showMessage = false) {
  const data = await api('/api/panel-update');
  $('#update-dot').hidden = !data.available; $('#update-bubble').hidden = !data.available;
  $('#update-current-version').textContent = data.current_version || statusCache?.panel_version || '-';
  $('#update-image-status').textContent = data.available ? '업데이트 가능' : '최신 이미지 사용 중';
  $('#update-image-detail').textContent = data.error || (data.available ? `${data.current_image} → ${data.latest_image}` : `이미지 ${data.current_image || '-'}`);
  if (showMessage && data.error) message(`업데이트 확인 실패: ${data.error}`, true);
  return data;
}
$('#apply-update').addEventListener('click', () => perform(() => api('/api/panel-update', {method:'POST'}), '새 구동기 적용을 시작했습니다. 잠시 후 화면을 새로고침합니다.'));

$('#logout').addEventListener('click', async () => { const data = await api('/api/auth/logout', {method:'POST'}); location.assign(data.redirect); });
$('#refresh-all').addEventListener('click', () => refreshAll(true));
async function refreshAll(notify = false) {
  try { await Promise.all([refreshStatus(), refreshResources(), loadLogs()]); if (notify) message('최신 상태로 갱신했습니다.'); } catch (error) { message(error.message, true); }
}

showView(location.hash.slice(1) || 'overview');
refreshAll();
checkPanelUpdate().catch(() => {});
setInterval(() => refreshStatus().catch(() => {}), 3000);
setInterval(() => refreshResources().catch(() => {}), 5000);
setInterval(() => loadLogs().catch(() => {}), 5000);
setInterval(() => checkPanelUpdate().catch(() => {}), 300000);
