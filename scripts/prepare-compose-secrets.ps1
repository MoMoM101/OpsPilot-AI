[CmdletBinding()]
param(
    [string]$EnvFile = ".env",
    [string]$OutputDirectory = ".secrets",
    [switch]$GenerateMissing,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$envPath = [IO.Path]::GetFullPath((Join-Path $repositoryRoot $EnvFile))
$outputPath = [IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputDirectory))
if (-not $outputPath.StartsWith($repositoryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Secret output directory must remain inside the repository"
}
$values = @{}
if ([IO.File]::Exists($envPath)) {
    foreach ($line in [IO.File]::ReadAllLines($envPath)) {
        if ($line.TrimStart().StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $key, $value = $line.Split("=", 2)
        $values[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
}

$mapping = [ordered]@{
    OPSPILOT_POSTGRES_PASSWORD = "postgres_password"
    OPSPILOT_ALERTMANAGER_WEBHOOK_TOKEN = "alertmanager_webhook_token"
    OPSPILOT_RUNNER_BOOTSTRAP_TOKEN = "runner_bootstrap_token"
    OPSPILOT_CONTROL_PLANE_BOOTSTRAP_TOKEN = "control_plane_bootstrap_token"
}

[IO.Directory]::CreateDirectory($outputPath) | Out-Null
$isUnix = [Environment]::OSVersion.Platform -eq [PlatformID]::Unix
if ($isUnix) {
    [IO.File]::SetUnixFileMode(
        $outputPath,
        [IO.UnixFileMode]::UserRead -bor
            [IO.UnixFileMode]::UserWrite -bor
            [IO.UnixFileMode]::UserExecute
    )
}
$encoding = [Text.UTF8Encoding]::new($false)
foreach ($entry in $mapping.GetEnumerator()) {
    $target = Join-Path $outputPath $entry.Value
    if ([IO.File]::Exists($target) -and -not $Force) {
        if ($isUnix) {
            [IO.File]::SetUnixFileMode(
                $target,
                [IO.UnixFileMode]::UserRead -bor
                    [IO.UnixFileMode]::UserWrite -bor
                    [IO.UnixFileMode]::GroupRead -bor
                    [IO.UnixFileMode]::OtherRead
            )
        }
        Write-Output "EXISTS $($entry.Value)"
        continue
    }
    $value = $values[$entry.Key]
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = [Environment]::GetEnvironmentVariable($entry.Key)
    }
    if ([string]::IsNullOrWhiteSpace($value) -and $GenerateMissing) {
        if ($entry.Key -eq "OPSPILOT_POSTGRES_PASSWORD") {
            throw "Database password cannot be generated; copy the existing value explicitly"
        }
        $bytes = [byte[]]::new(48)
        [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
        $value = [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
    }
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required secret is missing or empty: $($entry.Key)"
    }
    if ($value.Contains("`n") -or $value.Contains("`r")) {
        throw "Secret contains a newline: $($entry.Key)"
    }
    [IO.File]::WriteAllText($target, $value, $encoding)
    if ($isUnix) {
        # Compose implements file-backed secrets as bind mounts. The owner-only
        # parent directory protects the host path, while the mounted file must
        # remain readable by the service's non-root UID.
        [IO.File]::SetUnixFileMode(
            $target,
            [IO.UnixFileMode]::UserRead -bor
                [IO.UnixFileMode]::UserWrite -bor
                [IO.UnixFileMode]::GroupRead -bor
                [IO.UnixFileMode]::OtherRead
        )
    }
    Write-Output "WROTE $($entry.Value)"
}
