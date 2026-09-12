"""Exercise the real Windows entry point's option binding without installing."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


DISTRIBUTION = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows PowerShell entry point")
class PowerShellEntryTests(unittest.TestCase):
    def invoke(self, script, *args):
        powershell = shutil.which("powershell.exe")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable")
        return subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(DISTRIBUTION / script), *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)

    def test_bootstrap_help_does_not_start_installation(self):
        with tempfile.TemporaryDirectory(prefix="studio-help-") as temporary:
            root = Path(temporary) / "not-created"
            result = self.invoke("bootstrap.ps1", "-InstallRoot", str(root), "-?")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(root.exists())

    def test_doctor_named_custom_root_is_checked_without_network_or_changes(self):
        with tempfile.TemporaryDirectory(prefix="studio-routing-") as temporary:
            root = Path(temporary) / "custom root"
            root.mkdir()
            marker = root / "keep-user-file.txt"
            marker.write_text("preserve", encoding="utf-8")
            before = sorted(path.name for path in root.iterdir())
            result = self.invoke("doctor.ps1", "-InstallRoot", str(root))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing a directory not owned by RhinoMCP Studio", result.stderr)
            self.assertIn("custom root", result.stderr)
            self.assertEqual(sorted(path.name for path in root.iterdir()), before)
            self.assertEqual(marker.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
