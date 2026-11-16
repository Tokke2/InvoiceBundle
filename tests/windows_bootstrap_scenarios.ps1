$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $root 'autostart\start_fakturabunten.ps1') -NoMain

$script:scenario = ''
$script:discovery = 0
$script:questions = 0
$script:opened = 0
$script:starts = 0

function Get-InstalledPython {
    $script:discovery++
    if ($script:scenario -eq 'existing' -or
        ($script:scenario -eq 'appeared' -and $script:discovery -ge 2)) {
        return [pscustomobject]@{ Found = $true; Executable = 'C:\Existing Python\python.exe' }
    }
    if ($script:scenario -eq 'broken') {
        return [pscustomobject]@{ Found = $true; Executable = '' }
    }
    return [pscustomobject]@{ Found = $false; Executable = '' }
}
function Ask-ToOpenPythonDownload {
    $script:questions++
    return ($script:scenario -ne 'declined')
}
function Open-PythonDownload { $script:opened++ }
function Start-Application([string]$PythonExe) {
    if ($PythonExe -ne 'C:\Existing Python\python.exe') { throw 'wrong interpreter' }
    $script:starts++
}
function Reset-Scenario([string]$name) {
    $script:scenario = $name
    $script:discovery = 0
    $script:questions = 0
    $script:opened = 0
    $script:starts = 0
}

Reset-Scenario 'existing'
if ((Start-Fakturabunten) -ne 0 -or (Start-Fakturabunten) -ne 0) { throw 'existing Python must start' }
if ($script:questions -ne 0 -or $script:opened -ne 0 -or $script:starts -ne 2) { throw 'existing Python must not prompt' }

Reset-Scenario 'broken'
if ((Start-Fakturabunten) -ne 1) { throw 'broken Python must fail safely' }
if ($script:questions -ne 0 -or $script:opened -ne 0 -or $script:starts -ne 0) { throw 'broken Python must not prompt' }

Reset-Scenario 'declined'
if ((Start-Fakturabunten) -ne 2) { throw 'declining installation must exit' }
if ($script:questions -ne 1 -or $script:opened -ne 0 -or $script:starts -ne 0) { throw 'declined offer opened a page or started' }

Reset-Scenario 'accepted'
if ((Start-Fakturabunten) -ne 2) { throw 'accepted offer must wait for manual installation' }
if ($script:questions -ne 1 -or $script:opened -ne 1 -or $script:starts -ne 0 -or $script:discovery -ne 2) { throw 'offer must recheck and open only with consent' }

Reset-Scenario 'appeared'
if ((Start-Fakturabunten) -ne 0) { throw 'Python appearing during the question must start' }
if ($script:questions -ne 1 -or $script:opened -ne 0 -or $script:starts -ne 1) { throw 'do not open download after Python appears' }
Write-Output 'Windows bootstrap scenarios passed'
