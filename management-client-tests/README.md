# Managed authorization client tests

This console links the exact authorization client used by the Rhino plug-in and requires only .NET 8; it does not require Rhino or NuGet packages.

```sh
dotnet restore management-client-tests/ManagementClient.Tests.csproj --configfile management-client-tests/NuGet.Config
dotnet run --project management-client-tests/ManagementClient.Tests.csproj --no-restore -c Release
```

The tests cover signed approvals and denials, request binding and replay rejection, nonce freshness, strict configuration and URL validation, credential-free diagnostics, invalid signatures and payloads, network errors, five-second timeouts, response size limits, and authorization expiry/configuration changes while waiting to dispatch.

To verify interoperability against an actual management service without starting Rhino:

```sh
dotnet run --project management-client-tests/ManagementClient.Tests.csproj --no-build -c Release -- --live /path/to/management.json create_object 0.6.1
```

The live check makes a real authorization request only; it does not run the Rhino command. It emits JSON containing the decision and local management status, never the installation token or public key. Exit code 0 means approved and 1 means denied. The fixture configuration file contains an installation credential and must be handled as a secret.
