# Changelog

Server and plugin share one version. Update them together: the server sends
commands the matching plugin understands, and an older plugin silently ignores
parameters it does not know.

## 0.6.1 — production distribution preparation (2026-09-12)

- Prepare persistent management hosting on Render with HTTPS and first-start
  initialization that preserves existing credentials and signing keys.
- Publish Studio sources under catsony5-web/rhinomcp-studio and prepare validated
  installer assets as a GitHub Release draft. A public production management URL
  and actual external connection verification are required before end-user release.
- Keep 0.6.0 local-demo packages distinct from the production version. Existing
  local-demo installations require explicit management-service migration.
- Exclude deleted objects retained by Rhino Undo from all-object modifications;
  retain one modification per active object. Correct the rollback regression
  fixture to measure Rhino's actual Extrusion geometry without an invalid cast.
- Launch the installed MCP through the package entry point, preventing duplicate
  server module initialization from exposing an empty tool list. Verify the exact
  installer command using a real stdio connection and offline modeling guidance.

## 0.6.0 — managed distribution (prepared 2026-09-12)

- Require fresh online authorization at the Rhino TCP entry point for every new
  command except local capabilities and management status. Denied or unreachable
  service leaves the document untouched; in-flight work is allowed to finish.
- Verify a server RSA-PSS signature bound to installation, actual plugin version,
  command and random request nonce. Queued approvals expire after 30 seconds;
  approvals are not reused across requests.
- Add owner-operated SQLite management service, authenticated administration,
  global/version/installation maintenance controls and audit records.
- Register installations without user login, retain credentials during ordinary
  upgrades, and include only the server URL and public key in client bundles.
- This release requires a configured management service. Existing 0.5.x installations
  must be upgraded; they cannot be remotely paused retroactively.

## 0.4.1 — unreleased (prepared 2026-09-10)

### Fixed

- `get_object_info` guidance now names the accepted `id` and `name` selectors,
  states that at least one is needed, and explains ID precedence and discovery.
  The signature, response and execution behavior are unchanged.
- `update_object_attributes` works again with the Newtonsoft assembly loaded by
  Rhino 8. A missing overload prevented all updates in 0.4.0, including calls that
  only changed an object's layer. This was a 0.4.0 regression; see Changed below.
- Attribute edits use a detached copy before committing, preserving existing and
  newly assigned user strings. Scalar encoding, null deletion and validation stay
  unchanged; no wire-contract change is required.

### Changed

- Newtonsoft.Json is pinned to 13.0.3, the version Rhino 8 bundles and loads
  before any plugin. 0.4.0 compiled against 13.0.4, whose new
  `JToken.ToString(Formatting)` overload the compiler chose for an unchanged call;
  Rhino's 13.0.3 has no such overload, so every attribute update failed at runtime.
  Compiling against the bundled version keeps that class of mismatch impossible.

## 0.4.0 — unreleased (prepared 2026-09-09)

### Fixed: fresh installs of 0.3.2 fail to start

`rhinomcp 0.3.2` on PyPI declares `mcp[cli]>=1.16.0` with no upper bound. Since
MCP Python SDK 2.0 (2026-07-28) removed `mcp.server.fastmcp`, a new `uvx rhinomcp`
install resolves the 2.x SDK and fails at import. 0.4.0 moves the server to the
2.x API (`mcp>=2.0.0,<3`) instead of pinning the retired 1.x line.

### Server (`rhinomcp` on PyPI)

- MCP Python SDK 2.x. The tool catalog, prompts, resources and instructions are
  unchanged for clients; no client configuration changes are needed.
- Tool errors keep their text. SDK 2.x reports an unexpected tool exception to
  the client as only `Error executing tool <name>`; RhinoMCP re-raises failures
  as `ToolError` so messages such as "start Rhino and run `mcpstart`" still reach
  the agent.
- Version compatibility guard. The server reads the plugin's version once per
  connection and warns when the two differ; `describe_capabilities` now also
  reports `server_version`, `plugin_matches_server` and `update_advice`. A
  command the connected plugin does not support fails with update instructions
  instead of a bare "Unknown command type", and a parameter an older plugin would
  silently ignore (`sweep1.cap_planar_ends`) is refused rather than dropped.
- Client configuration in the README now launches `uvx rhinomcp@latest`, so the
  server is re-resolved on every client start instead of staying on the first
  version uv downloaded. See "Staying up to date" in the README.
- New `create_planar_region` tool: builds a planar face from closed boundary
  curves, with inner boundaries as holes. Requires plugin 0.4.0.
- New `get_modeling_guidance` tool, the `rhinomcp://guidance/{topic}` resource and
  six packaged guides (`overview`, `transforms`, `planar_regions`, `organization`,
  `verification`, `recovery`). The `asset_general_strategy` prompt and the server
  instructions use the same packaged content. No experiment checkout or separate
  skill is required.
- `sweep1` gains `cap_planar_ends` (default off). Requires plugin 0.4.0; an older
  plugin ignores the flag and returns uncapped surfaces.
- `create_layer`: `parent` accepts an exact full path such as `Assembly::Left`;
  a simple name must identify exactly one layer. Missing or ambiguous parents
  return errors instead of creating a mislocated layer (plugin 0.4.0).
- `capture_viewport`: `zoom_to_fit` fits visible objects to the requested image
  size, and the original camera and projection are restored afterwards
  (plugin 0.4.0).
- `analyze_objects`: `naked_edge_count` counts all naked topological edges,
  including inner hole boundaries (plugin 0.4.0; 0.3.2 reports outer edges only).
- `create_object` documents anchor points (centered boxes, base-anchored
  cylinders); `modify_object` documents its pivot and transform order.
- Development: dependencies refreshed to current releases; the lint rule set is
  pinned in the root `ruff.toml` because ruff 0.16 widened its defaults.

### Plugin (`rhinomcp` on Yak)

- `create_planar_region` command with coplanarity and planar-face checks.
- `sweep1`: optional planar-end capping at document tolerance. Every result must
  become a valid solid before any is added; otherwise the command fails without
  changing the document.
- `create_layer`: parent lookup by full path or unique name, with explicit
  not-found and ambiguous-name errors.
- `capture_viewport`: snapshots every viewport before refreshing or fitting and
  restores camera, target and projection without another redraw; finishes queued
  redraws on Mac before capturing.
- `analyze_objects`: Brep naked edges are counted from edge valence, so inner
  loops are included and seams are not.
- Newtonsoft.Json 13.0.4 (reverted in 0.4.1: Rhino 8 loads its own 13.0.3).

### Experiments harness (contributors)

- Gateways moved to SDK 2.x; the native pilot registers low-level handlers and
  returns gateway rejections as tool errors as before. Recorded catalogs keep the
  camelCase wire format. Comparisons against runs recorded before this change
  must use their archived sources.

## 0.3.2 and earlier

See the GitHub releases for earlier versions.
