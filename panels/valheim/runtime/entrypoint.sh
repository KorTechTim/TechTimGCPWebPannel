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
    if [ -s /server/BepInEx/core/BepInEx.dll ] \
      && [ -s /server/BepInEx/core/BepInEx.Preloader.dll ] \
      && [ -s /server/doorstop_libs/libdoorstop_x64.so ]; then
      # Doorstop 4 uses ENABLED/TARGET_ASSEMBLY; keep the older names for legacy packs.
      export DOORSTOP_ENABLED=1
      export DOORSTOP_TARGET_ASSEMBLY=/server/BepInEx/core/BepInEx.Preloader.dll
      export DOORSTOP_ENABLE=TRUE
      export DOORSTOP_INVOKE_DLL_PATH=/server/BepInEx/core/BepInEx.Preloader.dll
      export DOORSTOP_CORLIB_OVERRIDE_PATH=/server/unstripped_corlib
      export LD_LIBRARY_PATH="/server/doorstop_libs:${LD_LIBRARY_PATH:-}"
      export LD_PRELOAD="/server/doorstop_libs/libdoorstop_x64.so${LD_PRELOAD:+:$LD_PRELOAD}"
      echo 'Linux BepInEx loader detected. Starting the modded server runtime.'
    fi
    exec ./valheim_server.x86_64 -nographics -batchmode -savedir /saves -logFile - "$@"
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
