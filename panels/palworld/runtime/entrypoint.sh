#!/bin/bash
set -euo pipefail

APP_ID="2394010"
INSTALL_MARKER="/server/.techtim-installed.json"
PALWORLD_USER="palworld"
PALWORLD_HOME="/home/palworld"

drop_root_privileges() {
  if [ "$(id -u)" -ne 0 ]; then
    return
  fi

  mkdir -p /server "$PALWORLD_HOME/.steam/sdk64"
  chown -R "$PALWORLD_USER:$PALWORLD_USER" /server "$PALWORLD_HOME"

  exec gosu "$PALWORLD_USER" env \
    HOME="$PALWORLD_HOME" \
    USER="$PALWORLD_USER" \
    LOGNAME="$PALWORLD_USER" \
    /usr/local/bin/palworld-entrypoint "$@"
}

drop_root_privileges "$@"

install_server() {
  mkdir -p /server
  rm -f "$INSTALL_MARKER"
  echo "Running SteamCMD as $(id -un) (uid=$(id -u))."

  /opt/steamcmd/steamcmd.sh +@sSteamCmdForcePlatformType linux \
    +force_install_dir /server +login anonymous +app_update "$APP_ID" validate +quit

  test -s /server/PalServer.sh
  test -s "/server/steamapps/appmanifest_${APP_ID}.acf"
  chmod +x /server/PalServer.sh

  printf '{"app_id":"%s","completed_at":"%s"}\n' \
    "$APP_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${INSTALL_MARKER}.tmp"
  mv "${INSTALL_MARKER}.tmp" "$INSTALL_MARKER"
  echo "Palworld Dedicated Server SteamCMD installation completed."
}

run_server() {
  if [ "${1:-}" = "serve" ]; then
    shift
  fi

  if [ ! -s /server/PalServer.sh ] || [ ! -f "$INSTALL_MARKER" ]; then
    echo "Palworld is not installed. Install or update the engine from the panel first." >&2
    exit 1
  fi

  mkdir -p /server/Pal/Saved "$PALWORLD_HOME/.steam/sdk64"

  if [ -s /server/linux64/steamclient.so ]; then
    ln -sf /server/linux64/steamclient.so "$PALWORLD_HOME/.steam/sdk64/steamclient.so"
  fi

  cd /server
  echo "Starting Palworld as $(id -un) (uid=$(id -u))."
  exec ./PalServer.sh "$@"
}

case "${1:-serve}" in
  install)
    install_server
    ;;
  check-user)
    if [ "$(id -u)" -eq 0 ]; then
      echo "Palworld runtime is still running as root." >&2
      exit 1
    fi

    echo "Palworld runtime user check passed: $(id -un) (uid=$(id -u))."
    ;;
  *)
    run_server "$@"
    ;;
esac
