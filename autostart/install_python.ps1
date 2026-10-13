# Fakturabunten — installerar alltid senaste stabila Python på datorn.
# Anropas av "Installera senaste Python.bat". Skriver inte Python i appmappen.
param()

$ErrorActionPreference = "Stop"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}

$AppDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$LogDir = Join-Path $AppDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "starta.log"

function Write-Log([string]$Msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
    Add-Content -Path $Log -Value $line -Encoding UTF8
    Write-Host $Msg
}

function Get-ArchTag {
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($arch -eq "ARM64") { return "arm64" }
    if ($arch -eq "x86") { return "win32" }
    return "amd64"
}

function Get-InstallerUrl([string]$Tag) {
    $fallback = @{
        amd64 = "https://www.python.org/ftp/python/3.14.8/python-3.14.8-amd64.exe"
        arm64 = "https://www.python.org/ftp/python/3.14.8/python-3.14.8-arm64.exe"
        win32 = "https://www.python.org/ftp/python/3.14.8/python-3.14.8.exe"
    }
    try {
        $page = Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/downloads/windows/"
        if ($Tag -eq "win32") {
            $rx = 'https://www\.python\.org/ftp/python/(3\.\d+\.\d+)/python-\1\.exe'
        } else {
            $rx = "https://www\.python\.org/ftp/python/(3\.\d+\.\d+)/python-\1-$Tag\.exe"
        }
        $m = [regex]::Match($page.Content, $rx)
        if ($m.Success -and $m.Groups[1].Value -notmatch '[a-zA-Z]') {
            return $m.Value
        }
    } catch {
        Write-Log ("Kunde inte läsa python.org, använder reservlänk: " + $_.Exception.Message)
    }
    return $fallback[$Tag]
}

$tag = Get-ArchTag
$url = Get-InstallerUrl $tag
$tmpDir = Join-Path $AppDir "logs"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$tmp = Join-Path $tmpDir ("python-installer-" + [guid]::NewGuid().ToString("N") + ".exe")

Write-Log "INSTALL_PYTHON_DATOR: $url"
Write-Host "Hämtar $url"

$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if ($curl) {
    & curl.exe -L --fail --retry 3 --retry-delay 2 -o $tmp $url
    if ($LASTEXITCODE -ne 0) { throw "Nedladdningen misslyckades (curl $LASTEXITCODE)" }
} else {
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tmp
}

Write-Host "Installerar senaste Python på den här datorn..."
# /passive visar installerarens egen förloppsindikator.
# InstallAllUsers=0 kräver ingen administratör. PrependPath gör att
# python och py finns i kommandotolken efteråt.
$arg = "/passive InstallAllUsers=0 PrependPath=1 AppendPath=0 Include_pip=1 Include_launcher=1 Include_test=0 Include_doc=0 Shortcuts=1 AssociateFiles=1 CompileAll=0"
$proc = Start-Process -FilePath $tmp -ArgumentList $arg -Wait -PassThru
$code = $proc.ExitCode
Remove-Item -Force $tmp -ErrorAction SilentlyContinue

if ($code -ne 0 -and $code -ne 3010) {
    Write-Log "INSTALL_PYTHON_FAIL: exit $code"
    throw "Python-installeraren avslutades med kod $code"
}

Write-Log "INSTALL_PYTHON_OK: på datorn (exit $code)"
exit 0
