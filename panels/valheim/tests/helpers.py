from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import docker

from app.config import ServerConfig, Settings
from app.service import LABELS, PanelService
from app.storage import write_json


class FakeContainer:
    def __init__(self, owner, name, status="exited", labels=None):
        self.owner, self.name, self.status = owner, name, status
        self.labels = dict(LABELS if labels is None else labels)
        self.id = name + "-id"
        self.image = SimpleNamespace(id="runtime-image")
        self.output = b"Valheim version: 1.0.12\nGame server connected\n"
        self.attrs = {"State": {"ExitCode": 0, "StartedAt": "2026-09-13T01:00:00Z"}}
        self.signals = []
        self.stubborn = False
        self.removed = False
        self.stats_payload = {}
        self.policy = None

    def reload(self): pass
    def logs(self, **kwargs): return self.output
    def stats(self, **kwargs): return self.stats_payload
    def update(self, restart_policy): self.policy = restart_policy
    def unpause(self): self.status = "running"
    def kill(self, signal):
        self.signals.append(signal)
        if not self.stubborn: self.status = "exited"
    def remove(self, force=False):
        if self.status == "running" and not force:
            raise RuntimeError("Cannot remove running container")
        self.removed = True
        self.owner.registry.pop(self.name, None)


class FakeContainers:
    def __init__(self, parent):
        self.parent = parent
        self.registry = {}
        self.runs = []

    def get(self, name):
        if name not in self.registry:
            raise docker.errors.NotFound("not found")
        return self.registry[name]

    def add(self, name="valheim-server", status="running", labels=None):
        value = FakeContainer(self, name, status, labels)
        self.registry[name] = value
        return value

    def run(self, image, **kwargs):
        self.runs.append((image, kwargs))
        value = self.add(kwargs["name"], labels=kwargs.get("labels"))
        if kwargs.get("command") == ["install"]:
            value.status = "exited"
            value.output = b"Success! App '896660' fully installed."
            value.attrs["State"]["ExitCode"] = 0 if self.parent.install_success else 1
            if self.parent.install_success:
                self.parent.engine_dir.mkdir(exist_ok=True)
                (self.parent.engine_dir / "valheim_server.x86_64").write_bytes(b"fake executable")
                write_json(self.parent.engine_dir / ".techtim-installed.json", {"app_id": "896660"})
        return value


class FakeDocker:
    def __init__(self, engine_dir):
        self.engine_dir = engine_dir
        self.install_success = True
        self.containers = FakeContainers(self)
        self.images = SimpleNamespace(get=lambda image: SimpleNamespace(id="runtime-image"),
                                      pull=lambda image: SimpleNamespace(id="runtime-image"))
        self.api = SimpleNamespace(pull=lambda *args, **kwargs: iter([{"status": "Pull complete"}]))

    def ping(self): return True
    def close(self): pass


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = Settings(self.root, self.root / "host", scheduler_enabled=False, stop_timeout=0)
        self.docker = FakeDocker(self.root / "server")
        self.service = PanelService(self.settings, lambda: self.docker)

    def installed(self):
        (self.service.server / "valheim_server.x86_64").write_bytes(b"fake executable")
        write_json(self.service.server / ".techtim-installed.json", {"app_id": "896660"})
        write_json(self.service.config_file, ServerConfig(password="viking-secret").model_dump())

    def world(self, name="Dedicated", data=b"original db"):
        root = self.service.saves / "worlds_local"
        (root / (name + ".db")).write_bytes(data)
        (root / (name + ".fwl")).write_bytes(b"world metadata")
