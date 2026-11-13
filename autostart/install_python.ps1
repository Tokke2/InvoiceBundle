# Fakturabunten — kontrollera och uppdatera datorns Python.
# Python på datorn uppdateras i stället för att lämna kvar en extra version.
# Ny Python installeras bara när ingen körbar Python hittas alls.
[CmdletBinding()]
param(
    [switch]$Elevated,
    [int]$WaitForPid = 0,
    [switch]$UpdatePackages,
    [switch]$UseUserPackages,
    [string]$PythonExe = "",
    [string]$Slot = ""
)

$ErrorActionPreference = "Stop"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}

$AppDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$LogDir = Join-Path $AppDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "starta.log"
$StateFile = Join-Path (Join-Path $AppDir 'data') 'python_update_state.json'
$TempInstaller = $null

function Write-Log([string]$Msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
    Add-Content -Path $Log -Value $line -Encoding UTF8
    Write-Host $Msg
}

function Write-WeeklyState([string]$Status, [string]$Message) {
    if ([string]::IsNullOrWhiteSpace($Slot)) { return }
    try {
        $stateDir = Split-Path -Parent $StateFile
        New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
        $state = [ordered]@{
            last_slot  = $Slot
            status     = $Status
            worker_pid = 0
            app_pid    = 0
            updated_at = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
            message    = $Message
        }
        $temp = $StateFile + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
        $json = ConvertTo-Json -InputObject $state -Depth 4
        $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($temp, $json, $utf8NoBom)
        Move-Item -LiteralPath $temp -Destination $StateFile -Force
    } catch {
        Write-Log ("PYTHON_WEEKLY_STATE_WRITE_FAIL: " + $_.Exception.Message)
    }
}

function Wait-ForApplicationExit([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    $target = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $target) { return }
    $startTime = $target.StartTime
    Write-Log "PYTHON_WEEKLY_WAIT: väntar tills Fakturabunten har stängts före uppdatering."
    while ($true) {
        Start-Sleep -Seconds 2
        $target = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if (-not $target) { break }
        try {
            if ($target.StartTime -ne $startTime) { break }
        } catch { break }
    }
}

function Normalize-Path([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    try {
        return [IO.Path]::GetFullPath(
            [Environment]::ExpandEnvironmentVariables($Value)
        ).TrimEnd('\')
    } catch {
        return $Value.Trim().TrimEnd('\')
    }
}

function Get-PythonInfo([string]$Exe) {
    if ([string]::IsNullOrWhiteSpace($Exe) -or
        -not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
        return $null
    }
    try {
        $code = 'import sys, struct, platform; print("%d.%d.%d|%d|%s" % (sys.version_info[:3] + (struct.calcsize("P") * 8, platform.machine())))'
        $lines = @(& $Exe -c $code 2>$null)
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0 -or $lines.Count -eq 0) { return $null }
        $parts = ([string]$lines[-1]).Trim().Split('|')
        if ($parts.Length -lt 3) { return $null }
        $version = [version]$parts[0]
        $installDir = Split-Path -Parent $Exe
        return [pscustomobject]@{
            Version    = $version
            ExePath    = (Normalize-Path $Exe)
            InstallDir = (Normalize-Path $installDir)
            Bits       = [int]$parts[1]
            Machine    = [string]$parts[2]
        }
    } catch {
        return $null
    }
}

function Get-RegistryViews {
    if ([Environment]::Is64BitOperatingSystem) {
        return @(
            [Microsoft.Win32.RegistryView]::Registry64,
            [Microsoft.Win32.RegistryView]::Registry32
        )
    }
    return @([Microsoft.Win32.RegistryView]::Registry32)
}

function Get-PathScope([string]$InstallDir) {
    $path = Normalize-Path $InstallDir
    $userRoot = Normalize-Path (Join-Path $env:LOCALAPPDATA "Programs\Python")
    if ($path.StartsWith($userRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        return "User"
    }
    $programRoots = @(
        (Normalize-Path $env:ProgramFiles),
        (Normalize-Path ([Environment]::GetEnvironmentVariable('ProgramFiles(x86)')))
    ) | Where-Object { $_ }
    foreach ($root in $programRoots) {
        if ($path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            return "Machine"
        }
    }
    return "Other"
}

function Get-RegistryPythonEntries {
    $result = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    $hives = @(
        @{ Hive = [Microsoft.Win32.RegistryHive]::CurrentUser; Name = "HKCU" },
        @{ Hive = [Microsoft.Win32.RegistryHive]::LocalMachine; Name = "HKLM" }
    )
    foreach ($hive in $hives) {
        foreach ($view in (Get-RegistryViews)) {
            $baseKey = $null
            $coreKey = $null
            try {
                $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
                    $hive.Hive, $view
                )
                $coreKey = $baseKey.OpenSubKey('Software\Python\PythonCore')
                if ($null -eq $coreKey) { continue }
                foreach ($tag in $coreKey.GetSubKeyNames()) {
                    if ($tag -notmatch '^\d+\.\d+$') { continue }
                    $installKey = $null
                    try {
                        $installKey = $coreKey.OpenSubKey("$tag\InstallPath")
                        if ($null -eq $installKey) { continue }
                        $dir = [string]$installKey.GetValue('')
                        $exe = [string]$installKey.GetValue('ExecutablePath')
                        if ([string]::IsNullOrWhiteSpace($exe) -and $dir) {
                            $exe = Join-Path $dir 'python.exe'
                        }
                        if ([string]::IsNullOrWhiteSpace($exe)) { continue }
                        $key = (Normalize-Path $exe).ToLowerInvariant()
                        if ($seen.ContainsKey($key)) { continue }
                        $seen[$key] = $true
                        $info = Get-PythonInfo $exe
                        $valid = ($null -ne $info)
                        if ($valid) {
                            $version = $info.Version
                            $installDir = $info.InstallDir
                            $bits = $info.Bits
                            $machine = $info.Machine
                        } else {
                            $version = [version]("$tag.0")
                            $installDir = Normalize-Path $dir
                            $bits = 0
                            $machine = ""
                        }
                        $result.Add([pscustomobject]@{
                            Version     = $version
                            ExePath     = (Normalize-Path $exe)
                            InstallDir  = $installDir
                            Bits        = $bits
                            Machine     = $machine
                            Scope       = (Get-PathScope $installDir)
                            Registry    = $hive.Name
                            RegistryTag = $tag
                            Valid       = $valid
                        })
                    } finally {
                        if ($null -ne $installKey) { $installKey.Dispose() }
                    }
                }
            } catch {
                Write-Log ("PYTHON_REGISTRY_READ_FAIL: " + $_.Exception.Message)
            } finally {
                if ($null -ne $coreKey) { $coreKey.Dispose() }
                if ($null -ne $baseKey) { $baseKey.Dispose() }
            }
        }
    }
    return $result.ToArray()
}

function Find-UnregisteredPython($KnownEntries) {
    $known = @{}
    foreach ($entry in $KnownEntries) {
        if ($entry.ExePath) { $known[(Normalize-Path $entry.ExePath).ToLowerInvariant()] = $true }
    }
    $candidates = New-Object System.Collections.Generic.List[string]
    $localAppPython = Join-Path $AppDir 'python\python.exe'
    if (Test-Path -LiteralPath $localAppPython -PathType Leaf) {
        Write-Log "PYTHON_APP_LOCAL_IGNORED: $localAppPython; only system Python installations are eligible."
    }

    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -and
        $command.Source -notmatch '(?i)\\Microsoft\\WindowsApps\\') {
        $candidates.Add($command.Source)
    }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        (Join-Path $env:LOCALAPPDATA 'Python'),
        $env:ProgramFiles,
        [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) }
    foreach ($root in $roots) {
        try {
            foreach ($folder in (Get-ChildItem -LiteralPath $root -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)) {
                $exe = Join-Path $folder.FullName 'python.exe'
                if (Test-Path -LiteralPath $exe -PathType Leaf) {
                    $candidates.Add($exe)
                }
            }
        } catch {}
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        $normalized = Normalize-Path $candidate
        $key = $normalized.ToLowerInvariant()
        if ($seen.ContainsKey($key) -or $known.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $info = Get-PythonInfo $normalized
        if ($null -ne $info) { return $info }
    }
    try {
        $storePython = @(Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -like 'PythonSoftwareFoundation.Python*'
        })
        if ($storePython.Count -gt 0) {
            return [pscustomobject]@{
                ExePath = "Microsoft Store Python: $($storePython[0].InstallLocation)"
            }
        }
    } catch {}
    return $null
}

function Get-ArchTag($PythonInfo) {
    if ($PythonInfo) {
        if ($PythonInfo.Bits -eq 32) { return 'win32' }
        if ($PythonInfo.Machine -match '(?i)arm64|aarch64') { return 'arm64' }
        return 'amd64'
    }
    $arch = $env:PROCESSOR_ARCHITEW6432
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    if ($arch -eq 'ARM64') { return 'arm64' }
    if ($arch -eq 'x86') { return 'win32' }
    return 'amd64'
}

function Get-LatestInstallerInfo([string]$Tag) {
    $fallbackVersion = '3.14.8'
    $fallback = @{
        amd64 = "https://www.python.org/ftp/python/$fallbackVersion/python-$fallbackVersion-amd64.exe"
        arm64 = "https://www.python.org/ftp/python/$fallbackVersion/python-$fallbackVersion-arm64.exe"
        win32 = "https://www.python.org/ftp/python/$fallbackVersion/python-$fallbackVersion.exe"
    }
    try {
        $page = Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/downloads/windows/'
        if ($Tag -eq 'win32') {
            $rx = 'https://www\.python\.org/ftp/python/(3\.\d+\.\d+)/python-\1\.exe'
        } else {
            $rx = "https://www\.python\.org/ftp/python/(3\.\d+\.\d+)/python-\1-$Tag\.exe"
        }
        $match = [regex]::Match($page.Content, $rx)
        if ($match.Success) {
            return [pscustomobject]@{
                Version = [version]$match.Groups[1].Value
                Url     = $match.Value
            }
        }
        Write-Log 'Kunde inte hitta stabil Windows-installer på python.org; använder reservversionen.'
    } catch {
        Write-Log ("Kunde inte läsa python.org, använder reservversionen: " + $_.Exception.Message)
    }
    return [pscustomobject]@{
        Version = [version]$fallbackVersion
        Url     = $fallback[$Tag]
    }
}

function Get-DefaultInstallDir([version]$Version, [string]$Scope, [int]$Bits) {
    $folder = 'Python{0}{1}' -f $Version.Major, $Version.Minor
    if ($Scope -eq 'User') {
        return Join-Path (Join-Path $env:LOCALAPPDATA 'Programs\Python') $folder
    }
    $base = $env:ProgramFiles
    if ($Bits -eq 32 -and [Environment]::Is64BitOperatingSystem) {
        $base = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    }
    return Join-Path $base $folder
}

function Get-UninstallEntry($PythonInfo, [string]$Scope) {
    $targetDir = Normalize-Path $PythonInfo.InstallDir
    $hiveSpec = if ($Scope -eq 'User') {
        @(@{ Hive = [Microsoft.Win32.RegistryHive]::CurrentUser; Name = 'HKCU' })
    } else {
        @(@{ Hive = [Microsoft.Win32.RegistryHive]::LocalMachine; Name = 'HKLM' })
    }
    $uninstallMatches = New-Object System.Collections.Generic.List[object]
    foreach ($hive in $hiveSpec) {
        foreach ($view in (Get-RegistryViews)) {
            $baseKey = $null
            $uninstallRoot = $null
            try {
                $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive.Hive, $view)
                $uninstallRoot = $baseKey.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall')
                if ($null -eq $uninstallRoot) { continue }
                foreach ($subName in $uninstallRoot.GetSubKeyNames()) {
                    $key = $null
                    try {
                        $key = $uninstallRoot.OpenSubKey($subName)
                        if ($null -eq $key) { continue }
                        $displayName = [string]$key.GetValue('DisplayName')
                        $publisher = [string]$key.GetValue('Publisher')
                        if ($displayName -notmatch '^Python\s+' -or
                            $publisher -notmatch 'Python Software Foundation') { continue }
                        $installLocation = Normalize-Path ([string]$key.GetValue('InstallLocation'))
                        $displayVersion = [string]$key.GetValue('DisplayVersion')
                        $versionMatch = [regex]::Match(
                            ($displayVersion + ' ' + $displayName),
                            '(\d+\.\d+\.\d+)'
                        )
                        $samePath = $installLocation -and
                            [string]::Equals($installLocation, $targetDir, [StringComparison]::OrdinalIgnoreCase)
                        $sameVersion = $false
                        if ($versionMatch.Success) {
                            try {
                                $candidateVersion = [version]$versionMatch.Groups[1].Value
                                $sameVersion = (
                                    $candidateVersion.Major -eq $PythonInfo.Version.Major -and
                                    $candidateVersion.Minor -eq $PythonInfo.Version.Minor -and
                                    $candidateVersion.Build -eq $PythonInfo.Version.Build
                                )
                            } catch {}
                        }
                        $archMatch = $true
                        if ($PythonInfo.Bits -eq 32) {
                            $archMatch = ($displayName -match '(?i)32-bit|x86')
                        } elseif ($PythonInfo.Bits -eq 64) {
                            $archMatch = ($displayName -match '(?i)64-bit|ARM64')
                        }
                        if (-not $samePath -and -not ($sameVersion -and $archMatch)) { continue }
                        $quiet = [string]$key.GetValue('QuietUninstallString')
                        $uninstall = [string]$key.GetValue('UninstallString')
                        if (-not $quiet -and -not $uninstall) { continue }
                        $uninstallMatches.Add([pscustomobject]@{
                            DisplayName         = $displayName
                            InstallLocation     = $installLocation
                            QuietUninstallString = $quiet
                            UninstallString     = $uninstall
                            RegistryKey         = "$($hive.Name)\$subName"
                        })
                    } finally {
                        if ($null -ne $key) { $key.Dispose() }
                    }
                }
            } catch {
                Write-Log ("PYTHON_UNINSTALL_REGISTRY_READ_FAIL: " + $_.Exception.Message)
            } finally {
                if ($null -ne $uninstallRoot) { $uninstallRoot.Dispose() }
                if ($null -ne $baseKey) { $baseKey.Dispose() }
            }
        }
    }
    if ($uninstallMatches.Count -eq 0) { return $null }
    $exact = @($uninstallMatches | Where-Object {
        $_.InstallLocation -and
        [string]::Equals($_.InstallLocation, $targetDir, [StringComparison]::OrdinalIgnoreCase)
    })
    if ($exact.Count -gt 0) { return $exact[0] }
    if ($uninstallMatches.Count -eq 1) { return $uninstallMatches[0] }
    return $null
}

function Invoke-PythonUninstaller($Entry) {
    $raw = [string]$Entry.QuietUninstallString
    $hasQuietCommand = -not [string]::IsNullOrWhiteSpace($raw)
    if (-not $hasQuietCommand) { $raw = [string]$Entry.UninstallString }
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "Ingen avinstallerare finns för $($Entry.DisplayName)."
    }
    $command = [Environment]::ExpandEnvironmentVariables($raw.Trim())
    if ($command -match '(?i)\bmsiexec(?:\.exe)?\b') {
        $command = [regex]::Replace($command, '(?i)(/i|/package)(?=\s*\{)', '/x', 1)
        if ($command -notmatch '(?i)/(qn|quiet|passive)\b') {
            $command += ' /qn /norestart'
        }
    } elseif (-not $hasQuietCommand) {
        if ($command -notmatch '(?i)/uninstall\b') { $command += ' /uninstall' }
        if ($command -notmatch '(?i)/(quiet|passive|verysilent)\b') {
            $command += ' /quiet /norestart'
        }
    }

    Write-Log ("PYTHON_REMOVE: $($Entry.DisplayName)")
    $shell = New-Object -ComObject WScript.Shell
    $process = $shell.Exec($command)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ($process.Status -eq 0) {
        if ($watch.Elapsed.TotalMinutes -gt 10) {
            throw "Avinstallationen tog för lång tid: $($Entry.DisplayName)."
        }
        Start-Sleep -Milliseconds 250
    }
    $code = $process.ExitCode
    if ($code -ne 0 -and $code -ne 3010) {
        throw "Avinstalleraren för $($Entry.DisplayName) avslutades med kod $code."
    }
}

function Invoke-PythonInstaller([string]$Installer, [string]$Scope, [string]$TargetDir) {
    $allUsers = if ($Scope -eq 'Machine') { '1' } else { '0' }
    $launcherAllUsers = $allUsers
    $args = @(
        '/passive',
        "InstallAllUsers=$allUsers",
        "InstallLauncherAllUsers=$launcherAllUsers",
        'PrependPath=1',
        'AppendPath=0',
        'Include_pip=1',
        'Include_launcher=1',
        'Include_test=0',
        'Include_doc=0',
        'Shortcuts=1',
        'AssociateFiles=1',
        'CompileAll=0'
    )
    if (-not [string]::IsNullOrWhiteSpace($TargetDir)) {
        $args += ('TargetDir="{0}"' -f $TargetDir)
    }
    Write-Host 'Startar Python-installerns förloppsfönster...'
    $process = Start-Process -FilePath $Installer -ArgumentList ($args -join ' ') -Wait -PassThru
    if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
        throw "Python-installationen avslutades med kod $($process.ExitCode)."
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-MachineElevation {
    if (Test-IsAdministrator) { return }
    if ($Elevated) { throw 'Administratörsbehörighet saknas för den befintliga systeminstallationen.' }
    Write-Log 'PYTHON_ELEVATE: ber om administratörsbehörighet för befintlig system-Python.'
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Elevated' -f $PSCommandPath
    if ($WaitForPid -gt 0) { $arguments += " -WaitForPid $WaitForPid" }
    if ($UpdatePackages) { $arguments += ' -UpdatePackages' }
    if ($UseUserPackages -or -not (Test-IsAdministrator)) { $arguments += ' -UseUserPackages' }
    if ($PythonExe) { $arguments += (' -PythonExe "{0}"' -f $PythonExe) }
    if ($Slot) { $arguments += (' -Slot "{0}"' -f $Slot) }
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs -Wait -PassThru
    exit $process.ExitCode
}

function Update-AppAutostart([string]$OldExe, [string]$NewExe) {
    $newWindowed = Join-Path (Split-Path -Parent $NewExe) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $newWindowed -PathType Leaf)) { return }
    $oldWindowed = Join-Path (Split-Path -Parent $OldExe) 'pythonw.exe'
    $startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    $linkPath = Join-Path $startup 'Fakturabunten.lnk'
    if (Test-Path -LiteralPath $linkPath -PathType Leaf) {
        try {
            $shell = New-Object -ComObject WScript.Shell
            $link = $shell.CreateShortcut($linkPath)
            $target = Normalize-Path $link.TargetPath
            if ([string]::Equals($target, (Normalize-Path $OldExe), [StringComparison]::OrdinalIgnoreCase) -or
                [string]::Equals($target, (Normalize-Path $oldWindowed), [StringComparison]::OrdinalIgnoreCase)) {
                $link.TargetPath = $newWindowed
                Write-Log 'AUTOSTART_PYTHON_PATH_UPDATED: genvägen pekar nu på senaste Python.'
            }
            $link.WorkingDirectory = $AppDir
            $link.IconLocation = (Join-Path $AppDir 'app_icon.ico') + ',0'
            $link.Description = 'Fakturabunten'
            $link.Save()
        } catch {
            Write-Log ("AUTOSTART_SHORTCUT_UPDATE_FAIL: " + $_.Exception.Message)
        }
    }
    try {
        $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
        $run = Get-ItemProperty -LiteralPath $runKey -Name 'Fakturabunten' -ErrorAction SilentlyContinue
        $command = [string]$run.Fakturabunten
        if ($command) {
            # Migrera en gammal Python-Run-post till en ikonbärande .lnk.
            # Run-posterna visar pythonw/Python och får aldrig återupplivas.
            if (-not (Test-Path -LiteralPath $linkPath -PathType Leaf)) {
                $shell = New-Object -ComObject WScript.Shell
                $link = $shell.CreateShortcut($linkPath)
                $mainScript = Join-Path $AppDir 'main.pyw'
                if (-not (Test-Path -LiteralPath $mainScript -PathType Leaf)) {
                    $mainScript = Join-Path $AppDir 'main.py'
                }
                $link.TargetPath = $newWindowed
                $link.Arguments = ('"{0}" --minimized' -f $mainScript)
                $link.WorkingDirectory = $AppDir
                $link.IconLocation = (Join-Path $AppDir 'app_icon.ico') + ',0'
                $link.Description = 'Fakturabunten'
                $link.WindowStyle = 7
                $link.Save()
            }
            if (Test-Path -LiteralPath $linkPath -PathType Leaf) {
                Remove-ItemProperty -LiteralPath $runKey -Name 'Fakturabunten' -ErrorAction SilentlyContinue
                Write-Log 'AUTOSTART_LEGACY_RUN_REMOVED: ikonbärande genväg används i stället.'
            }
        }
    } catch {
        # Om .lnk-skapandet misslyckas tar vi hellre bort autostarten
        # än att lämna kvar en pythonw-post med Python-ikonen.
        try {
            if ($runKey) {
                Remove-ItemProperty -LiteralPath $runKey -Name 'Fakturabunten' -ErrorAction SilentlyContinue
            }
        } catch { }
        Write-Log ("AUTOSTART_RUN_MIGRATION_FAIL: " + $_.Exception.Message)
    }
}

function Download-Installer([string]$Url, [string]$Path) {
    Write-Log "INSTALL_PYTHON_DOWNLOAD: $Url"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L --fail --retry 3 --retry-delay 2 -o $Path $Url
        if ($LASTEXITCODE -ne 0) {
            throw "Nedladdningen misslyckades (curl $LASTEXITCODE)."
        }
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or
        (Get-Item -LiteralPath $Path).Length -lt 1048576) {
        throw 'Python-installern hämtades inte korrekt; befintlig Python har inte ändrats.'
    }
}

function Get-FallbackInstallerInfo([string]$Tag) {
    $versionText = '3.14.8'
    $url = switch ($Tag) {
        'win32' { "https://www.python.org/ftp/python/$versionText/python-$versionText.exe" }
        'arm64' { "https://www.python.org/ftp/python/$versionText/python-$versionText-arm64.exe" }
        default { "https://www.python.org/ftp/python/$versionText/python-$versionText-amd64.exe" }
    }
    return [pscustomobject]@{
        Version = [version]$versionText
        Url = $url
    }
}

function Test-AppPythonRuntime([string]$Exe, [switch]$EnsureDependencies) {
    if ([string]::IsNullOrWhiteSpace($Exe) -or
        -not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
        return $false
    }
    if ($EnsureDependencies) {
        $ensureCode = "import sys; sys.path.insert(0, sys.argv[1]); from ensure_packages import ensure_packages; raise SystemExit(0 if ensure_packages(force_console=True) else 1)"
        $ensureOutput = & $Exe -c $ensureCode $AppDir 2>&1
        $ensureExit = $LASTEXITCODE
        foreach ($line in $ensureOutput) {
            if ($null -ne $line) { Write-Log ("PYTHON_DEPENDENCY_CHECK: " + [string]$line) }
        }
        if ($ensureExit -ne 0) {
            Write-Log "PYTHON_RUNTIME_NOT_READY: dependency check failed for $Exe (exit $ensureExit)"
            return $false
        }
    }
    # Håll detta i takt med main.py:s _RUNTIME_PROBE. Nyare PyMuPDF
    # använder pymupdf; fitz behövs bara för äldre installationer.
    $probeCode = @'
import importlib
for name in ('PySide6', 'reportlab', 'pypdf', 'PIL', 'pytesseract', 'qrcode'):
    importlib.import_module(name)
try:
    importlib.import_module('pymupdf')
except Exception:
    importlib.import_module('fitz')
from PySide6.QtWidgets import QApplication
app = QApplication([])
app.quit()
print('FAKTURABUNTEN_RUNTIME_OK')
'@
    $probeOutput = & $Exe -c $probeCode 2>&1
    $probeExit = $LASTEXITCODE
    foreach ($line in $probeOutput) {
        if ($null -ne $line) { Write-Log ("PYTHON_RUNTIME_PROBE: " + [string]$line) }
    }
    if ($probeExit -ne 0) {
        Write-Log "PYTHON_RUNTIME_NOT_READY: import probe failed for $Exe (exit $probeExit)"
        return $false
    }
    Write-Log "PYTHON_RUNTIME_READY: $Exe"
    return $true
}

function Rollback-NewPython([string]$InstallDir, [version]$Version, [string]$Scope) {
    try {
        $info = Get-PythonInfo (Join-Path $InstallDir 'python.exe')
        if ($null -eq $info) { return }
        $entry = Get-UninstallEntry $info $Scope
        if ($entry) {
            Write-Log 'PYTHON_ROLLBACK: tar bort den nya versionen eftersom ersättningen inte kunde slutföras.'
            Invoke-PythonUninstaller $entry
        } else {
            Write-Log 'PYTHON_ROLLBACK_FAIL: avinstalleraren för den nya versionen hittades inte.'
        }
    } catch {
        Write-Log ("PYTHON_ROLLBACK_FAIL: " + $_.Exception.Message)
    }
}

try {
    Wait-ForApplicationExit $WaitForPid
    $registered = @(Get-RegistryPythonEntries)
    $unregistered = Find-UnregisteredPython $registered
    if ($unregistered) {
        throw "Python finns på $($unregistered.ExePath), men är inte registrerad som en standardinstallation som skriptet kan ersätta säkert. Ingen ny installation gjordes."
    }
    $selected = $null
    if ($PythonExe) {
        $requestedExe = Normalize-Path $PythonExe
        if ([IO.Path]::GetFileName($requestedExe) -ieq 'pythonw.exe') {
            $requestedExe = Normalize-Path (Join-Path (Split-Path -Parent $requestedExe) 'python.exe')
        }
        if (-not (Test-Path -LiteralPath $requestedExe -PathType Leaf)) {
            throw "Appens aktiva Python hittades inte: $requestedExe. Ingen annan installation väljs."
        }
        $requestedEntries = @($registered | Where-Object {
            [string]::Equals($_.ExePath, $requestedExe, [StringComparison]::OrdinalIgnoreCase)
        })
        if ($requestedEntries.Count -eq 0) {
            throw "Appens aktiva Python ($requestedExe) är inte en igenkänd Python.org-installation. Den lämnas orörd; ingen annan Python installeras."
        }
        $selected = $requestedEntries[0]
        if ($selected.Scope -ne 'User' -and $selected.Scope -ne 'Machine') {
            throw "Appens aktiva Python finns på en hanterad/okänd plats ($requestedExe). Den lämnas orörd."
        }
    } elseif ($registered.Count -gt 0) {
        $supported = @($registered | Where-Object { $_.Scope -eq 'User' -or $_.Scope -eq 'Machine' })
        if ($supported.Count -eq 0) {
            $paths = ($registered | ForEach-Object { $_.ExePath }) -join '; '
            throw "Python finns, men är installerad på en plats som det här skriptet inte kan ersätta säkert: $paths. Ingen ny installation gjordes."
        }
        $selected = $supported | Sort-Object `
            @{ Expression = { $_.Version }; Descending = $true }, `
            @{ Expression = { if ($_.Scope -eq 'User') { 0 } else { 1 } } } |
            Select-Object -First 1
    } elseif ($UpdatePackages) {
        throw 'Appens aktuella Python kunde inte hittas i registrerade installationer; ingen annan Python väljs.'
    }
    if ($selected -and -not $selected.Valid) {
        throw "En Python-installation hittades men kunde inte startas: $($selected.ExePath). Ingen ny installation gjordes."
    }
    if ($selected) {
        $otherNewest = $registered |
            Where-Object { $_.Scope -eq 'Other' -and $_.Valid } |
            Sort-Object -Property Version -Descending |
            Select-Object -First 1
        if ($otherNewest -and $otherNewest.Version -ge $selected.Version) {
            throw "En lika ny eller nyare, icke-standard Python finns på $($otherNewest.ExePath). Den lämnas orörd och ingen sidoinstallation görs."
        }
    }

    $PythonExeForPackages = if ($selected) { $selected.ExePath } else { '' }
    $tag = Get-ArchTag $selected
    $release = Get-LatestInstallerInfo $tag
    Write-Log ("PYTHON_LATEST: Python $($release.Version) ($tag)")

    if ($selected -and $selected.Scope -eq 'Machine' -and $selected.Version -lt $release.Version) {
        Ensure-MachineElevation
    }

    if ($selected -and $selected.Version -ge $release.Version) {
        Write-Log ("PYTHON_CURRENT: Python $($selected.Version) finns redan; ingen ominstallation behövs.")
    } else {
        $sameSeries = $selected -and
            $selected.Version.Major -eq $release.Version.Major -and
            $selected.Version.Minor -eq $release.Version.Minor
        $oldUninstaller = $null
        $newInstallDir = $null

        if ($selected -and -not $sameSeries) {
            $oldUninstaller = Get-UninstallEntry $selected $selected.Scope
            if (-not $oldUninstaller) {
                throw "Python $($selected.Version) hittades, men dess tysta avinstallerare saknas. Ingen ny version installerades och den befintliga lämnades orörd."
            }
            $newInstallDir = Get-DefaultInstallDir $release.Version $selected.Scope $selected.Bits
            $newExeExisting = Join-Path $newInstallDir 'python.exe'
            if (Test-Path -LiteralPath $newExeExisting -PathType Leaf) {
                $existingAtTarget = Get-PythonInfo $newExeExisting
                if ($existingAtTarget) {
                    throw "Python finns redan i målmappen $newInstallDir men är inte den valda registrerade installationen. Ingen ny installation gjordes."
                }
                throw "Målmappen $newInstallDir innehåller en okänd python.exe. Den skrivs inte över."
            }
        } elseif ($selected) {
            $newInstallDir = $selected.InstallDir
        } else {
            $newInstallDir = Get-DefaultInstallDir $release.Version 'User' 64
            $newExeExisting = Join-Path $newInstallDir 'python.exe'
            if (Test-Path -LiteralPath $newExeExisting -PathType Leaf) {
                throw "En python.exe finns redan i $newInstallDir men kunde inte verifieras. Ingen ny installation gjordes."
            }
        }

        $TempInstaller = Join-Path $LogDir ("python-installer-" + [guid]::NewGuid().ToString('N') + '.exe')
        Download-Installer $release.Url $TempInstaller

        if (-not $selected) {
            Write-Host 'Python saknas — installerar senaste stabila versionen.'
            Invoke-PythonInstaller $TempInstaller 'User' $newInstallDir
            $newInfo = Get-PythonInfo (Join-Path $newInstallDir 'python.exe')
            if (-not $newInfo -or $newInfo.Version -lt $release.Version) {
                throw 'Python installerades inte som väntat. Kontrollera logs/starta.log.'
            }
            if (-not (Test-AppPythonRuntime $newInfo.ExePath -EnsureDependencies)) {
                Rollback-NewPython $newInstallDir $release.Version 'User'
                $fallbackRelease = Get-FallbackInstallerInfo $tag
                if ($fallbackRelease.Version -ge $release.Version) {
                    throw "Python $($release.Version) saknar fungerande appberoenden och ingen äldre reservversion är tillgänglig."
                }
                $release = $fallbackRelease
                $newInstallDir = Get-DefaultInstallDir $release.Version 'User' 64
                $fallbackExe = Join-Path $newInstallDir 'python.exe'
                if (Test-Path -LiteralPath $fallbackExe -PathType Leaf) {
                    throw "Reservmappen $newInstallDir innehåller redan en Python som inte kunde verifieras; den lämnas orörd."
                }
                Write-Host "Den senaste Python-versionen klarade inte appkontrollen — försöker Python $($release.Version)."
                Download-Installer $release.Url $TempInstaller
                Invoke-PythonInstaller $TempInstaller 'User' $newInstallDir
                $newInfo = Get-PythonInfo $fallbackExe
                if (-not $newInfo -or $newInfo.Version -lt $release.Version -or
                    -not (Test-AppPythonRuntime $newInfo.ExePath -EnsureDependencies)) {
                    Rollback-NewPython $newInstallDir $release.Version 'User'
                    throw "Python $($release.Version) kunde inte verifieras med Fakturabuntens beroenden."
                }
                Write-Log ("PYTHON_RUNTIME_FALLBACK: installerade Python $($newInfo.Version) efter att den senaste versionen inte klarade appkontrollen.")
            }
            Write-Log ("INSTALL_PYTHON_OK: Python $($newInfo.Version) installerades och appberoendena verifierades.")
            $PythonExeForPackages = $newInfo.ExePath
        } elseif ($sameSeries) {
            Write-Host "Uppdaterar Python $($selected.Version) till $($release.Version) i samma installationsmapp..."
            Invoke-PythonInstaller $TempInstaller $selected.Scope $selected.InstallDir
            $newInfo = Get-PythonInfo $selected.ExePath
            if (-not $newInfo -or $newInfo.Version -lt $release.Version) {
                throw 'Python-uppdateringen verifierades inte. Kontrollera logs/starta.log.'
            }
            if (-not (Test-AppPythonRuntime $newInfo.ExePath -EnsureDependencies)) {
                throw "Python $($newInfo.Version) kunde inte klara appens beroendekontroll. Kontrollera om Python 3.14 eller en annan systemtolk finns installerad; befintliga systemtolkar lämnas orörda."
            }
            Write-Log ("INSTALL_PYTHON_OK: befintlig Python uppdaterad i samma mapp till $($newInfo.Version) och appberoendena verifierade.")
            $PythonExeForPackages = $newInfo.ExePath
        } else {
            Write-Host "Ersätter Python $($selected.Version) med Python $($release.Version)..."
            # Installera och verifiera den nya versionen först. Om det misslyckas
            # ligger den gamla fortfarande kvar; därefter tas den gamla bort.
            Invoke-PythonInstaller $TempInstaller $selected.Scope $newInstallDir
            $newExe = Join-Path $newInstallDir 'python.exe'
            $newInfo = Get-PythonInfo $newExe
            if (-not $newInfo -or $newInfo.Version -lt $release.Version) {
                throw 'Den nya Python-versionen kunde inte verifieras; den gamla installationen lämnades kvar.'
            }
            if (-not (Test-AppPythonRuntime $newExe -EnsureDependencies)) {
                Rollback-NewPython $newInstallDir $release.Version $selected.Scope
                $PythonExeForPackages = $selected.ExePath
                Write-Log ("PYTHON_RUNTIME_FALLBACK: Python $($release.Version) klarade inte appkontrollen; befintlig Python $($selected.Version) lämnas kvar och fortsätter användas.")
            } else {
                try {
                    Invoke-PythonUninstaller $oldUninstaller
                    $oldStillRegistered = @(Get-RegistryPythonEntries | Where-Object {
                        [string]::Equals($_.ExePath, $selected.ExePath, [StringComparison]::OrdinalIgnoreCase)
                    })
                    $oldStillRuns = Get-PythonInfo $selected.ExePath
                    if ($oldStillRegistered.Count -gt 0 -or $oldStillRuns) {
                        throw 'Den gamla Python-installationen finns fortfarande efter avinstallationen.'
                    }
                } catch {
                    Rollback-NewPython $newInstallDir $release.Version $selected.Scope
                    throw ("Ersättningen av Python misslyckades; skriptet försökte återställa den nya installationen. " + $_.Exception.Message)
                }
                Update-AppAutostart $selected.ExePath $newExe
                Write-Log ("INSTALL_PYTHON_OK: Python $($selected.Version) ersatt med $($newInfo.Version); den äldre installationen togs bort efter godkänd appkontroll.")
                $PythonExeForPackages = $newExe
            }
        }
    }

    if ($UpdatePackages) {
        if (-not $PythonExeForPackages -or -not (Test-Path -LiteralPath $PythonExeForPackages -PathType Leaf)) {
            throw 'Appens Python kunde inte fastställas efter kontrollen; paketuppdateringen avbryts.'
        }
        $packageHelper = Join-Path $AppDir 'ensure_packages.py'
        if (-not (Test-Path -LiteralPath $packageHelper -PathType Leaf)) {
            throw "Paketuppdateraren saknas: $packageHelper"
        }
        Write-Log ("WEEKLY_PACKAGE_UPDATE_START: $PythonExeForPackages")
        if ($UseUserPackages) {
            $packageOutput = & $PythonExeForPackages $packageHelper --upgrade-all --user 2>&1
        } else {
            $packageOutput = & $PythonExeForPackages $packageHelper --upgrade-all 2>&1
        }
        $packageExitCode = $LASTEXITCODE
        foreach ($line in $packageOutput) {
            if ($null -ne $line) { Write-Log ("PACKAGE_PIP: " + [string]$line) }
        }
        if ($packageExitCode -ne 0) {
            throw "Paketuppdateringen misslyckades (exit $packageExitCode)."
        }
        Write-Log 'WEEKLY_PACKAGE_UPDATE_OK: requirements.txt uppdaterades.'
    }
    Write-WeeklyState 'success' 'Python-kontroll och paketuppdatering slutfördes.'
} catch {
    $failureMessage = $_.Exception.Message
    Write-WeeklyState 'failed' $failureMessage
    Write-Log ("INSTALL_PYTHON_FAIL: " + $failureMessage)
    Write-Host ("Fel: " + $failureMessage)
    exit 1
} finally {
    if ($TempInstaller -and (Test-Path -LiteralPath $TempInstaller)) {
        Remove-Item -Force $TempInstaller -ErrorAction SilentlyContinue
    }
}
exit 0
