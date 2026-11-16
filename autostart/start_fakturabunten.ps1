# The Windows start file must work before Python is installed. It only offers
# the official download page if no Python installation is discoverable; it
# never installs, upgrades or removes an existing interpreter.
param([switch]$NoMain)

$ErrorActionPreference = 'Stop'
$AppDir = Split-Path -Parent $PSScriptRoot
# The Python Install Manager can otherwise auto-install a missing version
# when an alias or version specifier is executed. Discovery must be read-only.
$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = '0'

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
            $lines = @(& $launcher.Source -0p 2>$null)
            foreach ($line in $lines) {
                if ([string]$line -match '(?i)((?:[a-z]:\\|\\\\)[^\r\n]*?python(?:w)?\.exe)\s*$') {
                    $paths.Add($Matches[1])
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
            $result = @(& $path -c $probe 2>$null)
            if ($LASTEXITCODE -ne 0 -or $result.Count -eq 0) { continue }
            $versionText = ([string]$result[-1]).Trim()
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
    Write-Host 'Ingen Python hittades.'
    $answer = Read-Host 'Vill du oppna Python.org for att installera senaste stabila Python? [j/N]'
    return ($answer -match '^(?i:j|ja|y|yes)$')
}

function Open-PythonDownload {
    $url = 'https://www.python.org/downloads/windows/'
    try {
        Start-Process -FilePath $url | Out-Null
        Write-Host 'Installera Python fran den officiella sidan och starta sedan Fakturabunten igen.'
    } catch {
        Write-Host "Kunde inte oppna webblasaren. Oppna sjalv: $url"
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
    } else {
        $executable = $PythonExe
        $file = $py
    }
    $arguments = '"{0}" --minimized' -f $file
    Start-Process -FilePath $executable -ArgumentList $arguments `
        -WorkingDirectory $AppDir -WindowStyle Hidden | Out-Null
}

function Start-Fakturabunten {
    if (-not (Test-Path -LiteralPath (Join-Path $AppDir 'main.py') -PathType Leaf)) {
        Write-Host 'Fakturabunten saknas i startfilens mapp.'
        return 1
    }
    $python = Get-InstalledPython
    if ($python.Executable) {
        try { Start-Application $python.Executable; return 0 }
        catch { Write-Host ("Kunde inte starta Fakturabunten: " + $_.Exception.Message); return 1 }
    }
    if ($python.Found) {
        Write-Host 'Python hittades, men ingen tillganglig systemtolk kan starta Fakturabunten.'
        Write-Host 'Programmet kraver Python 3.10 eller senare. Befintlig Python har inte andrats.'
        return 1
    }
    if (-not (Ask-ToOpenPythonDownload)) {
        Write-Host 'Ingen Python installerades. Starta filen igen nar Python finns.'
        return 2
    }
    # An interpreter can appear while the question is on screen.
    $python = Get-InstalledPython
    if ($python.Executable) {
        try { Start-Application $python.Executable; return 0 }
        catch { Write-Host ("Kunde inte starta Fakturabunten: " + $_.Exception.Message); return 1 }
    }
    if ($python.Found) {
        Write-Host 'Python hittades, men ingen tillganglig systemtolk kan starta Fakturabunten.'
        Write-Host 'Programmet kraver Python 3.10 eller senare. Befintlig Python har inte andrats.'
        return 1
    }
    Open-PythonDownload
    return 2
}

if (-not $NoMain) { exit (Start-Fakturabunten) }
