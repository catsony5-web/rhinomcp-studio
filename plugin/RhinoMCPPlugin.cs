using System;
using Rhino;
using Rhino.PlugIns;

namespace RhinoMCPPlugin
{
    public class RhinoMCPPlugin : PlugIn
    {
        public RhinoMCPPlugin() { Instance = this; }
        public static RhinoMCPPlugin Instance { get; private set; }
        public override PlugInLoadTime LoadTime => PlugInLoadTime.AtStartup;

        protected override LoadReturnCode OnLoad(ref string errorMessage)
        {
            if (Environment.GetEnvironmentVariable("RHINO_MCP_AUTOSTART") != "0")
                RhinoApp.Idle += StartWhenReady;
            return LoadReturnCode.Success;
        }

        private void StartWhenReady(object sender, EventArgs args)
        {
            // Wait until Rhino has a document and can service work on the UI thread.
            if (RhinoDoc.ActiveDoc == null) return;
            RhinoApp.Idle -= StartWhenReady;
            RhinoMCPServerController.StartServer();
        }

        protected override void OnShutdown()
        {
            RhinoApp.Idle -= StartWhenReady;
            RhinoMCPServerController.StopServer();
            base.OnShutdown();
        }
    }
}
