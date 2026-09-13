from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.self_update import run_options, wait_for_http


class SelfUpdateTests(unittest.TestCase):
    def test_compose_network_volumes_and_direct_port_bindings_are_preserved(self):
        container = SimpleNamespace(name="valheim-panel", attrs={
            "Config": {"Env": ["DATA_DIR=/data", "PANEL_VERSION=old"], "Labels": {"label": "value"},
                       "Cmd": ["uvicorn", "app.main:app"], "WorkingDir": "/app"},
            "HostConfig": {"Binds": ["/host:/data"], "NetworkMode": "valheim_default",
                           "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8081"}]},
                           "RestartPolicy": {"Name": "unless-stopped"}},
        })
        options = run_options(container)
        self.assertEqual(options["network"], "valheim_default")
        self.assertEqual(options["volumes"], ["/host:/data"])
        self.assertEqual(options["ports"], {"8080/tcp": [("127.0.0.1", 8081)]})
        self.assertEqual(options["environment"], ["DATA_DIR=/data"])

    def test_running_container_must_pass_http_probe(self):
        container = SimpleNamespace(status="running", reload=lambda: None,
                                    exec_run=lambda args: SimpleNamespace(exit_code=1))
        with patch('app.self_update.time.monotonic', side_effect=[0, 0, 99]), patch('app.self_update.time.sleep'):
            with self.assertRaises(RuntimeError): wait_for_http(container, timeout=5)

    def test_http_probe_success_finishes_health_check(self):
        container = SimpleNamespace(status="running", reload=lambda: None,
                                    exec_run=lambda args: SimpleNamespace(exit_code=0))
        wait_for_http(container, timeout=5)
