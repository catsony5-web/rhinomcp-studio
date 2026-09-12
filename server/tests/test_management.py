"""A management refusal must never become a retry or an uncertain mutation."""

import json
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import rhinomcp
from rhinomcp.server import ManagementPolicyError, RhinoConnection
from rhinomcp.validation import validate_command, validate_response


STATUS = {
    "configured": True, "state": "maintenance", "reason": "점검 중",
    "installation_id": "10236a96-2e08-4b0e-88dd-8dff0c406d50",
    "service_url": "https://manager.example.com",
    "last_checked_at": "2026-09-12T00:00:00Z", "version": "0.6.0",
}


@pytest.mark.parametrize("command", ["get_document_summary", "create_object", "run_command"])
def test_refusal_keeps_socket_and_does_not_retry(command):
    socket = MagicMock()
    connection = RhinoConnection("127.0.0.1", 1999, socket)
    answer = json.dumps({"status": "error", "error_code": "management_denied", "message": "점검 중"}).encode()
    with patch.object(connection, "receive_full_response", return_value=answer):
        with pytest.raises(ManagementPolicyError, match="점검 중"):
            connection._send_command_locked(command, {})
    assert socket.sendall.call_count == 1
    socket.close.assert_not_called()
    assert connection.sock is socket


@pytest.mark.asyncio
async def test_mcp_client_receives_refusal_reason():
    with patch("rhinomcp.tools.boolean_operations.get_rhino_connection", side_effect=ManagementPolicyError("점검 중: update required")):
        with pytest.raises(ToolError, match="점검 중: update required"):
            await rhinomcp.mcp.call_tool("boolean_union", {"object_ids": ["a", "b"]})


@pytest.mark.asyncio
async def test_status_is_readonly_and_available_without_running_geometry():
    connection = MagicMock()
    connection.send_command.return_value = STATUS
    with patch("rhinomcp.tools.get_management_status.get_rhino_connection", return_value=connection):
        await rhinomcp.mcp.call_tool("get_management_status", {})
    connection.send_command.assert_called_once_with("get_management_status", {})
    tool = next(t for t in await rhinomcp.mcp.list_tools() if t.name == "get_management_status")
    assert tool.annotations.read_only_hint is True


def test_status_contract_excludes_credentials_and_accepts_unconfigured_state():
    assert validate_command("get_management_status", {})
    assert validate_response("get_management_status", STATUS)
    assert validate_response("get_management_status", {**STATUS, "configured": False, "installation_id": None, "service_url": None, "last_checked_at": None})
    assert not validate_response("get_management_status", {**STATUS, "installation_token": "secret"}, raise_on_error=False)
    assert not validate_command("get_management_status", {"disable": True}, raise_on_error=False)
