using System;
using System.IO;

namespace RhinoMCPPlugin.Management;

internal static class ManagementRuntime
{
    // Fixed per-user path: deleting configuration or changing installer roots never disables the gate.
    internal static readonly ManagementClient Client = new ManagementClient(ConfigurationPath(), PluginVersion());

    private static string ConfigurationPath()
    {
        string root = OperatingSystem.IsMacOS()
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library", "Application Support")
            : Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(root, "RhinoMCPStudio", "management.json");
    }

    private static string PluginVersion()
    {
        Version version = typeof(ManagementRuntime).Assembly.GetName().Version;
        return version == null ? "unknown" : $"{version.Major}.{version.Minor}.{version.Build}";
    }
}
