"""Installer registration against the real local service; no Rhino/Codex install."""

import importlib.util
import json
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("cryptography", "starlette", "uvicorn"))


@unittest.skipUnless(AVAILABLE, "Management service dependencies are optional for installer unit tests")
class InstallerServiceIntegrationTests(unittest.TestCase):
    def test_enroll_real_service_then_reuse_same_identity_when_server_is_offline(self):
        sys.path.insert(0, str(REPO / "management"))
        try:
            from control_service import Service, create_app, initialize
            import uvicorn
        finally:
            sys.path.pop(0)
        spec = importlib.util.spec_from_file_location("integration_studio_manager", REPO / "distribution/manager.py")
        manager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manager)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            private = base / "private"
            initialize(private, "integration-" + secrets.token_urlsafe(20))
            service = Service(private, True)
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{sock.getsockname()[1]}"
            profile = manager.validate_profile(service.profile(url, True))
            app = create_app(private, True, url)
            server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, proxy_headers=False))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(server.started)
                with patch.object(manager.sys, "platform", "win32"):
                    registration = manager.enroll(profile, "0.6.0")
                self.assertEqual(registration["service_url"], url)
                self.assertGreaterEqual(len(registration["installation_token"]), 32)
            finally:
                server.should_exit = True
                thread.join(5)
                sock.close()
            self.assertFalse(thread.is_alive())
            path = base / "per-user/management.json"
            serialized = json.dumps(registration, indent=2) + "\n"
            manager.write_atomic(path, serialized)
            state = {"management": {"path": str(path.absolute()), "sha256": manager.hashlib.sha256(serialized.encode()).hexdigest()}}
            with patch.object(manager, "management_path", return_value=path):
                _, _, reused = manager.prepare_registration(profile, "0.6.0", state, base / "install-root", False)
            self.assertEqual(json.loads(reused)["installation_id"], registration["installation_id"])
            with patch.object(manager.sys, "platform", "win32"):
                with self.assertRaisesRegex(manager.InstallError, "no offline"):
                    manager.enroll(profile, "0.6.0")


if __name__ == "__main__":
    unittest.main()
