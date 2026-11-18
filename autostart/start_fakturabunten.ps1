# The Windows start file must work before Python is installed. It only offers
# the official download page if no Python installation is discoverable; it
# never installs, upgrades or removes an existing interpreter.
param([switch]$NoMain)

$ErrorActionPreference = 'Stop'
$AppDir = Split-Path -Parent $PSScriptRoot
# The Python Install Manager can otherwise auto-install a missing version
# when an alias or version specifier is executed. Discovery must be read-only.
$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = '0'

function Test-LauncherInteractiveGui {
    return (
        (-not $NoMain) -and
        (-not [Console]::IsOutputRedirected) -and
        (-not [Console]::IsInputRedirected) -and
        ($env:FAKTURA_HEADLESS -ne '1')
    )
}

function Hide-LauncherConsole {
    if (-not (Test-LauncherInteractiveGui)) { return }
    try {
        if (-not ('Fakturabunten.NativeConsole' -as [type])) {
            Add-Type -Namespace Fakturabunten -Name NativeConsole -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern System.IntPtr GetConsoleWindow();
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint GetConsoleProcessList(uint[] processList, uint processCount);
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);
'@ | Out-Null
        }
        $hwnd = [Fakturabunten.NativeConsole]::GetConsoleWindow()
        $pids = New-Object uint[] 8
        $count = [Fakturabunten.NativeConsole]::GetConsoleProcessList($pids, 8)
        # Re-spawn windowless if launched from Explorer into Windows Terminal (<=2 console procs)
        # so the terminal tab closes immediately, or hide the classic console window in place.
        if ($count -gt 0 -and $count -le 2) {
            if ($env:WT_SESSION -and ($env:FB_DETACHED_LAUNCHER -ne '1')) {
                $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { Join-Path $PSScriptRoot 'start_fakturabunten.ps1' }
                $psi = New-Object System.Diagnostics.ProcessStartInfo
                $psi.FileName = (Join-Path $PSHOME 'powershell.exe')
                if (-not (Test-Path -LiteralPath $psi.FileName -PathType Leaf)) {
                    $psi.FileName = 'powershell.exe'
                }
                $psi.Arguments = ('-NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $scriptPath)
                $psi.WorkingDirectory = $AppDir
                $psi.UseShellExecute = $false
                $psi.CreateNoWindow = $true
                $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
                $psi.EnvironmentVariables['FB_DETACHED_LAUNCHER'] = '1'
                [System.Diagnostics.Process]::Start($psi) | Out-Null
                exit 0
            }
            if ($hwnd -ne [IntPtr]::Zero) {
                [Fakturabunten.NativeConsole]::ShowWindow($hwnd, 0) | Out-Null
            }
        }
    } catch { }
}

function Invoke-HiddenProcess([string]$FilePath, [string[]]$ArgumentList, [int]$TimeoutMs = 15000) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $escaped = @()
    foreach ($arg in $ArgumentList) {
        if ($arg -match '[\s"]') {
            $escaped += ('"' + ($arg -replace '(\\*)"', '$1$1\"') + '"')
        } else {
            $escaped += $arg
        }
    }
    $psi.Arguments = ($escaped -join ' ')
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    if ($null -eq $proc) {
        return [pscustomobject]@{ ExitCode = -1; StdoutLines = @() }
    }
    $errTask = $proc.StandardError.ReadToEndAsync()
    $stdout = $proc.StandardOutput.ReadToEnd()
    if (-not $proc.WaitForExit($TimeoutMs)) {
        try { $proc.Kill() } catch { }
        return [pscustomobject]@{ ExitCode = -1; StdoutLines = @() }
    }
    try { $null = $errTask.GetAwaiter().GetResult() } catch { }
    $lines = @()
    if ($stdout) {
        $lines = @($stdout -split "\r?\n" | Where-Object { $_ -ne '' })
    }
    return [pscustomobject]@{ ExitCode = $proc.ExitCode; StdoutLines = $lines }
}

function Show-LauncherMessage([string]$Text, [bool]$IsError = $false) {
    if (Test-LauncherInteractiveGui) {
        try {
            Add-Type -AssemblyName System.Windows.Forms | Out-Null
            $icon = if ($IsError) { [System.Windows.Forms.MessageBoxIcon]::Warning } else { [System.Windows.Forms.MessageBoxIcon]::Information }
            $owner = New-Object System.Windows.Forms.Form
            $owner.TopMost = $true
            $owner.ShowInTaskbar = $false
            try {
                [System.Windows.Forms.MessageBox]::Show($owner, $Text, 'Fakturabunten', [System.Windows.Forms.MessageBoxButtons]::OK, $icon) | Out-Null
            } finally {
                $owner.Dispose()
            }
            return
        } catch { }
    }
    Write-Host $Text
}

function Test-AppLocalPython([string]$Path) {
    try {
        $base = [IO.Path]::GetFullPath($AppDir).TrimEnd('\') + '\'
        $full = [IO.Path]::GetFullPath($Path)
        return $full.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

function Get-InstalledPython {
    $paths = New-Object 'System.Collections.Generic.List[string]'
    $seen = @{}
    $registered = $false
    $uncertain = $false
    $views = @([Microsoft.Win32.RegistryView]::Registry32)
    if ([Environment]::Is64BitOperatingSystem) {
        $views = @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)
    }

    # PEP 514: inspect all vendors and both registry views, not just a
    # python.org install in the default directory. A stale/broken registered
    # interpreter still suppresses the installation offer.
    foreach ($hive in @([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryHive]::LocalMachine)) {
        foreach ($view in $views) {
            $baseKey = $null
            $pythonKey = $null
            try {
                $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
                $pythonKey = $baseKey.OpenSubKey('Software\Python')
                if ($null -eq $pythonKey) { continue }
                foreach ($company in $pythonKey.GetSubKeyNames()) {
                    $companyKey = $null
                    try {
                        $companyKey = $pythonKey.OpenSubKey($company)
                        if ($null -eq $companyKey) { continue }
                        foreach ($tag in $companyKey.GetSubKeyNames()) {
                            $installKey = $null
                            try {
                                $installKey = $companyKey.OpenSubKey("$tag\InstallPath")
                                if ($null -eq $installKey) { continue }
                                $registered = $true
                                $exe = [string]$installKey.GetValue('ExecutablePath')
                                $dir = [string]$installKey.GetValue('')
                                if (-not $exe -and $dir) { $exe = Join-Path $dir 'python.exe' }
                                if ($exe) { $paths.Add([Environment]::ExpandEnvironmentVariables($exe)) }
                            } finally {
                                if ($null -ne $installKey) { $installKey.Dispose() }
                            }
                        }
                    } finally {
                        if ($null -ne $companyKey) { $companyKey.Dispose() }
                    }
                }
            } catch {
                # If registry discovery is inaccessible, avoid asserting that
                # Python is absent and offering a potentially duplicate install.
                $uncertain = $true
            } finally {
                if ($null -ne $pythonKey) { $pythonKey.Dispose() }
                if ($null -ne $baseKey) { $baseKey.Dispose() }
            }
        }
    }

    # -0p is a list operation, not a launch/install operation, for both the
    # legacy launcher and the newer Python Install Manager.
    $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        try {
            $probeRes = Invoke-HiddenProcess $launcher.Source @('-0p')
            if ($probeRes.ExitCode -eq 0) {
                foreach ($line in $probeRes.StdoutLines) {
                    if ([string]$line -match '(?i)((?:[a-z]:\\|\\\\)[^\r\n]*?python(?:w)?\.exe)\s*$') {
                        $paths.Add($Matches[1])
                    }
                }
            }
        } catch { }
    }

    # PATH can contain pyenv/conda or a portable registered system Python.
    foreach ($directory in ($env:PATH -split ';')) {
        $directory = $directory.Trim().Trim('"')
        if (-not $directory -or $directory -match '(?i)\\Microsoft\\WindowsApps(?:\\|$)') { continue }
        try {
            foreach ($item in @(Get-ChildItem -LiteralPath $directory -Filter 'python*.exe' -File -ErrorAction SilentlyContinue)) {
                if ($item.Name -match '(?i)^python(?:[23](?:\.\d+)?)?\.exe$') {
                    $paths.Add($item.FullName)
                }
            }
        } catch { }
    }

    $roots = New-Object 'System.Collections.Generic.List[string]'
    if ($env:LOCALAPPDATA) {
        $roots.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python'))
        $roots.Add((Join-Path $env:LOCALAPPDATA 'Python'))
        $roots.Add((Join-Path $env:LOCALAPPDATA 'uv\python'))
    }
    if ($env:ProgramFiles) { $roots.Add($env:ProgramFiles) }
    $programFiles32 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    if ($programFiles32) { $roots.Add($programFiles32) }
    if ($env:USERPROFILE) {
        foreach ($relative in @('.pyenv\pyenv-win\versions', '.conda\envs', 'anaconda3\envs', 'miniconda3\envs', 'miniforge3\envs')) {
            $roots.Add((Join-Path $env:USERPROFILE $relative))
        }
    }
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        try {
            foreach ($folder in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
                if ($folder.Name -match '(?i)^Python' -or $root -match '(?i)(pyenv-win\\versions|uv\\python|\\envs)$') {
                    $paths.Add((Join-Path $folder.FullName 'python.exe'))
                }
            }
        } catch { }
    }
    if ($env:USERPROFILE) {
        foreach ($name in @('anaconda3', 'miniconda3', 'miniforge3')) {
            $paths.Add((Join-Path (Join-Path $env:USERPROFILE $name) 'python.exe'))
        }
    }

    # A Microsoft Store Python is not the WindowsApps placeholder. Look for
    # a real registered package and never execute the placeholder to detect it.
    if (Get-Command Get-AppxPackage -ErrorAction SilentlyContinue) {
        try {
            foreach ($pkg in @(Get-AppxPackage -Name 'PythonSoftwareFoundation.Python*' -ErrorAction Stop)) {
                if ($pkg.Name -match '(?i)^PythonSoftwareFoundation\.Python\.\d') {
                    $registered = $true
                    if ($pkg.InstallLocation) { $paths.Add((Join-Path $pkg.InstallLocation 'python.exe')) }
                }
            }
        } catch { $uncertain = $true }
    }

    $selection = Join-Path $AppDir 'data\python_runtime_selection.json'
    if (Test-Path -LiteralPath $selection -PathType Leaf) {
        try {
            $saved = Get-Content -LiteralPath $selection -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($saved.executable) { $paths.Add([string]$saved.executable) }
        } catch { }
    }

    $found = ($registered -or $uncertain)
    $best = ''
    $bestVersion = [version]'0.0'
    # Windows PowerShell 5 can strip embedded double quotes when passing a
    # native -c argument. Python single quotes survive the Windows argv rules.
    $probe = "import sys; print('%d.%d.%d' % sys.version_info[:3])"
    foreach ($raw in $paths) {
        if (-not $raw) { continue }
        $path = [Environment]::ExpandEnvironmentVariables($raw.Trim('"'))
        if ([IO.Path]::GetFileName($path) -ieq 'pythonw.exe') {
            $path = Join-Path (Split-Path -Parent $path) 'python.exe'
        }
        $key = $path.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $found = $true
        if (Test-AppLocalPython $path) { continue }
        try {
            $probeRes = Invoke-HiddenProcess $path @('-c', $probe)
            if ($probeRes.ExitCode -ne 0 -or $probeRes.StdoutLines.Count -eq 0) { continue }
            $versionText = ([string]$probeRes.StdoutLines[-1]).Trim()
            $version = [version]$versionText
            if ($version -ge [version]'3.10' -and $version -gt $bestVersion) {
                $best = $path
                $bestVersion = $version
            }
        } catch { }
    }
    return [pscustomobject]@{ Found = $found; Executable = $best; Version = $bestVersion }
}

function Ask-ToOpenPythonDownload {
    if (Test-LauncherInteractiveGui) {
        try {
            Add-Type -AssemblyName System.Windows.Forms | Out-Null
            $owner = New-Object System.Windows.Forms.Form
            $owner.TopMost = $true
            $owner.ShowInTaskbar = $false
            try {
                $reply = [System.Windows.Forms.MessageBox]::Show(
                    $owner,
                    "Ingen Python hittades.`n`nVill du öppna Python.org för att installera senaste stabila Python?",
                    'Fakturabunten',
                    [System.Windows.Forms.MessageBoxButtons]::YesNo,
                    [System.Windows.Forms.MessageBoxIcon]::Question,
                    [System.Windows.Forms.MessageBoxDefaultButton]::Button1
                )
            } finally {
                $owner.Dispose()
            }
            return ($reply -eq [System.Windows.Forms.DialogResult]::Yes)
        } catch { }
    }
    Write-Host 'Ingen Python hittades.'
    $answer = Read-Host 'Vill du oppna Python.org for att installera senaste stabila Python? [j/N]'
    return ($answer -match '^(?i:j|ja|y|yes)$')
}

function Open-PythonDownload {
    $url = 'https://www.python.org/downloads/windows/'
    try {
        Start-Process -FilePath $url | Out-Null
        Show-LauncherMessage 'Installera Python från den officiella sidan och starta sedan Fakturabunten igen.' $false
    } catch {
        Show-LauncherMessage "Kunde inte öppna webbläsaren. Öppna själv: $url" $true
    }
}

function Start-Application([string]$PythonExe) {
    $windowless = Join-Path (Split-Path -Parent $PythonExe) 'pythonw.exe'
    $pyw = Join-Path $AppDir 'main.pyw'
    $py = Join-Path $AppDir 'main.py'
    if ((Test-Path -LiteralPath $windowless -PathType Leaf) -and
        (Test-Path -LiteralPath $pyw -PathType Leaf)) {
        $executable = $windowless
        $file = $pyw
        $arguments = '"{0}" --minimized' -f $file
        Start-Process -FilePath $executable -ArgumentList $arguments `
            -WorkingDirectory $AppDir -WindowStyle Hidden | Out-Null
        return
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $PythonExe
    $psi.Arguments = '"{0}" --minimized' -f $py
    $psi.WorkingDirectory = $AppDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    [System.Diagnostics.Process]::Start($psi) | Out-Null
}

function Start-Fakturabunten {
    if (-not (Test-Path -LiteralPath (Join-Path $AppDir 'main.py') -PathType Leaf)) {
        Show-LauncherMessage 'Fakturabunten saknas i startfilens mapp.' $true
        return 1
    }
    $python = Get-InstalledPython
    if ($python.Executable) {
        try { Start-Application $python.Executable; return 0 }
        catch { Show-LauncherMessage ("Kunde inte starta Fakturabunten: " + $_.Exception.Message) $true; return 1 }
    }
    if ($python.Found) {
        Show-LauncherMessage ("Python hittades, men ingen tillgänglig systemtolk kan starta Fakturabunten.`nProgrammet kräver Python 3.10 eller senare. Befintlig Python har inte ändrats.") $true
        return 1
    }
    if (-not (Ask-ToOpenPythonDownload)) {
        Show-LauncherMessage 'Ingen Python installerades. Starta filen igen när Python finns.' $false
        return 2
    }
    # An interpreter can appear while the question is on screen.
    $python = Get-InstalledPython
    if ($python.Executable) {
        try { Start-Application $python.Executable; return 0 }
        catch { Show-LauncherMessage ("Kunde inte starta Fakturabunten: " + $_.Exception.Message) $true; return 1 }
    }
    if ($python.Found) {
        Show-LauncherMessage ("Python hittades, men ingen tillgänglig systemtolk kan starta Fakturabunten.`nProgrammet kräver Python 3.10 eller senare. Befintlig Python har inte ändrats.") $true
        return 1
    }
    Open-PythonDownload
    return 2
}

if (-not $NoMain) {
    Hide-LauncherConsole
    exit (Start-Fakturabunten)
}
