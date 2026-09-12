import argparse
import base64
import hashlib
import importlib.util
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from contextlib import redirect_stdout
from unittest.mock import MagicMock
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("studio_manager", Path(__file__).resolve().parents[1] / "manager.py")
studio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(studio)


def public_key_fixture():
    def der(tag, value):
        length = len(value)
        size = length.to_bytes((length.bit_length() + 7) // 8, "big")
        return bytes([tag]) + (bytes([length]) if length < 128 else bytes([128 + len(size)]) + size) + value
    rsa = der(0x30, der(0x02, b"\0" + b"\xc1" * 384) + der(0x02, b"\x01\0\x01"))
    spki = der(0x30, bytes.fromhex("300d06092a864886f70d0101010500") + der(0x03, b"\0" + rsa))
    return "-----BEGIN PUBLIC KEY-----\n" + base64.b64encode(spki).decode("ascii") + "\n-----END PUBLIC KEY-----\n"


PROFILE = {"service_url": "https://management.example.invalid", "public_key_pem": public_key_fixture(), "allow_insecure_loopback": False}
REGISTRATION = dict(PROFILE, installation_id="9d40fc3e-1b69-451f-a206-daf3a494543e", installation_token="fixture-token-" + "x" * 32)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.settings = studio.server_settings(Path("C:/Users/한국 이름/Studio/python.exe"))

    def test_preserves_unrelated_tables_comments_and_quoted_header(self):
        original = '# Keep this comment\nmodel = "gpt-test"\n\n[mcp_servers.other]\ncommand = "other"\n\n[projects."C:/my project"]\ntrust_level = "trusted"\n'
        updated = studio.replace_config(original, self.settings)
        self.assertTrue(updated.startswith(original))
        self.assertEqual(studio.target_config(updated), self.settings)
        self.assertEqual(studio.replace_config(updated, self.settings), updated)
        self.assertEqual(studio.without_target(updated).rstrip(), original.rstrip())
        quoted = updated.replace('[mcp_servers.rhino-studio', '[mcp_servers."rhino-studio"')
        self.assertEqual(studio.without_target(quoted).rstrip(), original.rstrip())

    def test_header_inside_multiline_string_is_not_removed(self):
        original = 'instructions = """\n[mcp_servers.rhino-studio]\nThis is an example, not a table.\n"""\n[other]\nvalue = 1\n'
        updated = studio.replace_config(original, self.settings)
        self.assertTrue(updated.startswith(original))
        self.assertEqual(studio.without_target(updated).rstrip(), original.rstrip())

    def test_refuses_inline_config_instead_of_deleting_other_settings(self):
        original = 'mcp_servers = {rhino-studio = {command = "mine"}, other = {command = "keep"}}\n'
        with self.assertRaises(studio.InstallError):
            studio.replace_config(original, self.settings)

    def test_refuses_invalid_toml(self):
        with self.assertRaises(studio.InstallError):
            studio.target_config('[broken')


class FilesystemTests(unittest.TestCase):
    def test_rejects_unowned_directory_and_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "studio"
            root.mkdir()
            (root / "unrelated.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(studio.InstallError):
                studio.checked_root(root)
            with self.assertRaises(studio.InstallError):
                studio.inside(root, root / "../unrelated")
            self.assertEqual((root / "unrelated.txt").read_text(), "keep")

    def test_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            outside = base / "outside"
            outside.mkdir()
            alias = base / "alias"
            try:
                alias.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Creating symlinks needs a platform permission")
            with self.assertRaises(studio.InstallError):
                studio.checked_root(alias)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "studio"
        self.bundle = self.base / "bundle"
        (self.bundle / "wheels").mkdir(parents=True)
        (self.bundle / "plugin").mkdir()
        self.files = {
            "wheels/rhinomcp-0.5.0-py3-none-any.whl": b"test wheel",
            "plugin/rhinomcp-studio-0.5.0.yak": b"test plugin",
            "requirements.lock": b"dependency==1.0 --hash=sha256:fake\n",
            "management-server.json": json.dumps(PROFILE).encode("utf-8"),
        }
        for relative, data in self.files.items():
            (self.bundle / relative).write_bytes(data)
        self.manifest = {"name": studio.PACKAGE, "version": "0.5.0", "wheel": next(iter(self.files)),
                         "plugin": "plugin/rhinomcp-studio-0.5.0.yak",
                         "management_profile": "management-server.json",
                         "sha256": {key: hashlib.sha256(value).hexdigest() for key, value in self.files.items()}}
        (self.bundle / "bundle.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        self.config = self.base / "codex/config.toml"
        self.original = '# Other settings remain byte-for-byte\nmodel = "existing"\n\n[mcp_servers.keep]\ncommand = "keep"\n'
        studio.write_atomic(self.config, self.original)
        self.args = argparse.Namespace(install_root=self.root, bundle=str(self.bundle), uv=str(self.base / "uv"),
                                       rhino_path=None, codex_config=str(self.config), replace_upstream=False)
        self.registration_path = self.base / "per-user/management.json"
        self.commands = []
        self.packages = {}
        self.patches = [
            patch.object(studio, "locate_yak", return_value=self.base / "yak"),
            patch.object(studio, "require_rhino_closed"),
            patch.object(studio, "installed_packages", side_effect=lambda _: dict(self.packages)),
            patch.object(studio, "manual_upstream_plugin", return_value=[]),
            patch.object(studio, "run", side_effect=self.fake_run),
            patch.object(studio, "require_supported_rhino", return_value="8.29"),
            patch.object(studio, "management_path", return_value=self.registration_path),
            patch.object(studio, "enroll", return_value=REGISTRATION),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def fake_run(self, command, **kwargs):
        command = [str(value) for value in command]
        self.commands.append(command)
        if "venv" in command:
            folder = Path(command[-1])
            python = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            python.parent.mkdir(parents=True)
            python.write_text("fake", encoding="utf-8")
        if command[0].endswith("yak") and command[1] == "install":
            self.packages[studio.PACKAGE] = "0.5.0"
        elif command[0].endswith("yak") and command[1] == "uninstall":
            self.packages.pop(command[2], None)
        return "ok"

    def test_install_reinstall_and_uninstall_preserve_other_config(self):
        studio.install(self.args)
        after_first = studio.read_text(self.config)
        self.assertTrue(after_first.startswith(self.original))
        self.assertEqual(studio.load_state(self.root)["version"], "0.5.0")
        install_calls = len([call for call in self.commands if "sync" in call])
        studio.install(self.args)
        self.assertEqual(studio.read_text(self.config), after_first)
        self.assertEqual(len([call for call in self.commands if "sync" in call]), install_calls)
        studio.uninstall(self.args)
        self.assertEqual(studio.read_text(self.config).rstrip(), self.original.rstrip())
        self.assertFalse((self.root / "state.json").exists())

    def test_user_modified_registration_is_not_overwritten_or_removed(self):
        studio.install(self.args)
        updated = studio.read_text(self.config).replace('tool_timeout_sec = 120', 'tool_timeout_sec = 180')
        studio.write_atomic(self.config, updated)
        calls = len(self.commands)
        with self.assertRaises(studio.InstallError):
            studio.install(self.args)
        with self.assertRaises(studio.InstallError):
            studio.uninstall(self.args)
        self.assertEqual(studio.read_text(self.config), updated)
        self.assertEqual(len(self.commands), calls)
        self.assertTrue((self.root / "state.json").exists())

    def test_upstream_collision_requires_explicit_option(self):
        self.packages["rhinomcp"] = "0.4.1"
        with self.assertRaises(studio.InstallError):
            studio.install(self.args)
        self.assertEqual(self.commands, [])
        self.assertEqual(studio.read_text(self.config), self.original)
        self.args.replace_upstream = True
        studio.install(self.args)
        self.assertTrue(any(call[-2:] == ["uninstall", "rhinomcp"] for call in self.commands))

    def test_does_not_adopt_another_studio_installation(self):
        self.packages[studio.PACKAGE] = "0.5.0"
        with self.assertRaisesRegex(studio.InstallError, "does not own"):
            studio.install(self.args)
        self.assertEqual(self.commands, [])
        self.assertEqual(studio.read_text(self.config), self.original)

    def test_does_not_remove_a_plugin_updated_elsewhere(self):
        studio.install(self.args)
        self.packages[studio.PACKAGE] = "0.6.0"
        registered = studio.read_text(self.config)
        with self.assertRaisesRegex(studio.InstallError, "updated outside"):
            studio.uninstall(self.args)
        self.assertEqual(studio.read_text(self.config), registered)
        self.assertEqual(self.packages[studio.PACKAGE], "0.6.0")

    def test_tampered_bundle_never_runs_an_installer(self):
        (self.bundle / self.manifest["wheel"]).write_bytes(b"corrupted")
        with self.assertRaises(studio.InstallError):
            studio.install(self.args)
        self.assertEqual(self.commands, [])
        self.assertEqual(studio.read_text(self.config), self.original)

    def test_failed_environment_install_leaves_existing_config_unchanged(self):
        original_run = self.fake_run
        def fail_install(command, **kwargs):
            if "sync" in command:
                raise studio.InstallError("simulated unavailable dependency")
            return original_run(command, **kwargs)
        with patch.object(studio, "run", side_effect=fail_install):
            with self.assertRaises(studio.InstallError):
                studio.install(self.args)
        self.assertEqual(studio.read_text(self.config), self.original)
        self.assertFalse((self.root / "releases/0.5.0").exists())
        self.assertNotIn(studio.PACKAGE, self.packages)

    def test_same_version_reinstall_detects_missing_python(self):
        studio.install(self.args)
        state = studio.load_state(self.root)
        Path(state["settings"]["command"]).unlink()
        with self.assertRaisesRegex(studio.InstallError, "incomplete"):
            studio.install(self.args)

    def test_uninstall_can_resume_after_plugin_was_already_removed(self):
        studio.install(self.args)
        self.packages.clear()
        studio.uninstall(self.args)
        self.assertFalse((self.root / "state.json").exists())
        self.assertEqual(studio.read_text(self.config).rstrip(), self.original.rstrip())

    def test_package_parser_ignores_directory_banner(self):
        with patch.object(studio, "run", return_value='Package directory: C:\\packages\\8.0\nrhinomcp-studio (0.5.0)\nrhinomcp (0.4.1)'):
            # Temporarily bypass the lifecycle test's package-list stub.
            self.patches[2].stop()
            try:
                self.assertEqual(studio.installed_packages(self.base / "yak"), {"rhinomcp-studio": "0.5.0", "rhinomcp": "0.4.1"})
            finally:
                self.patches[2].start()

    def test_reinstall_reuses_identity_without_enrolling_again(self):
        studio.install(self.args)
        before = self.registration_path.read_bytes()
        with patch.object(studio, "enroll", side_effect=AssertionError("Must not create a new identity")):
            studio.install(self.args)
        self.assertEqual(self.registration_path.read_bytes(), before)
        self.assertNotIn(REGISTRATION["installation_token"], (self.root / "state.json").read_text())

    def test_missing_registration_does_not_reset_a_disabled_identity(self):
        studio.install(self.args)
        self.registration_path.unlink()
        before = studio.read_text(self.config)
        with patch.object(studio, "enroll", side_effect=AssertionError("Must not enroll again")):
            with self.assertRaisesRegex(studio.InstallError, "not reset"):
                studio.install(self.args)
        self.assertEqual(studio.read_text(self.config), before)

    def test_offline_enrollment_leaves_rhino_and_codex_unchanged(self):
        with patch.object(studio, "enroll", side_effect=studio.InstallError("server unavailable")):
            with self.assertRaises(studio.InstallError):
                studio.install(self.args)
        self.assertEqual(self.commands, [])
        self.assertEqual(studio.read_text(self.config), self.original)
        self.assertFalse(self.registration_path.exists())
        self.assertFalse((self.root / "state.json").exists())

    def test_failed_state_write_restores_prior_registration_config_and_state(self):
        studio.install(self.args)
        before_config = self.config.read_bytes()
        before_registration = self.registration_path.read_bytes()
        before_state = (self.root / "state.json").read_bytes()
        write = studio.write_atomic
        def write_then_fail(path, content):
            write(path, content)
            if path == self.root / "state.json" and content.encode("utf-8") != before_state:
                raise OSError("simulated state persistence failure")
        with patch.object(studio, "write_atomic", side_effect=write_then_fail):
            with self.assertRaises(OSError):
                studio.install(self.args)
        self.assertEqual(self.config.read_bytes(), before_config)
        self.assertEqual(self.registration_path.read_bytes(), before_registration)
        self.assertEqual((self.root / "state.json").read_bytes(), before_state)

    def test_new_install_failure_removes_new_registration(self):
        original_run = self.fake_run
        def fail_plugin(command, **kwargs):
            if "install" in command:
                raise studio.InstallError("simulated plugin install failure")
            return original_run(command, **kwargs)
        with patch.object(studio, "run", side_effect=fail_plugin):
            with self.assertRaises(studio.InstallError):
                studio.install(self.args)
        self.assertFalse(self.registration_path.exists())
        self.assertFalse((self.root / "state.json").exists())
        self.assertEqual(studio.read_text(self.config), self.original)

    def test_other_custom_root_cannot_adopt_fixed_registration(self):
        studio.install(self.args)
        before = self.registration_path.read_bytes()
        with self.assertRaisesRegex(studio.InstallError, "another installation"):
            studio.prepare_registration(PROFILE, "0.6.0", {}, self.base / "another-root", False)
        self.assertEqual(self.registration_path.read_bytes(), before)

    def test_service_change_requires_explicit_flag(self):
        studio.install(self.args)
        new_profile = dict(PROFILE, service_url="https://new-operator.example.invalid")
        state = studio.load_state(self.root)
        with patch.object(studio, "enroll", return_value=dict(REGISTRATION, **new_profile)) as enrollment:
            with self.assertRaisesRegex(studio.InstallError, "--change-management-service"):
                studio.prepare_registration(new_profile, "0.6.0", state, self.root, False)
            enrollment.assert_not_called()
            _, _, updated = studio.prepare_registration(new_profile, "0.6.0", state, self.root, True)
        self.assertEqual(json.loads(updated)["service_url"], new_profile["service_url"])

    def test_uninstall_preserves_modified_management_registration(self):
        studio.install(self.args)
        before = studio.read_text(self.config)
        for content in ('{"unrelated": true}', ""):
            with self.subTest(content=content):
                self.registration_path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(studio.InstallError, "preserved"):
                    studio.uninstall(self.args)
                self.assertEqual(self.registration_path.read_text(), content)
                self.assertEqual(studio.read_text(self.config), before)

    def test_doctor_reports_status_without_secrets(self):
        studio.install(self.args)
        def diagnostic(command="describe_capabilities"):
            if command == "describe_capabilities":
                return {"version": "0.5.0", "commands": []}
            return {"configured": True, "state": "blocked", "reason": REGISTRATION["installation_token"],
                    "installation_id": REGISTRATION["installation_id"], "service_url": PROFILE["service_url"],
                    "installation_token": REGISTRATION["installation_token"], "public_key_pem": PROFILE["public_key_pem"]}
        output = io.StringIO()
        with patch.object(studio, "bridge_status", side_effect=diagnostic), patch.object(studio, "run", return_value="ok"), redirect_stdout(output):
            studio.doctor(self.args)
        report = json.loads(output.getvalue())
        self.assertTrue(report["management_registered"])
        self.assertTrue(report["management_registration_matches"])
        self.assertEqual(report["management_status"]["state"], "blocked")
        self.assertNotIn(REGISTRATION["installation_token"], output.getvalue())
        self.assertNotIn("public_key_pem", output.getvalue())
        self.assertEqual(report["management_status"]["reason"], "[redacted]")

    def test_doctor_rejects_unconfigured_or_mismatched_plugin_registration(self):
        studio.install(self.args)
        matching = {"configured": True, "state": "allowed", "installation_id": REGISTRATION["installation_id"],
                    "service_url": PROFILE["service_url"]}
        for change in ({"configured": False}, {"configured": "true"}, {"installation_id": None},
                       {"installation_id": "d87659ad-a3b2-41f2-9cf9-c588ffaf4585"}, {"service_url": "https://other.example.invalid"}):
            with self.subTest(change=change):
                output = io.StringIO()
                responses = [{"version": "0.5.0", "commands": []}, dict(matching, **change)]
                with patch.object(studio, "bridge_status", side_effect=responses), patch.object(studio, "run", return_value="ok"), redirect_stdout(output):
                    with self.assertRaisesRegex(studio.InstallError, "Diagnosis needs attention"):
                        studio.doctor(self.args)
                report = json.loads(output.getvalue())
                self.assertTrue(report["management_status_available"])
                self.assertFalse(report["management_registration_matches"])

    def test_doctor_accepts_matching_registration_without_claiming_online_approval(self):
        studio.install(self.args)
        for policy_state in ("blocked", "unavailable", "not_checked"):
            with self.subTest(policy_state=policy_state):
                output = io.StringIO()
                responses = [{"version": "0.5.0", "commands": []},
                             {"configured": True, "state": policy_state, "installation_id": REGISTRATION["installation_id"],
                              "service_url": PROFILE["service_url"]}]
                with patch.object(studio, "bridge_status", side_effect=responses), patch.object(studio, "run", return_value="ok"), redirect_stdout(output):
                    studio.doctor(self.args)
                report = json.loads(output.getvalue())
                self.assertTrue(report["management_registration_matches"])
                self.assertEqual(report["management_status"]["state"], policy_state)
                self.assertNotIn("allowed", report["management_status"])


class ManagementProfileTests(unittest.TestCase):
    def test_production_https_and_explicit_loopback_demo(self):
        self.assertEqual(studio.validate_profile(PROFILE), PROFILE)
        for url in ("http://127.0.0.1:8765", "http://[::1]:8765", "http://localhost:8765"):
            self.assertTrue(studio.validate_profile(dict(PROFILE, service_url=url, allow_insecure_loopback=True))["allow_insecure_loopback"])

    def test_rejects_unsafe_urls_and_extra_secrets(self):
        urls = ("http://example.org", "http://127.0.0.1:8765", "https://user:password@example.org", "https://example.org?token=x", "https://example.org#fragment", "https://example.org?", "https://example.org#", "https://example.org\\other", "https://example.org\n", "https://example.org/base")
        for url in urls:
            with self.subTest(url=url), self.assertRaises(studio.InstallError):
                studio.validate_profile(dict(PROFILE, service_url=url))
        for url in ("http://127.0.0.2", "http://example.org"):
            with self.subTest(url=url), self.assertRaises(studio.InstallError):
                studio.validate_profile(dict(PROFILE, service_url=url, allow_insecure_loopback=True))
        for key in ("private_key_pem", "admin_password", "installation_token"):
            with self.subTest(key=key), self.assertRaises(studio.InstallError):
                studio.validate_profile(dict(PROFILE, **{key: "secret"}))

    def test_rejects_private_or_malformed_public_keys(self):
        for key in ("", "-----BEGIN PRIVATE KEY-----\nYWJj\n-----END PRIVATE KEY-----", "-----BEGIN PUBLIC KEY-----\nYWJj\n-----END PUBLIC KEY-----"):
            with self.subTest(key=key), self.assertRaises(studio.InstallError):
                studio.validate_profile(dict(PROFILE, public_key_pem=key))

    def test_enrollment_request_is_bounded_and_strict(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 201
        response.read.return_value = json.dumps({key: REGISTRATION[key] for key in ("installation_id", "installation_token")}).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(studio.urllib.request, "build_opener", return_value=opener), patch.object(studio.sys, "platform", "win32"):
            self.assertEqual(studio.enroll(PROFILE, "0.6.0"), REGISTRATION)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, PROFILE["service_url"] + "/v1/enroll")
        self.assertEqual(json.loads(request.data), {"client_version": "0.6.0", "platform": "windows"})
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 5)
        response.read.assert_called_once_with(studio.MAX_MANAGEMENT_BYTES + 1)
        self.assertIsNone(studio.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid"))

    def test_network_failure_does_not_leak_response_or_offer_offline_fallback(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError("secret-value")
        with patch.object(studio.urllib.request, "build_opener", return_value=opener), patch.object(studio.sys, "platform", "win32"):
            with self.assertRaisesRegex(studio.InstallError, "no offline") as error:
                studio.enroll(PROFILE, "0.6.0")
        self.assertNotIn("secret-value", str(error.exception))


class BundleManagementTests(unittest.TestCase):
    def setUp(self):
        build_spec = importlib.util.spec_from_file_location("studio_build", Path(__file__).resolve().parents[1] / "build.py")
        self.builder = importlib.util.module_from_spec(build_spec)
        with patch.dict(sys.modules, {"manager": studio}):
            build_spec.loader.exec_module(self.builder)

    def test_missing_profile_refuses_build(self):
        with self.assertRaisesRegex(studio.InstallError, "No management server configured"):
            self.builder.build(argparse.Namespace())

    def test_bundle_contains_only_public_profile_with_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            version = studio.tomllib.loads((self.builder.REPO / "server/pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
            profile = base / "public.json"
            profile.write_text(json.dumps(PROFILE), encoding="utf-8")
            wheel = base / f"rhinomcp-{version}-py3-none-any.whl"
            wheel.write_bytes(b"wheel-fixture")
            plugin = base / f"rhinomcp-studio-{version}.yak"
            with zipfile.ZipFile(plugin, "w") as archive:
                archive.writestr("manifest.yml", f"name: rhinomcp-studio\nversion: {version}\n")
            args = argparse.Namespace(output=str(base / "dist"), wheel=str(wheel), plugin=str(plugin), management_profile=str(profile))
            with patch.object(self.builder.shutil, "which", return_value="uv"), patch.object(self.builder, "run", return_value="dependency==1\n"):
                output = self.builder.build(args)
            with zipfile.ZipFile(output) as archive:
                prefix = f"rhinomcp-studio-{version}/"
                public = archive.read(prefix + "management-server.json")
                metadata = json.loads(archive.read(prefix + "bundle.json"))
                self.assertEqual(json.loads(public), PROFILE)
                self.assertEqual(metadata["management_profile"], "management-server.json")
                self.assertEqual(metadata["sha256"]["management-server.json"], hashlib.sha256(public).hexdigest())
                self.assertFalse(metadata["local_demo_only"])
                for relative in ("docs/VALIDATION_KO.md", "management/README_KO.md"):
                    self.assertEqual(metadata["sha256"][relative], hashlib.sha256(archive.read(prefix + relative)).hexdigest())
                for name in archive.namelist():
                    self.assertNotIn(REGISTRATION["installation_token"].encode(), archive.read(name))


if __name__ == "__main__":
    unittest.main()
