# Architectural modeling in Rhino and Grasshopper

## Inspect and establish dimensions

Start with get_document_summary, then read relevant objects and layers. Check
document units and absolute tolerance before sending coordinates. Convert stated
millimeters/meters into document units; never change the document unit system to
make an example fit. Re-read the active document after a reconnect or document
switch. Preserve existing user geometry and Grasshopper definitions.

If Studio is not connected, use StudioMCPVersion/StudioMCPStart in Rhino to identify
and start the intended plugin, then reconnect Codex. A generic mcpstart command can
start another installed MCP product; inspect the actual Studio bridge/version
before any modeling. StudioMCPTest is a development test, not a read-only setup step.

Identify the baseline or boundary, base/top elevation, height, thickness, opening
positions, intended result count and target layer. Ask about missing values that
change the design rather than inventing them. Use existing object GUIDs when
deriving coordinates from user work. A viewport image alone does not establish
exact dimensions or world coordinates.

## Prefer the typed wall and slab tools

Use create_wall for a straight, vertical wall and create_floor_slab for a horizontal
polygon slab when their limits fit the request. Read their current schemas. These
produce plain closed Rhino Breps, without BIM types, material layers, automatic wall
joins or persistent parametric history. Do not promise those features.

For create_wall, start/end are [x,y,z] on the base centerline. Their Z values must
agree within document tolerance and start.z is used. Local X points from start to
end; local Y points left when viewed from above. Thickness is centered, half on
each side. Height goes in world +Z. openings is an array of
{offset, width, bottom, height}; offset is distance along local X and bottom is
height above the base. bottom=0 is a door notch; positive bottom makes a window.
Openings cut through the full thickness and need clearance greater than tolerance
from wall ends, the top and other openings. Positive dimensions and positive bottom
must exceed tolerance. Do not silently move or shrink an opening to make it fit.

For create_floor_slab, outer is an ordered polygon of [x,y,z] vertices and holes is
an optional array of polygons. outer[0].z is the TOP; positive thickness extends
DOWNWARD in world -Z. All Z values must agree within tolerance and are projected
to that top elevation. Winding may be either direction and a final repeated first
vertex is optional. Boundaries must be simple, closed and nondegenerate. Holes
must be strictly inside the outer boundary, pairwise disjoint and nonnested.
Crossing or touching boundaries are rejected. Do not discard a failed hole.

The layer parameter is an existing full path or GUID; omitting it uses the current
layer. Read or create the intended task layer explicitly before assigning it.
Retain id/result_ids, input dimensions and task ownership for later verification.

## Verify Rhino results

Both tools validate a closed manifold Brep and return geometry_health, expected_volume,
volume, volume_error and volume_tolerance. Inspect those fields, then independently
query the returned GUID with analyze_objects and measure_objects. Check location,
bounds, height/thickness, solid validity, opening placement and layer assignment.

Expected wall volume is (baseline length * height - sum(opening width * opening
height)) * thickness. Expected slab volume is (outer area - sum(hole areas)) *
thickness. Values are in document units cubed. Volume alone cannot prove that a
door is in the requested location; inspect representative views and geometry too.
Report unverified conditions explicitly. A successful tool call is not acceptance.

## Grasshopper definitions

Read gh_get_document_info and gh_list_components before changes. For a known owned
graph, use gh_get_graph with its graph_id. Search installed component types with
gh_search_components and read gh_get_component_type_info; confirm GUIDs, input and
output indices, access modes and required values instead of guessing from names.

Use gh_build_graph with a task-specific graph_id and aliases for a new graph.
Retain its instance-ID mapping. Use gh_mutate_graph for targeted edits to an existing
owned graph rather than rebuilding or clearing the user's canvas. Parameter values
represent document-scale lengths when the definition creates geometry; label units
and make the intended slider range explicit.

Run gh_run_solution when required and inspect runtime errors/warnings. Read relevant
outputs through gh_get_parameter_value or gh_get_graph(include_values=true), check
expected counts, branches and numeric values, and inspect the preview. A graph with
no errors but empty or incorrect outputs is not complete. Preview geometry is not
automatically a baked Rhino object; do not claim a Rhino object GUID unless one was
actually created and verified. Preserve unrelated components, wires and values.

## Uncertain execution

A timeout or disconnected response does not prove that a mutation failed. NEVER
retry an ambiguous create/edit/build/solve operation blindly. Read the current
document, known GUIDs, task layer or graph_id and reconcile the observed result
before deciding whether another mutation is needed. An automatic version mismatch
or validation rejection calls for diagnosis, not bypassing the check. Limit cleanup
to objects known to belong to this task and use the recovery topic when ownership
or execution state is uncertain.
