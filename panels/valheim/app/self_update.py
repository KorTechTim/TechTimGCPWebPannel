"""Replace the panel from a helper container; retain the old image for rollback."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import fcntl
import os
import time

import docker
from docker.types import LogConfig

from .config import PANEL_VERSION
from .storage import read_json, write_json

STATUS = Path("/update-data/panel-update-status.json")
OPERATION = Path("/update-data/operation.json")
KST = timezone(timedelta(hours=9), name="KST")


@contextmanager
def docker_client():
    client = docker.from_env(timeout=30)
    try:
        yield client
    finally:
        client.close()


def write_operation(status, message):
    write_json(OPERATION, {
        "status": status,
        "name": "웹패널 업데이트",
        "message": message,
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
    })


def run_options(container):
    config = container.attrs["Config"]
    host = container.attrs["HostConfig"]
    volumes = list(host.get("Binds") or [])
    if not any(bind.split(":", 2)[1] == "/host/proc" for bind in volumes if ":" in bind):
        volumes.append("/proc:/host/proc:ro")
    options = {
        "name": container.name, "detach": True,
        "environment": [v for v in config.get("Env", []) if not v.startswith("PANEL_VERSION=")],
        "labels": config.get("Labels", {}), "volumes": volumes,
        "restart_policy": host.get("RestartPolicy", {"Name": "unless-stopped"}),
        "init": bool(host.get("Init")),
    }
    for source, target in (("Cmd", "command"), ("Entrypoint", "entrypoint"), ("WorkingDir", "working_dir"), ("User", "user")):
        if config.get(source):
            options[target] = config[source]
    network = host.get("NetworkMode", "default")
    if network not in {"default", "bridge", ""}:
        options["network"] = network
    bindings = host.get("PortBindings") or {}
    if bindings and network != "host":
        options["ports"] = {port: [(b.get("HostIp") or "0.0.0.0", int(b["HostPort"])) for b in bound]
                            for port, bound in bindings.items() if bound}
    if host.get("LogConfig", {}).get("Type"):
        log = host["LogConfig"]
        options["log_config"] = LogConfig(type=log["Type"], config=log.get("Config", {}))
    return options


def wait_for_http(container, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container.reload()
        if container.status in {"dead", "exited"}:
            logs = container.logs(tail=30).decode(errors="replace")
            raise RuntimeError(f"새 패널 프로세스가 종료되었습니다: {logs[-1200:]}")
        if container.status == "running":
            probe = container.exec_run(["python", "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"])
            if probe.exit_code == 0:
                return
        time.sleep(2)
    raise RuntimeError("패널 HTTP 응답을 확인하지 못했습니다.")


def main():
    target_name = os.getenv("TARGET_CONTAINER", "valheim-panel")
    target_image = os.environ["TARGET_IMAGE"]
    proxy_name = os.getenv("PROXY_CONTAINER", "valheim-panel-proxy")
    time.sleep(2)
    with Path("/update-data/.maintenance.lock").open("a") as lock, docker_client() as client:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = client.containers.get(target_name)
        target.reload()
        previous_image = target.image.id
        latest_image = client.images.get(target_image)
        latest_image_id = latest_image.id
        options = run_options(target)
        target.stop(timeout=30)
        target.remove()

        def restart_proxy():
            try:
                proxy = client.containers.get(proxy_name)
            except docker.errors.NotFound:
                return
            proxy.restart(timeout=10)

        try:
            replacement = client.containers.run(latest_image_id, **options)
            wait_for_http(replacement)
            restart_proxy()
            image_id = latest_image_id.removeprefix("sha256:")[:12]
            write_json(STATUS, {
                "status": "completed",
                "message": f"웹패널 {PANEL_VERSION} 업데이트 완료 · 이미지 {image_id}",
                "version": PANEL_VERSION,
                "image_id": image_id,
            })
            write_operation("completed", f"웹패널 {PANEL_VERSION} 업데이트 완료")
        except Exception as error:
            try:
                client.containers.get(target_name).remove(force=True)
            except docker.errors.NotFound:
                pass
            try:
                previous = client.containers.run(previous_image, **options)
                wait_for_http(previous)
                restart_proxy()
                write_json(STATUS, {"status": "failed", "rollback": "completed",
                                    "message": f"업데이트 실패 후 이전 패널로 복구했습니다: {error}"})
                write_operation("failed", f"웹패널 업데이트 실패 후 이전 버전으로 복구했습니다: {error}")
            except Exception as rollback_error:
                write_json(STATUS, {"status": "failed", "rollback": "failed",
                                    "message": f"패널 복구 확인이 필요합니다: {rollback_error}"})
                write_operation("failed", f"웹패널 업데이트 및 복구 실패: {rollback_error}")
                raise


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if read_json(STATUS, {}).get("status") != "failed":
            write_json(STATUS, {"status": "failed", "message": str(error)})
        write_operation("failed", f"웹패널 업데이트 실패: {error}")
        raise
