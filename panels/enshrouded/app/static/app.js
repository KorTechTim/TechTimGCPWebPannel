const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let statusCache = null;
let configCache = null;
let currentLog = 'all';
let currentPath = '';
let editingPath = '';
let editorOriginal = '';
let confirmResolver = null;
let textInputResolver = null;
let updatePollTimer = null;
let installPollTimer = null;
let updateRenderedProgress = 0;
let noticeTimer = null;
let resourceHistory = JSON.parse(localStorage.getItem('enshrouded-resource-history') || '[]').filter((row) => row[0] > Date.now() - 600000);
let lastReady = false;
const UPDATE_ACTIVE = new Set(['queued','running','pulling','downloading','preparing','replacing','verifying','reconnecting']);
const PRESET_DETAILS = {
  ko:{Default:['기본','처음 플레이하는 이용자에게 권장되는 표준 밸런스입니다.','표준 적 수','표준 자원','기본 생존 규칙'],Relaxed:['여유롭게','적의 수가 줄고 자원과 전리품이 늘어 건축과 가벼운 탐험에 집중하기 좋습니다.','적 수 감소','자원 증가','건축 중심'],Hard:['어려움','적의 수와 공격성이 증가해 전투 난도가 높아집니다.','적 수 증가','공격성 증가','전투 중심'],Survival:['생존','더 공격적인 적과 함께 허기 및 강화된 사망 불이익 등 추가 생존 요소가 적용됩니다.','허기 사용','강화된 적','큰 사망 불이익'],Custom:['사용자 지정','enshrouded_server.json의 개별 게임 설정을 원하는 조합으로 직접 구성합니다.','개별 수치 조정','30개 이상 항목','고급 설정']},
  en:{Default:['Default','The recommended baseline balance for first-time players.','Standard enemies','Standard resources','Core survival'],Relaxed:['Relaxed','Fewer enemies and more resources and loot for building and light adventure.','Fewer enemies','More resources','Building focus'],Hard:['Hard','More enemies with greater aggression for a tougher combat experience.','More enemies','Higher aggression','Combat focus'],Survival:['Survival','More aggressive enemies plus hunger and stronger death penalties.','Hunger enabled','Aggressive enemies','Harsh death penalty'],Custom:['Custom','Combine individual gameplay settings directly in enshrouded_server.json.','Fine tuning','30+ settings','Advanced']},
  zh:{Default:['默认','推荐新玩家使用的标准平衡设置。','标准敌人','标准资源','基础生存'],Relaxed:['轻松','敌人更少，资源与战利品更多，适合建造和轻松探索。','敌人减少','资源增加','建造优先'],Hard:['困难','敌人数量与攻击性提高，战斗更具挑战。','敌人增加','攻击性提高','战斗优先'],Survival:['生存','更强的敌人，并启用饥饿和更严厉的死亡惩罚。','启用饥饿','强敌','严厉死亡惩罚'],Custom:['自定义','在 enshrouded_server.json 中自由组合各项游戏设置。','独立调整','30多项设置','高级']},
  ja:{Default:['デフォルト','初めて遊ぶプレイヤーに推奨される標準バランスです。','標準の敵数','標準の資源','基本サバイバル'],Relaxed:['リラックス','敵が少なく資源と戦利品が増え、建築と気軽な冒険に向きます。','敵が少ない','資源増加','建築重視'],Hard:['ハード','敵の数と攻撃性が増え、戦闘がより厳しくなります。','敵が多い','攻撃性上昇','戦闘重視'],Survival:['サバイバル','より攻撃的な敵に加え、空腹と重い死亡ペナルティが適用されます。','空腹あり','強い敵','重い死亡ペナルティ'],Custom:['カスタム','enshrouded_server.json で各ゲーム設定を自由に組み合わせます。','個別調整','30項目以上','上級設定']}
};
const PRESET_GAME_SETTINGS = {
  Default:{playerHealthFactor:1,playerManaFactor:1,playerStaminaFactor:1,playerBodyHeatFactor:1,playerDivingTimeFactor:1,shroudTimeFactor:1,enableDurability:true,enableStarvingDebuff:false,foodBuffDurationFactor:1,fromHungerToStarving:600000000000,tombstoneMode:'AddBackpackMaterials',enableGliderTurbulences:true,fishingDifficulty:'Normal',miningDamageFactor:1,plantGrowthSpeedFactor:1,resourceDropStackAmountFactor:1,factoryProductionSpeedFactor:1,perkUpgradeRecyclingFactor:.5,perkCostFactor:1,experienceCombatFactor:1,experienceMiningFactor:1,experienceExplorationQuestsFactor:1,randomSpawnerAmount:'Automatic',aggroPoolAmount:'Normal',enemyDamageFactor:1,enemyHealthFactor:1,enemyStaminaFactor:1,enemyPerceptionRangeFactor:1,bossDamageFactor:1,bossHealthFactor:1,threatBonus:1,pacifyAllEnemies:false,weatherFrequency:'Normal',tamingStartleRepercussion:'LoseSomeProgress',dayTimeDuration:1800000000000,nightTimeDuration:720000000000,curseModifier:'Normal'},
  Relaxed:{playerHealthFactor:2,playerManaFactor:2,playerStaminaFactor:2,playerBodyHeatFactor:2,playerDivingTimeFactor:1.5,shroudTimeFactor:1.5,enableDurability:false,enableStarvingDebuff:false,foodBuffDurationFactor:1.5,fromHungerToStarving:600000000000,tombstoneMode:'NoTombstone',enableGliderTurbulences:false,fishingDifficulty:'Easy',miningDamageFactor:1.5,plantGrowthSpeedFactor:2,resourceDropStackAmountFactor:1.5,factoryProductionSpeedFactor:2,perkUpgradeRecyclingFactor:1,perkCostFactor:.5,experienceCombatFactor:1.5,experienceMiningFactor:1.25,experienceExplorationQuestsFactor:1,randomSpawnerAmount:'Few',aggroPoolAmount:'Few',enemyDamageFactor:.5,enemyHealthFactor:.5,enemyStaminaFactor:.5,enemyPerceptionRangeFactor:.75,bossDamageFactor:.5,bossHealthFactor:.5,threatBonus:.5,pacifyAllEnemies:false,weatherFrequency:'Rare',tamingStartleRepercussion:'KeepProgress',dayTimeDuration:1800000000000,nightTimeDuration:720000000000,curseModifier:'Easy'},
  Hard:{playerHealthFactor:1,playerManaFactor:1,playerStaminaFactor:1,playerBodyHeatFactor:1,playerDivingTimeFactor:.9,shroudTimeFactor:1,enableDurability:true,enableStarvingDebuff:false,foodBuffDurationFactor:.9,fromHungerToStarving:600000000000,tombstoneMode:'AddBackpackMaterials',enableGliderTurbulences:true,fishingDifficulty:'Normal',miningDamageFactor:1,plantGrowthSpeedFactor:1,resourceDropStackAmountFactor:1,factoryProductionSpeedFactor:1,perkUpgradeRecyclingFactor:.5,perkCostFactor:1,experienceCombatFactor:.5,experienceMiningFactor:.5,experienceExplorationQuestsFactor:1,randomSpawnerAmount:'More',aggroPoolAmount:'Normal',enemyDamageFactor:1.25,enemyHealthFactor:1,enemyStaminaFactor:1,enemyPerceptionRangeFactor:1,bossDamageFactor:1,bossHealthFactor:1.5,threatBonus:1.5,pacifyAllEnemies:false,weatherFrequency:'Normal',tamingStartleRepercussion:'LoseSomeProgress',dayTimeDuration:1800000000000,nightTimeDuration:720000000000,curseModifier:'Normal'},
  Survival:{playerHealthFactor:.75,playerManaFactor:1,playerStaminaFactor:1,playerBodyHeatFactor:.75,playerDivingTimeFactor:.75,shroudTimeFactor:1,enableDurability:true,enableStarvingDebuff:true,foodBuffDurationFactor:.7,fromHungerToStarving:600000000000,tombstoneMode:'Everything',enableGliderTurbulences:true,fishingDifficulty:'Hard',miningDamageFactor:.75,plantGrowthSpeedFactor:1,resourceDropStackAmountFactor:.75,factoryProductionSpeedFactor:1,perkUpgradeRecyclingFactor:.3,perkCostFactor:1.25,experienceCombatFactor:.5,experienceMiningFactor:.5,experienceExplorationQuestsFactor:1,randomSpawnerAmount:'More',aggroPoolAmount:'Normal',enemyDamageFactor:1.5,enemyHealthFactor:1,enemyStaminaFactor:1,enemyPerceptionRangeFactor:1,bossDamageFactor:1,bossHealthFactor:1.5,threatBonus:1.5,pacifyAllEnemies:false,weatherFrequency:'Often',tamingStartleRepercussion:'LoseAllProgress',dayTimeDuration:1800000000000,nightTimeDuration:1200000000000,curseModifier:'Hard'},
};
const GAME_SETTING_GROUPS = [
  {title:'플레이어 능력', icon:'abilities', copy:'체력, 마나, 스태미나와 환경 대응 능력을 조정합니다.', fields:[
    {key:'playerHealthFactor',label:'플레이어 체력',desc:'최대 체력 배율',type:'number',min:.25,max:4,step:.25},
    {key:'playerManaFactor',label:'플레이어 마나',desc:'최대 마나 배율',type:'number',min:.25,max:4,step:.25},
    {key:'playerStaminaFactor',label:'플레이어 스태미나',desc:'최대 스태미나 배율',type:'number',min:.25,max:4,step:.25},
    {key:'playerBodyHeatFactor',label:'추위 저항 체온',desc:'추운 지역 체류 가능 시간',type:'select',options:[.5,.75,1,1.5,2]},
    {key:'playerDivingTimeFactor',label:'잠수 시간',desc:'수중 산소 지속 배율',type:'number',min:.5,max:2,step:.05},
    {key:'shroudTimeFactor',label:'장막 체류 시간',desc:'장막 안에서 버틸 수 있는 시간',type:'number',min:.5,max:2,step:.25},
  ]},
  {title:'생존 규칙', icon:'survival', copy:'내구도, 허기, 음식 효과와 사망 규칙을 설정합니다.', fields:[
    {key:'enableDurability',label:'무기 내구도',desc:'무기와 장비 내구도 사용',type:'boolean'},
    {key:'enableStarvingDebuff',label:'허기 및 굶주림',desc:'굶주림 피해 사용',type:'boolean'},
    {key:'foodBuffDurationFactor',label:'음식 효과 시간',desc:'음식 버프 지속 배율',type:'number',min:.5,max:2,step:.05},
    {key:'fromHungerToStarving',label:'굶주림 전환 시간',desc:'배고픔에서 굶주림까지',type:'number',min:5,max:20,step:1,unit:'minutes'},
    {key:'tombstoneMode',label:'사망 시 묘비',desc:'사망 시 잃는 아이템 범위',type:'select',options:['AddBackpackMaterials','Everything','NoTombstone']},
    {key:'enableGliderTurbulences',label:'글라이더 난기류',desc:'비행 중 난기류 사용',type:'boolean'},
    {key:'fishingDifficulty',label:'낚시 난이도',desc:'낚시 미니게임 강도',type:'select',options:['VeryEasy','Easy','Normal','Hard','VeryHard']},
  ]},
  {title:'자원과 성장', icon:'resources', copy:'채집량, 제작 속도, 강화 비용과 경험치 획득량을 조정합니다.', fields:[
    {key:'miningDamageFactor',label:'채광 효율',desc:'채광 피해와 자원 수확량',type:'number',min:.5,max:2,step:.25},
    {key:'plantGrowthSpeedFactor',label:'작물 성장 속도',desc:'식물 성장 속도 배율',type:'number',min:.25,max:2,step:.25},
    {key:'resourceDropStackAmountFactor',label:'자원 획득량',desc:'전리품 묶음 수량 배율',type:'number',min:.25,max:2,step:.25},
    {key:'factoryProductionSpeedFactor',label:'작업대 생산 속도',desc:'제작 소요 시간 배율',type:'number',min:.25,max:2,step:.25},
    {key:'perkUpgradeRecyclingFactor',label:'무기 재활용 반환',desc:'강화 무기 분해 룬 반환율',type:'number',min:0,max:1,step:.05},
    {key:'perkCostFactor',label:'무기 강화 비용',desc:'강화에 필요한 룬 배율',type:'number',min:.25,max:2,step:.25},
    {key:'experienceCombatFactor',label:'전투 경험치',desc:'전투 경험치 획득 배율',type:'number',min:.25,max:2,step:.25},
    {key:'experienceMiningFactor',label:'채광 경험치',desc:'채광 경험치 획득 배율',type:'number',min:0,max:2,step:.25},
    {key:'experienceExplorationQuestsFactor',label:'탐험·퀘스트 경험치',desc:'탐험과 퀘스트 경험치 배율',type:'number',min:.25,max:2,step:.25},
  ]},
  {title:'적과 전투', icon:'combat', copy:'적 수, 공격성, 일반 적과 보스의 전투 능력을 조정합니다.', fields:[
    {key:'randomSpawnerAmount',label:'적 개체 수',desc:'월드에 생성되는 적 수',type:'select',options:['Few','Normal','More','Many','Automatic']},
    {key:'aggroPoolAmount',label:'동시 공격 적 수',desc:'동시에 공격 가능한 적 수',type:'select',options:['Few','Normal','More','Many']},
    {key:'enemyDamageFactor',label:'적 피해량',desc:'일반 적 공격 피해 배율',type:'number',min:.25,max:5,step:.25},
    {key:'enemyHealthFactor',label:'적 체력',desc:'일반 적 체력 배율',type:'number',min:.25,max:4,step:.25},
    {key:'enemyStaminaFactor',label:'적 기절 저항',desc:'적 스태미나 배율',type:'number',min:.5,max:2,step:.25},
    {key:'enemyPerceptionRangeFactor',label:'적 감지 범위',desc:'시야와 청각 감지 배율',type:'number',min:.5,max:2,step:.25},
    {key:'bossDamageFactor',label:'보스 피해량',desc:'보스 공격 피해 배율',type:'number',min:.2,max:5,step:.1},
    {key:'bossHealthFactor',label:'보스 체력',desc:'보스 체력 배율',type:'number',min:.2,max:5,step:.1},
    {key:'threatBonus',label:'적 공격 빈도',desc:'일반 적 공격 빈도 배율',type:'number',min:.25,max:4,step:.25},
    {key:'pacifyAllEnemies',label:'적 선제공격 방지',desc:'공격받기 전까지 일반 적 중립',type:'boolean'},
  ]},
  {title:'월드와 시간', icon:'world', copy:'날씨, 길들이기, 낮과 밤, 장막 저주를 설정합니다.', fields:[
    {key:'weatherFrequency',label:'날씨 현상 빈도',desc:'새로운 날씨가 나타나는 빈도',type:'select',options:['Disabled','Rare','Normal','Often']},
    {key:'tamingStartleRepercussion',label:'길들이기 실패 불이익',desc:'동물이 놀랐을 때 진행도 손실',type:'select',options:['KeepProgress','LoseSomeProgress','LoseAllProgress']},
    {key:'dayTimeDuration',label:'낮 시간',desc:'게임 내 낮의 실제 길이',type:'number',min:2,max:60,step:1,unit:'minutes'},
    {key:'nightTimeDuration',label:'밤 시간',desc:'게임 내 밤의 실제 길이',type:'number',min:2,max:60,step:1,unit:'minutes'},
    {key:'curseModifier',label:'장막 저주',desc:'저주 발생 난이도',type:'select',options:['Easy','Normal','Hard']},
  ]},
];
const SAVE_REMINDER_SCOPES = [
  ['#settings-form', '#view-settings .save-config', 'config'],
  ['#view-roles', '#view-roles .save-config', 'config'],
  ['#view-world', '#view-world .save-config', 'config'],
  ['#schedule-form', '#save-schedule', 'schedule'],
  ['#discord-form', '#discord-save', 'discord'],
  ['#backup-form', '#backup-settings-save', 'backup'],
];
const RUNNING_LOCKED_VIEWS = new Set(['settings', 'roles', 'world', 'files']);

function setUnsaved(button, dirty) {
  if (!button) return;
  button.classList.add('save-reminder-button');
  button.dataset.unsavedMessage = I18N.t('save_reminder');
  if (dirty) button.dataset.unsaved = 'true'; else delete button.dataset.unsaved;
}
function markUnsaved(viewSelector) { setUnsaved($(`${viewSelector} .save-reminder-button`), true); }
function clearUnsavedGroup(group) { SAVE_REMINDER_SCOPES.filter((scope) => scope[2] === group).forEach((scope) => setUnsaved($(scope[1]), false)); }
function refreshUnsavedMessages() { $$('.save-reminder-button').forEach((button) => { button.dataset.unsavedMessage = I18N.t('save_reminder'); }); }
function bindUnsavedReminders() {
  SAVE_REMINDER_SCOPES.forEach(([rootSelector, buttonSelector]) => {
    const root = $(rootSelector); const button = $(buttonSelector);
    setUnsaved(button, false);
    if (!root) return;
    const changed = () => setUnsaved(button, true);
    root.addEventListener('input', changed);
    root.addEventListener('change', changed);
  });
}

function syncRunningViewLock(name, announce = false) {
  const view = $(`#view-${name}`); if (!view) return;
  const wasLocked = view.classList.contains('running-locked');
  const locked = serverRunning() && RUNNING_LOCKED_VIEWS.has(name);
  view.classList.toggle('running-locked', locked);
  const dialog = $('#running-lock-dialog');
  if (!locked && dialog?.open) dialog.close();
  if (locked && dialog && !dialog.open && (announce || !wasLocked)) {
    dialog.showModal();
    document.body.classList.add('modal-open');
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) { location.href = '/login'; throw new Error('Login required'); }
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data?.detail || data || `HTTP ${response.status}`);
  return data;
}
const json = (method, body) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
function closeNotice() {
  clearTimeout(noticeTimer);
  const dialog = $('#notice-dialog');
  if (dialog?.open) dialog.close();
  document.body.classList.remove('modal-open');
}
function message(text, error = false) {
  const dialog = $('#notice-dialog');
  if (!dialog || !text) { closeNotice(); return; }
  clearTimeout(noticeTimer);
  dialog.classList.toggle('error', error);
  $('#notice-dialog-title').textContent = I18N.t(error ? 'error_title' : 'notice_title');
  $('#notice-dialog-copy').textContent = text;
  if (!dialog.open) dialog.showModal();
  document.body.classList.add('modal-open');
  if (text !== I18N.t('loading')) noticeTimer = setTimeout(closeNotice, error ? 8000 : 5000);
}
async function perform(work, success) { try { message(I18N.t('loading')); const data = await work(); message(success || data?.message || I18N.t('confirm')); return data; } catch (error) { message(error.message, true); throw error; } }
function bytes(value) { let n = Number(value) || 0; const units = ['B','KB','MB','GB','TB']; let i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; } return `${n >= 10 || !i ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`; }
function formatUptime(value) { const seconds = Math.max(0, Number(value) || 0); const language = I18N.current(); const units = {ko:['일','시간','분'],en:['d','h','m'],zh:['天','小时','分'],ja:['日','時間','分']}[language] || ['d','h','m']; const parts = [[Math.floor(seconds / 86400), units[0]],[Math.floor(seconds % 86400 / 3600), units[1]],[Math.floor(seconds % 3600 / 60), units[2]]].filter(([amount]) => amount > 0).slice(0, 2); return parts.length ? parts.map(([amount, unit]) => `${amount}${unit}`).join(' ') : ({ko:'1분 미만',en:'< 1m',zh:'少于1分',ja:'1分未満'}[language] || '< 1m'); }
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
  syncRunningViewLock(name, true);
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
    $('#summary-server-name').textContent = statusCache.server_name || '-';
    $('#summary-players').textContent = `${query.players ?? '-'} / ${query.max_players ?? 16}`;
    $('#summary-uptime').textContent = serverRunning() ? formatUptime(statusCache.uptime_seconds) : '-';
    $('#summary-query-port').textContent = statusCache.query_port ?? '-';
    $('#summary-preset').textContent = I18N.t(String(statusCache.game_settings_preset || 'default').toLowerCase());
    $('#panel-version').textContent = statusCache.panel_version;
    $('#sidebar-version').textContent = `v${statusCache.panel_version}`;
    $('#install-button').hidden = statusCache.installed;
    $$('[data-action="start"]').forEach((button) => button.disabled = serverRunning() || statusCache.busy);
    $$('[data-action="stop"]').forEach((button) => button.disabled = !serverRunning() || statusCache.busy);
    $$('[data-action="restart"]').forEach((button) => button.disabled = !serverRunning() || statusCache.busy);
    $$('.save-config,#add-role').forEach((button) => button.disabled = serverRunning());
    $('#file-lock').hidden = !serverRunning();
    const activeView = $('.view.active');
    if (activeView) syncRunningViewLock(activeView.id.replace('view-', ''));
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
function drawNetworkChart() {
  const canvas = $('#network-chart'); const rect = canvas.getBoundingClientRect(); const ratio = devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio)); canvas.height = Math.max(1, Math.round(rect.height * ratio));
  const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio); const w = rect.width; const h = rect.height; const left = 46;
  ctx.clearRect(0, 0, w, h); ctx.strokeStyle = '#29433b'; ctx.lineWidth = 1;
  [0, .25, .5, .75, 1].forEach((part) => { const y = 3 + (h - 6) * part; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(w, y); ctx.stroke(); });
  const now = Date.now(); const start = now - 600000; const points = resourceHistory.filter((row) => row[0] >= start);
  const ceiling = Math.max(1024, ...points.flatMap((row) => [Number(row[3]) || 0, Number(row[4]) || 0])) * 1.15;
  $('#network-max').textContent = `${bytes(ceiling)}/s`; $('#network-mid').textContent = `${bytes(ceiling / 2)}/s`;
  [[3,'#5dd2bd'],[4,'#e7a94c']].forEach(([index, color]) => { ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.lineCap = 'round'; points.forEach((row, pointIndex) => { const x = left + Math.max(0, Math.min(1, (row[0] - start) / 600000)) * (w - left); const y = h - 3 - Math.max(0, Math.min(1, (Number(row[index]) || 0) / ceiling)) * (h - 6); if (pointIndex) ctx.lineTo(x, y); else ctx.moveTo(x, y); }); ctx.stroke(); });
}
function renderCharts() { drawChart($('#cpu-chart'), 1, '#5dd2bd'); drawChart($('#memory-chart'), 2, '#e7a94c'); drawNetworkChart(); }
async function refreshResources() {
  try {
    const data = await api('/api/resources'); const now = Date.now();
    resourceHistory.push([now, Number(data.cpu_percent) || 0, Number(data.memory_percent) || 0, Number(data.network_receive_bps) || 0, Number(data.network_transmit_bps) || 0]);
    resourceHistory = resourceHistory.filter((row) => row[0] > now - 600000).slice(-650);
    if (resourceHistory.length % 10 === 0) localStorage.setItem('enshrouded-resource-history', JSON.stringify(resourceHistory));
    $('#cpu-value').textContent = `${data.cpu_percent.toFixed(1)}%`; $('#memory-value').textContent = `${data.memory_percent.toFixed(1)}%`; $('#disk-value').textContent = `${data.disk_percent.toFixed(1)}%`;
    $('#memory-detail').textContent = `${bytes(data.memory_used)} / ${bytes(data.memory_total)}`; $('#disk-detail').textContent = `${bytes(data.disk_used)} / ${bytes(data.disk_total)}`; $('#disk-free').textContent = `${bytes(data.disk_total - data.disk_used)} free`; $('#disk-meter').style.width = `${data.disk_percent}%`;
    $('#network-value').textContent = `${bytes((data.network_receive_bps || 0) + (data.network_transmit_bps || 0))}/s`; $('#network-receive').textContent = `${bytes(data.network_receive_bps)}/s`; $('#network-transmit').textContent = `${bytes(data.network_transmit_bps)}/s`;
    renderCharts();
  } catch (error) { console.warn(error); }
}

async function runAction(action) {
  const label = action === 'install' ? I18N.t('install') : I18N.t(action);
  if (action === 'install') {
    return openInstallConfirmation();
  }
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
  const presetName = config.game_settings_preset || 'Default';
  const preset = $(`input[name="preset"][value="${presetName}"]`); if (preset) preset.checked = true;
  renderPresetDescription(presetName);
  renderGameSettings(presetName === 'Custom' ? (config.game_settings || {}) : structuredClone(PRESET_GAME_SETTINGS[presetName] || PRESET_GAME_SETTINGS.Default));
  clearUnsavedGroup('config');
}
function renderPresetDescription(value='Default'){ const details=(PRESET_DETAILS[I18N.current()]||PRESET_DETAILS.ko)[value]||PRESET_DETAILS.ko.Default; $('#preset-description-kicker').textContent=`${value.toUpperCase()} PRESET`; $('#preset-description-title').textContent=details[0]; $('#preset-description-copy').textContent=details[1]; $('#preset-description-tags').innerHTML=details.slice(2).map(tag=>`<span>${escapeHtml(tag)}</span>`).join(''); }
function applyPreset(value) {
  renderPresetDescription(value);
  if (value !== 'Custom') renderGameSettings(structuredClone(PRESET_GAME_SETTINGS[value] || PRESET_GAME_SETTINGS.Default));
  markUnsaved('#view-world');
}
function gameSettingValue(field, value) { return field.unit === 'minutes' ? Number(value) / 60000000000 : value; }
function renderGameSettings(settings = {}) {
  const root = $('#game-settings-groups');
  root.innerHTML = GAME_SETTING_GROUPS.map((group) => `<section class="game-setting-group"><header><span class="game-setting-group-icon game-setting-icon-${group.icon}" aria-hidden="true"></span><div><h4>${escapeHtml(group.title)}</h4><p>${escapeHtml(group.copy)}</p></div></header><div class="game-setting-grid">${group.fields.map((field) => {
    const value = gameSettingValue(field, settings[field.key]);
    let control = '';
    if (field.type === 'boolean') control = `<input data-game-setting="${field.key}" type="checkbox" role="switch" ${value ? 'checked' : ''}>`;
    else if (field.type === 'select') control = `<select data-game-setting="${field.key}">${field.options.map((option) => `<option value="${escapeHtml(option)}" ${String(option) === String(value) ? 'selected' : ''}>${escapeHtml(option)}</option>`).join('')}</select>`;
    else control = `<div class="game-setting-number-control"><div class="game-setting-range-label"><span>MIN ${field.min}</span><span>MAX ${field.max}</span></div><input class="game-setting-slider" data-game-setting-range="${field.key}" type="range" value="${escapeHtml(value)}" min="${field.min}" max="${field.max}" step="${field.step}" aria-label="${escapeHtml(field.label)} 범위"><div class="game-setting-number-row"><input data-game-setting="${field.key}" type="number" value="${escapeHtml(value)}" min="${field.min}" max="${field.max}" step="${field.step}">${field.unit === 'minutes' ? '<span>분</span>' : ''}</div></div>`;
    return `<label class="game-setting-field ${field.type === 'boolean' ? 'is-boolean' : ''}"><div><strong>${escapeHtml(field.label)}</strong><code>${escapeHtml(field.key)}</code><small>${escapeHtml(field.desc)}</small></div>${control}</label>`;
  }).join('')}</div></section>`).join('');
  const count = GAME_SETTING_GROUPS.reduce((total, group) => total + group.fields.length, 0);
  $('#game-settings-count').textContent = count;
  const markCustom = () => {
    const custom = $('input[name="preset"][value="Custom"]');
    custom.checked = true;
    renderPresetDescription('Custom');
    markUnsaved('#view-world');
  };
  $$('[data-game-setting]', root).forEach((input) => {
    const syncSlider = () => {
      const slider = $(`[data-game-setting-range="${input.dataset.gameSetting}"]`, root);
      if (slider && input.value !== '') slider.value = input.value;
      markCustom();
    };
    input.addEventListener('change', syncSlider);
    input.addEventListener('input', syncSlider);
  });
  $$('[data-game-setting-range]', root).forEach((slider) => {
    slider.addEventListener('input', () => {
      const input = $(`[data-game-setting="${slider.dataset.gameSettingRange}"]`, root);
      if (input) input.value = slider.value;
      markCustom();
    });
  });
}
function collectGameSettings() {
  const settings = structuredClone(configCache?.game_settings || {});
  GAME_SETTING_GROUPS.flatMap((group) => group.fields).forEach((field) => {
    const input = $(`[data-game-setting="${field.key}"]`);
    if (!input) return;
    let value = field.type === 'boolean' ? input.checked : field.type === 'number' ? Number(input.value) : input.value;
    if (field.unit === 'minutes') value = Math.round(value * 60000000000);
    settings[field.key] = value;
  });
  return settings;
}
async function loadConfig() { fillSettings(await api('/api/config')); }
function collectSettings() {
  const form = $('#settings-form'); const data = structuredClone(configCache);
  data.server_name = form.elements.server_name.value.trim(); data.slot_count = Number(form.elements.slot_count.value); data.query_port = Number(form.elements.query_port.value); data.voice_chat_mode = form.elements.voice_chat_mode.value; data.enable_voice_chat = form.elements.enable_voice_chat.checked; data.enable_text_chat = form.elements.enable_text_chat.checked; data.tags = form.elements.tags.value.split(',').map((v) => v.trim()).filter(Boolean); data.roles = collectRoles(); data.game_settings_preset = $('input[name="preset"]:checked')?.value || 'Default'; data.game_settings = collectGameSettings(); return data;
}
async function saveConfig() { const result = await perform(() => api('/api/config', json('POST', collectSettings())), I18N.t('save_changes')); fillSettings(result); }
function renderRoles(roles) { const list = $('#roles-list'); list.innerHTML = ''; roles.forEach((role) => addRole(role)); }
function syncPasswordToggle(button) {
  const input = button.closest('.role-password-control').querySelector('[data-role="password"]');
  const visible = input.type === 'text';
  const label = I18N.t(visible ? 'hide_password' : 'show_password');
  button.classList.toggle('is-visible', visible);
  button.setAttribute('aria-label', label);
  button.title = label;
}
function refreshPasswordToggleLabels() { $$('.role-password-toggle').forEach(syncPasswordToggle); }
function addRole(role = {name:'New role',password:'change-this-password',can_kick_ban:false,can_access_inventories:false,can_edit_world:true,can_edit_base:false,can_extend_base:false,reserved_slots:0}) {
  if ($$('.role-row').length >= 8) return message('Maximum 8 roles', true);
  const row = $('#role-template').content.firstElementChild.cloneNode(true); row.querySelector('.role-index').textContent = String($$('.role-row').length + 1).padStart(2,'0');
  Object.entries(role).forEach(([key,value]) => { const input = row.querySelector(`[data-role="${key}"]`); if (input) input.type === 'checkbox' ? input.checked = !!value : input.value = value; });
  const passwordToggle = row.querySelector('.role-password-toggle');
  passwordToggle.addEventListener('click', () => {
    const input = row.querySelector('[data-role="password"]');
    input.type = input.type === 'password' ? 'text' : 'password';
    syncPasswordToggle(passwordToggle);
  });
  syncPasswordToggle(passwordToggle);
  row.querySelector('.remove-role').addEventListener('click', () => { if ($$('.role-row').length <= 1) return; row.remove(); $$('.role-row .role-index').forEach((el,index) => el.textContent = String(index+1).padStart(2,'0')); markUnsaved('#view-roles'); });
  $('#roles-list').append(row); I18N.apply(row);
}
function collectRoles() { return $$('.role-row').map((row) => { const role = {}; $$('[data-role]', row).forEach((input) => { role[input.dataset.role] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value.trim(); }); return role; }); }

async function loadSchedule() { const data = await api('/api/schedule'); const form = $('#schedule-form'); form.elements.enabled.checked = data.enabled; form.elements.time.value = data.time; form.elements.skip_when_players_online.checked = data.skip_when_players_online; $$('[name="weekday"]', form).forEach((input) => input.checked = data.weekdays.includes(Number(input.value))); }
async function saveSchedule() { const form = $('#schedule-form'); const body = {enabled:form.elements.enabled.checked,time:form.elements.time.value,skip_when_players_online:form.elements.skip_when_players_online.checked,weekdays:$$('[name="weekday"]:checked',form).map((el)=>Number(el.value))}; await perform(() => api('/api/schedule', json('POST',body)), I18N.t('save_schedule')); clearUnsavedGroup('schedule'); }

async function loadLogs() { try { const data = await api(`/api/logs?kind=${currentLog}`); const output = $('#log-output'); const nearBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 80; output.textContent = data.log; if ($('#auto-scroll').checked && nearBottom) output.scrollTop = output.scrollHeight; } catch (error) { console.warn(error); } }

async function loadBackups() {
  const [settings,data] = await Promise.all([api('/api/backups/settings'),api('/api/backups')]); const form = $('#backup-form'); form.elements.enabled.checked = settings.enabled; form.elements.times.value = settings.times.join(', '); form.elements.retention_count.value = settings.retention_count; form.elements.retention_days.value = settings.retention_days;
  const list = $('#backup-list'); list.innerHTML = ''; if (!data.backups.length) { list.innerHTML = `<div class="record-row"><strong>${escapeHtml(I18N.t('no_backups'))}</strong></div>`; return; }
  data.backups.forEach((backup) => { const row = document.createElement('div'); row.className = 'record-row'; row.innerHTML = `<strong>${escapeHtml(backup.name)}</strong><span>${bytes(backup.size)}</span><span>${formatDate(backup.modified_at)}</span><div class="actions"><button data-download>${escapeHtml(I18N.t('download'))}</button><button class="danger" data-restore>${escapeHtml(I18N.t('restore'))}</button></div>`; row.querySelector('[data-download]').onclick = () => location.href = `/api/backups/download?name=${encodeURIComponent(backup.name)}`; row.querySelector('[data-restore]').onclick = async () => { if (await confirmAction(I18N.t('restore'), backup.name)) await perform(() => api('/api/backups/restore', json('POST',{name:backup.name}))); }; list.append(row); });
}
async function saveBackupSettings() { const form = $('#backup-form'); const body = {enabled:form.elements.enabled.checked,times:form.elements.times.value.split(',').map(v=>v.trim()).filter(Boolean).slice(0,3),retention_count:Number(form.elements.retention_count.value),retention_days:Number(form.elements.retention_days.value)}; await perform(() => api('/api/backups/settings',json('POST',body)),I18N.t('save_policy')); clearUnsavedGroup('backup'); loadBackups(); }

function breadcrumbs(path) {
  const root = $('#breadcrumbs');
  root.innerHTML = '<button data-path="">/data</button>';
  let current = '';
  path.split('/').filter(Boolean).forEach((part) => {
    current += `${current ? '/' : ''}${part}`;
    root.insertAdjacentHTML('beforeend', `<span>/</span><button data-path="${escapeHtml(current)}">${escapeHtml(part)}</button>`);
  });
  $$('button', root).forEach((button) => button.onclick = () => loadFiles(button.dataset.path));
}
async function loadFiles(path = '') {
  const data = await api(`/api/files?path=${encodeURIComponent(path)}`);
  currentPath = data.path;
  breadcrumbs(currentPath);
  const list = $('#file-list');
  list.innerHTML = '';
  data.entries.forEach((entry) => {
    const row = document.createElement('div');
    row.className = 'file-row';
    const iconType = entry.type === 'folder' ? 'folder' : entry.editable ? 'editable' : 'file';
    row.innerHTML = `<div class="file-icon file-icon-${iconType}" aria-hidden="true"></div><button class="file-entry-name" type="button" title="${escapeHtml(entry.name)}">${escapeHtml(entry.name)}</button><span class="file-meta">${entry.type === 'folder' ? 'Folder' : bytes(entry.size)}</span><span class="file-meta">${formatDate(entry.modified_at)}</span><div class="file-actions"></div>`;
    const openEntry = () => {
      if (entry.type === 'folder') return loadFiles(entry.path);
      if (entry.editable) return openEditor(entry.path);
      location.href = `/api/files/download?path=${encodeURIComponent(entry.path)}`;
    };
    $('.file-entry-name', row).onclick = openEntry;
    const actions = $('.file-actions', row);
    if (entry.type === 'folder') {
      const open = document.createElement('button');
      open.textContent = 'Open';
      open.onclick = openEntry;
      actions.append(open);
    } else {
      if (entry.editable) {
        const edit = document.createElement('button');
        edit.textContent = I18N.t('edit');
        edit.disabled = data.locked;
        edit.onclick = openEntry;
        actions.append(edit);
      }
      const down = document.createElement('button');
      down.textContent = I18N.t('download');
      down.onclick = () => location.href = `/api/files/download?path=${encodeURIComponent(entry.path)}`;
      actions.append(down);
    }
    const remove = document.createElement('button');
    remove.className = 'danger';
    remove.textContent = I18N.t('delete');
    remove.disabled = data.locked;
    remove.onclick = async () => {
      if (await confirmAction(I18N.t('delete'), entry.name)) {
        await perform(() => api(`/api/files?path=${encodeURIComponent(entry.path)}`, {method:'DELETE'}));
        loadFiles(currentPath);
      }
    };
    actions.append(remove);
    list.append(row);
  });
}
async function openEditor(path) { const data=await api(`/api/files/text?path=${encodeURIComponent(path)}`); editingPath=path; editorOriginal=data.content; $('#file-editor-name').textContent=path; $('#file-editor').value=data.content; $('#file-editor').disabled=data.locked; $('#file-editor-save').disabled=data.locked; $('#file-dirty').classList.remove('visible'); $('#file-editor-dialog').showModal(); document.body.classList.add('modal-open'); }
function closeEditor(){ $('#file-editor-dialog').close(); document.body.classList.remove('modal-open'); }
async function saveEditor(){ await perform(()=>api(`/api/files/text?path=${encodeURIComponent(editingPath)}`,json('POST',{content:$('#file-editor').value})),I18N.t('save')); editorOriginal=$('#file-editor').value; closeEditor(); loadFiles(currentPath); }

function updateDiscordPreview(){ const name=$('#discord-form').elements.username.value.trim(); $('#discord-preview-name').textContent=name||'TechTim Enshrouded Server'; }
async function loadDiscord(){ const data=await api('/api/discord'); const form=$('#discord-form'); Object.entries(data.config).forEach(([key,value])=>{ const input=form.elements[key]; if(!input)return; input.type==='checkbox'?input.checked=!!value:input.value=key==='webhook_hint'?value:input.value; }); form.elements.webhook_url.placeholder=data.config.webhook_hint||'https://discord.com/api/webhooks/...'; updateDiscordPreview(); }
async function saveDiscord(){ const form=$('#discord-form'); const body={}; ['enabled','notify_server_start','notify_server_stop','notify_server_restart','notify_backup','notify_migration','notify_errors'].forEach((name)=>body[name]=form.elements[name].checked); body.webhook_url=form.elements.webhook_url.value.trim(); body.username=form.elements.username.value.trim(); await perform(()=>api('/api/discord',json('POST',body)),I18N.t('save_integration')); clearUnsavedGroup('discord'); form.elements.webhook_url.value=''; loadDiscord(); }

async function importMigration(file){ if(!file)return; if(serverRunning())return message(I18N.t('import_warning'),true); if(!await confirmAction(I18N.t('import_move'),file.name))return; const body=new FormData(); body.append('file',file); await perform(()=>api('/api/migration/import',{method:'POST',body}),I18N.t('import_move')); await Promise.all([loadConfig(),loadBackups(),loadFiles('')]); }

const INSTALL_STAGE_LABELS = {queued:'요청 접수',validate:'설정 확인',runtime:'런타임 준비',container:'컨테이너 구성',steamcmd:'SteamCMD · Wine 설치',verify:'접속 준비 확인',complete:'설치 완료',failed:'설치 실패'};
function renderInstallProgress(operation = {}, log = '') {
  const progress = Math.max(0, Math.min(100, Number(operation.progress) || 0));
  $('#install-progress-percent').textContent = `${progress}%`;
  $('#install-progress-bar').style.width = `${progress}%`;
  $('#install-progress-dialog .progress').setAttribute('aria-valuenow', progress);
  $('#install-progress-stage').textContent = INSTALL_STAGE_LABELS[operation.stage] || operation.name || '설치 준비';
  $('#install-progress-message').textContent = operation.message || '설치 작업을 준비하고 있습니다.';
  const output = $('#install-log-output');
  if (log) {
    const nearBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 80;
    output.textContent = log;
    if (nearBottom) output.scrollTop = output.scrollHeight;
  }
  $('#install-progress-dialog').classList.toggle('is-failed', operation.status === 'failed');
  $('#install-progress-dialog').classList.toggle('is-complete', operation.status === 'completed');
}
function openInstallConfirmation() {
  clearTimeout(installPollTimer);
  const dialog = $('#install-progress-dialog');
  dialog.classList.add('is-confirming');
  dialog.classList.remove('is-failed', 'is-complete');
  $('#install-progress-message').textContent = '새 서버 설치와 첫 기동을 시작합니다.';
  if (!dialog.open) dialog.showModal();
  document.body.classList.add('modal-open');
}
async function startInstallProgress() {
  const dialog = $('#install-progress-dialog');
  dialog.classList.remove('is-confirming', 'is-failed', 'is-complete');
  renderInstallProgress({status:'running', progress:0, stage:'queued', message:'설치 요청을 준비하고 있습니다.'}, '설치 로그를 기다리고 있습니다.');
  try {
    await api('/api/install', {method:'POST'});
    scheduleInstallPoll(200);
  } catch (error) {
    renderInstallProgress({status:'failed', progress:100, stage:'failed', message:error.message}, error.message);
  }
}
function closeInstallProgress() {
  clearTimeout(installPollTimer);
  if ($('#install-progress-dialog').open) $('#install-progress-dialog').close();
  document.body.classList.remove('modal-open');
}
function scheduleInstallPoll(delay = 1000) { clearTimeout(installPollTimer); installPollTimer = setTimeout(pollInstallProgress, delay); }
async function pollInstallProgress() {
  try {
    const [status, installLogs, serverLogs] = await Promise.all([api('/api/status'), api('/api/logs?kind=install'), api('/api/logs?kind=server')]);
    statusCache = status;
    const operation = status.operation || {};
    const sections = [];
    if (installLogs.log && !installLogs.log.includes('아직 기록된 로그가 없습니다.')) sections.push(`[패널 설치]\n${installLogs.log.trim()}`);
    if (serverLogs.log && !serverLogs.log.includes('아직 기록된 로그가 없습니다.')) sections.push(`[서버 설치]\n${serverLogs.log.trim()}`);
    renderInstallProgress(operation, sections.join('\n\n') || '설치 로그를 기다리고 있습니다.');
    if (operation.status === 'running' || operation.status === 'queued') scheduleInstallPoll(1000);
    else refreshStatus();
  } catch (error) {
    renderInstallProgress({status:'running', progress:Number($('#install-progress-percent').textContent.replace('%','')) || 0, stage:'verify', message:'패널 연결을 다시 확인하고 있습니다.'}, error.message);
    scheduleInstallPoll(1400);
  }
}

function updateStageIndex(stage) { return Math.max(0, ['pull','replace','verify','complete'].indexOf(stage)); }
function renderUpdate(data) {
  const state = data.status || 'idle'; const active = UPDATE_ACTIVE.has(state); const failed = state === 'failed'; const completed = state === 'completed';
  const labels = {idle:'업데이트 준비',queued:'이미지 확인 중',running:'업데이트 진행 중',pulling:'이미지 다운로드 중',downloading:'이미지 다운로드 중',preparing:'교체 준비 중',replacing:'패널 교체 중',verifying:'재연결 확인 중',reconnecting:'패널 재연결 중',completed:'업데이트 완료',failed:'업데이트 실패'};
  const fallback = {queued:5,pulling:12,downloading:12,preparing:30,replacing:48,verifying:78,reconnecting:88,completed:100,failed:100};
  const progress = Math.max(0, Math.min(100, Number(data.progress ?? fallback[state] ?? 0)));
  updateRenderedProgress = active ? Math.max(updateRenderedProgress, progress) : progress;
  const availability = data.update_available;
  const availabilityLabel = availability === true ? '새 업데이트 사용 가능' : availability === false ? '최신 버전 사용 중' : data.checked === false ? '업데이트 확인 필요' : '업데이트 상태 확인 중';
  $('#update-status').textContent = data.current_version || data.version || statusCache?.panel_version || '1.0.8';
  $('#update-state').textContent = active || failed || completed ? (labels[state] || state) : availabilityLabel;
  $('#update-progress-label').textContent = active || failed || completed ? (labels[state] || '업데이트 상태') : availabilityLabel;
  $('#update-progress-percent').textContent = `${Math.round(updateRenderedProgress)}%`;
  $('#update-progress').style.width = `${updateRenderedProgress}%`;
  $('#panel-update-progress .progress').setAttribute('aria-valuenow', String(Math.round(updateRenderedProgress)));
  $('#update-message').textContent = data.message || '업데이트 상태를 확인하고 있습니다.';
  $('#panel-update-progress').classList.toggle('is-complete', completed);
  $('#panel-update-progress').classList.toggle('is-failed', failed);
  $('#panel-update-progress').classList.toggle('is-current', !active && availability === false);
  $('#panel-update-progress').classList.toggle('is-available', !active && availability === true);
  const stage = data.stage === 'rollback' ? 'verify' : (data.stage || (completed ? 'complete' : 'pull'));
  const stageIndex = updateStageIndex(stage);
  $$('.panel-update-steps li').forEach((item,index)=>{item.classList.toggle('done',completed||index<stageIndex);item.classList.toggle('active',!completed&&index===stageIndex);});
  $('#apply-update').disabled = active || (!failed && availability === false);
  $('#apply-update').textContent = active ? '업데이트 중' : failed ? '다시 시도' : availability === false ? '최신 버전' : I18N.t('apply_update');
  return active;
}
function scheduleUpdatePoll(delay=1200){ clearTimeout(updatePollTimer); updatePollTimer=setTimeout(pollUpdate,delay); }
async function loadUpdate(check=false){ const data=await api(`/api/panel-update${check?'?check=true':''}`); if(renderUpdate(data))scheduleUpdatePoll(); return data; }
async function pollUpdate(){ try{await loadUpdate();}catch(_error){renderUpdate({status:'reconnecting',stage:'verify',progress:Math.max(updateRenderedProgress,88),version:statusCache?.panel_version,message:'패널 교체 중 연결이 잠시 중단되었습니다. 자동으로 다시 연결하고 있습니다.'});scheduleUpdatePoll(1600);} }
async function openUpdateDialog(){ const dialog=$('#panel-update-dialog'); dialog.showModal(); document.body.classList.add('modal-open'); renderUpdate({status:'idle',progress:0,version:statusCache?.panel_version,message:'최신 패널 이미지가 있는지 확인하고 있습니다.'}); try{await loadUpdate(true);}catch(error){renderUpdate({status:'idle',checked:false,progress:0,version:statusCache?.panel_version,message:error.message});} }
function closeUpdateDialog(){ clearTimeout(updatePollTimer); if($('#panel-update-dialog').open)$('#panel-update-dialog').close(); document.body.classList.remove('modal-open'); }

function requestText(title){ const dialog=$('#text-input-dialog'); $('#text-input-title').textContent=title; $('#text-input-value').value=''; dialog.showModal(); document.body.classList.add('modal-open'); requestAnimationFrame(()=>$('#text-input-value').focus()); return new Promise((resolve)=>{textInputResolver=resolve;}); }
function closeTextInput(value=null){ if($('#text-input-dialog').open)$('#text-input-dialog').close(); document.body.classList.remove('modal-open'); if(textInputResolver){textInputResolver(value);textInputResolver=null;} }

function confirmAction(title, copy){ const dialog=$('#confirm-dialog'); $('#confirm-title').textContent=title; $('#confirm-copy').textContent=copy; dialog.showModal(); document.body.classList.add('modal-open'); return new Promise((resolve)=>{confirmResolver=resolve;}); }
function closeConfirm(value){ if($('#confirm-dialog').open)$('#confirm-dialog').close(); document.body.classList.remove('modal-open'); if(confirmResolver){confirmResolver(value);confirmResolver=null;} }

function bindEvents(){
  bindUnsavedReminders();
  $$('.nav-item').forEach((button)=>button.onclick=()=>showView(button.dataset.view)); $$('[data-view-target]').forEach((button)=>button.onclick=()=>showView(button.dataset.viewTarget)); $$('[data-action]').forEach((button)=>button.onclick=()=>runAction(button.dataset.action)); $$('.save-config').forEach((button)=>button.onclick=saveConfig); $('#add-role').onclick=()=>{addRole();markUnsaved('#view-roles');}; $('#save-schedule').onclick=saveSchedule;
  $$('.terminal-tabs button').forEach((button)=>button.onclick=()=>{currentLog=button.dataset.log;$$('.terminal-tabs button').forEach(b=>b.classList.toggle('active',b===button));loadLogs();}); $('#export-log').onclick=()=>location.href='/api/logs/export';
  $('#backup-now').onclick=async()=>{await perform(()=>api('/api/backups',{method:'POST'}),I18N.t('backup_now'));setTimeout(loadBackups,900);}; $('#backup-settings-save').onclick=(event)=>{event.preventDefault();saveBackupSettings();};
  $('#file-parent').onclick=()=>loadFiles(currentPath.split('/').slice(0,-1).join('/')); $('#file-refresh').onclick=()=>loadFiles(currentPath); $('#new-folder').onclick=async()=>{const name=(await requestText(I18N.t('new_folder')))?.trim();if(name){await perform(()=>api('/api/files/directory',json('POST',{path:currentPath,name})));loadFiles(currentPath);}}; $('#file-upload').onchange=async(event)=>{const file=event.target.files[0];if(!file)return;const body=new FormData();body.append('file',file);body.append('path',currentPath);await perform(()=>api('/api/files/upload',{method:'POST',body}));event.target.value='';loadFiles(currentPath);};
  $('#file-editor').oninput=()=>$('#file-dirty').classList.toggle('visible',$('#file-editor').value!==editorOriginal); $('#file-editor-save').onclick=saveEditor; $('#file-editor-cancel').onclick=closeEditor; $('#file-editor-dialog .dialog-head button').onclick=closeEditor; document.addEventListener('keydown',(event)=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'&&$('#file-editor-dialog').open){event.preventDefault();saveEditor();}});
  $('#discord-save').onclick=saveDiscord; $('#discord-test').onclick=()=>perform(()=>api('/api/discord/test',{method:'POST'}),I18N.t('test_send')); $('#migration-export').onclick=()=>location.href='/api/migration/export'; $('#migration-import').onchange=(event)=>{importMigration(event.target.files[0]);event.target.value='';};
  $$('[name="preset"]').forEach(input=>input.onchange=()=>applyPreset(input.value)); $('#discord-form').elements.username.oninput=updateDiscordPreview;
  $('#panel-update-button').onclick=openUpdateDialog; $('#close-panel-update').onclick=closeUpdateDialog; $('#cancel-panel-update').onclick=closeUpdateDialog; $('#apply-update').onclick=async()=>{updateRenderedProgress=3;renderUpdate({status:'queued',stage:'pull',progress:3,version:statusCache?.panel_version,message:'업데이트 요청을 전달하고 있습니다.'});scheduleUpdatePoll(500);try{await api('/api/panel-update',{method:'POST'});}catch(error){renderUpdate({status:'reconnecting',stage:'verify',progress:Math.max(updateRenderedProgress,30),version:statusCache?.panel_version,message:`업데이트 상태를 다시 확인하고 있습니다. ${error.message}`});}scheduleUpdatePoll(700);}; $('#logout-button').onclick=async()=>{await api('/api/auth/logout',{method:'POST'});location.href='/login';};
  $('#text-input-close').onclick=()=>closeTextInput(); $('#text-input-cancel').onclick=()=>closeTextInput(); $('#text-input-form').onsubmit=(event)=>{event.preventDefault();if($('#text-input-value').reportValidity())closeTextInput($('#text-input-value').value);};
  $('#confirm-close').onclick=()=>closeConfirm(false); $('#confirm-cancel').onclick=()=>closeConfirm(false); $('#confirm-accept').onclick=()=>closeConfirm(true);
  $('#running-lock-close').onclick=()=>{if($('#running-lock-dialog').open)$('#running-lock-dialog').close();document.body.classList.remove('modal-open');};
  $('#running-lock-dialog').addEventListener('close',()=>document.body.classList.remove('modal-open'));
  $('#install-progress-cancel').onclick=closeInstallProgress; $('#install-progress-start').onclick=startInstallProgress; $('#install-progress-close').onclick=closeInstallProgress;
  $('#install-progress-dialog').addEventListener('close',()=>{clearTimeout(installPollTimer);document.body.classList.remove('modal-open');});
  $('#notice-dialog-close').onclick=closeNotice;
  $('#notice-dialog').addEventListener('close',()=>{clearTimeout(noticeTimer);document.body.classList.remove('modal-open');});
  window.addEventListener('resize',renderCharts); window.addEventListener('languagechange',()=>{const active=$('.nav-item.active');$('#view-title').textContent=$('span',active)?.textContent||I18N.t('home');renderPresetDescription($('input[name="preset"]:checked')?.value||'Default');refreshPasswordToggleLabels();refreshUnsavedMessages();refreshStatus();});
}
function initWeekdays(){ const labels={ko:['월','화','수','목','금','토','일'],en:['M','T','W','T','F','S','S'],zh:['一','二','三','四','五','六','日'],ja:['月','火','水','木','金','土','日']}; $('#weekday-options').innerHTML=(labels[I18N.current()]||labels.ko).map((label,index)=>`<label><input type="checkbox" name="weekday" value="${index}"><span>${label}</span></label>`).join(''); }
async function init(){ initWeekdays(); bindEvents(); await Promise.all([loadConfig(),refreshStatus(),refreshResources(),loadSchedule()]); const hash=location.hash.slice(1); if(hash&&$(`#view-${hash}`))showView(hash); setInterval(refreshStatus,3000); setInterval(refreshResources,1000); setInterval(()=>{if($('#view-logs').classList.contains('active'))loadLogs();},1500); requestAnimationFrame(function animate(){renderCharts();requestAnimationFrame(animate);}); }
init().catch((error)=>message(error.message,true));
