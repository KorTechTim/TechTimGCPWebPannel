#!/bin/bash
set -euo pipefail

APP_ID="896660"
INSTALL_MARKER="/server/.techtim-installed.json"
VALHEIM_USER="valheim"
VALHEIM_HOME="/home/valheim"

drop_root_privileges() {
  if [ "$(id -u)" -ne 0 ]; then
    return
  fi

  mkdir -p /server /saves "$VALHEIM_HOME/.steam/sdk64"
  chown -R "$VALHEIM_USER:$VALHEIM_USER" /server /saves "$VALHEIM_HOME"

  exec gosu "$VALHEIM_USER" env \
    HOME="$VALHEIM_HOME" \
    USER="$VALHEIM_USER" \
    LOGNAME="$VALHEIM_USER" \
    /usr/local/bin/valheim-entrypoint "$@"
}

drop_root_privileges "$@"

case "${1:-serve}" in
  install)
    mkdir -p /server
    rm -f "$INSTALL_MARKER"
    echo "Running SteamCMD as $(id -un) (uid=$(id -u))."
    /opt/steamcmd/steamcmd.sh +@sSteamCmdForcePlatformType linux \
      +force_install_dir /server +login anonymous +app_update "$APP_ID" validate +quit
    test -s /server/valheim_server.x86_64
    chmod +x /server/valheim_server.x86_64
    printf '{"app_id":"%s","runtime_user":"%s","completed_at":"%s"}\n' \
      "$APP_ID" "$VALHEIM_USER" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${INSTALL_MARKER}.tmp"
    mv "${INSTALL_MARKER}.tmp" "$INSTALL_MARKER"
    echo 'Valheim dedicated server installation completed.'
    ;;
  serve)
    shift
    if [ ! -s /server/valheim_server.x86_64 ] || [ ! -f "$INSTALL_MARKER" ]; then
      echo 'Valheim is not installed. Install the engine from the panel first.' >&2
      exit 1
    fi
    mkdir -p /saves/worlds_local "$VALHEIM_HOME/.steam/sdk64"
    if [ -s /server/linux64/steamclient.so ]; then
      ln -sf /server/linux64/steamclient.so "$VALHEIM_HOME/.steam/sdk64/steamclient.so"
    fi
    cd /server
    echo "Starting Valheim as $(id -un) (uid=$(id -u))."
    exec ./valheim_server.x86_64 -nographics -batchmode -savedir /saves -logFile /dev/stdout "$@"
    ;;
  check-user)
    if [ "$(id -u)" -eq 0 ]; then
      echo 'Valheim runtime is still running as root.' >&2
      exit 1
    fi
    echo "Valheim runtime user check passed: $(id -un) (uid=$(id -u))."
    ;;
  *) echo 'Expected install, serve, or check-user.' >&2; exit 2 ;;
esac
