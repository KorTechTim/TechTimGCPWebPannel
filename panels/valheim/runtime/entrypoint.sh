#!/bin/bash
set -euo pipefail

case "${1:-serve}" in
  install)
    mkdir -p /server
    rm -f /server/.techtim-installed.json
    /opt/steamcmd/steamcmd.sh +@sSteamCmdForcePlatformType linux \
      +force_install_dir /server +login anonymous +app_update 896660 validate +quit
    test -s /server/valheim_server.x86_64
    chmod +x /server/valheim_server.x86_64
    printf '{"app_id":"896660","completed_at":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      > /server/.techtim-installed.json.tmp
    mv /server/.techtim-installed.json.tmp /server/.techtim-installed.json
    echo 'Valheim dedicated server installation completed.'
    ;;
  serve)
    shift
    if [ ! -s /server/valheim_server.x86_64 ] || [ ! -f /server/.techtim-installed.json ]; then
      echo 'Valheim is not installed. Install the engine from the panel first.' >&2
      exit 1
    fi
    mkdir -p /saves/worlds_local
    cd /server
    exec ./valheim_server.x86_64 -nographics -batchmode -savedir /saves -logFile /dev/stdout "$@"
    ;;
  *) echo 'Expected install or serve.' >&2; exit 2 ;;
esac
