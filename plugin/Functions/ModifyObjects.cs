using System;
using System.Drawing;
using System.Linq;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using rhinomcp.Serializers;

namespace RhinoMCPPlugin.Functions;

public partial class RhinoMCPFunctions
{
    [McpCommand("modify_objects")]
    public JObject ModifyObjects(JObject parameters)
    {
        bool all = parameters["all"]?.ToObject<bool>() ?? false;
        JArray objectParameters = parameters["objects"] as JArray
            ?? throw new ArgumentException("objects must be an array");
        if (objectParameters.Count == 0 || objectParameters.Any(value => value is not JObject))
            throw new ArgumentException("objects must contain at least one modification object");
        if (all && objectParameters.Count != 1)
            throw new ArgumentException("all=true requires exactly one modification template");

        var doc = RhinoDoc.ActiveDoc;
        // Enumerate live objects; ObjectTable.CopyTo also includes deleted undo records.
        var objects = doc.Objects.GetObjectList(new ObjectEnumeratorSettings()).ToList();

        if (all)
        {
            // Get the first modification parameters (excluding the "all" property)
            JObject firstModification = (JObject)objectParameters.FirstOrDefault()!;

            // The template is not itself a target, even when it contains an id.
            objectParameters = new JArray();

            // Create new parameters object with all object IDs
            foreach (var obj in objects)
            {
                // Create a new copy of the modification parameters for each object
                JObject newModification = new JObject(firstModification) { ["id"] = obj.Id.ToString() };
                objectParameters.Add(newModification);
            }
        }

        int successCount = 0;
        int failureCount = 0;
        var errors = new JArray();

        foreach (JObject parameter in objectParameters)
        {
            if (parameter.ContainsKey("id") || parameter.ContainsKey("name"))
            {
                try
                {
                    ModifyObject(parameter);
                    successCount++;
                }
                catch (Exception ex)
                {
                    var identifier = parameter["id"]?.ToString() ?? parameter["name"]?.ToString() ?? "unknown";
                    errors.Add(new JObject
                    {
                        ["id"] = identifier,
                        ["error"] = ex.Message
                    });
                    failureCount++;
                }
            }
        }

        doc.Views.Redraw();

        return new JObject
        {
            ["success_count"] = successCount,
            ["failure_count"] = failureCount,
            ["total"] = successCount + failureCount,
            ["errors"] = errors
        };
    }
}
