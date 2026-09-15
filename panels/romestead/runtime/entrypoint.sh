#!/bin/bash
set -euo pipefail

APP_ID="4763510"
INSTALL_MARKER="/server/.techtim-installed.json"
RUNTIME_IMAGE="ghcr.io/kortechtim/romestead-runtime:steamcmd-nonroot-v1"
ROMESTEAD_USER="romestead"
ROMESTEAD_HOME="/home/romestead"

drop_root_privileges() {
  if [ "$(id -u)" -ne 0 ]; then
    return
  fi

  mkdir -p /server "$ROMESTEAD_HOME/.steam/sdk64"
  chown -R "$ROMESTEAD_USER:$ROMESTEAD_USER" /server "$ROMESTEAD_HOME"

  exec gosu "$ROMESTEAD_USER" env \
    HOME="$ROMESTEAD_HOME" \
    USER="$ROMESTEAD_USER" \
    LOGNAME="$ROMESTEAD_USER" \
    /usr/local/bin/romestead-entrypoint "$@"
}

drop_root_privileges "$@"

install_server() {
  mkdir -p /server
  rm -f "$INSTALL_MARKER"
  echo "Running SteamCMD as $(id -un) (uid=$(id -u))."

  /opt/steamcmd/steamcmd.sh +@sSteamCmdForcePlatformType linux \
    +force_install_dir /server +login anonymous +app_update "$APP_ID" validate +quit

  test -s /server/Server.dll
  printf '{"app_id":"%s","runtime_image":"%s","completed_at":"%s"}\n' \
    "$APP_ID" "$RUNTIME_IMAGE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${INSTALL_MARKER}.tmp"
  mv "${INSTALL_MARKER}.tmp" "$INSTALL_MARKER"
  echo 'Romestead dedicated server installation completed.'
}

run_server() {
  if [ "${1:-}" = "serve" ]; then
    shift
  fi

  if [ ! -s /server/Server.dll ]; then
    echo 'Romestead is not installed. Install or update the engine from the panel first.' >&2
    exit 1
  fi

  cd /server
  echo "Starting Romestead as $(id -un) (uid=$(id -u))."
  exec dotnet Server.dll "$@"
}

case "${1:-serve}" in
  install)
    install_server
    ;;
  check-user)
    if [ "$(id -u)" -eq 0 ]; then
      echo 'Romestead runtime is still running as root.' >&2
      exit 1
    fi
    echo "Romestead runtime user check passed: $(id -un) (uid=$(id -u))."
    ;;
  *)
    run_server "$@"
    ;;
esac
