using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoMCPPlugin.Functions;

public partial class RhinoMCPFunctions
{
    // Insert the complete result before deleting any input. Recovery targets only
    // this operation's objects; calling document Undo here could undo user work.
    private JArray CommitBrepResults(RhinoDoc doc, IEnumerable<Brep> results,
        string name, string operation, IEnumerable<RhinoObject> deleteSources = null,
        bool requireSolid = false)
    {
        var breps = results.ToArray();
        if (breps.Length == 0)
            throw new InvalidOperationException($"{operation} produced no geometry");

        foreach (var brep in breps)
        {
            if (brep == null || !brep.IsValid)
                throw new InvalidOperationException($"{operation} produced invalid geometry; no objects were changed");
            if (requireSolid && !brep.IsSolid)
                throw new InvalidOperationException($"{operation} did not produce a closed solid; no objects were changed");
        }

        var sources = (deleteSources ?? Enumerable.Empty<RhinoObject>())
            .GroupBy(obj => obj.Id).Select(group => group.First()).ToArray();
        foreach (var source in sources)
        {
            if (source.Document != doc || source.IsDeleted || source.IsReference ||
                source.IsInstanceDefinitionGeometry || !source.IsDeletable ||
                source.IsLocked || source.IsHidden)
                throw new InvalidOperationException($"Cannot delete source {source.Id}; no objects were changed. Use delete_sources=false to retain inputs.");

            var layer = doc.Layers[source.Attributes.LayerIndex];
            while (layer != null)
            {
                if (layer.IsLocked || !layer.IsVisible || layer.IsReference)
                    throw new InvalidOperationException($"Source {source.Id} is on a locked, hidden, or reference layer; no objects were changed. Use delete_sources=false to retain inputs.");
                layer = layer.ParentLayerId == Guid.Empty ? null : doc.Layers.FindId(layer.ParentLayerId);
            }
        }

        var addedIds = new List<Guid>();
        try
        {
            foreach (var brep in breps)
            {
                var attributes = new ObjectAttributes();
                if (!string.IsNullOrEmpty(name)) attributes.Name = name;
                var id = doc.Objects.AddBrep(brep, attributes);
                if (id == Guid.Empty)
                    throw new InvalidOperationException($"{operation} could not insert its complete result");
                addedIds.Add(id);
            }

            foreach (var source in sources)
            {
                if (!doc.Objects.Delete(source, true, false))
                    throw new InvalidOperationException($"{operation} could not delete source {source.Id}");
            }

            return new JArray(addedIds.Select(id => id.ToString()));
        }
        catch (Exception error)
        {
            var recoveryErrors = new List<string>();
            foreach (var source in sources)
            {
                try
                {
                    if (source.IsDeleted && !doc.Objects.Undelete(source.RuntimeSerialNumber))
                        recoveryErrors.Add($"restore source {source.Id}");
                }
                catch (Exception recoveryError)
                {
                    recoveryErrors.Add($"restore source {source.Id}: {recoveryError.Message}");
                }
            }
            foreach (var id in addedIds)
            {
                try
                {
                    var added = doc.Objects.FindId(id);
                    if (added != null && !added.IsDeleted && !doc.Objects.Delete(added, true, true))
                        recoveryErrors.Add($"remove result {id}");
                }
                catch (Exception recoveryError)
                {
                    recoveryErrors.Add($"remove result {id}: {recoveryError.Message}");
                }
            }
            doc.Views.Redraw();
            if (recoveryErrors.Count > 0)
                throw new InvalidOperationException($"{error.Message}. Recovery incomplete: {string.Join("; ", recoveryErrors)}. Inspect these objects before retrying.", error);
            throw new InvalidOperationException($"{error.Message}. Source geometry was retained and new results were removed.", error);
        }
    }
}
