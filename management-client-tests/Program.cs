using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using RhinoMCPPlugin.Management;

if (args.Length > 0 && args[0] == "--live")
{
    if (args.Length != 3 && args.Length != 4)
    {
        Console.Error.WriteLine("Usage: --live CONFIG_PATH COMMAND [VERSION]");
        return 2;
    }
    using var live = new ManagementClient(Path.GetFullPath(args[1]), args.Length == 4 ? args[3] : "0.6.0");
    var authorization = await live.AuthorizeAsync(args[2]);
    bool dispatchable = authorization.Allowed && live.IsGrantCurrent(authorization.Grant, out _);
    Console.WriteLine(JsonSerializer.Serialize(new { allowed = authorization.Allowed, dispatchable,
        code = authorization.Code, reason = authorization.Reason, status = live.GetStatus() }));
    return authorization.Allowed ? 0 : 1;
}

int passed = 0;
int failed = 0;
async Task Test(string name, Func<Fixture, Task> action)
{
    using var fixture = new Fixture();
    try { await action(fixture); Console.WriteLine("PASS " + name); passed++; }
    catch (Exception ex) { Console.WriteLine("FAIL " + name + ": " + ex.Message); failed++; }
}
static void Assert(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}
static async Task Denied(Fixture fixture, string expectedCode = "invalid_response")
{
    var result = await fixture.Client.AuthorizeAsync("create_object");
    Assert(!result.Allowed && result.Grant == null, "Authorization must fail closed.");
    Assert(result.Code == expectedCode, "Unexpected denial category: " + result.Code);
}

await Test("valid signed request binds identity/version/command; status excludes credentials", async f =>
{
    var result = await f.Client.AuthorizeAsync("create_object");
    Assert(result.Allowed && result.Grant != null, "Valid approval was denied.");
    Assert(f.Client.IsGrantCurrent(result.Grant, out _), "Fresh approval should dispatch.");
    Assert(f.Handler.Request["nonce"].GetValue<string>().Length == 64, "Expected cryptographic 32-byte nonce.");
    Assert(f.Handler.Authorization == "Bearer " + f.Token, "Installation bearer header missing.");
    Assert(f.Handler.Request["version"].GetValue<string>() == "0.6.0", "Wrong plugin version.");
    Assert(f.Handler.Request.Count == 4, "Request must contain only identity/version/command/nonce, no model data.");
    string status = JsonSerializer.Serialize(f.Client.GetStatus());
    Assert(!status.Contains(f.Token) && !status.Contains("PUBLIC KEY"), "Status leaked credential/key.");
    Assert((string)f.Client.GetStatus()["state"] == "allowed", "Status should report last approval.");
});
await Test("fresh HTTP request and nonce for every operation", async f =>
{
    Assert((await f.Client.AuthorizeAsync("create_object")).Allowed, "First authorization denied.");
    string nonce = f.Handler.Request["nonce"].GetValue<string>();
    Assert((await f.Client.AuthorizeAsync("create_object")).Allowed, "Second authorization denied.");
    Assert(f.Handler.Calls == 2 && nonce != f.Handler.Request["nonce"].GetValue<string>(), "Approval or nonce reused.");
});
await Test("only two fixed diagnostics are exempt", f =>
{
    Assert(ManagementClient.IsLocalDiagnostic("describe_capabilities"), "Capability diagnostic missing.");
    Assert(ManagementClient.IsLocalDiagnostic("get_management_status"), "Status diagnostic missing.");
    foreach (string name in new[] { "get_document_summary", "run_command", "execute_rhinocommon_csharp_code", "get_management_status ", "GET_MANAGEMENT_STATUS", null })
        Assert(!ManagementClient.IsLocalDiagnostic(name), "Unexpected authorization bypass: " + name);
    return Task.CompletedTask;
});
await Test("missing config is blocked without a network request", async f =>
{
    File.Delete(f.ConfigPath);
    await Denied(f, "unconfigured");
    Assert(f.Handler.Calls == 0 && !(bool)f.Client.GetStatus()["configured"], "Missing configuration was accepted.");
});
await Test("malformed config is blocked", async f =>
{
    File.WriteAllText(f.ConfigPath, "{"); await Denied(f, "invalid_configuration");
});
await Test("duplicate config property is blocked", async f =>
{
    string json = File.ReadAllText(f.ConfigPath);
    File.WriteAllText(f.ConfigPath, json.Insert(1, "\"service_url\":\"https://other.example\","));
    await Denied(f, "invalid_configuration");
});
await Test("oversized config is blocked", async f =>
{
    File.WriteAllText(f.ConfigPath, new string(' ', ManagementClient.MaxResponseBytes + 1));
    await Denied(f, "invalid_configuration");
});
await Test("HTTP remote host is rejected even with loopback flag", async f =>
{
    f.SetConfig("service_url", "http://example.com"); await Denied(f, "invalid_configuration");
});
await Test("HTTP loopback requires explicit permission", async f =>
{
    f.SetConfig("allow_insecure_loopback", false); await Denied(f, "invalid_configuration");
});
await Test("non-boolean insecure-loopback flag rejected", async f =>
{
    f.SetConfig("allow_insecure_loopback", "true"); await Denied(f, "invalid_configuration");
});
foreach (string url in new[] { "https://name:password@example.com", "https://example.com?x=1", "https://example.com#section", "https://example.com/path", "file:///tmp/api", "http://127.0.0.2", "http://localhost.example.com" })
    await Test("invalid service URL " + url.Split('?')[0], async f =>
    {
        f.SetConfig("service_url", url); await Denied(f, "invalid_configuration");
    });
await Test("HTTPS configuration accepted with normal trust transport", async f =>
{
    f.SetConfig("service_url", "https://management.example.com");
    f.SetConfig("allow_insecure_loopback", false);
    Assert((await f.Client.AuthorizeAsync("create_object")).Allowed, "HTTPS configuration rejected.");
    Assert(f.Handler.Url == "https://management.example.com/v1/authorize", "Wrong authorization endpoint.");
});
foreach (string loopback in new[] { "http://[::1]:8765", "http://localhost:8765" })
await Test("explicit local demo loopback accepted " + loopback, async f =>
{
    f.SetConfig("service_url", loopback);
    Assert((await f.Client.AuthorizeAsync("create_object")).Allowed, "Explicit loopback was rejected.");
});
await Test("private key cannot be used as configured public key", async f =>
{
    f.SetConfig("public_key_pem", f.Key.ExportPkcs8PrivateKeyPem()); await Denied(f, "invalid_configuration");
});
await Test("weak RSA key rejected", async f =>
{
    using var weak = RSA.Create(1024); f.SetConfig("public_key_pem", weak.ExportSubjectPublicKeyInfoPem());
    await Denied(f, "invalid_configuration");
});
await Test("signed management denial is surfaced", async f =>
{
    f.PayloadMutation = p => { p["allowed"] = false; p["code"] = "version_paused"; p["reason"] = "Version maintenance"; };
    await Denied(f, "version_paused");
    Assert((string)f.Client.GetStatus()["state"] == "blocked", "Wrong policy state.");
});
await Test("normal operation can have an empty signed reason", async f =>
{
    f.PayloadMutation = p => p["reason"] = "";
    Assert((await f.Client.AuthorizeAsync("create_object")).Allowed, "Valid empty reason was rejected.");
});
foreach (string field in new[] { "nonce", "installation_id", "version", "command" })
    await Test("signed mismatched " + field + " rejected", async f =>
    {
        f.PayloadMutation = p => p[field] = "mismatch"; await Denied(f);
    });
await Test("wrong protocol rejected", async f => { f.PayloadMutation = p => p["protocol"] = 2; await Denied(f); });
await Test("string allowed field rejected", async f => { f.PayloadMutation = p => p["allowed"] = "true"; await Denied(f); });
await Test("missing reason rejected", async f => { f.PayloadMutation = p => p.Remove("reason"); await Denied(f); });
await Test("noninteger timestamp rejected", async f => { f.PayloadMutation = p => p["issued_at"] = 1.5; await Denied(f); });
await Test("expired signed authorization rejected", async f =>
{
    f.PayloadMutation = p => { p["issued_at"] = f.Now.ToUnixTimeSeconds() - 31; p["expires_at"] = f.Now.ToUnixTimeSeconds() - 1; };
    await Denied(f);
});
await Test("excessive signed approval lifetime rejected", async f =>
{
    f.PayloadMutation = p => p["expires_at"] = f.Now.ToUnixTimeSeconds() + 31; await Denied(f);
});
await Test("future signed authorization rejected", async f =>
{
    f.PayloadMutation = p => { p["issued_at"] = f.Now.ToUnixTimeSeconds() + 6; p["expires_at"] = f.Now.ToUnixTimeSeconds() + 36; };
    await Denied(f);
});
await Test("wrong signing key rejected", async f =>
{
    using var other = RSA.Create(2048); f.SigningKey = other; await Denied(f);
});
await Test("legacy PKCS1 v1.5 signature rejected", async f => { f.Padding = RSASignaturePadding.Pkcs1; await Denied(f); });
await Test("duplicate signed property rejected", async f =>
{
    f.RawPayloadMutation = s => s.Insert(1, "\"allowed\":false,"); await Denied(f);
});
await Test("signature tampering rejected", async f => { f.CorruptSignature = true; await Denied(f); });
await Test("replayed response for next request rejected", async f =>
{
    Assert((await f.Client.AuthorizeAsync("create_object")).Allowed, "Initial approval failed.");
    byte[] old = f.LastEnvelope;
    f.Handler.Responder = (_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(old) });
    await Denied(f);
});
await Test("non-success/redirect HTTP response rejected without retry", async f =>
{
    f.Handler.Responder = (_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.TemporaryRedirect)
    { Headers = { Location = new Uri("https://other.example/") } });
    await Denied(f, "unavailable");
    Assert(f.Handler.Calls == 1, "A denied request was retried.");
});
await Test("network failure blocks without retry", async f =>
{
    f.Handler.Responder = (_, _) => throw new HttpRequestException("network unavailable");
    await Denied(f, "unavailable"); Assert(f.Handler.Calls == 1, "Request was retried.");
});
await Test("response timeout is bounded to five seconds", async f =>
{
    f.Handler.Responder = async (_, cancellation) => { await Task.Delay(Timeout.Infinite, cancellation); return null; };
    var watch = Stopwatch.StartNew(); await Denied(f, "unavailable");
    Assert(watch.Elapsed.TotalSeconds < 7, "Timeout took too long.");
});
await Test("oversized declared response rejected", async f =>
{
    f.Handler.Responder = (_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
    { Content = new ByteArrayContent(new byte[ManagementClient.MaxResponseBytes + 1]) });
    await Denied(f);
});
await Test("oversized streaming response rejected even without length", async f =>
{
    f.Handler.Responder = (_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
    { Content = new UnknownLengthContent(new byte[ManagementClient.MaxResponseBytes + 1]) });
    await Denied(f);
});
await Test("queued approval expires by monotonic time despite clock rollback", async f =>
{
    var result = await f.Client.AuthorizeAsync("create_object");
    f.Ticks += 30000; f.Now = f.Now.AddHours(-1);
    Assert(!f.Client.IsGrantCurrent(result.Grant, out _), "Queued authorization survived 30 seconds.");
});
await Test("queued approval expires by signed wall clock", async f =>
{
    var result = await f.Client.AuthorizeAsync("create_object"); f.Now = f.Now.AddSeconds(30);
    Assert(!f.Client.IsGrantCurrent(result.Grant, out _), "Expired signed authorization dispatched.");
});
await Test("config deletion after approval blocks dispatch", async f =>
{
    var result = await f.Client.AuthorizeAsync("create_object"); File.Delete(f.ConfigPath);
    Assert(!f.Client.IsGrantCurrent(result.Grant, out _), "Missing config allowed queued dispatch.");
});
await Test("config replacement after approval blocks dispatch", async f =>
{
    var result = await f.Client.AuthorizeAsync("create_object"); f.SetConfig("installation_token", "replacement-token");
    Assert((string)f.Client.GetStatus()["state"] == "not_checked", "Status retained previous identity approval.");
    Assert(!f.Client.IsGrantCurrent(result.Grant, out _), "Changed config allowed queued dispatch.");
});
Console.WriteLine($"RESULT passed={passed} failed={failed}");
return failed == 0 ? 0 : 1;

sealed class Fixture : IDisposable
{
    private readonly string directory = Path.Combine(Path.GetTempPath(), "rhinomcp-management-test-" + Guid.NewGuid().ToString("N"));
    internal string ConfigPath { get; }
    internal string Token { get; } = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    internal RSA Key { get; } = RSA.Create(3072);
    internal RSA SigningKey;
    internal RSASignaturePadding Padding = RSASignaturePadding.Pss;
    internal FakeHandler Handler { get; } = new FakeHandler();
    internal ManagementClient Client { get; }
    internal DateTimeOffset Now = DateTimeOffset.FromUnixTimeSeconds(1789185600);
    internal long Ticks = 1000;
    internal Action<JsonObject> PayloadMutation;
    internal Func<string, string> RawPayloadMutation;
    internal bool CorruptSignature;
    internal byte[] LastEnvelope;
    private readonly JsonObject config;

    internal Fixture()
    {
        Directory.CreateDirectory(directory);
        ConfigPath = Path.Combine(directory, "management.json");
        config = new JsonObject
        {
            ["service_url"] = "http://127.0.0.1:8765", ["allow_insecure_loopback"] = true,
            ["public_key_pem"] = Key.ExportSubjectPublicKeyInfoPem(),
            ["installation_id"] = "test-installation", ["installation_token"] = Token
        };
        File.WriteAllText(ConfigPath, config.ToJsonString());
        SigningKey = Key;
        Handler.Responder = (request, _) =>
        {
            var payload = new JsonObject
            {
                ["protocol"] = 1, ["allowed"] = true, ["code"] = "allowed", ["reason"] = "Normal operation",
                ["installation_id"] = request["installation_id"].DeepClone(),
                ["version"] = request["version"].DeepClone(), ["command"] = request["command"].DeepClone(),
                ["nonce"] = request["nonce"].DeepClone(), ["issued_at"] = Now.ToUnixTimeSeconds(),
                ["expires_at"] = Now.ToUnixTimeSeconds() + 30
            };
            PayloadMutation?.Invoke(payload);
            string text = payload.ToJsonString();
            byte[] bytes = Encoding.UTF8.GetBytes(RawPayloadMutation == null ? text : RawPayloadMutation(text));
            byte[] signature = SigningKey.SignData(bytes, HashAlgorithmName.SHA256, Padding);
            if (CorruptSignature) signature[0] ^= 1;
            LastEnvelope = JsonSerializer.SerializeToUtf8Bytes(new
            { payload = Convert.ToBase64String(bytes), signature = Convert.ToBase64String(signature) });
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(LastEnvelope) });
        };
        Client = new ManagementClient(ConfigPath, "0.6.0", Handler, () => Now, () => Ticks, 1000);
    }

    internal void SetConfig<T>(string name, T value)
    {
        config[name] = JsonSerializer.SerializeToNode(value);
        File.WriteAllText(ConfigPath, config.ToJsonString());
    }

    public void Dispose()
    {
        Client.Dispose(); Key.Dispose();
        // This directory was created with an unguessable name by this fixture only.
        Directory.Delete(directory, true);
    }
}

sealed class FakeHandler : HttpMessageHandler
{
    internal Func<JsonObject, CancellationToken, Task<HttpResponseMessage>> Responder;
    internal int Calls;
    internal JsonObject Request;
    internal string Authorization;
    internal string Url;
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Calls++; Authorization = request.Headers.Authorization?.ToString(); Url = request.RequestUri.AbsoluteUri;
        Request = JsonNode.Parse(await request.Content.ReadAsStringAsync(cancellationToken)).AsObject();
        return await Responder(Request, cancellationToken);
    }
}

sealed class UnknownLengthContent(byte[] bytes) : HttpContent
{
    protected override bool TryComputeLength(out long length) { length = 0; return false; }
    protected override Task SerializeToStreamAsync(Stream stream, TransportContext context) => stream.WriteAsync(bytes).AsTask();
    protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new MemoryStream(bytes));
}
