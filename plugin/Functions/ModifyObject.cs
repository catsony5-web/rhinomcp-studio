using System;
using System.Drawing;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using rhinomcp.Serializers;

namespace RhinoMCPPlugin.Functions;

public partial class RhinoMCPFunctions
{
    /// <summary>
    /// Modifies an existing object in the Rhino document.
    /// </summary>
    /// <param name="parameters">
    /// JSON object containing:
    /// - id: GUID of the object to modify (required if name not provided)
    /// - name: Name of the object to modify (required if id not provided)
    /// - new_name: Optional new name for the object
    /// - new_color: Optional [r, g, b] color array (0-255)
    /// - translation: Optional [x, y, z] translation vector
    /// - rotation: Optional [x, y, z] rotation in radians (applied around object center)
    /// - scale: Optional [x, y, z] scale factors (applied from bounding box min)
    /// </param>
    /// <returns>JSON object with updated object info</returns>
    /// <exception cref="InvalidOperationException">Thrown when object is not found</exception>
    [McpCommand("modify_object")]
    public JObject ModifyObject(JObject parameters)
    {
        var doc = RhinoDoc.ActiveDoc;
        var obj = getObjectByIdOrName(parameters);
        if (obj.IsDeleted || obj.IsLocked || obj.IsReference || obj.IsInstanceDefinitionGeometry)
            throw new InvalidOperationException($"Object {obj.Id} is locked, deleted, or reference geometry and cannot be modified");
        var layer = doc.Layers[obj.Attributes.LayerIndex];
        while (layer != null)
        {
            if (layer.IsLocked || layer.IsReference)
                throw new InvalidOperationException($"Object {obj.Id} is on a locked or reference layer and cannot be modified");
            layer = layer.ParentLayerId == Guid.Empty ? null : doc.Layers.FindId(layer.ParentLayerId);
        }
        var geometry = obj.Geometry;
        var xform = Transform.Identity;
        using var originalAttributes = obj.Attributes.Duplicate();
        using var attributes = originalAttributes.Duplicate();

        // Handle different modifications based on parameters
        bool attributesModified = false;
        bool geometryModified = false;

        // Change name if provided
        if (parameters["new_name"] != null)
        {
            string name = parameters["new_name"].ToString();
            attributes.Name = name;
            attributesModified = true;
        }

        // Change color if provided
        if (parameters["new_color"] != null)
        {
            int[] color = parameters["new_color"]?.ToObject<int[]>() ?? new[] { 0, 0, 0 };
            if (color.Length != 3)
                throw new ArgumentException("new_color must contain three RGB values");
            attributes.ObjectColor = Color.FromArgb(color[0], color[1], color[2]);
            attributes.ColorSource = ObjectColorSource.ColorFromObject;
            attributesModified = true;
        }

        // Change translation if provided
        if (parameters["translation"] != null)
        {
            xform *= applyTranslation(parameters);
            geometryModified = true;
        }

        // Apply rotation if provided. Rotation is composed before scale on
        // purpose: scaling after a rotation applies a world-axis, non-uniform
        // scale to an already-rotated object, which shears it. Scaling first
        // (xform = T * R * S) keeps a combined scale and rotation a clean
        // similarity with no shear.
        if (parameters["rotation"] != null)
        {
            xform *= applyRotation(parameters, geometry);
            geometryModified = true;
        }

        // Apply scale if provided
        if (parameters["scale"] != null)
        {
            xform *= applyScale(parameters, geometry);
            geometryModified = true;
        }

        if (geometryModified && !xform.IsValid)
            throw new ArgumentException("Object transform must contain finite values");

        if (attributesModified && !doc.Objects.ModifyAttributes(obj, attributes, true))
            throw new InvalidOperationException($"Could not modify attributes of object {obj.Id}");

        var resultId = obj.Id;
        if (geometryModified)
        {
            try
            {
                resultId = doc.Objects.Transform(obj, xform, true);
                if (resultId == Guid.Empty)
                    throw new InvalidOperationException($"Could not transform object {obj.Id}");
            }
            catch (Exception error)
            {
                if (attributesModified && !doc.Objects.ModifyAttributes(obj, originalAttributes, true))
                    throw new InvalidOperationException($"{error.Message}. Could not restore the object's original attributes; inspect {obj.Id} before retrying.", error);
                throw;
            }
        }

        // Update views
        doc.Views.Redraw();

        return Serializer.RhinoObject(getObjectByIdOrName(new JObject { ["id"] = resultId }));

    }
}
