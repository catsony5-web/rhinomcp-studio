using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using Rhino.Geometry.Intersect;

namespace RhinoMCPPlugin.Functions;

public partial class RhinoMCPFunctions
{
    private sealed class WallOpening
    {
        public double Offset, Width, Bottom, Height;
        public double Right => Offset + Width;
        public double Top => Bottom + Height;
    }

    [McpCommand("create_wall")]
    public JObject CreateWall(JObject parameters)
    {
        var doc = RhinoDoc.ActiveDoc ?? throw new InvalidOperationException("No active Rhino document");
        var tolerance = doc.ModelAbsoluteTolerance;
        var start = ArchitecturePoint(parameters["start"], "start");
        var end = ArchitecturePoint(parameters["end"], "end");
        var height = ArchitectureDimension(parameters["height"], "height", tolerance);
        var thickness = ArchitectureDimension(parameters["thickness"], "thickness", tolerance);
        if (Math.Abs(start.Z - end.Z) > tolerance)
            throw new ArgumentException("Wall start and end must have the same Z within document tolerance");
        var xAxis = new Vector3d(end.X - start.X, end.Y - start.Y, 0);
        var length = xAxis.Length;
        if (!double.IsFinite(length) || length <= tolerance || !xAxis.Unitize())
            throw new ArgumentException("Wall baseline must be longer than document tolerance");
        var yAxis = Vector3d.CrossProduct(Vector3d.ZAxis, xAxis);
        var openings = new List<WallOpening>();
        if (parameters["openings"] != null)
        {
            if (parameters["openings"] is not JArray array)
                throw new ArgumentException("openings must be an array");
            foreach (var token in array)
            {
                if (token is not JObject item)
                    throw new ArgumentException("Each opening must be an object");
                var opening = new WallOpening
                {
                    Offset = ArchitectureNumber(item["offset"], "opening.offset"),
                    Width = ArchitectureDimension(item["width"], "opening.width", tolerance),
                    Bottom = ArchitectureNumber(item["bottom"], "opening.bottom"),
                    Height = ArchitectureDimension(item["height"], "opening.height", tolerance)
                };
                if (opening.Offset <= tolerance || length - opening.Right <= tolerance
                    || opening.Bottom < 0 || (opening.Bottom > 0 && opening.Bottom <= tolerance)
                    || height - opening.Top <= tolerance)
                    throw new ArgumentException("Openings need clearance greater than document tolerance at wall ends and top; bottom must be zero or greater than tolerance");
                foreach (var other in openings)
                {
                    if (opening.Offset <= other.Right + tolerance && other.Offset <= opening.Right + tolerance
                        && opening.Bottom <= other.Top + tolerance && other.Bottom <= opening.Top + tolerance)
                        throw new ArgumentException("Openings must not overlap or touch; their separation must exceed document tolerance");
                }
                openings.Add(opening);
            }
        }

        // The profile lies on the right face; extrusion goes across the centerline
        // to the left face. Doors are notches in the outer loop, windows are holes.
        var origin = start - yAxis * (thickness / 2);
        Point3d At(double x, double z) => origin + xAxis * x + Vector3d.ZAxis * z;
        var outline = new List<Point3d> { At(0, 0) };
        foreach (var door in openings.Where(o => o.Bottom == 0).OrderBy(o => o.Offset))
        {
            outline.Add(At(door.Offset, 0));
            outline.Add(At(door.Offset, door.Top));
            outline.Add(At(door.Right, door.Top));
            outline.Add(At(door.Right, 0));
        }
        outline.Add(At(length, 0));
        outline.Add(At(length, height));
        outline.Add(At(0, height));
        var holes = openings.Where(o => o.Bottom > 0).Select(o => new List<Point3d>
        {
            At(o.Offset, o.Bottom), At(o.Right, o.Bottom),
            At(o.Right, o.Top), At(o.Offset, o.Top)
        }).ToList();
        var expectedVolume = (length * height - openings.Sum(o => o.Width * o.Height)) * thickness;
        var plane = new Plane(origin, xAxis, Vector3d.ZAxis);
        using var solid = ArchitectureExtrudeRegion(outline, holes, plane, yAxis * thickness, tolerance);
        var result = ArchitectureAddSolid(doc, solid, expectedVolume, parameters);
        result["length"] = length;
        result["height"] = height;
        result["thickness"] = thickness;
        result["opening_count"] = openings.Count;
        result["local_x"] = new JArray(xAxis.X, xAxis.Y, xAxis.Z);
        result["local_y"] = new JArray(yAxis.X, yAxis.Y, yAxis.Z);
        result["base_z"] = start.Z;
        return result;
    }

    [McpCommand("create_floor_slab")]
    public JObject CreateFloorSlab(JObject parameters)
    {
        var doc = RhinoDoc.ActiveDoc ?? throw new InvalidOperationException("No active Rhino document");
        var tolerance = doc.ModelAbsoluteTolerance;
        var thickness = ArchitectureDimension(parameters["thickness"], "thickness", tolerance);
        var outer = ArchitecturePolygon(parameters["outer"], "outer", tolerance);
        var topZ = outer[0].Z;
        var holes = new List<List<Point3d>>();
        if (parameters["holes"] != null)
        {
            if (parameters["holes"] is not JArray array)
                throw new ArgumentException("holes must be an array of polygons");
            for (var i = 0; i < array.Count; i++)
                holes.Add(ArchitecturePolygon(array[i], $"holes[{i}]", tolerance));
        }
        foreach (var polygon in new[] { outer }.Concat(holes))
        {
            for (var i = 0; i < polygon.Count; i++)
            {
                var point = polygon[i];
                if (Math.Abs(point.Z - topZ) > tolerance)
                    throw new ArgumentException("Every slab point must lie on the same horizontal XY plane within document tolerance");
                polygon[i] = new Point3d(point.X, point.Y, topZ);
            }
        }
        var area = ArchitecturePolygonArea(outer) - holes.Sum(ArchitecturePolygonArea);
        var plane = new Plane(new Point3d(0, 0, topZ), Vector3d.ZAxis);
        using var solid = ArchitectureExtrudeRegion(outer, holes, plane, -Vector3d.ZAxis * thickness, tolerance);
        var result = ArchitectureAddSolid(doc, solid, area * thickness, parameters);
        result["area"] = area;
        result["thickness"] = thickness;
        result["top_z"] = topZ;
        result["bottom_z"] = topZ - thickness;
        result["hole_count"] = holes.Count;
        return result;
    }

    private static double ArchitectureNumber(JToken token, string label)
    {
        if (token == null || (token.Type != JTokenType.Integer && token.Type != JTokenType.Float))
            throw new ArgumentException($"{label} must be a finite number");
        var number = token.Value<double>();
        if (!double.IsFinite(number))
            throw new ArgumentException($"{label} must be a finite number");
        return number;
    }

    private static double ArchitectureDimension(JToken token, string label, double tolerance)
    {
        var number = ArchitectureNumber(token, label);
        if (number <= tolerance)
            throw new ArgumentException($"{label} must be greater than document tolerance ({tolerance})");
        return number;
    }

    private static Point3d ArchitecturePoint(JToken token, string label)
    {
        if (token is not JArray point || point.Count != 3)
            throw new ArgumentException($"{label} must contain exactly three coordinates [x,y,z]");
        return new Point3d(ArchitectureNumber(point[0], label), ArchitectureNumber(point[1], label),
            ArchitectureNumber(point[2], label));
    }

    private static List<Point3d> ArchitecturePolygon(JToken token, string label, double tolerance)
    {
        if (token is not JArray array || array.Count < 3)
            throw new ArgumentException($"{label} must contain at least three vertices");
        var points = array.Select((point, i) => ArchitecturePoint(point, $"{label}[{i}]")).ToList();
        if (points[0].DistanceTo(points[points.Count - 1]) <= tolerance)
            points.RemoveAt(points.Count - 1);
        if (points.Count < 3)
            throw new ArgumentException($"{label} must contain at least three distinct vertices");
        return points;
    }

    private static double ArchitecturePolygonArea(List<Point3d> points)
    {
        // Subtract the origin first to avoid cancellation for large site coordinates.
        var origin = points[0];
        double twiceArea = 0;
        for (var i = 1; i < points.Count - 1; i++)
        {
            var a = points[i] - origin;
            var b = points[i + 1] - origin;
            twiceArea += a.X * b.Y - b.X * a.Y;
        }
        return Math.Abs(twiceArea) / 2;
    }

    private static Brep ArchitectureExtrudeRegion(List<Point3d> outer, List<List<Point3d>> holes,
        Plane plane, Vector3d direction, double tolerance)
    {
        var curves = new List<Curve>();
        Brep[] faces = null;
        try
        {
            foreach (var polygon in new[] { outer }.Concat(holes))
            {
                for (var i = 0; i < polygon.Count; i++)
                {
                    if (polygon[i].DistanceTo(polygon[(i + 1) % polygon.Count]) <= tolerance)
                        throw new ArgumentException("Polygon edges must be longer than document tolerance");
                }
                var closed = new List<Point3d>(polygon) { polygon[0] };
                var curve = new PolylineCurve(closed);
                curves.Add(curve);
                if (!curve.IsValid || !curve.IsClosed || !curve.IsInPlane(plane, tolerance))
                    throw new ArgumentException("Polygon must define a valid closed planar curve");
                var self = Intersection.CurveSelf(curve, tolerance);
                if (self != null && self.Count > 0)
                    throw new ArgumentException("Polygon must not self-intersect or touch itself");
                using var area = AreaMassProperties.Compute(curve);
                if (area == null || !double.IsFinite(area.Area) || area.Area <= tolerance * tolerance)
                    throw new ArgumentException("Polygon area must be greater than squared document tolerance");
            }
            for (var i = 1; i < curves.Count; i++)
            {
                for (var j = 0; j < i; j++)
                {
                    var events = Intersection.CurveCurve(curves[i], curves[j], tolerance, tolerance);
                    if (events != null && events.Count > 0)
                        throw new ArgumentException("Polygon boundaries must not cross or touch within document tolerance");
                    var relation = Curve.PlanarClosedCurveRelationship(curves[i], curves[j], plane, tolerance);
                    if ((j == 0 && relation != RegionContainment.AInsideB)
                        || (j > 0 && relation != RegionContainment.Disjoint))
                        throw new ArgumentException("Holes must be strictly inside the outer polygon, disjoint, and nonnested");
                }
            }
            faces = Brep.CreatePlanarBreps(curves, tolerance);
            if (faces == null || faces.Length != 1 || !faces[0].IsValid || faces[0].Faces.Count != 1
                || faces[0].Loops.Count(loop => loop.LoopType == BrepLoopType.Inner) != holes.Count
                || faces[0].Loops.Count != holes.Count + 1)
                throw new InvalidOperationException("Profile construction did not produce the expected single planar face and holes");
            using var path = new LineCurve(outer[0], outer[0] + direction);
            var solid = faces[0].Faces[0].CreateExtrusion(path, true);
            if (solid == null)
                throw new InvalidOperationException("Capped profile extrusion failed; no document objects were added");
            return solid;
        }
        finally
        {
            if (faces != null)
                foreach (var face in faces) face?.Dispose();
            foreach (var curve in curves) curve.Dispose();
        }
    }

    private static JObject ArchitectureAddSolid(RhinoDoc doc, Brep solid, double expectedVolume, JObject parameters)
    {
        var tolerance = doc.ModelAbsoluteTolerance;
        if (!solid.IsValid || !solid.IsSolid || !solid.IsManifold)
            throw new InvalidOperationException("Construction must produce a valid closed manifold Brep; no objects were added");
        if (solid.SolidOrientation == BrepSolidOrientation.Inward)
            solid.Flip();
        if (solid.SolidOrientation != BrepSolidOrientation.Outward)
            throw new InvalidOperationException("Constructed solid has no outward orientation; no objects were added");
        using var mass = VolumeMassProperties.Compute(solid);
        using var area = AreaMassProperties.Compute(solid);
        if (mass == null || area == null || !double.IsFinite(mass.Volume) || mass.Volume <= 0
            || !double.IsFinite(expectedVolume) || expectedVolume <= 0)
            throw new InvalidOperationException("Solid volume could not be verified; no objects were added");
        var allowedError = Math.Max(expectedVolume * 1e-8, area.Area * tolerance);
        var volumeError = Math.Abs(mass.Volume - expectedVolume);
        if (!double.IsFinite(allowedError) || volumeError > allowedError)
            throw new InvalidOperationException("Solid volume differs from the requested dimensions; no objects were added");

        var attributes = new ObjectAttributes { LayerIndex = doc.Layers.CurrentLayerIndex };
        if (parameters["name"] != null)
        {
            if (parameters["name"].Type != JTokenType.String)
                throw new ArgumentException("name must be a string");
            attributes.Name = parameters["name"].Value<string>();
        }
        if (parameters["layer"] != null)
        {
            if (parameters["layer"].Type != JTokenType.String)
                throw new ArgumentException("layer must be an existing layer full path or GUID");
            var layerText = parameters["layer"].Value<string>();
            var isId = Guid.TryParse(layerText, out var layerId);
            var layer = doc.Layers.FirstOrDefault(candidate => !candidate.IsDeleted
                && (isId ? candidate.Id == layerId : candidate.FullPath.Equals(layerText, StringComparison.OrdinalIgnoreCase)));
            if (layer == null)
                throw new ArgumentException($"Existing layer '{layerText}' was not found");
            attributes.LayerIndex = layer.Index;
        }

        var nakedEdges = solid.Edges.Count(edge => edge.Valence == EdgeAdjacency.Naked);
        var nonmanifoldEdges = solid.Edges.Count(edge => edge.Valence == EdgeAdjacency.NonManifold);
        if (nakedEdges != 0 || nonmanifoldEdges != 0)
            throw new InvalidOperationException("Constructed solid has unjoined or nonmanifold edges; no objects were added");
        var result = new JObject
        {
            ["success"] = true,
            ["expected_volume"] = expectedVolume,
            ["volume"] = mass.Volume,
            ["volume_error"] = volumeError,
            ["volume_tolerance"] = allowedError,
            ["document_units"] = doc.ModelUnitSystem.ToString(),
            ["tolerance"] = tolerance,
            ["layer"] = doc.Layers[attributes.LayerIndex].FullPath,
            ["geometry_health"] = new JObject
            {
                ["is_valid"] = true, ["is_solid"] = true, ["is_manifold"] = true,
                ["solid_orientation"] = "outward", ["naked_edge_count"] = nakedEdges,
                ["nonmanifold_edge_count"] = nonmanifoldEdges, ["face_count"] = solid.Faces.Count
            }
        };
        Guid id = Guid.Empty;
        try
        {
            id = doc.Objects.AddBrep(solid, attributes);
            if (id == Guid.Empty)
                throw new InvalidOperationException("Document insertion failed");
            result["id"] = id.ToString();
            result["result_ids"] = new JArray(id.ToString());
            doc.Views.Redraw();
            return result;
        }
        catch (Exception error)
        {
            if (id != Guid.Empty)
            {
                try
                {
                    var added = doc.Objects.FindId(id);
                    if (added != null && !added.IsDeleted && !doc.Objects.Delete(added, true, true))
                        throw new InvalidOperationException($"Could not remove new result {id}");
                }
                catch (Exception cleanupError)
                {
                    throw new InvalidOperationException($"{error.Message}. Cleanup failed for result {id}: {cleanupError.Message}. Inspect this object before retrying.", error);
                }
            }
            throw;
        }
    }
}
