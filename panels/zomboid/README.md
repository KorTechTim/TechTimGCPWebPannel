# TechTim Project Zomboid GCP Panel

Project Zomboid Dedicated Server를 GCP Linux VM에서 설치하고 운영하는 웹 패널입니다. 팰월드 패널의 운영 중심 레이아웃과 TechTim Windows용 T2Zomboid의 설정 체계를 결합했습니다.

## 주요 기능

- SteamCMD App `380870` 공개 Build 42 또는 `legacy41` 설치·검증
- 비루트 `zomboid` 사용자로 게임 프로세스 실행
- `servertest.ini`, `servertest_SandboxVars.lua`, 스폰 파일 관리
- Workshop App `108600` 항목, 내부 Mod ID, 맵 순서 관리
- 서버 시작·정상 저장 종료·재시작과 실시간 로그
- 월드·설정·DB ZIP 백업, 복원, 보관 정책
- 중지 상태 전용 GUI 파일 탐색기와 원본 설정 편집기
- GCP VM CPU, 메모리, 디스크, 네트워크 `/proc` 모니터링
- 디스크 80% 도달 시 75% 목표 자동 정리, 최근 백업 보호
- 한국 시간 예약 재시작과 웹패널 자체 업데이트·롤백

## 데이터 구조

```text
/opt/techtim/zomboid/data/
├─ server/                         # SteamCMD 전용 서버
├─ Zomboid/
│  ├─ Server/servertest.ini
│  ├─ Server/servertest_SandboxVars.lua
│  ├─ Saves/Multiplayer/servertest/
│  └─ db/servertest.db
├─ backups/
├─ exports/
└─ logs/
```

## 로컬 검증

```bash
python -m unittest discover -s panels/zomboid/tests -v
bash -n zomboid/zomboid-webui-install.sh
bash -n zomboid/gcp-create.sh
bash -n panels/zomboid/runtime/entrypoint.sh
node --check panels/zomboid/app/static/app.js
```

초기 패널 로그인은 `admin / admin`이며 첫 로그인에서 4자 이상의 새 비밀번호로 변경합니다. 게임 관리자 비밀번호는 기본 설정 화면에서 별도로 등록합니다.
