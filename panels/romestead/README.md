# TechTim Romestead Server Panel

Romestead Dedicated Server를 GCP VM에서 관리하기 위한 TechTim Web UI 패널입니다.

## 기능

- FastAPI 기반 Web UI
- admin/admin 최초 로그인 및 비밀번호 변경 강제
- SteamCMD anonymous 기반 Romestead 엔진 설치
- SteamCMD와 .NET 서버를 `romestead` 전용 사용자로 실행하는 비-root 런타임
- config.json 조회/저장
- 서버 시작/중지/재시작/상태/로그 조회
- 설치 로그와 서버 로그 자동 갱신 및 자동 스크롤
- saved_worlds ZIP 다운로드/업로드

## Local Docker Build

```bash
docker build -t romestead-panel .
docker run --rm -p 8080:8080 \
  -e DATA_DIR=/data \
  -e HOST_DATA_DIR=/tmp/romestead-panel-data \
  -v /tmp/romestead-panel-data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  romestead-panel
```

초기 계정:

```text
admin / admin
```

게임 엔진은 호스트의 `/opt/techtim/romestead/data/server`에 유지됩니다. 기존
설치 파일이 root 소유인 경우 새 런타임 시작 시 권한을 자동으로 보정하며,
설치와 서버 실행에는 다음 고정 런타임 태그를 사용합니다.

```text
ghcr.io/kortechtim/romestead-runtime:steamcmd-nonroot-v1
```
