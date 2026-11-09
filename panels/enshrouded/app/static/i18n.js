(function () {
  const dictionaries = {
    ko: {
      server_summary: '서버 간단 정보', uptime: '업타임', world_preset: '월드 난이도', network: '네트워크', receive: '수신', transmit: '송신',
      language: '한국어', login_title: '관리자 성화에 입장', login_copy: 'TechTim(T2) 인슈어라오디드 구글클라우드 구동기 관리페이지',
      username: '관리자 계정', password: '비밀번호', login: '로그인', initial_title: '첫 관리자 비밀번호 설정',
      initial_copy: '기본 비밀번호 admin 대신 사용할 새 패널 비밀번호를 입력하세요.', new_password: '새 비밀번호', confirm_password: '새 비밀번호 확인', password_mismatch: '입력한 비밀번호가 서로 일치하지 않습니다.', save_password: '비밀번호 저장',
      home: '홈', logs: '관리로그 및 터미널', settings: '서버 기본 설정', roles: '서버 역활 및 접속비밀번호', world: '월드 설정', schedule: '예약 작업',
      files: '서버 폴더 탐색기', discord: '디스코드 연동', backups: '백업 · 복원', migration: '이사하기', update: '패널 업데이트', logout: '로그아웃',
      panel_name: 'ENSHROUDED GCP PANEL', realm_control: 'EMBER REALM CONTROL', hero_title: '불꽃이 꺼지지 않도록',
      hero_copy: '설치부터 백업, 역할 권한, 새 Google Cloud 계정으로의 이사까지 하나의 패널에서 관리합니다.',
      install: '설치 및 시작', start: '서버 시작', stop: '서버 중지', restart: '재시작', status: '서버 상태', players: '접속 인원', version: '패널 버전', runtime: '실행 환경',
      cpu: 'CPU', memory: '메모리', disk: '디스크', ten_minutes: '최근 10분', now: '현재', overview: '서버 개요', ready: '온라인', running: '시작 중', stopped: '중지됨', missing: '미설치',
      log_title: '실시간 작업 로그', all: '전체', server: '서버', install_log: '설치', control: '작업', export_log: '로그 내보내기', auto_scroll: '자동 스크롤',
      basic_settings: '기본 서버 설정', server_name: '서버 이름', max_players: '최대 접속 인원', query_port: '조회 포트', voice_mode: '음성 채팅 범위', voice_chat: '음성 채팅 사용', text_chat: '텍스트 채팅 사용', tags: '서버 태그', save_changes: '변경사항 저장',
      roles_title: '역할별 접속 권한', roles_copy: '입력한 비밀번호에 따라 플레이어 권한이 결정됩니다. 역할별 비밀번호는 반드시 서로 달라야 합니다.', role_name: '역할 이름', role_password: '접속 비밀번호', reserved_slots: '예약 슬롯', kick_ban: '추방 · 차단', inventories: '보관함 사용', edit_world: '월드 활동', edit_base: '기지 편집', extend_base: '불꽃 제단 확장', add_role: '역할 추가', remove: '삭제',
      world_title: '월드 난이도', world_copy: '공식 프리셋을 선택합니다. 세부 설정은 서버 폴더의 enshrouded_server.json에서 직접 편집할 수 있습니다.', default: '기본', relaxed: '여유롭게', hard: '어려움', survival: '생존', custom: '사용자 지정',
      schedule_title: '예약 재시작', enabled: '사용', restart_time: '재시작 시간', weekdays: '실행 요일', skip_players: '접속자가 있으면 건너뛰기', save_schedule: '예약 저장',
      files_title: '서버 폴더 탐색기', parent: '상위 폴더', new_folder: '새 폴더', upload: '업로드', refresh: '새로고침', download: '받기', delete: '삭제', edit: '편집', file_locked: '서버 실행 중에는 파일 변경이 잠깁니다.',
      discord_title: 'Discord 운영 알림', webhook: '웹훅 URL', display_name: '표시 이름', test_send: '테스트 전송', save_integration: '연동 설정 저장', integration_use: '연동 사용',
      backup_title: '백업 · 복원', backup_now: '지금 백업', backup_times: '예약 시간 (최대 3개)', retention_count: '최대 보관 개수', retention_days: '최대 보관 기간', save_policy: '보관 정책 저장', restore: '복원', no_backups: '아직 생성된 백업이 없습니다.',
      migration_title: 'Google Cloud 계정 이사', migration_copy: '월드 세이브와 서버·패널 설정을 하나의 ZIP으로 옮깁니다. 역할 비밀번호와 Discord 웹훅이 포함되므로 파일을 안전하게 보관하세요.', export_move: '이사 파일 내보내기', import_move: '이사 파일 가져오기', export_copy: '현재 서버에서 ZIP을 내려받습니다.', import_copy: '새 계정의 패널에서 ZIP을 올리면 즉시 복원됩니다.', import_warning: '가져오기는 서버를 중지한 상태에서만 가능하며 현재 데이터의 안전 백업을 먼저 생성합니다.',
      update_title: '패널 업데이트', update_copy: 'TechTim의 최신 Enshrouded 패널 이미지를 확인하고 안전하게 교체합니다.', check_update: '업데이트 확인', apply_update: '업데이트 적용',
      save: '저장', cancel: '취소', confirm: '확인', close: '닫기', dirty: '저장하지 않은 변경사항이 있습니다.', loading: '불꽃을 깨우는 중입니다…',
    },
    en: {
      server_summary: 'Server Snapshot', uptime: 'Uptime', world_preset: 'World Difficulty', network: 'Network', receive: 'Receive', transmit: 'Transmit',
      language: 'English', login_title: 'Enter the Admin Flame', login_copy: 'Safely manage your Enshrouded server on Google Cloud.', username: 'Administrator', password: 'Password', login: 'Sign in', initial_title: 'Set the first admin password', initial_copy: 'Choose a new panel password to replace the default admin password.', new_password: 'New password', confirm_password: 'Confirm new password', password_mismatch: 'The passwords do not match.', save_password: 'Save password',
      home: 'Home', logs: 'Operations Log', settings: 'Server Settings', roles: 'Roles & Passwords', world: 'World Settings', schedule: 'Scheduled Tasks', files: 'Server Files', discord: 'Discord', backups: 'Backup & Restore', migration: 'Move Server', update: 'Panel Update', logout: 'Sign out', panel_name: 'ENSHROUDED GCP PANEL', realm_control: 'EMBER REALM CONTROL', hero_title: 'Keep the flame alive', hero_copy: 'Manage installation, backups, access roles, and migration to a new Google Cloud account from one panel.', install: 'Install & Start', start: 'Start Server', stop: 'Stop Server', restart: 'Restart', status: 'Server Status', players: 'Players', version: 'Panel Version', runtime: 'Runtime', cpu: 'CPU', memory: 'Memory', disk: 'Disk', ten_minutes: 'Last 10 minutes', now: 'Now', overview: 'Server Overview', ready: 'Online', running: 'Starting', stopped: 'Stopped', missing: 'Not installed', log_title: 'Live Operations Log', all: 'All', server: 'Server', install_log: 'Install', control: 'Tasks', export_log: 'Export Logs', auto_scroll: 'Auto-scroll', basic_settings: 'Basic Server Settings', server_name: 'Server Name', max_players: 'Maximum Players', query_port: 'Query Port', voice_mode: 'Voice Chat Mode', voice_chat: 'Enable Voice Chat', text_chat: 'Enable Text Chat', tags: 'Server Tags', save_changes: 'Save Changes', roles_title: 'Role-based Access', roles_copy: 'The password used to join determines player permissions. Every role needs a unique password.', role_name: 'Role Name', role_password: 'Join Password', reserved_slots: 'Reserved Slots', kick_ban: 'Kick & Ban', inventories: 'Use Inventories', edit_world: 'World Access', edit_base: 'Edit Base', extend_base: 'Extend Flame Altars', add_role: 'Add Role', remove: 'Remove', world_title: 'World Difficulty', world_copy: 'Choose an official preset. Fine-grained settings remain editable in enshrouded_server.json.', default: 'Default', relaxed: 'Relaxed', hard: 'Hard', survival: 'Survival', custom: 'Custom', schedule_title: 'Scheduled Restart', enabled: 'Enabled', restart_time: 'Restart Time', weekdays: 'Weekdays', skip_players: 'Skip while players are online', save_schedule: 'Save Schedule', files_title: 'Server File Explorer', parent: 'Parent', new_folder: 'New Folder', upload: 'Upload', refresh: 'Refresh', download: 'Download', delete: 'Delete', edit: 'Edit', file_locked: 'File changes are locked while the server is running.', discord_title: 'Discord Operations Alerts', webhook: 'Webhook URL', display_name: 'Display Name', test_send: 'Send Test', save_integration: 'Save Integration', integration_use: 'Enable Integration', backup_title: 'Backup & Restore', backup_now: 'Back Up Now', backup_times: 'Schedule Times (up to 3)', retention_count: 'Maximum Backups', retention_days: 'Maximum Age', save_policy: 'Save Policy', restore: 'Restore', no_backups: 'No backups have been created yet.', migration_title: 'Move Google Cloud Account', migration_copy: 'Move world saves and server/panel settings in one ZIP. It contains role passwords and the Discord webhook, so store it securely.', export_move: 'Export Move File', import_move: 'Import Move File', export_copy: 'Download a ZIP from this server.', import_copy: 'Upload the ZIP on the new account to restore immediately.', import_warning: 'Import requires a stopped server and creates a safety backup of current data first.', update_title: 'Panel Update', update_copy: 'Check and safely install the latest TechTim Enshrouded panel image.', check_update: 'Check Update', apply_update: 'Apply Update', save: 'Save', cancel: 'Cancel', confirm: 'Confirm', close: 'Close', dirty: 'You have unsaved changes.', loading: 'Awakening the flame…',
    },
    zh: {
      server_summary: '服务器概览', uptime: '运行时间', world_preset: '世界难度', network: '网络', receive: '接收', transmit: '发送',
      confirm_password: '确认新密码', password_mismatch: '两次输入的密码不一致。',
      language: '中文', login_title: '进入管理员圣火', login_copy: '安全管理 Google Cloud 上的 Enshrouded 服务器。', username: '管理员账户', password: '密码', login: '登录', initial_title: '设置初始管理员密码', initial_copy: '请设置新密码以替换默认 admin 密码。', new_password: '新密码', save_password: '保存密码', home: '主页', logs: '管理日志', settings: '服务器设置', roles: '角色与密码', world: '世界设置', schedule: '计划任务', files: '服务器文件', discord: 'Discord 联动', backups: '备份与恢复', migration: '迁移服务器', update: '面板更新', logout: '退出', panel_name: 'ENSHROUDED GCP PANEL', realm_control: 'EMBER REALM CONTROL', hero_title: '让火焰永不熄灭', hero_copy: '在一个面板中管理安装、备份、角色权限以及迁移到新的 Google Cloud 账户。', install: '安装并启动', start: '启动服务器', stop: '停止服务器', restart: '重新启动', status: '服务器状态', players: '在线人数', version: '面板版本', runtime: '运行环境', cpu: 'CPU', memory: '内存', disk: '磁盘', ten_minutes: '最近10分钟', now: '现在', overview: '服务器概览', ready: '在线', running: '启动中', stopped: '已停止', missing: '未安装', log_title: '实时工作日志', all: '全部', server: '服务器', install_log: '安装', control: '任务', export_log: '导出日志', auto_scroll: '自动滚动', basic_settings: '基本服务器设置', server_name: '服务器名称', max_players: '最大玩家数', query_port: '查询端口', voice_mode: '语音聊天范围', voice_chat: '启用语音聊天', text_chat: '启用文字聊天', tags: '服务器标签', save_changes: '保存更改', roles_title: '按角色管理权限', roles_copy: '玩家输入的密码决定权限。每个角色必须使用不同密码。', role_name: '角色名称', role_password: '加入密码', reserved_slots: '预留名额', kick_ban: '踢出与封禁', inventories: '使用仓库', edit_world: '世界活动', edit_base: '编辑基地', extend_base: '扩展火焰祭坛', add_role: '添加角色', remove: '删除', world_title: '世界难度', world_copy: '选择官方预设。详细设置可在 enshrouded_server.json 中编辑。', default: '默认', relaxed: '轻松', hard: '困难', survival: '生存', custom: '自定义', schedule_title: '计划重启', enabled: '启用', restart_time: '重启时间', weekdays: '星期', skip_players: '有玩家在线时跳过', save_schedule: '保存计划', files_title: '服务器文件管理器', parent: '上级文件夹', new_folder: '新建文件夹', upload: '上传', refresh: '刷新', download: '下载', delete: '删除', edit: '编辑', file_locked: '服务器运行时文件修改会被锁定。', discord_title: 'Discord 运营通知', webhook: 'Webhook URL', display_name: '显示名称', test_send: '发送测试', save_integration: '保存联动设置', integration_use: '启用联动', backup_title: '备份与恢复', backup_now: '立即备份', backup_times: '计划时间（最多3个）', retention_count: '最大保留数量', retention_days: '最大保留天数', save_policy: '保存策略', restore: '恢复', no_backups: '尚未创建备份。', migration_title: '迁移 Google Cloud 账户', migration_copy: '将世界存档及服务器、面板设置打包为一个 ZIP。文件包含角色密码和 Discord Webhook，请妥善保存。', export_move: '导出迁移文件', import_move: '导入迁移文件', export_copy: '从当前服务器下载 ZIP。', import_copy: '在新账户面板上传 ZIP 即可恢复。', import_warning: '导入只能在服务器停止时进行，并会先备份当前数据。', update_title: '面板更新', update_copy: '检查并安全安装最新 TechTim Enshrouded 面板。', check_update: '检查更新', apply_update: '应用更新', save: '保存', cancel: '取消', confirm: '确认', close: '关闭', dirty: '存在未保存的更改。', loading: '正在唤醒火焰…',
    },
    ja: {
      server_summary: 'サーバー概要', uptime: '稼働時間', world_preset: 'ワールド難易度', network: 'ネットワーク', receive: '受信', transmit: '送信',
      confirm_password: '新しいパスワードの確認', password_mismatch: '入力したパスワードが一致しません。',
      language: '日本語', login_title: '管理者の炎へ入る', login_copy: 'Google Cloud の Enshrouded サーバーを安全に管理します。', username: '管理者アカウント', password: 'パスワード', login: 'ログイン', initial_title: '初期管理者パスワード設定', initial_copy: '既定の admin パスワードに代わる新しいパスワードを設定してください。', new_password: '新しいパスワード', save_password: 'パスワードを保存', home: 'ホーム', logs: '管理ログ', settings: 'サーバー設定', roles: 'ロール・パスワード', world: 'ワールド設定', schedule: '予約タスク', files: 'サーバーファイル', discord: 'Discord連携', backups: 'バックアップ・復元', migration: '引っ越し', update: 'パネル更新', logout: 'ログアウト', panel_name: 'ENSHROUDED GCP PANEL', realm_control: 'EMBER REALM CONTROL', hero_title: '炎を絶やさないために', hero_copy: 'インストール、バックアップ、ロール権限、新しい Google Cloud アカウントへの移行を一つのパネルで管理します。', install: 'インストールして開始', start: 'サーバー開始', stop: 'サーバー停止', restart: '再起動', status: 'サーバー状態', players: '接続人数', version: 'パネルバージョン', runtime: '実行環境', cpu: 'CPU', memory: 'メモリ', disk: 'ディスク', ten_minutes: '直近10分', now: '現在', overview: 'サーバー概要', ready: 'オンライン', running: '起動中', stopped: '停止中', missing: '未インストール', log_title: 'リアルタイム作業ログ', all: 'すべて', server: 'サーバー', install_log: 'インストール', control: '作業', export_log: 'ログを書き出す', auto_scroll: '自動スクロール', basic_settings: '基本サーバー設定', server_name: 'サーバー名', max_players: '最大接続人数', query_port: 'クエリポート', voice_mode: 'ボイスチャット範囲', voice_chat: 'ボイスチャットを使用', text_chat: 'テキストチャットを使用', tags: 'サーバータグ', save_changes: '変更を保存', roles_title: 'ロール別アクセス権限', roles_copy: '参加時のパスワードで権限が決まります。ロールごとに異なるパスワードが必要です。', role_name: 'ロール名', role_password: '参加パスワード', reserved_slots: '予約スロット', kick_ban: 'キック・BAN', inventories: '保管箱の利用', edit_world: 'ワールド活動', edit_base: '拠点編集', extend_base: '炎の祭壇を拡張', add_role: 'ロール追加', remove: '削除', world_title: 'ワールド難易度', world_copy: '公式プリセットを選択します。詳細設定は enshrouded_server.json で編集できます。', default: 'デフォルト', relaxed: 'リラックス', hard: 'ハード', survival: 'サバイバル', custom: 'カスタム', schedule_title: '予約再起動', enabled: '使用', restart_time: '再起動時刻', weekdays: '曜日', skip_players: 'プレイヤー接続中はスキップ', save_schedule: '予約を保存', files_title: 'サーバーファイル管理', parent: '上のフォルダー', new_folder: '新規フォルダー', upload: 'アップロード', refresh: '更新', download: 'ダウンロード', delete: '削除', edit: '編集', file_locked: 'サーバー稼働中はファイル変更がロックされます。', discord_title: 'Discord運用通知', webhook: 'Webhook URL', display_name: '表示名', test_send: 'テスト送信', save_integration: '連携設定を保存', integration_use: '連携を使用', backup_title: 'バックアップ・復元', backup_now: '今すぐバックアップ', backup_times: '予約時刻（最大3件）', retention_count: '最大保管数', retention_days: '最大保管期間', save_policy: '保管ポリシーを保存', restore: '復元', no_backups: '作成済みのバックアップはありません。', migration_title: 'Google Cloud アカウント引っ越し', migration_copy: 'ワールドセーブとサーバー・パネル設定を一つのZIPで移動します。ロールのパスワードとDiscord Webhookを含むため安全に保管してください。', export_move: '引っ越しファイルを書き出す', import_move: '引っ越しファイルを読み込む', export_copy: '現在のサーバーからZIPをダウンロードします。', import_copy: '新しいアカウントのパネルでZIPをアップロードすると復元されます。', import_warning: '読み込みはサーバー停止中のみ可能で、現在データの安全バックアップを先に作成します。', update_title: 'パネル更新', update_copy: '最新のTechTim Enshroudedパネルを確認し安全に置き換えます。', check_update: '更新を確認', apply_update: '更新を適用', save: '保存', cancel: 'キャンセル', confirm: '確認', close: '閉じる', dirty: '未保存の変更があります。', loading: '炎を目覚めさせています…',
    },
  };

  const interfaceMessages = {
    ko: {
      save_reminder: '변경사항이 있습니다. 저장을 눌러주세요.',
      running_lock_title: '설정 변경 제한',
      running_lock_copy: '서버가 운영 중에는 설정할 수 없습니다.',
      notice_title: '안내',
      error_title: '확인이 필요합니다.',
    },
    en: {
      save_reminder: 'Changes are waiting. Please save them.',
      running_lock_title: 'Settings locked',
      running_lock_copy: 'Settings cannot be changed while the server is running.',
      notice_title: 'Notice',
      error_title: 'Attention required',
    },
    zh: {
      save_reminder: '有未保存的更改，请点击保存。',
      running_lock_title: '设置已锁定',
      running_lock_copy: '服务器运行时无法更改设置。',
      notice_title: '提示',
      error_title: '需要确认',
    },
    ja: {
      save_reminder: '変更があります。保存してください。',
      running_lock_title: '設定を変更できません',
      running_lock_copy: 'サーバー稼働中は設定を変更できません。',
      notice_title: 'お知らせ',
      error_title: '確認が必要です',
    },
  };
  Object.entries(interfaceMessages).forEach(([language, messages]) => Object.assign(dictionaries[language], messages));

  const credentialLabels = {
    ko: '초기 계정 패스워드는 admin / admin 입니다.',
    en: 'Initial account / password: admin / admin',
    zh: '初始账号 / 密码：admin / admin',
    ja: '初期アカウント / パスワード: admin / admin',
  };
  Object.entries(credentialLabels).forEach(([language, label]) => { dictionaries[language].initial_credentials = label; });

  const supported = Object.keys(dictionaries);
  function current() { const saved = localStorage.getItem('techtim-language'); return supported.includes(saved) ? saved : 'ko'; }
  function t(key) { return dictionaries[current()][key] || dictionaries.ko[key] || key; }
  function apply(root = document) {
    document.documentElement.lang = current();
    root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    root.querySelectorAll('[data-language-select]').forEach((select) => { select.value = current(); });
  }
  function setLanguage(language) { if (supported.includes(language)) localStorage.setItem('techtim-language', language); apply(); window.dispatchEvent(new CustomEvent('languagechange', {detail: language})); }
  window.I18N = {dictionaries, current, t, apply, setLanguage};
  document.addEventListener('DOMContentLoaded', () => { apply(); document.querySelectorAll('[data-language-select]').forEach((el) => el.addEventListener('change', () => setLanguage(el.value))); });
}());
