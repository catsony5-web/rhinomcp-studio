using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace RhinoMCPPlugin.Management;

/// <summary>Fresh, signed authorization for each command. No cached approval or offline mode.</summary>
internal sealed class ManagementClient : IDisposable
{
    internal const int MaxResponseBytes = 16 * 1024;
    internal const int ApprovalLifetimeSeconds = 30;
    private readonly HttpClient http;
    private readonly string configPath;
    private readonly string version;
    private readonly Func<DateTimeOffset> utcNow;
    private readonly Func<long> timestamp;
    private readonly long timestampFrequency;
    private readonly object statusLock = new object();
    private string lastConfigFingerprint;
    private string lastState = "not_checked";
    private string lastReason = "아직 사용 승인을 확인하지 않았습니다. Authorization has not been checked.";
    private string lastCheckedAt;

    internal ManagementClient(string configPath, string version, HttpMessageHandler handler = null,
        Func<DateTimeOffset> utcNow = null, Func<long> timestamp = null, long timestampFrequency = 0)
    {
        this.configPath = configPath;
        this.version = version;
        this.utcNow = utcNow ?? (() => DateTimeOffset.UtcNow);
        this.timestamp = timestamp ?? Stopwatch.GetTimestamp;
        this.timestampFrequency = timestampFrequency > 0 ? timestampFrequency : Stopwatch.Frequency;
        http = new HttpClient(handler ?? new HttpClientHandler
        {
            AllowAutoRedirect = false,
            AutomaticDecompression = DecompressionMethods.None
        }) { Timeout = Timeout.InfiniteTimeSpan };
    }

    internal static bool IsLocalDiagnostic(string command) =>
        command == "describe_capabilities" || command == "get_management_status";

    internal async Task<AuthorizationResult> AuthorizeAsync(string command)
    {
        Configuration configuration;
        try { configuration = LoadConfiguration(); }
        catch (ConfigurationException ex) { return Reject(ex.Code, ex.Message, null); }

        var startedAt = utcNow();
        long startedTimestamp = timestamp();
        string nonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            using var request = new HttpRequestMessage(HttpMethod.Post, configuration.AuthorizeUrl);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", configuration.Token);
            request.Content = new StringContent(JsonSerializer.Serialize(new
            {
                installation_id = configuration.InstallationId,
                version,
                command,
                nonce
            }), Encoding.UTF8, "application/json");
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead,
                timeout.Token).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                return Reject("unavailable", "관리 서버가 사용을 승인하지 않았습니다. Management service did not authorize this request. 관리자에게 상태를 확인하세요.", configuration);
            byte[] body = await ReadBoundedAsync(response.Content, timeout.Token).ConfigureAwait(false);
            using var envelope = ParseObject(body);
            string payloadBase64 = RequiredString(envelope.RootElement, "payload", MaxResponseBytes);
            string signatureBase64 = RequiredString(envelope.RootElement, "signature", 2048);
            byte[] payload = Convert.FromBase64String(payloadBase64);
            byte[] signature = Convert.FromBase64String(signatureBase64);
            using RSA key = OpenPublicKey(configuration.PublicKeyPem);
            if (signature.Length != key.KeySize / 8 || !key.VerifyData(payload, signature,
                HashAlgorithmName.SHA256, RSASignaturePadding.Pss))
                throw new InvalidDataException("Signature verification failed.");
            using var signed = ParseObject(payload);
            var fields = signed.RootElement;
            RequireEqual(fields, "nonce", nonce);
            RequireEqual(fields, "installation_id", configuration.InstallationId);
            RequireEqual(fields, "version", version);
            RequireEqual(fields, "command", command);
            if (RequiredInteger(fields, "protocol") != 1)
                throw new InvalidDataException("Unsupported protocol.");
            long issuedAt = RequiredInteger(fields, "issued_at");
            long expiresAt = RequiredInteger(fields, "expires_at");
            long now = utcNow().ToUnixTimeSeconds();
            if (issuedAt > long.MaxValue - ApprovalLifetimeSeconds ||
                expiresAt != issuedAt + ApprovalLifetimeSeconds || issuedAt > now + 5 ||
                issuedAt < startedAt.ToUnixTimeSeconds() - 5 || now >= expiresAt ||
                ElapsedSeconds(startedTimestamp) >= ApprovalLifetimeSeconds)
                throw new InvalidDataException("Authorization is expired or has invalid timestamps.");
            if (!fields.TryGetProperty("allowed", out var allowed) ||
                (allowed.ValueKind != JsonValueKind.True && allowed.ValueKind != JsonValueKind.False))
                throw new InvalidDataException("The allowed field must be boolean.");
            string code = RequiredString(fields, "code", 128);
            string reason = RequiredString(fields, "reason", 2048, allowEmpty: true);
            if (!allowed.GetBoolean())
                return Reject("blocked", reason + " / MCP 요청이 중지되었습니다. 관리자 안내를 확인하세요. Request blocked; contact the administrator.", configuration, code);
            var grant = new AuthorizationGrant(configuration.Fingerprint, startedTimestamp, expiresAt);
            RecordStatus(configuration.Fingerprint, "allowed", reason);
            return new AuthorizationResult(true, code, reason, grant);
        }
        catch (OperationCanceledException)
        {
            return Reject("unavailable", "관리 서버 응답 시간이 초과되었습니다. Authorization timed out. 인터넷 연결과 관리 서버 상태를 확인하세요.", configuration);
        }
        catch (HttpRequestException)
        {
            return Reject("unavailable", "관리 서버에 연결할 수 없습니다. Cannot reach the management service. 인터넷 연결과 관리 서버 주소를 확인하세요.", configuration);
        }
        catch (Exception ex) when (ex is JsonException || ex is InvalidDataException ||
            ex is FormatException || ex is CryptographicException || ex is IOException || ex is ArgumentException)
        {
            return Reject("invalid_response", "사용 승인 응답을 검증하지 못했습니다. Authorization response could not be verified. 관리자에게 문의하세요.", configuration);
        }
    }

    /// <summary>Called immediately before dispatch, including after waiting for Rhino's UI thread.</summary>
    internal bool IsGrantCurrent(AuthorizationGrant grant, out string reason)
    {
        Configuration configuration;
        try { configuration = LoadConfiguration(); }
        catch (ConfigurationException ex)
        {
            Reject(ex.Code, ex.Message, null);
            reason = ex.Message;
            return false;
        }
        if (grant == null || configuration.Fingerprint != grant.ConfigurationFingerprint ||
            ElapsedSeconds(grant.StartedTimestamp) >= ApprovalLifetimeSeconds ||
            utcNow().ToUnixTimeSeconds() >= grant.ExpiresAt)
        {
            reason = "대기 중 사용 승인이 만료되었거나 설정이 변경되었습니다. Authorization expired or configuration changed. 새 요청을 보내세요.";
            Reject("authorization_expired", reason, configuration);
            return false;
        }
        reason = null;
        return true;
    }

    internal Dictionary<string, object> GetStatus()
    {
        Configuration configuration;
        try { configuration = LoadConfiguration(); }
        catch (ConfigurationException ex)
        {
            return Status(false, ex.Code, ex.Message, null, null, null);
        }
        lock (statusLock)
        {
            bool same = configuration.Fingerprint == lastConfigFingerprint;
            return Status(true, same ? lastState : "not_checked",
                same ? lastReason : "설정됨. 다음 요청에서 온라인 승인을 확인합니다. Configured; authorization is checked on the next request.",
                configuration.InstallationId, configuration.ServiceUrl, same ? lastCheckedAt : null);
        }
    }

    private Dictionary<string, object> Status(bool configured, string state, string reason,
        string installationId, string serviceUrl, string checkedAt) => new Dictionary<string, object>
        {
            ["configured"] = configured, ["state"] = state, ["reason"] = reason,
            ["installation_id"] = installationId, ["service_url"] = serviceUrl,
            ["last_checked_at"] = checkedAt, ["version"] = version
        };

    private double ElapsedSeconds(long since) => (timestamp() - since) / (double)timestampFrequency;

    private AuthorizationResult Reject(string state, string reason, Configuration configuration, string code = null)
    {
        RecordStatus(configuration?.Fingerprint, state, reason);
        return new AuthorizationResult(false, code ?? state, reason, null);
    }

    private void RecordStatus(string fingerprint, string state, string reason)
    {
        lock (statusLock)
        {
            lastConfigFingerprint = fingerprint;
            lastState = state;
            lastReason = reason;
            lastCheckedAt = utcNow().ToString("O");
        }
    }

    private Configuration LoadConfiguration()
    {
        try
        {
            using var file = new FileStream(configPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            if (file.Length > MaxResponseBytes) throw new InvalidDataException("Configuration too large.");
            using var buffer = new MemoryStream();
            var chunk = new byte[4096];
            int count;
            while ((count = file.Read(chunk, 0, Math.Min(chunk.Length, MaxResponseBytes + 1 - (int)buffer.Length))) > 0)
            {
                buffer.Write(chunk, 0, count);
                if (buffer.Length > MaxResponseBytes) throw new InvalidDataException("Configuration too large.");
            }
            byte[] bytes = buffer.ToArray();
            using var parsed = ParseObject(bytes);
            var fields = parsed.RootElement;
            string service = RequiredString(fields, "service_url", 2048);
            bool allowLoopback = fields.TryGetProperty("allow_insecure_loopback", out var flag) &&
                flag.ValueKind == JsonValueKind.True;
            if (fields.TryGetProperty("allow_insecure_loopback", out flag) &&
                flag.ValueKind != JsonValueKind.True && flag.ValueKind != JsonValueKind.False)
                throw new InvalidDataException("Invalid loopback flag.");
            if (!Uri.TryCreate(service, UriKind.Absolute, out var url) ||
                !string.IsNullOrEmpty(url.UserInfo) || !string.IsNullOrEmpty(url.Query) ||
                !string.IsNullOrEmpty(url.Fragment) || string.IsNullOrEmpty(url.Host) || url.AbsolutePath != "/" ||
                (url.Scheme != Uri.UriSchemeHttps && !(url.Scheme == Uri.UriSchemeHttp && allowLoopback &&
                    (url.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase) || url.Host == "127.0.0.1" || url.Host == "[::1]"))))
                throw new InvalidDataException("Invalid management URL.");
            string publicKey = RequiredString(fields, "public_key_pem", 8192);
            using var key = OpenPublicKey(publicKey);
            string installationId = RequiredString(fields, "installation_id", 256);
            string token = RequiredString(fields, "installation_token", 4096);
            if (token.Any(char.IsWhiteSpace) || token.Any(char.IsControl))
                throw new InvalidDataException("Invalid installation token.");
            return new Configuration(url.AbsoluteUri.TrimEnd('/'), publicKey, installationId, token,
                Convert.ToHexString(SHA256.HashData(bytes)));
        }
        catch (Exception ex) when (ex is FileNotFoundException || ex is DirectoryNotFoundException)
        {
            throw new ConfigurationException("unconfigured", "관리 설정이 없습니다. Management configuration is missing. 관리형 설치 프로그램으로 등록하세요.");
        }
        catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException ||
            ex is JsonException || ex is InvalidDataException || ex is ArgumentException ||
            ex is FormatException || ex is CryptographicException)
        {
            throw new ConfigurationException("invalid_configuration", "관리 설정을 읽거나 검증할 수 없습니다. Invalid management configuration. 관리형 설치 프로그램으로 설정을 복구하세요.");
        }
    }

    private static RSA OpenPublicKey(string pem)
    {
        const string begin = "-----BEGIN PUBLIC KEY-----";
        const string end = "-----END PUBLIC KEY-----";
        string text = pem.Trim();
        if (!text.StartsWith(begin, StringComparison.Ordinal) || !text.EndsWith(end, StringComparison.Ordinal))
            throw new InvalidDataException("An SPKI public key is required.");
        byte[] der = Convert.FromBase64String(text.Substring(begin.Length, text.Length - begin.Length - end.Length));
        var rsa = RSA.Create();
        try
        {
            rsa.ImportSubjectPublicKeyInfo(der, out int read);
            if (read != der.Length || rsa.KeySize < 3072 || rsa.KeySize > 8192)
                throw new InvalidDataException("Invalid public key.");
            return rsa;
        }
        catch { rsa.Dispose(); throw; }
    }

    private static async Task<byte[]> ReadBoundedAsync(HttpContent content, CancellationToken cancellation)
    {
        if (content.Headers.ContentLength > MaxResponseBytes) throw new InvalidDataException("Response too large.");
        using var source = await content.ReadAsStreamAsync(cancellation).ConfigureAwait(false);
        using var result = new MemoryStream();
        byte[] buffer = new byte[4096];
        int read;
        while ((read = await source.ReadAsync(buffer.AsMemory(0, Math.Min(buffer.Length,
            MaxResponseBytes + 1 - (int)result.Length)), cancellation).ConfigureAwait(false)) > 0)
        {
            result.Write(buffer, 0, read);
            if (result.Length > MaxResponseBytes) throw new InvalidDataException("Response too large.");
        }
        return result.ToArray();
    }

    private static JsonDocument ParseObject(byte[] bytes)
    {
        var document = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 8 });
        try
        {
            if (document.RootElement.ValueKind != JsonValueKind.Object)
                throw new InvalidDataException("Expected JSON object.");
            RejectDuplicateKeys(document.RootElement);
            return document;
        }
        catch { document.Dispose(); throw; }
    }

    private static void RejectDuplicateKeys(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var field in value.EnumerateObject())
            {
                if (!names.Add(field.Name)) throw new InvalidDataException("Duplicate JSON key.");
                RejectDuplicateKeys(field.Value);
            }
        }
        else if (value.ValueKind == JsonValueKind.Array)
            foreach (var item in value.EnumerateArray()) RejectDuplicateKeys(item);
    }

    private static string RequiredString(JsonElement fields, string name, int limit, bool allowEmpty = false)
    {
        if (!fields.TryGetProperty(name, out var field) || field.ValueKind != JsonValueKind.String)
            throw new InvalidDataException("Missing string field.");
        string value = field.GetString();
        if ((!allowEmpty && string.IsNullOrWhiteSpace(value)) || value.Length > limit)
            throw new InvalidDataException("Invalid string field.");
        return value;
    }

    private static long RequiredInteger(JsonElement fields, string name)
    {
        if (!fields.TryGetProperty(name, out var field) || field.ValueKind != JsonValueKind.Number ||
            !field.TryGetInt64(out long value)) throw new InvalidDataException("Invalid integer field.");
        return value;
    }

    private static void RequireEqual(JsonElement fields, string name, string expected)
    {
        if (RequiredString(fields, name, 1024) != expected)
            throw new InvalidDataException("Authorization does not match the request.");
    }

    public void Dispose() => http.Dispose();

    private sealed record Configuration(string ServiceUrl, string PublicKeyPem, string InstallationId,
        string Token, string Fingerprint)
    {
        internal Uri AuthorizeUrl => new Uri(ServiceUrl + "/v1/authorize");
    }

    private sealed class ConfigurationException : Exception
    {
        internal string Code { get; }
        internal ConfigurationException(string code, string message) : base(message) { Code = code; }
    }
}

internal sealed record AuthorizationGrant(string ConfigurationFingerprint, long StartedTimestamp, long ExpiresAt);
internal sealed record AuthorizationResult(bool Allowed, string Code, string Reason, AuthorizationGrant Grant);
