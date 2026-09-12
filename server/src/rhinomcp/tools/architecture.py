"""Coordinate-based architectural solids; Rhino validates topology and tolerance."""

import math
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from typing_extensions import TypedDict

from rhinomcp.server import get_rhino_connection, mcp


class WallOpening(TypedDict):
    offset: float
    width: float
    bottom: float
    height: float


def _number(value: float, label: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")


def _point(point: List[float], label: str) -> None:
    if not isinstance(point, (list, tuple)) or len(point) != 3:
        raise ValueError(f"{label} must be [x,y,z]")
    for coordinate in point:
        _number(coordinate, label)


def _polygon(points: List[List[float]], label: str) -> None:
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        raise ValueError(f"{label} must contain at least three vertices")
    for point in points:
        _point(point, label)
    vertices = points[:-1] if points[0] == points[-1] else points
    if len(vertices) < 3 or len({tuple(point) for point in vertices}) != len(vertices):
        raise ValueError(f"{label} must have distinct vertices (one closing vertex is allowed)")


def _attributes(params: Dict[str, Any], layer: Optional[str], name: Optional[str]) -> None:
    for key, value in (("layer", layer), ("name", name)):
        if value is not None:
            if not isinstance(value, str) or (key == "layer" and not value.strip()):
                raise ValueError(f"{key} must be a {'nonempty ' if key == 'layer' else ''}string")
            params[key] = value


@mcp.tool(annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def create_wall(
    ctx: Context,
    start: List[float],
    end: List[float],
    height: float,
    thickness: float,
    openings: Optional[List[WallOpening]] = None,
    layer: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one closed straight wall Brep in document units, preserving existing objects.

    start/end are [x,y,z] on the horizontal base centerline. Height goes +Z;
    thickness is centered on the line. Opening offset is measured from start
    towards end; bottom is above the base, with zero allowed for doors. Openings
    must clear both ends/top and each other by more than document tolerance.
    layer is an existing full path or GUID (omitted uses the current layer).
    Returns object GUID, actual/expected volumes and geometry_health. This is
    plain Rhino geometry, without BIM semantics or a parametric editing history.
    """
    _point(start, "start")
    _point(end, "end")
    _number(height, "height", positive=True)
    _number(thickness, "thickness", positive=True)
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    _number(length, "baseline length", positive=True)
    if openings is not None and not isinstance(openings, list):
        raise ValueError("openings must be an array")
    normalized = []
    for opening in openings or []:
        if not isinstance(opening, dict) or set(opening) != {"offset", "width", "bottom", "height"}:
            raise ValueError("Each opening needs exactly offset, width, bottom, height")
        for key, value in opening.items():
            _number(value, f"opening.{key}", positive=key in ("width", "height", "offset"))
        if opening["bottom"] < 0 or opening["offset"] + opening["width"] >= length or opening["bottom"] + opening["height"] >= height:
            raise ValueError("Opening must fit inside wall ends and top, with nonnegative bottom")
        for other in normalized:
            if (opening["offset"] <= other["offset"] + other["width"]
                and other["offset"] <= opening["offset"] + opening["width"]
                and opening["bottom"] <= other["bottom"] + other["height"]
                and other["bottom"] <= opening["bottom"] + opening["height"]):
                raise ValueError("Openings must not overlap or touch")
        normalized.append(dict(opening))
    params = {"start": start, "end": end, "height": height, "thickness": thickness, "openings": normalized}
    _attributes(params, layer, name)
    return get_rhino_connection().send_command("create_wall", params)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def create_floor_slab(
    ctx: Context,
    outer: List[List[float]],
    thickness: float,
    holes: Optional[List[List[List[float]]]] = None,
    layer: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one closed floor Brep from horizontal polygons in document units.

    Each vertex is [x,y,z]. outer[0].z is the TOP; thickness extends downward
    in world -Z. A repeated closing vertex is optional; winding is irrelevant.
    All vertices must have the same Z within document tolerance (then projected
    to outer[0].z). Holes must be strictly inside, disjoint and nonnested;
    self intersections, boundary touching and degenerate edges are rejected.
    layer is an existing full path or GUID. Returns GUID, expected/actual volume
    and geometry_health. No source objects are created or changed.
    """
    _polygon(outer, "outer")
    _number(thickness, "thickness", positive=True)
    if holes is not None and not isinstance(holes, list):
        raise ValueError("holes must be an array")
    for index, hole in enumerate(holes or []):
        _polygon(hole, f"holes[{index}]")
    params = {"outer": outer, "thickness": thickness, "holes": holes or []}
    _attributes(params, layer, name)
    return get_rhino_connection().send_command("create_floor_slab", params)
