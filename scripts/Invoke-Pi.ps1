# Run a local Bash script on the Pi without storing its contents remotely.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptPath,

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.:-]*$')]
    [string]$PiAddress = '100.111.233.84',

    [ValidatePattern('^[a-z_][a-z0-9_-]*$')]
    [string]$SshUser = 'ben',

    [string]$IdentityFile = $env:GARCHING_BOARD_SSH_KEY,
    [string]$KnownHostsFile = $env:GARCHING_BOARD_KNOWN_HOSTS,
    [switch]$Root
)

$ErrorActionPreference = 'Stop'
foreach ($entry in @{
    ScriptPath = $ScriptPath
    IdentityFile = $IdentityFile
    KnownHostsFile = $KnownHostsFile
}.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace($entry.Value) -or
        -not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) {
        throw "$($entry.Key) must refer to an existing file. See README.md for SSH access settings."
    }
}

$identityPath = (Resolve-Path -LiteralPath $IdentityFile).ProviderPath
$knownHostsPath = (Resolve-Path -LiteralPath $KnownHostsFile).ProviderPath
$scriptText = (Get-Content -LiteralPath $ScriptPath -Raw -Encoding UTF8).Replace("`r`n", "`n")
$payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($scriptText))
$shellCommand = if ($Root) { 'sudo -n bash' } else { 'bash' }
$remoteCommand = "printf '%s' '$payload' | base64 -d | $shellCommand"
$sshArguments = @(
    '-i', $identityPath,
    '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=yes',
    '-o', "UserKnownHostsFile=`"$knownHostsPath`"",
    '-o', 'HostKeyAlias=garching-board.local',
    '-o', 'ConnectTimeout=8', '-o', 'ConnectionAttempts=1',
    '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
    "$SshUser@$PiAddress", $remoteCommand
)

$sshCommand = Get-Command ssh.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
& $sshCommand.Source @sshArguments
if ($LASTEXITCODE -ne 0) {
    throw "Pi command failed with SSH exit code $LASTEXITCODE"
}
