FROM mornedhels/enshrouded-server:1.8.1-wine@sha256:002a8ac3387eddc5151b18ab5e7c02f9382f8e941dcfc75e56fa5134bd18f283

LABEL org.opencontainers.image.title="TechTim Enshrouded Runtime" \
      org.opencontainers.image.description="Pinned Enshrouded Wine runtime with graceful shutdown fix"

# Upstream 1.8.1 escapes the process pattern and waits for the 60-second fallback.
RUN python3 - <<'PY'
from pathlib import Path

path = Path("/usr/local/etc/enshrouded/enshrouded-server")
content = path.read_text()
old = r"grep '\\[e]nshrouded_server'"
new = "grep '[e]nshrouded_server'"
if old not in content:
    raise SystemExit("upstream shutdown pattern changed")
path.write_text(content.replace(old, new))
PY
