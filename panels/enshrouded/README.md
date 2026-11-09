# TechTim Enshrouded GCP Panel

Google Cloud의 x86_64 Ubuntu VM에서 Enshrouded 1.0 전용 서버를 관리하는 웹 패널입니다.

## Runtime

- Base: `mornedhels/enshrouded-server:1.8.1-wine`
- Pinned digest: `sha256:002a8ac3387eddc5151b18ab5e7c02f9382f8e941dcfc75e56fa5134bd18f283`
- TechTim runtime: `ghcr.io/kortechtim/enshrouded-runtime:wine-v1`
- The derived runtime includes the upstream Wine graceful-shutdown process matching fix.

## Features

- Korean, English, Chinese, and Japanese interface
- Install, start, stop, restart, status, resource monitoring, and combined logs
- Official server role passwords and permissions
- Official difficulty presets and raw JSON editing through the file explorer
- Scheduled restart and up to three scheduled backup times
- Backup retention and disk usage visibility
- Discord webhook notifications
- Safe UTF-8 configuration editor with server-running lock and `Ctrl/Cmd+S`
- Single-ZIP migration export/import for moving to another Google Cloud account

The migration archive contains role passwords and the configured Discord webhook. Treat it as a secret.
