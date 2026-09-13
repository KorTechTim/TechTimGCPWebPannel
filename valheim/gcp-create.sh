#!/bin/bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to the target Google Cloud project.}"
: "${ADMIN_CIDR:?Set ADMIN_CIDR to the administrator public IP/CIDR, such as 203.0.113.10/32.}"
: "${INSTALL_CODE:?Set a Valheim install code accepted by the TechTim verification API.}"
INSTANCE_NAME="${INSTANCE_NAME:-techtim-valheim}"
ZONE="${ZONE:-asia-northeast3-a}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-4}"
NETWORK="${NETWORK:-default}"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

command -v gcloud >/dev/null || { echo 'Install and authenticate the Google Cloud CLI first.' >&2; exit 1; }
if [[ ! "$INSTALL_CODE" =~ ^[A-Za-z0-9_-]{4,128}$ ]]; then echo 'Invalid install code format.' >&2; exit 1; fi
python3 - "$ADMIN_CIDR" <<'PY'
import ipaddress, sys
network = ipaddress.ip_network(sys.argv[1])
if network.version != 4 or network.prefixlen == 0:
    raise SystemExit('Use a specific administrator IPv4 CIDR for the panel.')
PY

if ! gcloud compute firewall-rules describe "${INSTANCE_NAME}-panel" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud compute firewall-rules create "${INSTANCE_NAME}-panel" --project="$PROJECT_ID" \
    --network="$NETWORK" --direction=INGRESS --action=ALLOW --rules=tcp:8080 \
    --source-ranges="$ADMIN_CIDR" --target-tags="$INSTANCE_NAME"
fi
if ! gcloud compute firewall-rules describe "${INSTANCE_NAME}-game" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud compute firewall-rules create "${INSTANCE_NAME}-game" --project="$PROJECT_ID" \
    --network="$NETWORK" --direction=INGRESS --action=ALLOW --rules=udp:2456-2457 \
    --source-ranges=0.0.0.0/0 --target-tags="$INSTANCE_NAME"
fi
gcloud compute instances create "$INSTANCE_NAME" --project="$PROJECT_ID" --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=50GB --boot-disk-type=pd-balanced --network="$NETWORK" --tags="$INSTANCE_NAME" \
  --no-service-account --no-scopes \
  --metadata="install-code=$INSTALL_CODE" \
  --metadata-from-file="startup-script=$script_dir/valheim-webui-install.sh"
gcloud compute instances describe "$INSTANCE_NAME" --project="$PROJECT_ID" --zone="$ZONE" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
