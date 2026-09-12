using Newtonsoft.Json.Linq;
using RhinoMCPPlugin.Management;

namespace RhinoMCPPlugin.Functions;

public partial class RhinoMCPFunctions
{
    [McpCommand("get_management_status", ReadOnly = true)]
    public JObject GetManagementStatus(JObject parameters) => JObject.FromObject(ManagementRuntime.Client.GetStatus());
}
