# TechTim Valheim Server Panel

발헤임 정식 전용 서버를 GCP VM에서 설치하고 관리하는 한국어 웹패널입니다. 기존 TechTim 패널처럼 FastAPI와 Docker를 사용하며, 화면·설정·파일 관리·서버 제어를 모듈로 분리했습니다. 패널 버전은 `1.0.0`입니다.

2026-09-13 기준으로 [Valheim 1.0 출시 발표](https://www.valheim.com/news/valheim-1-0-has-arrived-/), [1.0 FAQ](https://www.valheimgame.com/support/valheim-1-0-faq/), [9월 11일 핫픽스](https://www.valheimgame.com/news/hotfix-1-0-10-1-0-12/) 및 [공식 전용 서버 가이드](https://www.valheimgame.com/support/a-guide-to-dedicated-servers/)를 확인해 구현했습니다. Steam 정식 브랜치를 설치하므로 특정 핫픽스 번호를 고정하지 않습니다. 실제 설치된 Steam build ID를 상태 API에서 확인할 수 있습니다.

현재 구현한 기능은 다음과 같습니다.

- 초기 `admin / admin` 로그인과 최초 비밀번호 변경 강제, 만료되는 세션, 로그인 시도 제한.
- SteamCMD의 Valheim Dedicated Server 앱 `896660` 설치·업데이트 및 설치 로그.
- 시작·정상 중지·재시작, 실행 상태와 로그, CPU·메모리·디스크·네트워크 표시.
- 서버 이름·월드·비밀번호·UDP 포트·공개 여부·크로스플레이·월드 프리셋 설정.
- 게임 자체의 저장 간격과 자동 백업 개수·간격 설정.
- `.db`/`.fwl` 월드 파일 쌍 업로드, 월드 ZIP 다운로드, 패널 ZIP 백업·복원·삭제.
- 관리자·차단·접속 허용 목록, KST 기준 하루 최대 3회 예약 재시작.
- 웹패널 자체 업데이트와 실패 시 이전 이미지 복구, 교체 후 HTTP 응답 확인.
- 모바일 화면과 대화상자, 실행 중 쓰기 잠금, 설치·백업·복원·시작 간 작업 잠금.

공식 가이드의 기본 통신 범위는 UDP 2456–2457입니다. 다른 기본 포트를 설정하면 해당 포트와 다음 포트를 함께 사용합니다. 크로스플레이는 PlayFab을 이용하며 공개 IP, 참가 코드 또는 목록으로 접속합니다. 크로스플레이 서버에는 로컬 IP로 접속할 수 없습니다. 공식 1.0의 인원 범위는 1–10명이며, 임의의 `-maxplayers`, RCON, 모드 옵션은 이 패널에 넣지 않았습니다. 관련 근거는 [공식 서버 가이드](https://www.valheimgame.com/support/a-guide-to-dedicated-servers/)와 [1.0 FAQ](https://www.valheimgame.com/support/valheim-1-0-faq/)입니다.

실행 구조는 다음과 같습니다.

```text
브라우저 → VM:8080 → Nginx → valheim-panel:8080
                               └─ Docker socket → valheim-server
                                                → valheim-server-installer
                                                → valheim-panel-updater
```

| 경로 | 내용 |
| --- | --- |
| `app/main.py` | HTTP API, 로그인 화면, 파일 응답 |
| `app/config.py` | 설정 검증, 공식 서버 실행 인수 생성 |
| `app/service.py` | Docker 제어, 작업 잠금, 백업, 예약, 리소스 |
| `app/storage.py` | 원자적 파일 저장, 경로·ZIP 검증, 월드 파일 교체 |
| `app/auth.py` | 인증과 세션 |
| `app/self_update.py` | 별도 컨테이너에서 패널 교체·복구 |
| `app/static/` | HTML, CSS, JavaScript, TechTim용 룬 아이콘 |
| `runtime/` | Ubuntu 24.04, SteamCMD 및 비-root 게임 실행 환경 |
| `../../valheim/` | GCP VM 생성 스크립트와 VM 초기 설치 스크립트 |

기본 영구 저장 루트는 `/opt/techtim/valheim/data`입니다.

| 하위 경로 | 역할 |
| --- | --- |
| `server/` | Steam 서버 실행 파일과 설치 완료 마커 → 게임 컨테이너 `/server` |
| `saves/worlds_local/` | `.db`, `.fwl` 및 게임 자체 백업 → 게임 컨테이너 `/saves/worlds_local` |
| `saves/*list.txt` | 게임 권한 목록 |
| `backups/` | 패널에서 만든 ZIP 백업과 변경 전 백업 |
| `valheim-config.json` | 패널의 게임 실행 설정 |
| `auth.json`, `sessions.json` | 패널 인증 상태 |
| `restart-schedule.json` | KST 재시작 시각과 마지막 실행 결과 |
| `operation.json`, `*.log` | 작업 결과와 설치·제어 로그 |

패널의 `DATA_DIR`는 컨테이너 내부 `/data`입니다. `HOST_DATA_DIR`는 Docker에 전달하는 VM상의 절대 경로이며 두 값을 같은 경로로 오해하면 게임 데이터 마운트가 어긋납니다. 패널은 단일 Uvicorn worker로 실행합니다. 작업 잠금은 스레드 잠금과 파일 잠금을 함께 사용하며, 이전 패널에서 시작한 설치 helper가 실행 중이면 새 작업을 거부합니다.

개발용 실행은 Linux x86_64 Docker 환경에서 저장소 루트 기준으로 진행합니다. 게임 바이너리는 이미지에 포함하지 않고 엔진 설치 시 내려받습니다.

```bash
docker build --platform linux/amd64 -t techtim/valheim-runtime:local panels/valheim/runtime
mkdir -p /tmp/techtim-valheim-data
export VALHEIM_DATA_DIR=/tmp/techtim-valheim-data
docker compose -f panels/valheim/compose.local.yml up --build -d
```

접속 주소는 `http://127.0.0.1:8080`입니다. 로컬 구성은 `PULL_RUNTIME_IMAGE=0`으로 직접 빌드한 런타임 이미지를 사용합니다. 게임을 종료한 후 Compose를 내리세요. 게임 컨테이너는 패널이 별도로 생성하므로 `docker compose down`으로 함께 내려가지 않습니다. 로컬 이미지의 웹패널 업데이트는 새 이미지를 빌드한 뒤 Compose에서 적용합니다.

GCP 배포 준비와 실행 순서는 다음과 같습니다.

1. `.github/workflows/build-valheim-panel.yml`의 검사와 두 이미지 빌드가 통과해야 합니다. `main` 반영 후 `ghcr.io/kortechtim/valheim-panel:latest`와 `ghcr.io/kortechtim/valheim-runtime:steamcmd-nonroot-v1`이 게시됩니다. 런타임은 실제 컨테이너 UID 검사도 통과해야 합니다. PR에서는 빌드만 수행합니다. VM이 로그인 없이 받을 수 있도록 새 GHCR 패키지의 가시성도 확인합니다.
2. 기존 TechTim 설치 코드 검증 서비스가 `game=valheim`과 발급한 코드를 받아 `OK`를 반환하도록 연동합니다. 그 API의 구현은 이 저장소에 포함돼 있지 않습니다. 새 게임 등록 전에는 초기 설치 스크립트가 의도적으로 중단됩니다.
3. 대상 프로젝트에서 Compute Engine API를 활성화하고 Google Cloud CLI로 로그인합니다. VM 및 방화벽을 생성할 수 있는 계정이 필요합니다. 아래 스크립트를 실행하면 실제 유료 리소스가 생성됩니다.

```bash
export PROJECT_ID='YOUR_PROJECT_ID'
export ADMIN_CIDR='YOUR_PUBLIC_IPV4/32'
export INSTALL_CODE='YOUR_VALHEIM_INSTALL_CODE'
bash valheim/gcp-create.sh
```

기본값은 서울 `asia-northeast3-a`, `e2-standard-4`, Ubuntu 24.04 x86_64, 50GB Persistent Disk입니다. 이는 초기 구성값이며 실제 월드·동시 접속 규모에 대한 성능 보증은 아닙니다. `INSTANCE_NAME`, `ZONE`, `MACHINE_TYPE`, `NETWORK` 환경 변수로 바꿀 수 있습니다. 스크립트는 지정한 프로젝트만 대상으로 하며 VM에 서비스 계정을 연결하지 않습니다.

방화벽은 해당 VM 태그에 게임 UDP 2456–2457과 관리자 CIDR의 패널 TCP 8080만 허용합니다. 전체 포트를 여는 규칙은 만들지 않습니다. 기본 `default` VPC가 없는 프로젝트는 `NETWORK`를 지정하세요. 서브넷 선택이 필요한 커스텀 네트워크는 생성 명령에 해당 `--subnet`을 추가해야 합니다. [GCP VM 생성](https://docs.cloud.google.com/compute/docs/instances/create-start-instance), [VPC 방화벽](https://docs.cloud.google.com/firewall/docs/using-firewalls), [Ubuntu 이미지 계열](https://docs.cloud.google.com/compute/docs/images/os-details)을 기준으로 작성했습니다.

VM의 초기 설치는 `valheim-webui-install.sh`가 담당합니다. 완료 후 재부팅 시에는 기존 Compose 구성을 복구합니다. 로그는 `/var/log/techtim-valheim-install.log`, 설치 디렉터리는 `/opt/techtim/valheim`입니다. 브라우저에서 `http://VM_EXTERNAL_IP:8080`에 접속해 패널 비밀번호를 변경하고, 엔진 설치 → 서버 설정 저장 → 서버 시작 순서로 진행합니다. 패널 접속 비밀번호와 게임 접속 비밀번호는 서로 다릅니다.

월드 작업의 동작 범위는 다음과 같습니다.

- 같은 이름의 `.db`와 `.fwl`을 함께 업로드합니다. 업로드로 월드를 자동 선택하지 않으며 서버 설정에서 사용할 이름을 선택합니다.
- 이름이 같은 월드를 덮어쓰려면 화면에서 명시적으로 선택해야 합니다. 기존 데이터가 있으면 변경 전에 별도 ZIP 백업을 만듭니다.
- 패널 백업은 게임 서버가 완전히 중지된 상태에서 만듭니다. 실행 중 자동 백업은 게임 자체의 백업 설정으로 처리합니다.
- ZIP 복원은 `worlds_local`과 파일 쌍을 검증한 뒤 디렉터리를 교체합니다. 복원 전에도 현재 데이터를 백업합니다. 서버 바이너리와 패널 비밀번호는 복원 대상에 포함되지 않습니다.
- 패널 ZIP 백업에는 자동 삭제 정책이 없습니다. 필요한 백업을 내려받고 불필요한 파일은 화면에서 삭제해 디스크를 관리합니다.
- 중지는 SIGINT를 전송하고 기본 최대 120초 동안 프로세스 종료를 기다립니다. 시간 초과 시 강제 종료하지 않으며 후속 재시작·파일 쓰기를 진행하지 않습니다.
- 예약은 KST 하루 최대 3개 시각이며, 꺼진 서버를 켜지 않습니다. 겹친 작업으로 해당 분 전체가 바쁘면 그 회차는 실행되지 않습니다.

기존 월드의 1.0 호환성은 [공식 FAQ](https://www.valheimgame.com/support/valheim-1-0-faq/)의 설명을 따릅니다. 기존 세이브는 유지되지만 새 지역 생성은 미탐험 구역에 적용되므로 업데이트 전에 백업하고 월드를 선택하세요. 프리셋 기본값은 현재 월드 설정 유지입니다. 프리셋을 명시적으로 고르면 매 시작 시 적용합니다.

테스트는 저장소 루트에서 실행합니다.

```bash
python3 -m venv /tmp/valheim-test-env
/tmp/valheim-test-env/bin/pip install -r panels/valheim/requirements-dev.txt
DATA_DIR=/tmp/valheim-test-bootstrap \
HOST_DATA_DIR=/tmp/valheim-test-bootstrap \
SCHEDULER_ENABLED=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=panels/valheim \
  /tmp/valheim-test-env/bin/python -m unittest discover -s panels/valheim/tests -v
```

초기 구현 검증에서 46개 테스트를 통과했습니다. 구성·공식 실행 인수, API 인증과 최초 비밀번호 변경, 파일 쌍, 경로·ZIP 검증, 백업·복원, 정상 종료, 작업 중복 차단, 예약, 리소스 계산, 패널 업데이트 옵션 및 HTTP 확인을 다룹니다. macOS Python 3.11.9에서 실행했으며 GitHub Actions는 Python 3.12로 설정했습니다. JavaScript와 Bash 구문 검사를 통과했고 가상 Docker backend를 연결한 실제 브라우저에서 로그인, 설정 저장, 설치·시작·중지, 실행 중 설정 잠금과 390px 모바일 배치를 확인했습니다.

이 환경에는 Docker와 gcloud가 없어 실제 런타임 이미지 빌드, Steam 다운로드, VM 생성, 게임 클라이언트 접속, 실제 패널 교체·복구는 아직 검증하지 않았습니다. GCP 운영 전에는 두 이미지의 빌드, 설치 코드 연동, 새 월드 시작 및 재접속, 기존 월드 업로드 후 저장, 중지·재시작, Steam/크로스플레이 클라이언트 접속과 백업 복원까지 확인해야 합니다. CI의 가상 Docker 테스트 성공을 실제 게임 동작 확인으로 간주하지 않습니다.
