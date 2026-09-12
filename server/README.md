# RhinoMCP Studio Python server

This server connects local Codex MCP tools to the RhinoMCP Studio plugin in Rhino 8.
Use the Studio distribution ZIP and [installation guide](../docs/INSTALL_KO.md).
The Python distribution/module name remains `rhinomcp`; this is a modified build
of [Jingcheng Chen's upstream project](https://github.com/jingcheng-chen/rhinomcp).

From Studio 0.6.0, the Rhino plugin requires a fresh approval from the operator's
management service before each command. Maintenance, invalid authorization or
an unreachable service blocks new requests. `get_management_status` exposes
credential-free local diagnostics; it is not an approval cache. Do not bypass
a refusal by switching tools, transports or versions. Manual Rhino use and
already running work remain available. See the repository's `management/` folder
for the owner service and HTTPS deployment instructions.

The Studio Rhino commands are `StudioMCPStart`, `StudioMCPStop`,
`StudioMCPVersion` and the development-only `StudioMCPTest`. Generic `mcpstart`
can belong to another plugin and does not prove Studio is loaded. Verify the
Studio version and its bridge at `127.0.0.1:1999`. RhinoAiMCP has a different plugin
GUID and may remain installed; the original jingcheng-chen `rhinomcp` shares
Studio's GUID and must be replaced. Command separation alone does not establish
full runtime coexistence. Actual Windows validation is pending; macOS runtime
validation has not been completed.

## Bundled modeling guidance

RhinoMCP ships versioned modeling knowledge with the Python server. No experiment
checkout, local memory folder or separate skill installation is required.

- Call `get_modeling_guidance(topic="overview")` to start. Other topics are
  `transforms`, `planar_regions`, `architecture`, `organization`, `verification` and `recovery`.
- Clients supporting MCP resources can read `rhinomcp://guidance/{topic}`.
- The `asset_general_strategy` MCP prompt uses the same packaged overview.
- Server instructions advertise the guide, and individual tool descriptions retain
  essential behavior such as units and rotation pivots. Client support determines
  how instructions, prompts and resources appear; their presence does not guarantee
  an agent reads them.

The canonical Markdown files are packaged under `rhinomcp/guides`. Guide responses
include both the guide revision and installed package version. Any future optional
client skill should derive its content from these files, not maintain another copy.
The contributor experiment harness remains separate from normal modeling guidance.

This implementation uses MCP Python SDK 2.x (`mcp>=2.0.0,<3`); SDK 1.x is no
longer supported. New guidance ships when this server version is released;
local builds are not a PyPI publication. Restart an existing MCP server connection
after upgrading so its tool descriptions and instructions refresh.
