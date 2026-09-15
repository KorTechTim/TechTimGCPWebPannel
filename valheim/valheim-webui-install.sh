#!/bin/bash
set -euo pipefail
umask 077

INSTALL_DIR="/opt/techtim/valheim"
PANEL_IMAGE="${PANEL_IMAGE:-ghcr.io/kortechtim/valheim-panel:latest}"
RUNTIME_IMAGE="${VALHEIM_RUNTIME_IMAGE:-ghcr.io/kortechtim/valheim-runtime:steamcmd-nonroot-v1}"
VERIFY_API="https://www.techtim.kr/api/install/verify"
METADATA_ROOT="http://metadata.google.internal/computeMetadata/v1/instance/attributes"

if [ "$(id -u)" -ne 0 ]; then echo 'Run this installer as root.' >&2; exit 1; fi
if [ "$(uname -m)" != x86_64 ]; then echo 'An x86_64 Ubuntu VM is required.' >&2; exit 1; fi
exec > >(tee -a /var/log/techtim-valheim-install.log) 2>&1

mkdir -p "$INSTALL_DIR"
exec 9>"$INSTALL_DIR/.bootstrap.lock"
flock -n 9 || { echo 'An installer is already running.'; exit 1; }

# Startup scripts run again on VM reboot. Keep the existing Compose configuration.
if [ -f "$INSTALL_DIR/.bootstrap-complete" ] && [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
  systemctl enable --now docker
  docker compose -f "$INSTALL_DIR/docker-compose.yml" up -d
  echo 'Existing Valheim panel restored.'
  exit 0
fi

apt-get update -y
apt-get install -y curl ca-certificates gnupg
INSTALL_CODE="${INSTALL_CODE:-$(curl -fsS --connect-timeout 5 --max-time 10 -H 'Metadata-Flavor: Google' "$METADATA_ROOT/install-code" || true)}"
if [[ ! "$INSTALL_CODE" =~ ^[A-Za-z0-9_-]{4,128}$ ]]; then
  echo 'A valid install-code metadata value is required.'; exit 1
fi
VERIFY_RESULT=$(curl -fsSL --connect-timeout 10 --max-time 30 --get \
  --data-urlencode 'game=valheim' --data-urlencode "code=$INSTALL_CODE" "$VERIFY_API" || true)
if [ "$VERIFY_RESULT" != OK ]; then
  echo 'Valheim install code verification failed. Configure game=valheim in the TechTim verification service.'
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

mkdir -p "$INSTALL_DIR/data/server" "$INSTALL_DIR/data/saves/worlds_local" \
  "$INSTALL_DIR/data/backups" "$INSTALL_DIR/data/exports" "$INSTALL_DIR/nginx"
cat > "$INSTALL_DIR/nginx/default.conf" <<'NGINX'
server {
    listen 80;
    server_name _;
    client_max_body_size 2048M;
    client_body_timeout 3600s;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    location / {
        proxy_pass http://valheim-panel:8080;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX
cat > "$INSTALL_DIR/docker-compose.yml" <<COMPOSE
services:
  valheim-panel:
    image: ${PANEL_IMAGE}
    container_name: valheim-panel
    restart: unless-stopped
    environment:
      DATA_DIR: /data
      HOST_DATA_DIR: ${INSTALL_DIR}/data
      VALHEIM_RUNTIME_IMAGE: ${RUNTIME_IMAGE}
      PANEL_IMAGE: ${PANEL_IMAGE}
      PANEL_CONTAINER_NAME: valheim-panel
      PANEL_PROXY_CONTAINER: valheim-panel-proxy
      VALHEIM_SERVER_CONTAINER: valheim-server
    volumes:
      - ${INSTALL_DIR}/data:/data
      - /var/run/docker.sock:/var/run/docker.sock
    logging:
      driver: json-file
      options:
        max-size: '10m'
        max-file: '3'
  valheim-panel-proxy:
    image: nginx:alpine
    container_name: valheim-panel-proxy
    restart: unless-stopped
    ports:
      - '8080:80'
    volumes:
      - ${INSTALL_DIR}/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - valheim-panel
COMPOSE

# VPC ingress is configured separately by gcp-create.sh; only these game ports are needed.
if command -v iptables >/dev/null 2>&1; then
  for chain in INPUT DOCKER-USER; do
    if iptables -nL "$chain" >/dev/null 2>&1; then
      iptables -C "$chain" -p udp --dport 2456:2457 -j ACCEPT 2>/dev/null \
        || iptables -I "$chain" 1 -p udp --dport 2456:2457 -j ACCEPT
    fi
  done
fi
docker compose -f "$INSTALL_DIR/docker-compose.yml" pull
docker compose -f "$INSTALL_DIR/docker-compose.yml" up -d
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/health >/dev/null; then
    touch "$INSTALL_DIR/.bootstrap-complete"
    echo 'Valheim panel ready at http://VM_EXTERNAL_IP:8080. Initial login: admin / admin.'
    echo 'Change the panel password, install the engine, then save game settings and start the server.'
    exit 0
  fi
  sleep 2
done
echo 'Panel health check failed. Check docker compose logs.' >&2
exit 1
