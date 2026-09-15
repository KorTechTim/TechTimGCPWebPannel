from pathlib import Path
import unittest


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.panel_root = Path(__file__).resolve().parents[1]
        self.repository_root = self.panel_root.parents[1]

    def test_runtime_drops_root_before_install_and_serve(self):
        dockerfile = (self.panel_root / "runtime" / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (self.panel_root / "runtime" / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("mcr.microsoft.com/dotnet/runtime:8.0-noble", dockerfile)
        self.assertIn("gosu", dockerfile)
        self.assertIn("useradd --system --gid romestead", dockerfile)
        self.assertIn('exec gosu "$ROMESTEAD_USER"', entrypoint)
        self.assertIn('chown -R "$ROMESTEAD_USER:$ROMESTEAD_USER" /server', entrypoint)
        self.assertIn('+app_update "$APP_ID" validate +quit', entrypoint)
        self.assertIn('exec dotnet Server.dll "$@"', entrypoint)
        self.assertIn("check-user)", entrypoint)
        self.assertNotIn("/root/.steam", dockerfile + entrypoint)

    def test_panel_and_gcp_installer_use_fixed_nonroot_runtime(self):
        main_source = (self.panel_root / "app" / "main.py").read_text(encoding="utf-8")
        installer = (
            self.repository_root / "romestead" / "romestead-webui-install.sh"
        ).read_text(encoding="utf-8")

        runtime = "ghcr.io/kortechtim/romestead-runtime:steamcmd-nonroot-v1"
        self.assertIn(runtime, main_source)
        self.assertIn(runtime, installer)
        self.assertNotIn("STEAMCMD_IMAGE=", installer)
        self.assertNotIn("DOTNET_IMAGE=", installer)


if __name__ == "__main__":
    unittest.main()
