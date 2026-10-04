from datetime import datetime
import os
from types import SimpleNamespace
from unittest.mock import patch

from app.config import ServerConfig
from app.service import BusyError, KST, PanelService
from app.storage import read_json, write_json
from helpers import ServiceCase


class LifecycleTests(ServiceCase):
    def test_missing_engine_and_missing_password_prevent_start(self):
        with self.assertRaises(BusyError): self.service.start()
        self.installed()
        write_json(self.service.config_file, ServerConfig().model_dump())
        with self.assertRaises(ValueError): self.service.start()
        self.assertEqual(self.docker.containers.runs, [])

    def test_start_uses_two_udp_ports_and_distinct_host_mounts(self):
        self.installed()
        config = self.service.config().model_copy(update={"port": 2466})
        write_json(self.service.config_file, config.model_dump())
        self.service.start()
        image, options = self.docker.containers.runs[-1]
        self.assertEqual(options["ports"], {"2466/udp": 2466, "2467/udp": 2467})
        self.assertEqual(options["stop_signal"], "SIGINT")
        self.assertTrue(options["init"])
        self.assertEqual(options["cap_drop"], ["ALL"])
        self.assertEqual(options["cap_add"], ["CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID"])
        self.assertEqual(options["security_opt"], ["no-new-privileges:true"])
        self.assertIn(str(self.settings.host_data_dir / "saves"), options["volumes"])
        self.assertNotIn("/var/run/docker.sock", options["volumes"])
        self.assertEqual(options["restart_policy"], {"Name": "unless-stopped"})

    def test_running_server_blocks_start_install_and_save(self):
        self.installed()
        server = self.docker.containers.add()
        for action in (self.service.start, self.service.install, lambda: self.service.save_config({"world": "new"})):
            with self.assertRaises(BusyError): action()
        self.assertFalse(server.removed)

    def test_normal_stop_uses_only_sigint_and_disables_restart(self):
        server = self.docker.containers.add()
        self.service.stop()
        self.assertEqual(server.signals, ["SIGINT"])
        self.assertEqual(server.policy, {"Name": "no"})
        self.assertFalse(server.removed)

    def test_timeout_does_not_force_kill_or_restart_the_server(self):
        self.installed()
        server = self.docker.containers.add()
        server.stubborn = True
        with self.assertRaises(BusyError): self.service.restart()
        self.assertEqual(server.signals, ["SIGINT"])
        self.assertFalse(server.removed)
        self.assertEqual(self.docker.containers.runs, [])

    def test_unrelated_named_container_is_not_controlled(self):
        server = self.docker.containers.add(labels={"unrelated": "true"})
        with self.assertRaises(BusyError): self.service.stop()
        self.assertEqual(server.signals, [])

    def test_installer_success_creates_state_and_failed_update_invalidates_old_install(self):
        self.service.install()
        self.assertTrue(self.service.engine()["installed"])
        self.docker.install_success = False
        with self.assertRaises(RuntimeError): self.service.install()
        self.assertFalse(self.service.engine()["installed"])

    def test_legacy_runtime_marker_requires_engine_update(self):
        (self.service.server / "valheim_server.x86_64").write_bytes(b"fake executable")
        write_json(self.service.server / ".techtim-installed.json", {"app_id": "896660"})

        self.assertFalse(self.service.engine()["installed"])

    def test_custom_runtime_marker_is_accepted_after_nonroot_install(self):
        (self.service.server / "valheim_server.x86_64").write_bytes(b"fake executable")
        write_json(
            self.service.server / ".techtim-installed.json",
            {"app_id": "896660", "runtime_user": "valheim"},
        )

        self.assertTrue(self.service.engine()["installed"])

    def test_foreground_jobs_and_surviving_helpers_exclude_conflicting_operations(self):
        with self.service.operation("first"):
            with self.assertRaises(BusyError): self.service.reserve("second")
            other = PanelService(self.settings, lambda: self.docker)
            with self.assertRaises(BusyError): other.reserve("other worker")
        self.docker.containers.add(self.service.installer_name)
        with self.assertRaises(BusyError): self.service.reserve("while installer survives")
        self.assertFalse(self.service.lock.locked())

    def test_background_error_releases_lock_and_records_failure(self):
        handle = self.service.reserve("test")
        def fail(): raise ValueError("expected failure")
        self.service.run_reserved(handle, "test", fail)
        self.assertFalse(self.service.lock.locked())
        self.assertEqual(read_json(self.service.job_file, {})["status"], "failed")

    def test_panel_update_preparation_failure_is_visible_in_update_status(self):
        self.docker.containers.add(self.settings.panel_container)

        def fail_pull(*_args, **_kwargs):
            raise RuntimeError("registry unavailable")

        self.docker.api.pull = fail_pull
        with self.assertRaises(RuntimeError):
            self.service.update_panel()
        status = read_json(self.service.root / "panel-update-status.json", {})
        self.assertEqual(status["status"], "failed")
        self.assertIn("registry unavailable", status["message"])

    def test_panel_update_reports_version_and_image_when_already_current(self):
        self.docker.containers.add(self.settings.panel_container)

        self.service.update_panel()

        status = read_json(self.service.root / "panel-update-status.json", {})
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["version"], "1.1.0")
        self.assertEqual(status["image_id"], "runtime-imag")
        self.assertIn("1.1.0", status["message"])

    def test_panel_update_streams_pull_and_starts_latest_helper(self):
        self.docker.containers.add(self.settings.panel_container)
        pulls = []

        def stream_pull(repository, **options):
            pulls.append((repository, options))
            return iter([{"status": "Pull complete"}])

        self.docker.api.pull = stream_pull
        self.docker.images.get = lambda _image: SimpleNamespace(id="new-panel-image")

        self.service.update_panel()

        self.assertEqual(pulls[0][1], {"tag": "latest", "stream": True, "decode": True})
        image, options = self.docker.containers.runs[-1]
        self.assertEqual(image, "new-panel-image")
        self.assertEqual(options["command"], ["python", "-m", "app.self_update"])
        self.assertEqual(options["environment"]["TARGET_IMAGE"], self.settings.panel_image)

    def test_ready_state_survives_log_rotation_but_not_process_restart(self):
        server = self.docker.containers.add()
        self.assertTrue(self.service.status()["ready"])
        server.output = b"Later log lines"
        self.assertTrue(self.service.status()["ready"])
        server.attrs["State"]["StartedAt"] = "a new start"
        self.assertFalse(self.service.status()["ready"])

    def test_join_code_is_extracted_cached_and_reset_per_server_start(self):
        server = self.docker.containers.add()
        server.output = b'Session "TechTim" with join code 482731 and IP 1.2.3.4:2456 is active\n'
        self.assertEqual(self.service.status()["join_code"], "482731")
        server.output = b"Later log lines after rotation\n"
        self.assertEqual(self.service.status()["join_code"], "482731")
        server.attrs["State"]["StartedAt"] = "a new start"
        self.assertEqual(self.service.status()["join_code"], "")
        server.output = b'Session "TechTim" registered with join code AB12CD\n'
        self.assertEqual(self.service.status()["join_code"], "AB12CD")
        server.status = "exited"
        self.assertEqual(self.service.status()["join_code"], "")

    def test_schedule_runs_once_per_slot_and_does_not_start_offline_server(self):
        write_json(self.service.schedule_file, {"enabled": True, "times": ["04:00", "12:00"]})
        with patch.object(self.service, "restart") as restart:
            now = datetime(2026, 9, 13, 4, 0, tzinfo=KST)
            self.service.scheduled_restart(now)
            restart.assert_not_called()
            self.assertEqual(self.service.schedule()["last_result"], "skipped")
            self.docker.containers.add()
            self.service.scheduled_restart(now)
            restart.assert_not_called()
            noon = now.replace(hour=12)
            self.service.scheduled_restart(noon)
            self.service.scheduled_restart(noon)
            restart.assert_called_once()

    def test_failed_scheduled_stop_records_failure_without_second_restart(self):
        self.installed()
        self.docker.containers.add().stubborn = True
        write_json(self.service.schedule_file, {"enabled": True, "times": ["04:00"]})
        self.service.scheduled_restart(datetime(2026, 9, 13, 4, 0, tzinfo=KST))
        self.assertEqual(self.service.schedule()["last_result"], "failed")

    def test_resources_use_container_cpu_and_working_set_memory(self):
        server = self.docker.containers.add()
        server.stats_payload = {"cpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 1000, "online_cpus": 4},
                                "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
                                "memory_stats": {"usage": 1000, "limit": 4000, "stats": {"inactive_file": 200}}}
        result = self.service.resources()
        self.assertEqual(result["cpu_percent"], 80)
        self.assertEqual(result["memory_used"], 800)
        self.assertEqual(result["network_rx"], 0)

    def test_storage_cleanup_does_nothing_below_threshold(self):
        with patch("app.service.shutil.disk_usage", return_value=SimpleNamespace(total=100, used=79, free=21)):
            result = self.service.cleanup_storage_if_needed()

        self.assertFalse(result["triggered"])
        self.assertEqual(self.docker.images.prune_calls, 0)

    def test_storage_cleanup_prunes_docker_and_keeps_three_newest_backups(self):
        names = []
        for index in range(5):
            path = self.service.backups / f"backup-{index}.zip"
            path.write_bytes(b"backup")
            os.utime(path, (index + 1, index + 1))
            names.append(path.name)
        self.docker.images.prune_result = {
            "ImagesDeleted": [{"Deleted": "sha256:old"}],
            "SpaceReclaimed": 1024,
        }
        usage = [
            SimpleNamespace(total=100, used=90, free=10),
            SimpleNamespace(total=100, used=90, free=10),
            SimpleNamespace(total=100, used=82, free=18),
            SimpleNamespace(total=100, used=74, free=26),
        ]

        with patch("app.service.shutil.disk_usage", side_effect=usage):
            result = self.service.cleanup_storage_if_needed()

        self.assertTrue(result["triggered"])
        self.assertEqual(result["backups_deleted"], 2)
        self.assertEqual(result["images_deleted"], 1)
        self.assertEqual(result["space_reclaimed"], 1024)
        self.assertEqual(self.docker.images.prune_filters, {"dangling": True})
        self.assertEqual(sorted(path.name for path in self.service.backups.glob("*.zip")), names[2:])

    def test_storage_cleanup_prefers_automatic_safety_backups(self):
        names = [
            "valheim-20260101-000000-manual-000001.zip",
            "valheim-20260102-000000-before-update-000002.zip",
            "valheim-20260103-000000-manual-000003.zip",
            "valheim-20260104-000000-manual-000004.zip",
            "valheim-20260105-000000-manual-000005.zip",
        ]
        for index, name in enumerate(names):
            path = self.service.backups / name
            path.write_bytes(b"backup")
            os.utime(path, (index + 1, index + 1))
        usage = [
            SimpleNamespace(total=100, used=90, free=10),
            SimpleNamespace(total=100, used=90, free=10),
            SimpleNamespace(total=100, used=74, free=26),
            SimpleNamespace(total=100, used=74, free=26),
        ]

        with patch("app.service.shutil.disk_usage", side_effect=usage):
            result = self.service.cleanup_storage_if_needed()

        self.assertEqual(result["backups_deleted"], 1)
        self.assertTrue((self.service.backups / names[0]).exists())
        self.assertFalse((self.service.backups / names[1]).exists())

    def test_password_is_not_in_config_response_or_logs(self):
        self.installed()
        self.service.log("viking-secret should be redacted")
        self.assertNotIn("viking-secret", self.service.logs("control"))
        self.assertNotIn("password", self.service.public_config())
        self.assertTrue(self.service.public_config()["password_set"])
