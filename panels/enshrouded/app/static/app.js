const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let statusCache = null;
let configCache = null;
let currentLog = 'all';
let currentPath = '';
let editingPath = '';
let editorOriginal = '';
let confirmResolver = null;
let resourceHistory = JSON.parse(localStorage.getItem('enshrouded-resource-history') || '[]').filter((row) => row[0] > Date.now() - 600000);
let lastReady = false;

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) { location.href = '/login'; throw new Error('Login required'); }
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data?.detail || data || `HTTP ${response.status}`);
  return data;
}
const json = (method, body) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
function message(text, error = false) { const el = $('#global-message'); el.textContent = text || ''; el.classList.toggle('visible', !!text); el.classList.toggle('error', error); if (text) setTimeout(() => { if (el.textContent === text) el.classList.remove('visible'); }, 5000); }
async function perform(work, success) { try { message(I18N.t('loading')); const data = await work(); message(success || data?.message || I18N.t('confirm')); return data; } catch (error) { message(error.message, true); throw error; } }
function bytes(value) { let n = Number(value) || 0; const units = ['B','KB','MB','GB','TB']; let i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; } return `${n >= 10 || !i ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`; }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }
function formatDate(timestamp) { return new Intl.DateTimeFormat(I18N.current(), {dateStyle:'medium', timeStyle:'short'}).format(new Date(Number(timestamp) * 1000)); }
function serverRunning() { return ['running', 'restarting'].includes(statusCache?.server); }

function showView(name) {
  $$('.view').forEach((view) => view.classList.toggle('active', view.id === `view-${name}`));
  $$('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.view === name));
  const nav = $(`.nav-item[data-view="${name}"] span`);
  $('#view-title').textContent = nav?.textContent || I18N.t(name);
  location.hash = name === 'overview' ? '' : name;
  if (name === 'logs') loadLogs();
  if (name === 'files') loadFiles(currentPath);
  if (name === 'backups') loadBackups();
  if (name === 'discord') loadDiscord();
  if (name === 'schedule') loadSchedule();
  if (name === 'update') loadUpdate();
}

function stateText(status) {
  if (status?.ready) return I18N.t('ready');
  if (status?.server === 'running' || status?.server === 'restarting') return I18N.t('running');
  if (status?.server === 'missing') return I18N.t('missing');
  return I18N.t('stopped');
}
async function refreshStatus() {
  try {
    const previousReady = lastReady;
    statusCache = await api('/api/status');
    lastReady = !!statusCache.ready;
    $('#server-state').textContent = stateText(statusCache);
    $('#server-state').className = statusCache.ready ? 'online' : '';
    const query = statusCache.query || {};
    $('#player-count').textContent = `${query.players ?? '-'} / ${query.max_players ?? 16}`;
    $('#panel-version').textContent = statusCache.panel_version;
    $('#sidebar-version').textContent = `v${statusCache.panel_version}`;
    $('#install-button').hidden = statusCache.installed;
    $$('[data-action="start"]').forEach((button) => button.disabled = serverRunning() || statusCache.busy);
    $$('[data-action="stop"]').forEach((button) => button.disabled = !serverRunning() || statusCache.busy);
    $$('[data-action="restart"]').forEach((button) => button.disabled = !serverRunning() || statusCache.busy);
    $$('.save-config,#add-role').forEach((button) => button.disabled = serverRunning());
    $('#file-lock').hidden = !serverRunning();
    if (!previousReady && lastReady && sessionStorage.getItem('enshrouded-ready-notified') !== '1') {
      sessionStorage.setItem('enshrouded-ready-notified', '1');
      message(`${statusCache.server_name} · ${I18N.t('ready')}`);
    }
  } catch (error) { console.warn(error); }
}

function drawChart(canvas, index, color) {
  const rect = canvas.getBoundingClientRect(); const ratio = devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio)); canvas.height = Math.max(1, Math.round(rect.height * ratio));
  const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio); const w = rect.width; const h = rect.height; const left = 34;
  ctx.clearRect(0, 0, w, h); ctx.strokeStyle = '#29433b'; ctx.lineWidth = 1;
  [0, .25, .5, .75, 1].forEach((part) => { const y = 3 + (h - 6) * part; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(w, y); ctx.stroke(); });
  const now = Date.now(); const start = now - 600000; const points = resourceHistory.filter((row) => row[0] >= start);
  if (!points.length) return;
  ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  points.forEach((row, pointIndex) => { const x = left + Math.max(0, Math.min(1, (row[0] - start) / 600000)) * (w - left); const y = h - 3 - Math.max(0, Math.min(100, row[index])) / 100 * (h - 6); if (pointIndex) ctx.lineTo(x, y); else ctx.moveTo(x, y); }); ctx.stroke();
}
function renderCharts() { drawChart($('#cpu-chart'), 1, '#5dd2bd'); drawChart($('#memory-chart'), 2, '#e7a94c'); }
async function refreshResources() {
  try {
    const data = await api('/api/resources'); const now = Date.now();
    resourceHistory.push([now, Number(data.cpu_percent) || 0, Number(data.memory_percent) || 0]);
    resourceHistory = resourceHistory.filter((row) => row[0] > now - 600000).slice(-650);
    if (resourceHistory.length % 10 === 0) localStorage.setItem('enshrouded-resource-history', JSON.stringify(resourceHistory));
    $('#cpu-value').textContent = `${data.cpu_percent.toFixed(1)}%`; $('#memory-value').textContent = `${data.memory_percent.toFixed(1)}%`; $('#disk-value').textContent = `${data.disk_percent.toFixed(1)}%`;
    $('#memory-detail').textContent = `${bytes(data.memory_used)} / ${bytes(data.memory_total)}`; $('#disk-detail').textContent = `${bytes(data.disk_used)} / ${bytes(data.disk_total)}`; $('#disk-free').textContent = `${bytes(data.disk_total - data.disk_used)} free`; $('#disk-meter').style.width = `${data.disk_percent}%`;
    renderCharts();
  } catch (error) { console.warn(error); }
}

async function runAction(action) {
  const label = action === 'install' ? I18N.t('install') : I18N.t(action);
  if (!await confirmAction(label, `${label}?`)) return;
  await perform(() => api(action === 'install' ? '/api/install' : `/api/server/${action}`, {method:'POST'}));
  setTimeout(refreshStatus, 700);
}

function fillSettings(config) {
  configCache = structuredClone(config);
  const form = $('#settings-form');
  ['server_name','slot_count','query_port','voice_chat_mode'].forEach((name) => { form.elements[name].value = config[name]; });
  ['enable_voice_chat','enable_text_chat'].forEach((name) => { form.elements[name].checked = !!config[name]; });
  form.elements.tags.value = (config.tags || []).join(', ');
  renderRoles(config.roles || []);
  const preset = $(`input[name="preset"][value="${config.game_settings_preset}"]`); if (preset) preset.checked = true;
}
async function loadConfig() { fillSettings(await api('/api/config')); }
function collectSettings() {
  const form = $('#settings-form'); const data = structuredClone(configCache);
  data.server_name = form.elements.server_name.value.trim(); data.slot_count = Number(form.elements.slot_count.value); data.query_port = Number(form.elements.query_port.value); data.voice_chat_mode = form.elements.voice_chat_mode.value; data.enable_voice_chat = form.elements.enable_voice_chat.checked; data.enable_text_chat = form.elements.enable_text_chat.checked; data.tags = form.elements.tags.value.split(',').map((v) => v.trim()).filter(Boolean); data.roles = collectRoles(); data.game_settings_preset = $('input[name="preset"]:checked')?.value || 'Default'; return data;
}
async function saveConfig() { const result = await perform(() => api('/api/config', json('POST', collectSettings())), I18N.t('save_changes')); fillSettings(result); }
function renderRoles(roles) { const list = $('#roles-list'); list.innerHTML = ''; roles.forEach((role) => addRole(role)); }
function addRole(role = {name:'New role',password:'change-this-password',can_kick_ban:false,can_access_inventories:false,can_edit_world:true,can_edit_base:false,can_extend_base:false,reserved_slots:0}) {
  if ($$('.role-row').length >= 8) return message('Maximum 8 roles', true);
  const row = $('#role-template').content.firstElementChild.cloneNode(true); row.querySelector('.role-index').textContent = String($$('.role-row').length + 1).padStart(2,'0');
  Object.entries(role).forEach(([key,value]) => { const input = row.querySelector(`[data-role="${key}"]`); if (input) input.type === 'checkbox' ? input.checked = !!value : input.value = value; });
  row.querySelector('.remove-role').addEventListener('click', () => { if ($$('.role-row').length <= 1) return; row.remove(); $$('.role-row .role-index').forEach((el,index) => el.textContent = String(index+1).padStart(2,'0')); });
  $('#roles-list').append(row); I18N.apply(row);
}
function collectRoles() { return $$('.role-row').map((row) => { const role = {}; $$('[data-role]', row).forEach((input) => { role[input.dataset.role] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value.trim(); }); return role; }); }

async function loadSchedule() { const data = await api('/api/schedule'); const form = $('#schedule-form'); form.elements.enabled.checked = data.enabled; form.elements.time.value = data.time; form.elements.skip_when_players_online.checked = data.skip_when_players_online; $$('[name="weekday"]', form).forEach((input) => input.checked = data.weekdays.includes(Number(input.value))); }
async function saveSchedule() { const form = $('#schedule-form'); const body = {enabled:form.elements.enabled.checked,time:form.elements.time.value,skip_when_players_online:form.elements.skip_when_players_online.checked,weekdays:$$('[name="weekday"]:checked',form).map((el)=>Number(el.value))}; await perform(() => api('/api/schedule', json('POST',body)), I18N.t('save_schedule')); }

async function loadLogs() { try { const data = await api(`/api/logs?kind=${currentLog}`); const output = $('#log-output'); const nearBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 80; output.textContent = data.log; if ($('#auto-scroll').checked && nearBottom) output.scrollTop = output.scrollHeight; } catch (error) { console.warn(error); } }

async function loadBackups() {
  const [settings,data] = await Promise.all([api('/api/backups/settings'),api('/api/backups')]); const form = $('#backup-form'); form.elements.enabled.checked = settings.enabled; form.elements.times.value = settings.times.join(', '); form.elements.retention_count.value = settings.retention_count; form.elements.retention_days.value = settings.retention_days;
  const list = $('#backup-list'); list.innerHTML = ''; if (!data.backups.length) { list.innerHTML = `<div class="record-row"><strong>${escapeHtml(I18N.t('no_backups'))}</strong></div>`; return; }
  data.backups.forEach((backup) => { const row = document.createElement('div'); row.className = 'record-row'; row.innerHTML = `<strong>${escapeHtml(backup.name)}</strong><span>${bytes(backup.size)}</span><span>${formatDate(backup.modified_at)}</span><div class="actions"><button data-download>${escapeHtml(I18N.t('download'))}</button><button class="danger" data-restore>${escapeHtml(I18N.t('restore'))}</button></div>`; row.querySelector('[data-download]').onclick = () => location.href = `/api/backups/download?name=${encodeURIComponent(backup.name)}`; row.querySelector('[data-restore]').onclick = async () => { if (await confirmAction(I18N.t('restore'), backup.name)) await perform(() => api('/api/backups/restore', json('POST',{name:backup.name}))); }; list.append(row); });
}
async function saveBackupSettings() { const form = $('#backup-form'); const body = {enabled:form.elements.enabled.checked,times:form.elements.times.value.split(',').map(v=>v.trim()).filter(Boolean).slice(0,3),retention_count:Number(form.elements.retention_count.value),retention_days:Number(form.elements.retention_days.value)}; await perform(() => api('/api/backups/settings',json('POST',body)),I18N.t('save_policy')); loadBackups(); }

function breadcrumbs(path) { const root = $('#breadcrumbs'); root.innerHTML = '<button data-path="">/data</button>'; let current = ''; path.split('/').filter(Boolean).forEach((part) => { current += `${current ? '/' : ''}${part}`; root.insertAdjacentHTML('beforeend', `<span>/</span><button data-path="${escapeHtml(current)}">${escapeHtml(part)}</button>`); }); $$('button',root).forEach((button)=>button.onclick=()=>loadFiles(button.dataset.path)); }
async function loadFiles(path='') { const data = await api(`/api/files?path=${encodeURIComponent(path)}`); currentPath = data.path; breadcrumbs(currentPath); const list = $('#file-list'); list.innerHTML=''; data.entries.forEach((entry) => { const row=document.createElement('div'); row.className='file-row'; row.innerHTML=`<div class="file-icon">${entry.type==='folder'?'◆':'▧'}</div><div class="file-name">${escapeHtml(entry.name)}</div><span class="file-meta">${entry.type==='folder'?'Folder':bytes(entry.size)}</span><span class="file-meta">${formatDate(entry.modified_at)}</span><div class="file-actions"></div>`; const actions=$('.file-actions',row); if(entry.type==='folder'){ const open=document.createElement('button'); open.textContent='Open'; open.onclick=()=>loadFiles(entry.path); actions.append(open); } else { if(entry.editable){ const edit=document.createElement('button'); edit.textContent=I18N.t('edit'); edit.disabled=data.locked; edit.onclick=()=>openEditor(entry.path); actions.append(edit); } const down=document.createElement('button'); down.textContent=I18N.t('download'); down.onclick=()=>location.href=`/api/files/download?path=${encodeURIComponent(entry.path)}`; actions.append(down); } const del=document.createElement('button'); del.className='danger'; del.textContent=I18N.t('delete'); del.disabled=data.locked; del.onclick=async()=>{ if(await confirmAction(I18N.t('delete'),entry.name)){ await perform(()=>api(`/api/files?path=${encodeURIComponent(entry.path)}`,{method:'DELETE'})); loadFiles(currentPath); }}; actions.append(del); list.append(row); }); }
async function openEditor(path) { const data=await api(`/api/files/text?path=${encodeURIComponent(path)}`); editingPath=path; editorOriginal=data.content; $('#file-editor-name').textContent=path; $('#file-editor').value=data.content; $('#file-editor').disabled=data.locked; $('#file-editor-save').disabled=data.locked; $('#file-dirty').classList.remove('visible'); $('#file-editor-dialog').showModal(); document.body.classList.add('modal-open'); }
function closeEditor(){ $('#file-editor-dialog').close(); document.body.classList.remove('modal-open'); }
async function saveEditor(){ await perform(()=>api(`/api/files/text?path=${encodeURIComponent(editingPath)}`,json('POST',{content:$('#file-editor').value})),I18N.t('save')); editorOriginal=$('#file-editor').value; closeEditor(); loadFiles(currentPath); }

async function loadDiscord(){ const data=await api('/api/discord'); const form=$('#discord-form'); Object.entries(data.config).forEach(([key,value])=>{ const input=form.elements[key]; if(!input)return; input.type==='checkbox'?input.checked=!!value:input.value=key==='webhook_hint'?value:input.value; }); form.elements.webhook_url.placeholder=data.config.webhook_hint||'https://discord.com/api/webhooks/...'; }
async function saveDiscord(){ const form=$('#discord-form'); const body={}; ['enabled','notify_server_start','notify_server_stop','notify_server_restart','notify_backup','notify_migration','notify_errors'].forEach((name)=>body[name]=form.elements[name].checked); body.webhook_url=form.elements.webhook_url.value.trim(); body.username=form.elements.username.value.trim(); await perform(()=>api('/api/discord',json('POST',body)),I18N.t('save_integration')); form.elements.webhook_url.value=''; loadDiscord(); }

async function importMigration(file){ if(!file)return; if(serverRunning())return message(I18N.t('import_warning'),true); if(!await confirmAction(I18N.t('import_move'),file.name))return; const body=new FormData(); body.append('file',file); await perform(()=>api('/api/migration/import',{method:'POST',body}),I18N.t('import_move')); await Promise.all([loadConfig(),loadBackups(),loadFiles('')]); }
async function loadUpdate(){ const data=await api('/api/panel-update'); $('#update-status').textContent=data.version||`v${statusCache?.panel_version||'1.0.3'}`; $('#update-message').textContent=data.message||'Ready'; $('#update-progress').style.width=`${Number(data.progress)||0}%`; }

function confirmAction(title, copy){ const dialog=$('#confirm-dialog'); $('#confirm-title').textContent=title; $('#confirm-copy').textContent=copy; dialog.showModal(); document.body.classList.add('modal-open'); return new Promise((resolve)=>{confirmResolver=resolve;}); }
function closeConfirm(value){ if($('#confirm-dialog').open)$('#confirm-dialog').close(); document.body.classList.remove('modal-open'); if(confirmResolver){confirmResolver(value);confirmResolver=null;} }

function bindEvents(){
  $$('.nav-item').forEach((button)=>button.onclick=()=>showView(button.dataset.view)); $$('[data-view-target]').forEach((button)=>button.onclick=()=>showView(button.dataset.viewTarget)); $$('[data-action]').forEach((button)=>button.onclick=()=>runAction(button.dataset.action)); $$('.save-config').forEach((button)=>button.onclick=saveConfig); $('#add-role').onclick=()=>addRole(); $('#save-schedule').onclick=saveSchedule;
  $$('.terminal-tabs button').forEach((button)=>button.onclick=()=>{currentLog=button.dataset.log;$$('.terminal-tabs button').forEach(b=>b.classList.toggle('active',b===button));loadLogs();}); $('#export-log').onclick=()=>location.href='/api/logs/export';
  $('#backup-now').onclick=async()=>{await perform(()=>api('/api/backups',{method:'POST'}),I18N.t('backup_now'));setTimeout(loadBackups,900);}; $('#backup-settings-save').onclick=(event)=>{event.preventDefault();saveBackupSettings();};
  $('#file-parent').onclick=()=>loadFiles(currentPath.split('/').slice(0,-1).join('/')); $('#file-refresh').onclick=()=>loadFiles(currentPath); $('#new-folder').onclick=async()=>{const name=prompt(I18N.t('new_folder'));if(name){await perform(()=>api('/api/files/directory',json('POST',{path:currentPath,name})));loadFiles(currentPath);}}; $('#file-upload').onchange=async(event)=>{const file=event.target.files[0];if(!file)return;const body=new FormData();body.append('file',file);body.append('path',currentPath);await perform(()=>api('/api/files/upload',{method:'POST',body}));event.target.value='';loadFiles(currentPath);};
  $('#file-editor').oninput=()=>$('#file-dirty').classList.toggle('visible',$('#file-editor').value!==editorOriginal); $('#file-editor-save').onclick=saveEditor; $('#file-editor-cancel').onclick=closeEditor; $('#file-editor-dialog .dialog-head button').onclick=closeEditor; document.addEventListener('keydown',(event)=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'&&$('#file-editor-dialog').open){event.preventDefault();saveEditor();}});
  $('#discord-save').onclick=saveDiscord; $('#discord-test').onclick=()=>perform(()=>api('/api/discord/test',{method:'POST'}),I18N.t('test_send')); $('#migration-export').onclick=()=>location.href='/api/migration/export'; $('#migration-import').onchange=(event)=>{importMigration(event.target.files[0]);event.target.value='';};
  $('#apply-update').onclick=async()=>{if(await confirmAction(I18N.t('apply_update'),I18N.t('update_copy'))){await perform(()=>api('/api/panel-update',{method:'POST'}));setTimeout(loadUpdate,1000);}}; $('#logout-button').onclick=async()=>{await api('/api/auth/logout',{method:'POST'});location.href='/login';};
  $('#confirm-close').onclick=()=>closeConfirm(false); $('#confirm-cancel').onclick=()=>closeConfirm(false); $('#confirm-accept').onclick=()=>closeConfirm(true);
  window.addEventListener('resize',renderCharts); window.addEventListener('languagechange',()=>{const active=$('.nav-item.active');$('#view-title').textContent=$('span',active)?.textContent||I18N.t('home');refreshStatus();});
}
function initWeekdays(){ const labels={ko:['월','화','수','목','금','토','일'],en:['M','T','W','T','F','S','S'],zh:['一','二','三','四','五','六','日'],ja:['月','火','水','木','金','土','日']}; $('#weekday-options').innerHTML=(labels[I18N.current()]||labels.ko).map((label,index)=>`<label><input type="checkbox" name="weekday" value="${index}"><span>${label}</span></label>`).join(''); }
async function init(){ initWeekdays(); bindEvents(); await Promise.all([loadConfig(),refreshStatus(),refreshResources(),loadSchedule()]); const hash=location.hash.slice(1); if(hash&&$(`#view-${hash}`))showView(hash); setInterval(refreshStatus,3000); setInterval(refreshResources,1000); setInterval(()=>{if($('#view-logs').classList.contains('active'))loadLogs();},1500); requestAnimationFrame(function animate(){renderCharts();requestAnimationFrame(animate);}); }
init().catch((error)=>message(error.message,true));
