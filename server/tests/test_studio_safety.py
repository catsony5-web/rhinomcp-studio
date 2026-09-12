"""Regressions that exercise the send boundary, rather than a mock geometry kernel."""

import socket
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("failure", [socket.timeout(), ConnectionResetError(), OSError()])
def test_lost_mutation_response_never_resends(failure):
    import rhinomcp.server as srv

    sock = MagicMock()
    sock.recv.side_effect = failure
    conn = srv.RhinoConnection("127.0.0.1", 1999, sock=sock)
    with pytest.raises(srv.RhinoCommandOutcomeUnknownError, match="Do not repeat"):
        conn._send_command_locked("create_object", {"type": "BOX"})
    sock.sendall.assert_called_once()
    assert conn.sock is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_input_is_rejected_before_any_socket_call(value):
    import rhinomcp.server as srv

    sock = MagicMock()
    conn = srv.RhinoConnection("127.0.0.1", 1999, sock=sock)
    with pytest.raises(ValueError):
        conn.send_command("create_object", {"params": {"width": value}})
    sock.sendall.assert_not_called()


def test_missing_contract_blocks_strict_request(monkeypatch):
    import rhinomcp.server as srv
    import rhinomcp.validation as validation

    monkeypatch.setattr(srv, "RHINO_VALIDATE", "strict")
    monkeypatch.setattr(validation, "_schema_cache", {})
    def missing_schema(path):
        raise FileNotFoundError("missing packaged schema")
    monkeypatch.setattr(validation, "_load_schema", missing_schema)
    sock = MagicMock()
    conn = srv.RhinoConnection("127.0.0.1", 1999, sock=sock)
    with pytest.raises(ValueError, match="missing packaged schema"):
        conn.send_command("create_object", {"type": "BOX"})
    sock.sendall.assert_not_called()


def test_missing_validator_does_not_silently_pass(monkeypatch):
    import rhinomcp.validation as validation

    monkeypatch.setattr(validation, "HAS_JSONSCHEMA", False)
    with pytest.raises(RuntimeError, match="jsonschema is missing"):
        validation.validate_command("create_object", {})
    assert validation.validate_command("create_object", {}, raise_on_error=False) is False


def test_mismatched_plugin_cannot_receive_mutation(monkeypatch):
    import rhinomcp.server as srv

    monkeypatch.setattr(srv, "RHINO_REQUIRE_MATCH", True)
    monkeypatch.setattr(srv, "server_version", lambda: "0.5.0")
    sock = MagicMock()
    conn = srv.RhinoConnection("127.0.0.1", 1999, sock=sock)
    conn._capabilities = {"version": "0.4.1", "commands": []}
    with pytest.raises(srv.UnsupportedCommandError, match="Modeling was not sent"):
        conn.send_command("create_object", {"type": "BOX", "params": {"width": 1, "length": 1, "height": 1}})
    sock.sendall.assert_not_called()


def test_corrupt_mutation_response_is_unknown():
    import rhinomcp.server as srv

    sock = MagicMock()
    conn = srv.RhinoConnection("127.0.0.1", 1999, sock=sock)
    conn.receive_full_response = lambda _: b"invalid JSON"
    with pytest.raises(srv.RhinoCommandOutcomeUnknownError):
        conn._send_command_locked("modify_object", {})
    sock.sendall.assert_called_once()
