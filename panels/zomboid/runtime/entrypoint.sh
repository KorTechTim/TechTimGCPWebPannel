#!/bin/bash
set -euo pipefail

APP_ID="${STEAM_APP_ID:-380870}"
INSTALL_MARKER="/server/.techtim-installed.json"
ZOMBOID_USER="zomboid"
ZOMBOID_HOME="/home/zomboid"

drop_root_privileges() {
  if [ "$(id -u)" -ne 0 ]; then return; fi
  mkdir -p /server "$ZOMBOID_HOME/Zomboid" "$ZOMBOID_HOME/.steam/sdk64"
  chown -R "$ZOMBOID_USER:$ZOMBOID_USER" /server "$ZOMBOID_HOME"
  exec gosu "$ZOMBOID_USER" env HOME="$ZOMBOID_HOME" USER="$ZOMBOID_USER" LOGNAME="$ZOMBOID_USER" \
    /usr/local/bin/zomboid-entrypoint "$@"
}

drop_root_privileges "$@"

case "${1:-serve}" in
  install)
    branch="${2:-public}"
    rm -f "$INSTALL_MARKER"
    command=(/opt/steamcmd/steamcmd.sh +@sSteamCmdForcePlatformType linux +force_install_dir /server +login anonymous +app_update "$APP_ID")
    if [ "$branch" != "public" ]; then command+=( -beta "$branch" ); fi
    command+=( validate +quit )
    echo "Installing Project Zomboid branch '$branch' as $(id -un) (uid=$(id -u))."
    "${command[@]}"
    test -s /server/start-server.sh
    chmod +x /server/start-server.sh /server/ProjectZomboid64 2>/dev/null || true
    printf '{"app_id":"%s","branch":"%s","runtime_user":"%s","completed_at":"%s"}\n' \
      "$APP_ID" "$branch" "$ZOMBOID_USER" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${INSTALL_MARKER}.tmp"
    mv "${INSTALL_MARKER}.tmp" "$INSTALL_MARKER"
    echo 'Project Zomboid dedicated server installation completed.'
    ;;
  serve)
    memory_gb="${2:-8}"
    admin_password="${3:-}"
    if [ ! -s /server/start-server.sh ] || [ ! -f "$INSTALL_MARKER" ]; then
      echo 'Project Zomboid is not installed. Install the engine from the panel first.' >&2; exit 1
    fi
    if ! [[ "$memory_gb" =~ ^[0-9]+$ ]] || [ "$memory_gb" -lt 2 ] || [ "$memory_gb" -gt 64 ]; then
      echo 'Invalid Java memory size.' >&2; exit 2
    fi
    if [ -f /server/ProjectZomboid64.json ]; then
      sed -E -i "s/-Xms[0-9]+[kKmMgG]/-Xms${memory_gb}g/g; s/-Xmx[0-9]+[kKmMgG]/-Xmx${memory_gb}g/g" /server/ProjectZomboid64.json
    fi
    if [ -s /server/linux64/steamclient.so ]; then
      ln -sf /server/linux64/steamclient.so "$ZOMBOID_HOME/.steam/sdk64/steamclient.so"
    fi
    fifo=/tmp/zomboid-console
    rm -f "$fifo"; mkfifo "$fifo"; exec 3<>"$fifo"
    graceful_stop() {
      trap - TERM INT
      echo 'Panel requested a graceful save and shutdown.'
      printf 'save\nquit\n' >&3 || true
      for _ in $(seq 1 150); do kill -0 "$server_pid" 2>/dev/null || break; sleep 1; done
      kill -TERM "$server_pid" 2>/dev/null || true
    }
    trap graceful_stop TERM INT
    cd /server
    echo "Starting Project Zomboid as $(id -un) (uid=$(id -u)), memory=${memory_gb}GB."
    ./start-server.sh -servername "${SERVER_PROFILE:-servertest}" -adminpassword "$admin_password" <&3 &
    server_pid=$!
    wait "$server_pid"
    ;;
  check-user)
    test "$(id -u)" -ne 0 || { echo 'Runtime is still root.' >&2; exit 1; }
    echo "Runtime user check passed: $(id -un) (uid=$(id -u))."
    ;;
  *) echo 'Expected install, serve, or check-user.' >&2; exit 2 ;;
esac
