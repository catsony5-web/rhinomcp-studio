import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_release as release
from test_manager import public_key_fixture


VERSION = "0.6.1"
PROFILE = {"service_url": "https://mcp.operator.org", "public_key_pem": public_key_fixture(),
           "allow_insecure_loopback": False}


def nested_zip(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return stream.getvalue()


class ReleaseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / f"rhinomcp-studio-{VERSION}.zip"
        names = ("manager.py requirements.lock bootstrap.ps1 bootstrap.sh install.ps1 install.sh "
                 "doctor.ps1 doctor.sh uninstall.ps1 uninstall.sh INSTALL_KO.md DISTRIBUTION_MANAGEMENT_KO.md "
                 "LICENSE PROVENANCE.md README.md docs/VALIDATION_KO.md management/README_KO.md").split()
        self.files = {name: b"release fixture\n" for name in names}
        self.wheel = f"wheels/rhinomcp-{VERSION}-py3-none-any.whl"
        self.plugin = f"plugin/rhinomcp-studio-{VERSION}-any.yak"
        self.files[self.wheel] = nested_zip({f"rhinomcp-{VERSION}.dist-info/METADATA": f"Name: rhinomcp\nVersion: {VERSION}\n"})
        self.files[self.plugin] = nested_zip({"manifest.yml": f"name: rhinomcp-studio\nversion: {VERSION}\n", "net8.0/rhinomcp.rhp": b"fixture"})
        self.files["management-server.json"] = json.dumps(PROFILE).encode()

    def write_zip(self, *, mutate=None, metadata_mutate=None):
        metadata = {"name": "rhinomcp-studio", "version": VERSION, "local_demo_only": False,
                    "wheel": self.wheel, "plugin": self.plugin, "management_profile": "management-server.json",
                    "sha256": {name: hashlib.sha256(value).hexdigest() for name, value in self.files.items()}}
        files = dict(self.files)
        if mutate:
            mutate(files)
        if metadata_mutate:
            metadata_mutate(metadata)
        files["bundle.json"] = json.dumps(metadata).encode()
        with zipfile.ZipFile(self.path, "w") as archive:
            for name, value in files.items():
                archive.writestr(f"rhinomcp-studio-{VERSION}/" + name, value)
        self.path.with_suffix(".zip.sha256").write_text(f"{hashlib.sha256(self.path.read_bytes()).hexdigest()}  {self.path.name}\n")

    def test_valid_package_is_checked_without_executing_installer(self):
        self.write_zip()
        report = release.verify_release(self.path, VERSION)
        self.assertEqual(report["version"], VERSION)
        self.assertEqual(report["profile"]["service_url"], PROFILE["service_url"])

    def test_rejects_corrupted_outer_archive(self):
        self.write_zip()
        with self.path.open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(release.ReleaseError, "checksum"):
            release.verify_release(self.path, VERSION)

    def test_rejects_inner_tampering_even_with_new_zip_checksum(self):
        self.write_zip(mutate=lambda files: files.update({"manager.py": b"tampered"}))
        with self.assertRaisesRegex(release.manager.InstallError, "checksum"):
            release.verify_release(self.path, VERSION)

    def test_rejects_extra_unchecked_file(self):
        self.write_zip(mutate=lambda files: files.update({"installation-token.txt": b"untracked"}))
        with self.assertRaisesRegex(release.ReleaseError, "Every bundled file"):
            release.verify_release(self.path, VERSION)

    def test_rejects_traversal_before_extracting(self):
        self.write_zip(mutate=lambda files: files.update({"../outside.txt": b"outside"}))
        with self.assertRaisesRegex(release.ReleaseError, "unsafe"):
            release.verify_release(self.path, VERSION)
        self.assertFalse((self.path.parent / "outside.txt").exists())

    def test_rejects_local_demo_even_with_https_profile(self):
        self.write_zip(metadata_mutate=lambda metadata: metadata.update(local_demo_only=True))
        with self.assertRaisesRegex(release.ReleaseError, "local demo"):
            release.verify_release(self.path, VERSION)

    def test_rejects_missing_installation_guide(self):
        del self.files["INSTALL_KO.md"]
        self.write_zip()
        with self.assertRaisesRegex(release.ReleaseError, "documentation"):
            release.verify_release(self.path, VERSION)

    def test_rejects_mislabeled_wheel_and_plugin_versions(self):
        for member, replacement in ((self.wheel, nested_zip({"rhinomcp-0.6.0.dist-info/METADATA": "Name: rhinomcp\nVersion: 0.6.0\n"})),
                                    (self.plugin, nested_zip({"manifest.yml": "name: rhinomcp-studio\nversion: 0.6.0\n", "net8.0/rhinomcp.rhp": "fixture"}))):
            with self.subTest(member=member):
                previous = self.files[member]
                self.files[member] = replacement
                self.write_zip()
                with self.assertRaisesRegex(release.ReleaseError, "version"):
                    release.verify_release(self.path, VERSION)
                self.files[member] = previous

    def test_rejects_local_private_and_nonpublic_origins(self):
        for origin in ("https://localhost", "https://127.0.0.1", "https://192.168.0.1", "https://[::1]", "https://host.local", "https://management.example.invalid"):
            with self.subTest(origin=origin), self.assertRaises(release.ReleaseError):
                release.public_profile(dict(PROFILE, service_url=origin))
        with patch.object(release.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 443))]):
            with self.assertRaisesRegex(release.ReleaseError, "resolve"):
                release.public_profile(PROFILE, resolve=True)


try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    CRYPTOGRAPHY = True
except ImportError:
    CRYPTOGRAPHY = False


@unittest.skipUnless(CRYPTOGRAPHY, "Online release checks require cryptography")
class ServiceApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.profile = dict(PROFILE, public_key_pem=cls.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())

    def probe(self, mutation=None, corrupt_signature=False, raw_mutation=None, enrollment_mutation=None):
        def response(url, data=None, token=None):
            if url.endswith("/healthz"):
                return {"status": "ok", "protocol": 1}
            if url.endswith("/v1/enroll"):
                enrollment = {"installation_id": "bd9106a1-6062-463e-9af5-51307265d9fa", "installation_token": "a" * 64}
                if enrollment_mutation:
                    enrollment_mutation(enrollment)
                return enrollment
            self.assertEqual(token, "a" * 64)
            self.assertEqual(data["version"], VERSION)
            now = int(time.time())
            grant = dict(data, protocol=1, allowed=True, code="allowed", reason="", issued_at=now, expires_at=now + 30)
            if mutation:
                mutation(grant)
            payload = json.dumps(grant).encode()
            if raw_mutation:
                payload = raw_mutation(payload)
            signature = self.key.sign(payload, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
            if corrupt_signature:
                signature = bytes([signature[0] ^ 1]) + signature[1:]
            return {"payload": base64.b64encode(payload).decode(), "signature": base64.b64encode(signature).decode()}
        with patch.object(release, "request_json", side_effect=response), patch.object(release.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]):
            release.check_service(self.profile, VERSION)

    def test_accepts_real_rsa_pss_bound_approval(self):
        self.probe()

    def test_rejects_invalid_signature(self):
        with self.assertRaises(InvalidSignature):
            self.probe(corrupt_signature=True)

    def test_rejects_replay_expiry_denial_and_wrong_version(self):
        for mutation in (lambda grant: grant.update(nonce="stale"), lambda grant: grant.update(expires_at=1),
                         lambda grant: grant.update(allowed=False, code="global_paused"), lambda grant: grant.update(version="0.6.0")):
            with self.subTest(mutation=mutation), self.assertRaises(release.ReleaseError):
                self.probe(mutation)

    def test_rejects_grants_that_real_rhino_cannot_parse(self):
        for mutation in (lambda grant: grant.pop("reason"), lambda grant: grant.update(reason=None),
                         lambda grant: grant.update(reason="x" * 2049),
                         lambda grant: grant.update(reason="\U0001f600" * 1025),
                         lambda grant: grant.update(protocol=True),
                         lambda grant: grant.update(issued_at=float(grant["issued_at"]))):
            with self.subTest(mutation=mutation), self.assertRaises(release.ReleaseError):
                self.probe(mutation)

    def test_accepts_rhino_reason_length_boundary(self):
        self.probe(lambda grant: grant.update(reason="\U0001f600" * 1024))

    def test_requires_exact_lifetime_and_request_start_window(self):
        with patch.object(release.time, "time", return_value=1700000000):
            for issued, expires in ((1700000000, 1700000010), (1699999994, 1700000024),
                                    (1700000006, 1700000036), (1700000000, 1700000031),
                                    (1700000000, True)):
                with self.subTest(issued=issued, expires=expires), self.assertRaises(release.ReleaseError):
                    self.probe(lambda grant: grant.update(issued_at=issued, expires_at=expires))
            self.probe(lambda grant: grant.update(issued_at=1699999995, expires_at=1700000025))

    def test_rejects_grant_after_monotonic_lifetime_even_if_wall_clock_is_valid(self):
        with patch.object(release.time, "monotonic", side_effect=[100, 130]):
            with self.assertRaises(release.ReleaseError):
                self.probe()

    def test_rejects_duplicate_signed_fields_before_using_the_last_value(self):
        with self.assertRaisesRegex(release.ReleaseError, "duplicate"):
            self.probe(raw_mutation=lambda raw: raw.replace(b'"allowed": true', b'"allowed": false, "allowed": true'))

    def test_rejects_enrollment_that_overrides_the_pinned_profile(self):
        with self.assertRaisesRegex(release.ReleaseError, "registration fields"):
            self.probe(enrollment_mutation=lambda value: value.update(service_url="https://other.operator.org"))


class JsonResponseTests(unittest.TestCase):
    def test_http_reader_rejects_duplicate_fields(self):
        with patch.object(release.urllib.request, "build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"payload":"old", "payload":"new", "signature":"value"}'
            with self.assertRaisesRegex(release.ReleaseError, "duplicate"):
                release.request_json("https://mcp.operator.org/v1/authorize")

    def test_rejects_duplicate_nested_fields_excessive_depth_and_non_json_numbers(self):
        for raw in (b'{"extra":{"a":1,"a":2}}', b'{"extra":[{"a":1,"a":2}]}',
                    b'{"extra":NaN}', b'{"extra":Infinity}',
                    b'{"extra":' * 9 + b'null' + b'}' * 9):
            with self.subTest(raw=raw), self.assertRaises(release.ReleaseError):
                release.parse_object(raw)
        self.assertIsInstance(release.parse_object(b'{"extra":' * 8 + b'null' + b'}' * 8), dict)
        for raw in ('{"protocol":1}'.encode("utf-16"), b'\xef\xbb\xbf{"protocol":1}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                release.parse_object(raw)


if __name__ == "__main__":
    unittest.main()
