"""Architecture input/contract/transport tests, not Rhino geometry integration tests."""

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from jsonschema import Draft202012Validator

from rhinomcp.tools.architecture import create_floor_slab, create_wall


WALL = {"start": [0, 0, 0], "end": [6000, 0, 0], "height": 3000, "thickness": 200}
DOOR = {"offset": 800, "width": 900, "bottom": 0, "height": 2100}
WINDOW = {"offset": 3000, "width": 1500, "bottom": 900, "height": 1200}
OUTER = [[0, 0, 3000], [6000, 0, 3000], [6000, 4000, 3000], [0, 4000, 3000]]
HOLE = [[1000, 1000, 3000], [2000, 1000, 3000], [2000, 2000, 3000], [1000, 2000, 3000]]


@pytest.fixture
def connection():
    with patch("rhinomcp.tools.architecture.get_rhino_connection") as get_connection:
        connection = MagicMock()
        get_connection.return_value = connection
        yield connection


def test_wall_forwards_openings_attributes_and_preserves_health_response(connection):
    response = {"id": "object-id", "volume": 2862000000, "geometry_health": {"is_solid": True}, "_delta": {"created_ids": ["object-id"]}}
    connection.send_command.return_value = response
    result = create_wall(None, **WALL, openings=[DOOR, WINDOW], layer="Architecture::Walls", name="W-01")
    connection.send_command.assert_called_once_with("create_wall", {
        **WALL, "openings": [DOOR, WINDOW], "layer": "Architecture::Walls", "name": "W-01"
    })
    assert result is response


def test_slab_forwards_holes_without_changing_winding_or_coordinates(connection):
    outer = copy.deepcopy(OUTER)
    holes = [list(reversed(copy.deepcopy(HOLE)))]
    result = create_floor_slab(None, outer, 200, holes=holes)
    connection.send_command.assert_called_once_with("create_floor_slab", {"outer": OUTER, "thickness": 200, "holes": holes})
    assert outer == OUTER
    assert result is connection.send_command.return_value


def test_empty_optional_lists_and_attributes(connection):
    create_wall(None, **WALL)
    connection.send_command.assert_called_with("create_wall", {**WALL, "openings": []})
    create_floor_slab(None, OUTER, 200)
    connection.send_command.assert_called_with("create_floor_slab", {"outer": OUTER, "thickness": 200, "holes": []})


@pytest.mark.parametrize("changes", [
    {"height": 0}, {"height": -1}, {"height": float("nan")}, {"thickness": float("inf")},
    {"thickness": True}, {"start": [0, 0]}, {"start": [0, 0, float("-inf")]},
    {"end": [0, 0, 30]}, {"end": [float("inf"), 0, 0]}, {"layer": " "},
    {"openings": "door"}, {"openings": [{}]}, {"openings": [{**DOOR, "extra": 1}]},
    {"openings": [{**DOOR, "offset": 0}]}, {"openings": [{**DOOR, "width": -1}]},
    {"openings": [{**DOOR, "bottom": -1}]}, {"openings": [{**DOOR, "height": 3000}]},
    {"openings": [{**DOOR, "offset": 5900}]}, {"openings": [{**DOOR, "offset": float("nan")}]},
    {"openings": [DOOR, DOOR]}, {"openings": [DOOR, {**DOOR, "offset": 1700}]},
    {"openings": [WINDOW, {**WINDOW, "bottom": 2100, "height": 200}]},
])
def test_wall_rejects_invalid_input_before_transport(connection, changes):
    with pytest.raises(ValueError):
        create_wall(None, **{**WALL, **changes})
    connection.send_command.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"outer": []}, {"outer": [[0, 0, 0], [1, 0, 0], [0, 0, 0]]},
    {"outer": [OUTER[0], OUTER[1], OUTER[0], OUTER[2]]},
    {"outer": [[0, 0, 0], [1, 0, 0], [1, float("nan"), 0]]},
    {"thickness": 0}, {"thickness": float("inf")}, {"holes": "hole"},
    {"holes": [[]]}, {"holes": [[[0, 0], [1, 0], [1, 1]]]},
])
def test_slab_rejects_malformed_input_before_transport(connection, changes):
    with pytest.raises(ValueError):
        create_floor_slab(None, **{"outer": OUTER, "thickness": 200, **changes})
    connection.send_command.assert_not_called()


def test_closing_vertex_is_allowed(connection):
    create_floor_slab(None, OUTER + [OUTER[0]], 200)
    connection.send_command.assert_called_once()


def test_vertically_separated_openings_are_allowed(connection):
    create_wall(None, **WALL, openings=[{**DOOR, "height": 1000}, {**DOOR, "bottom": 1200, "height": 1000}])
    connection.send_command.assert_called_once()


@pytest.mark.parametrize("tool,args", [(create_wall, WALL), (create_floor_slab, {"outer": OUTER, "thickness": 200})])
def test_kernel_validation_errors_propagate(connection, tool, args):
    connection.send_command.side_effect = RuntimeError("Polygon must not self-intersect")
    with pytest.raises(RuntimeError, match="self-intersect"):
        tool(None, **args)


def _validator(command):
    path = Path(__file__).parents[2] / "contracts" / "commands" / f"{command}.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.mark.parametrize("command,payload", [
    ("create_wall", {**WALL, "openings": [DOOR, WINDOW]}),
    ("create_floor_slab", {"outer": OUTER, "thickness": 200, "holes": [HOLE]}),
])
def test_contract_accepts_documented_examples(command, payload):
    assert not list(_validator(command).iter_errors(payload))


@pytest.mark.parametrize("command,payload", [
    ("create_wall", {**WALL, "height": 0}),
    ("create_wall", {**WALL, "start": [0, 0]}),
    ("create_wall", {**WALL, "openings": [{**DOOR, "bottom": -1}]}),
    ("create_wall", {**WALL, "openings": [{"width": 900}]}),
    ("create_wall", {**WALL, "openings": [{**DOOR, "x_offset": 3}]}),
    ("create_floor_slab", {"outer": OUTER, "thickness": -1}),
    ("create_floor_slab", {"outer": OUTER, "thickness": 200, "holes": [None]}),
    ("create_floor_slab", {"outer": OUTER, "thickness": 200, "delete_sources": True}),
])
def test_contract_rejects_bad_shape_or_unrequested_parameters(command, payload):
    assert list(_validator(command).iter_errors(payload))
