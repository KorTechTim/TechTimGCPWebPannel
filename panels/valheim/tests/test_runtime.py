from pathlib import Path
import unittest


class RuntimeTests(unittest.TestCase):
    def test_runtime_drops_root_before_install_and_serve(self):
        runtime_root = Path(__file__).resolve().parents[1] / "runtime"
        dockerfile = (runtime_root / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (runtime_root / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("gosu", dockerfile)
        self.assertIn("useradd --system --gid valheim", dockerfile)
        self.assertIn('exec gosu "$VALHEIM_USER"', entrypoint)
        self.assertIn('chown -R "$VALHEIM_USER:$VALHEIM_USER" /server /saves', entrypoint)
        self.assertIn('"runtime_user":"%s"', entrypoint)
        self.assertIn("check-user)", entrypoint)
        self.assertIn('echo "Starting Valheim as $(id -un) (uid=$(id -u))."', entrypoint)
        self.assertNotIn("/root/.steam", dockerfile + entrypoint)


if __name__ == "__main__":
    unittest.main()
