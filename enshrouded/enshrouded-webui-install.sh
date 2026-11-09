#!/bin/bash
set -euo pipefail
umask 077

PANEL_VERSION="1.0.2"
INSTALL_DIR="/opt/techtim/enshrouded"
PANEL_IMAGE="${PANEL_IMAGE:-ghcr.io/kortechtim/enshrouded-panel:latest}"
RUNTIME_IMAGE="${ENSHROUDED_RUNTIME_IMAGE:-ghcr.io/kortechtim/enshrouded-runtime:wine-v1}"
VERIFY_API="https://www.techtim.kr/api/install/verify"
METADATA_ROOT="http://metadata.google.internal/computeMetadata/v1/instance/attributes"

if [ "$(id -u)" -ne 0 ]; then echo 'Run this installer as root.' >&2; exit 1; fi
if [ "$(uname -m)" != x86_64 ]; then echo 'An x86_64 Ubuntu VM is required.' >&2; exit 1; fi
exec > >(tee -a /var/log/techtim-enshrouded-install.log) 2>&1

mkdir -p "$INSTALL_DIR"
exec 9>"$INSTALL_DIR/.bootstrap.lock"
flock -n 9 || { echo 'An installer is already running.'; exit 1; }

if [ -f "$INSTALL_DIR/.bootstrap-complete" ] && [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
  systemctl enable --now docker
  docker compose -f "$INSTALL_DIR/docker-compose.yml" up -d
  echo 'Existing Enshrouded panel restored.'
  exit 0
fi

apt-get update -y
apt-get install -y curl ca-certificates gnupg
INSTALL_CODE="${INSTALL_CODE:-$(curl -fsS --connect-timeout 5 --max-time 10 -H 'Metadata-Flavor: Google' "$METADATA_ROOT/install-code" || true)}"
if [[ ! "$INSTALL_CODE" =~ ^[A-Za-z0-9_-]{4,128}$ ]]; then
  echo 'A valid install-code metadata value is required.'; exit 1
fi
VERIFY_RESULT=$(curl -fsSL --connect-timeout 10 --max-time 30 --get \
  --data-urlencode 'game=enshrouded' --data-urlencode "code=$INSTALL_CODE" "$VERIFY_API" || true)
if [ "$VERIFY_RESULT" != OK ]; then
  echo 'Enshrouded install code verification failed. Configure the verification service first.'
  exit 1
fi

timedatectl set-timezone Asia/Seoul
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
if [ "$ID" != ubuntu ]; then echo 'Ubuntu is required.'; exit 1; fi
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

mkdir -p "$INSTALL_DIR/data/server/savegame" "$INSTALL_DIR/data/server/logs" \
  "$INSTALL_DIR/data/backups" "$INSTALL_DIR/data/exports" "$INSTALL_DIR/data/panel-logs" "$INSTALL_DIR/nginx"
cat > "$INSTALL_DIR/nginx/default.conf" <<'NGINX'
server {
    listen 80;
    server_name _;
    client_max_body_size 4096M;
    client_body_timeout 3600s;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    location / {
        proxy_pass http://enshrouded-panel:8080;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX
cat > "$INSTALL_DIR/docker-compose.yml" <<COMPOSE
services:
  enshrouded-panel:
    image: ${PANEL_IMAGE}
    container_name: enshrouded-panel
    restart: unless-stopped
    environment:
      DATA_DIR: /data
      HOST_DATA_DIR: ${INSTALL_DIR}/data
      ENSHROUDED_RUNTIME_IMAGE: ${RUNTIME_IMAGE}
      PANEL_IMAGE: ${PANEL_IMAGE}
      PANEL_VERSION: ${PANEL_VERSION}
      PANEL_CONTAINER_NAME: enshrouded-panel
      PANEL_PROXY_CONTAINER: enshrouded-panel-proxy
      ENSHROUDED_SERVER_CONTAINER: enshrouded-server
      STORAGE_CLEANUP_THRESHOLD_PERCENT: '85'
      STORAGE_CLEANUP_TARGET_PERCENT: '78'
      STORAGE_MIN_BACKUPS: '3'
    volumes:
      - ${INSTALL_DIR}/data:/data
      - /var/run/docker.sock:/var/run/docker.sock
      - /proc:/host/proc:ro
    logging:
      driver: json-file
      options:
        max-size: '10m'
        max-file: '3'
  enshrouded-panel-proxy:
    image: nginx:alpine
    container_name: enshrouded-panel-proxy
    restart: unless-stopped
    ports:
      - '8080:80'
    volumes:
      - ${INSTALL_DIR}/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - enshrouded-panel
    logging:
      driver: json-file
      options:
        max-size: '10m'
        max-file: '3'
COMPOSE

if command -v iptables >/dev/null 2>&1; then
  for chain in INPUT DOCKER-USER; do
    if iptables -nL "$chain" >/dev/null 2>&1; then
      iptables -C "$chain" -p udp --dport 15637 -j ACCEPT 2>/dev/null \
        || iptables -I "$chain" 1 -p udp --dport 15637 -j ACCEPT
    fi
  done
fi
docker compose -f "$INSTALL_DIR/docker-compose.yml" pull
docker compose -f "$INSTALL_DIR/docker-compose.yml" up -d
for attempt in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8080/health >/dev/null; then
    touch "$INSTALL_DIR/.bootstrap-complete"
    echo 'Enshrouded panel ready at http://VM_EXTERNAL_IP:8080. Initial login: admin / admin.'
    echo 'Change the panel password and role passwords before installing the game server.'
    exit 0
  fi
  sleep 2
done
echo 'Panel health check failed. Check docker compose logs.' >&2
exit 1
