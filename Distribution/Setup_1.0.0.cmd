@echo off
setlocal DisableDelayedExpansion
set "ANREROLL_SETUP_LAUNCHER=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { if ($PSVersionTable.PSVersion -lt [version]'5.1') { throw 'PowerShell 5.1 or newer is required.' }; $launcher=[IO.Path]::GetFullPath($env:ANREROLL_SETUP_LAUNCHER); $content=[IO.File]::ReadAllText($launcher,[Text.Encoding]::UTF8); $marker='# ANREROLL_POWERSHELL_PAYLOAD'+[char]13+[char]10; $offset=$content.IndexOf($marker,[StringComparison]::Ordinal); if ($offset -lt 0) { throw 'Installer payload is missing.' }; Set-Location -LiteralPath ([IO.Path]::GetDirectoryName($launcher)); & ([scriptblock]::Create($content.Substring($offset+$marker.Length))) } catch { Write-Error $_; exit 1 }"
set "ANREROLL_SETUP_EXIT=%ERRORLEVEL%"
if not "%ANREROLL_SETUP_EXIT%"=="0" echo Setup failed. Review the error above.
if not defined ANREROLL_SETUP_NO_PAUSE pause
exit /b %ANREROLL_SETUP_EXIT%

# ANREROLL_POWERSHELL_PAYLOAD
#Requires -Version 5.1
# Arknights_Reroll resource release: v1.0.0
<#
.SYNOPSIS
Install MFWSide, ANReroll resources and an isolated Python Agent environment.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
.EXAMPLE
.\Setup.ps1 -InstallDir C:\Games\ANReroll -ResourceTag v1.0.0 -Launch
.NOTES
No administrator rights, system Python installation, PATH edits or device input.
Release ZIPs require GitHub SHA256 digests or matching .sha256 assets.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Get-Location).Path,
    [string]$ResourceTag = 'v1.0.0',
    [string]$AppTag = '',
    [string]$ResourceAsset = '',
    [string]$ResourceArchive = '',
    [string]$AppArchive = '',
    [string]$PythonExe = '',
    [string]$PythonPackage = '',
    [string]$Wheelhouse = '',
    [switch]$Update,
    [switch]$Launch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:AnrerollSetupPath = $PSCommandPath
# A generated CMD executes this same payload in memory. Only that one launcher
# is allowed in a fresh install directory; unrelated files remain protected.
if (-not $script:AnrerollSetupPath -and $env:ANREROLL_SETUP_LAUNCHER) {
    $launcher = [IO.Path]::GetFullPath($env:ANREROLL_SETUP_LAUNCHER)
    if ([IO.Path]::GetFileName($launcher) -notmatch '^Setup_[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.cmd$' -or
        -not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'Invalid installer launcher.' }
    $script:AnrerollSetupPath = $launcher
}
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Read-JsonFile([string]$Path) {
    return ([IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json)
}

function Write-JsonFile([string]$Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 30), (New-Object Text.UTF8Encoding($false)))
}

function Get-ChildPath([string]$Root, [string]$Relative) {
    $name = $Relative.Replace('\', '/')
    if ([IO.Path]::IsPathRooted($name) -or $name -match ':' -or -not $name) { throw "Unsafe path: $Relative" }
    $parts = $name.TrimEnd('/').Split('/')
    foreach ($part in $parts) {
        if (-not $part -or $part -in @('.', '..') -or $part -match '[<>|?*\x00-\x1f]' -or
            $part -match '[. ]$' -or $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
            throw "Unsafe Windows path: $Relative"
        }
    }
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $full = [IO.Path]::GetFullPath((Join-Path $Root ($parts -join '\')))
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Path escapes root: $Relative" }
    return $full
}

function Assert-NoReparse([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Reparse point is not allowed: $current" }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Assert-UnmanagedInstallDirectory([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root)) { return }
    # Permit the running installer itself, but never unrelated files/folders.
    # This keeps a newly downloaded setup.ps1 usable in its current directory.
    foreach ($item in @(Get-ChildItem -LiteralPath $Root -Force)) {
        if ($item.PSIsContainer -or -not $script:AnrerollSetupPath -or
            $item.FullName -ne [IO.Path]::GetFullPath($script:AnrerollSetupPath)) {
            throw 'InstallDir contains other files and is not managed by this installer. Use an empty directory or one containing only the running setup script.'
        }
        Assert-NoReparse $item.FullName
    }
}

function Assert-Hash([string]$Path, [string]$Expected) {
    if ($Expected -notmatch '^[a-fA-F0-9]{64}$') { throw "Missing/invalid SHA256 for $Path" }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing file: $Path" }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $Expected) { throw "SHA256 mismatch: $Path" }
}

function Read-Checksum([string]$Path) {
    $text = [IO.File]::ReadAllText($Path).Trim()
    if ($text -notmatch '^([a-fA-F0-9]{64})(?:[ \t]+[^\r\n]+)?$') { throw "Invalid checksum file: $Path" }
    return $Matches[1]
}

function Get-LocalArchive([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    Assert-NoReparse $full
    Assert-NoReparse ($full + '.sha256')
    Assert-Hash $full (Read-Checksum ($full + '.sha256'))
    return $full
}

function Download-File([string]$Url, [string]$Path, [hashtable]$Headers = @{}) {
    if (-not $Url.StartsWith('https://', [StringComparison]::OrdinalIgnoreCase)) { throw 'Downloads must use HTTPS.' }
    Assert-NoReparse $Path
    Write-Host ('Downloading ' + [IO.Path]::GetFileName($Path))
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path -Headers $Headers -TimeoutSec 120
}

function Get-Release([string]$Repository, [string]$Tag) {
    if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Invalid GitHub repository.' }
    $suffix = if ($Tag -eq 'latest') { 'latest' } else { 'tags/' + [Uri]::EscapeDataString($Tag) }
    $headers = @{ 'User-Agent' = 'ANReroll-setup'; Accept = 'application/vnd.github+json' }
    if ($env:GITHUB_TOKEN) { $headers.Authorization = 'Bearer ' + $env:GITHUB_TOKEN }
    try { return Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/$suffix" -Headers $headers -TimeoutSec 30 }
    catch { throw "Cannot read release $Repository ($Tag). Publish the release/assets first, or check GitHub access/rate limits. $($_.Exception.Message)" }
}

function Get-ReleaseAsset($Release, [string]$Pattern) {
    $assets = @($Release.assets | Where-Object { $_.name -match $Pattern })
    if ($assets.Count -ne 1) { throw "Expected one release asset matching $Pattern; found $($assets.Count)." }
    return $assets[0]
}

function Save-ReleaseAsset($Asset, [string]$Destination) {
    # Never forward a GitHub token to download redirects/third-party hosts.
    if ($env:GITHUB_TOKEN) {
        $headers = @{ 'User-Agent' = 'ANReroll-setup'; Accept = 'application/octet-stream'; Authorization = ('Bearer ' + $env:GITHUB_TOKEN) }
        Download-File $Asset.url $Destination $headers
    } else { Download-File $Asset.browser_download_url $Destination }
}

function Get-Artifact($Release, $Asset, [string]$Cache) {
    $path = Get-ChildPath $Cache $Asset.name
    Assert-NoReparse $path
    $digest = $Asset.PSObject.Properties['digest']
    $expected = ''
    if ($null -ne $digest -and $digest.Value -match '^sha256:([a-fA-F0-9]{64})$') { $expected = $Matches[1] }
    if (-not $expected) {
        $checkAsset = Get-ReleaseAsset $Release ('^' + [regex]::Escape($Asset.name + '.sha256') + '$')
        $checkPath = Get-ChildPath $Cache ($Asset.name + '.sha256')
        Save-ReleaseAsset $checkAsset $checkPath
        $expected = Read-Checksum $checkPath
    }
    if (Test-Path -LiteralPath $path) {
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -eq $expected) { return $path }
        Move-Item -LiteralPath $path -Destination ($path + '.invalid-' + [Guid]::NewGuid().ToString('N'))
    }
    $partial = $path + '.partial-' + [Guid]::NewGuid().ToString('N')
    Save-ReleaseAsset $Asset $partial
    Assert-Hash $partial $expected
    Move-Item -LiteralPath $partial -Destination $path
    return $path
}

function Expand-SafeZip([string]$Archive, [string]$Destination) {
    Assert-NoReparse $Destination
    if ((Test-Path -LiteralPath $Destination) -and @(Get-ChildItem -LiteralPath $Destination -Force).Count) {
        throw "Extraction destination is not empty: $Destination"
    }
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -gt 20000) { throw 'Archive contains too many entries.' }
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        [long]$total = 0
        foreach ($entry in $zip.Entries) {
            $path = Get-ChildPath $Destination $entry.FullName
            if (-not $seen.Add($path)) { throw "Duplicate archive path: $($entry.FullName)" }
            if ((($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) { throw 'Archive symlinks are not allowed.' }
            $total += $entry.Length
            if ($total -gt 2GB) { throw 'Archive expands beyond the 2 GB safety limit.' }
        }
        [void](New-Item -ItemType Directory -Path $Destination -Force)
        foreach ($entry in $zip.Entries) {
            $path = Get-ChildPath $Destination $entry.FullName
            if ($entry.FullName.EndsWith('/') -or $entry.FullName.EndsWith('\')) {
                [void](New-Item -ItemType Directory -Path $path -Force)
                continue
            }
            [void](New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($path)) -Force)
            $inputStream = $entry.Open()
            try {
                $outputStream = [IO.File]::Open($path, [IO.FileMode]::CreateNew)
                try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
            } finally { $inputStream.Dispose() }
        }
    } finally { $zip.Dispose() }
}

function Assert-ResourcePackage([string]$Root) {
    $manifest = Read-JsonFile (Join-Path $Root 'ANREROLL-RESOURCE.json')
    if ($manifest.schema_version -ne 1) { throw 'Unsupported resource manifest.' }
    $allowed = @('deployment/runtime.json', 'deployment/agent-requirements.txt', 'tools/verify_install.py', 'README.md', 'DEPLOYMENT.md', 'LICENSE.MaaReroll')
    $models = @('assets/resources/model/ocr/ko/det.onnx', 'assets/resources/model/ocr/ko/rec.onnx', 'assets/resources/model/ocr/ko/keys.txt')
    $expected = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    [void]$expected.Add('ANREROLL-RESOURCE.json')
    foreach ($property in $manifest.files.PSObject.Properties) {
        $name = $property.Name
        if ($name -notin $allowed -and $name -notmatch '^assets/(resources|agent)/') { throw "Unexpected resource file: $name" }
        if (($name -match '^assets/resources/model/' -and $name -notin $models) -or
            $name -match '^assets/resources/(debug|config)/|(^|/)__pycache__/|\.pyc$') { throw "Private/generated file in resources ZIP: $name" }
        $path = Get-ChildPath $Root $name
        Assert-Hash $path $property.Value
        if (-not $expected.Add($name)) { throw 'Duplicate resource manifest entry.' }
    }
    foreach ($item in Get-ChildItem -LiteralPath $Root -Recurse -File -Force) {
        $relative = $item.FullName.Substring($Root.TrimEnd('\').Length + 1).Replace('\', '/')
        if (-not $expected.Contains($relative)) { throw "Unlisted resource file: $relative" }
    }
    foreach ($required in @('assets/resources/interface.json', 'assets/agent/main.py', 'deployment/runtime.json', 'deployment/agent-requirements.txt', 'tools/verify_install.py')) {
        if (-not $expected.Contains($required)) { throw "Missing required release file: $required" }
    }
    foreach ($required in $models) { if (-not $expected.Contains($required)) { throw "Missing bundled OCR model: $required" } }
    return $manifest
}

function Test-Python([string]$Executable) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    $code = "import sys,struct,importlib.util as u; sys.exit(0 if (3,10)<=sys.version_info[:2]<(3,14) and struct.calcsize('P')==8 and u.find_spec('venv') and u.find_spec('ensurepip') else 1)"
    & $Executable -I -c $code 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Python([string]$Executable, [string[]]$Arguments) {
    # Windows PowerShell 5.1 can treat a native stderr line as a terminating
    # error even when the command succeeds. Judge native commands by exit code.
    $savedErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Executable -X utf8 @Arguments 2>&1 | Out-Host
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedErrorAction }
    if ($code -ne 0) { throw "Python command failed (exit $code). See the output above." }
}

function Get-AgentPython([string]$Root, $Runtime, [string]$Cache) {
    $venvPython = Join-Path $Root '.venv/Scripts/python.exe'
    Assert-NoReparse $venvPython
    if (Test-Path -LiteralPath $venvPython) {
        if (-not (Test-Python $venvPython)) { throw 'Existing Agent Python is not a compatible x64 interpreter.' }
        return $venvPython
    }
    $basePython = $PythonExe
    if ($basePython -and -not (Test-Python $basePython)) { throw 'PythonExe must be Python 3.10-3.13 x64 with venv/ensurepip.' }
    if (-not $basePython) {
        # Use a full official Python package, NOT the embeddable distribution.
        # NuGet Python includes venv and ensurepip and requires no registry/PATH edits.
        $python = $Runtime.python
        if ($python.version -notmatch '^3\.13\.\d+$' -or $python.url -ne "https://api.nuget.org/v3-flatcontainer/python/$($python.version)/python.$($python.version).nupkg") {
            throw 'Unexpected Python distribution URL/version.'
        }
        $pythonRoot = Get-ChildPath $Root ('runtime/python-' + $python.version)
        $basePython = Join-Path $pythonRoot 'tools/python.exe'
        Assert-NoReparse $basePython
        if (-not (Test-Path -LiteralPath $basePython)) {
            $package = $PythonPackage
            if (-not $package) {
                $package = Get-ChildPath $Cache ('python.' + $python.version + '.nupkg')
                if (-not (Test-Path -LiteralPath $package)) { Download-File $python.url $package }
            }
            Assert-Hash $package $python.sha256
            Expand-SafeZip $package $pythonRoot
        }
        if (-not (Test-Python $basePython)) { throw 'The local Python runtime could not start.' }
    }
    Write-Host 'Creating the external Agent virtual environment...'
    Invoke-Python -Executable $basePython -Arguments @('-I', '-m', 'venv', (Join-Path $Root '.venv'))
    return $venvPython
}

function Ensure-AgentPackages([string]$Executable, [string]$Requirements, [string]$Sdk) {
    if ($Sdk -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid SDK version.' }
    $probe = "import sys; from importlib.metadata import distributions; p={d.metadata['Name'].lower():d.version for d in distributions()}; expected={'maafw':'$Sdk','maaagentbinary':'1.0.1','numpy':'2.2.6','strenum':'0.4.15'}; sys.exit(0 if all(p.get(k)==v for k,v in expected.items()) else 1)"
    & $Executable -I -c $probe 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { return }
    if ($Update) { throw 'Existing Agent packages differ. Install to a new directory instead of modifying a working environment.' }
    $arguments = @('-I', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check', '--only-binary=:all:', '-r', $Requirements)
    if ($Wheelhouse) { $arguments += @('--no-index', '--find-links', [IO.Path]::GetFullPath($Wheelhouse)) }
    else { $arguments += @('--index-url', 'https://pypi.org/simple') }
    Invoke-Python -Executable $Executable -Arguments $arguments
    Invoke-Python -Executable $Executable -Arguments @('-I', '-m', 'pip', '--isolated', 'check')
}

function Install-ANReroll {
    if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) { throw 'Use Windows x64 PowerShell.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $root = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    if ($root -eq [IO.Path]::GetPathRoot($root).TrimEnd('\')) { throw 'InstallDir cannot be a drive root.' }
    Assert-NoReparse $root
    if (Test-Path -LiteralPath (Join-Path $root '.git')) { throw 'Do not install over a source checkout.' }
    $statePath = Join-Path $root '.anreroll-install.json'
    Assert-NoReparse $statePath
    $previousState = if (Test-Path -LiteralPath $statePath) { [IO.File]::ReadAllText($statePath) } else { $null }
    if (-not $previousState) { Assert-UnmanagedInstallDirectory $root }
    if ($previousState) {
        $state = $previousState | ConvertFrom-Json
        if ($state.schema_version -ne 1) { throw 'Unknown installation state.' }
        if ($state.status -eq 'ready' -and -not $Update) {
            Write-Host "Already installed: $root. Use -Update to replace managed app/resource files."
            if ($Launch) { Start-Process -FilePath (Join-Path $root 'MFWSide.exe') -WorkingDirectory $root -WindowStyle Hidden }
            return
        }
    }
    foreach ($process in @(Get-Process -Name MFWSide -ErrorAction SilentlyContinue)) {
        if ($process.Path -and $process.Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Close MFWSide and its tasks before installing/updating.' }
    }
    [void](New-Item -ItemType Directory -Path $root -Force)
    $cache = Get-ChildPath $root '.setup-cache'
    Assert-NoReparse $cache
    [void](New-Item -ItemType Directory -Path $cache -Force)
    $stage = Get-ChildPath $root ('.setup-stage-' + [Guid]::NewGuid().ToString('N'))
    [void](New-Item -ItemType Directory -Path $stage)
    Write-JsonFile $statePath @{ schema_version = 1; status = 'preparing' }
    try {
        $release = $null
        if ($ResourceArchive) { $resourceZip = Get-LocalArchive $ResourceArchive }
        else {
            $release = Get-Release 'D-Roote/Arknights_ReRoll' $ResourceTag
            $pattern = if ($ResourceAsset) { '^' + [regex]::Escape($ResourceAsset) + '$' } else { '^ANReroll-resources-.+\.zip$' }
            $resourceZip = Get-Artifact $release (Get-ReleaseAsset $release $pattern) $cache
        }
        $resourceStage = Join-Path $stage 'resource'
        Expand-SafeZip $resourceZip $resourceStage
        $manifest = Assert-ResourcePackage $resourceStage
        $runtime = Read-JsonFile (Join-Path $resourceStage 'deployment/runtime.json')
        if ($AppArchive) { $appZip = Get-LocalArchive $AppArchive; $selectedApp = 'local' }
        else {
            $selectedApp = if ($AppTag) { $AppTag } else { $runtime.app_tag }
            $appRelease = Get-Release $runtime.app_repository $selectedApp
            $appZip = Get-Artifact $appRelease (Get-ReleaseAsset $appRelease '^MFWSide.*windows-x64\.zip$') $cache
        }
        $appStage = Join-Path $stage 'app'
        Expand-SafeZip $appZip $appStage
        $executables = @(Get-ChildItem -LiteralPath $appStage -Filter MFWSide.exe -Recurse -File)
        if ($executables.Count -ne 1) { throw 'Expected exactly one MFWSide.exe in the app ZIP.' }
        $appRoot = $executables[0].DirectoryName
        $build = Read-JsonFile (Join-Path $appRoot 'BUILD-INFO.json')
        if ($build.name -ne 'MFWSide' -or $build.platform -ne 'windows-x86_64' -or $build.packages.MaaFw -ne $runtime.maafw_version) {
            throw 'MFWSide build SDK/platform does not match this resource release. Select a compatible AppTag.'
        }
        $payload = Join-Path $stage 'payload'
        [void](New-Item -ItemType Directory -Path $payload)
        foreach ($item in Get-ChildItem -LiteralPath $appRoot -Force) {
            if ($item.Name -notin @('MFWSide.exe', '_internal', 'BUILD-INFO.json', 'licenses', 'README.md')) { throw "Unexpected app component: $($item.Name)" }
            Copy-Item -LiteralPath $item.FullName -Destination $payload -Recurse
        }
        if (-not (Test-Path -LiteralPath (Join-Path $payload '_internal') -PathType Container)) { throw 'The app ZIP is missing _internal.' }
        foreach ($name in @('assets', 'deployment', 'tools', 'ANREROLL-RESOURCE.json', 'README.md', 'DEPLOYMENT.md', 'LICENSE.MaaReroll')) {
            Copy-Item -LiteralPath (Join-Path $resourceStage $name) -Destination $payload -Recurse -Force
        }
        $modelSource = Join-Path $payload 'assets/resources/model/ocr/ko'
        foreach ($property in $runtime.ocr.files.PSObject.Properties) {
            $source = Get-ChildPath $modelSource $property.Name
            Assert-NoReparse $source
            Assert-Hash $source $property.Value
        }
        $agentPython = Get-AgentPython $root $runtime $cache
        Ensure-AgentPackages $agentPython (Join-Path $payload 'deployment/agent-requirements.txt') $runtime.maafw_version
        Write-Host 'Verifying native resources, OCR models and Agent registration (no device input)...'
        Invoke-Python -Executable $agentPython -Arguments @('-I', '-X', 'utf8', (Join-Path $payload 'tools/verify_install.py'), $payload)
        $launcher = "@echo off`r`nsetlocal`r`ncd /d `"%~dp0`"`r`nstart `"`" `"%~dp0MFWSide.exe`"`r`n"
        [IO.File]::WriteAllText((Join-Path $payload 'Start-ANReroll.cmd'), $launcher, [Text.Encoding]::ASCII)
        $managed = @('MFWSide.exe', '_internal', 'BUILD-INFO.json', 'licenses', 'assets/resources', 'assets/agent',
                     'deployment', 'tools', 'ANREROLL-RESOURCE.json', 'README.md', 'DEPLOYMENT.md', 'LICENSE.MaaReroll', 'Start-ANReroll.cmd')
        $backup = Get-ChildPath $root ('.setup-backups/' + [DateTime]::UtcNow.ToString('yyyyMMddHHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
        Assert-NoReparse $backup
        $moved = New-Object 'System.Collections.Generic.List[string]'
        $placed = New-Object 'System.Collections.Generic.List[string]'
        try {
            foreach ($name in $managed) {
                $destination = Get-ChildPath $root $name
                Assert-NoReparse $destination
                if (Test-Path -LiteralPath $destination) {
                    $saved = Get-ChildPath $backup $name
                    [void](New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($saved)) -Force)
                    Move-Item -LiteralPath $destination -Destination $saved
                    $moved.Add($name)
                }
                $source = Get-ChildPath $payload $name
                if (Test-Path -LiteralPath $source) {
                    [void](New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force)
                    Move-Item -LiteralPath $source -Destination $destination
                    $placed.Add($name)
                }
            }
            Write-JsonFile $statePath @{ schema_version = 1; status = 'ready'; resources = $manifest.version; app = $selectedApp;
                maafw = $runtime.maafw_version; python = $agentPython; backup = $backup; installed_utc = [DateTime]::UtcNow.ToString('o') }
        } catch {
            foreach ($name in $placed) { Move-Item -LiteralPath (Get-ChildPath $root $name) -Destination (Get-ChildPath $payload $name) }
            foreach ($name in $moved) { Move-Item -LiteralPath (Get-ChildPath $backup $name) -Destination (Get-ChildPath $root $name) }
            throw
        }
        Write-Host "Ready: $root"
        Write-Host 'Start the app with Start-ANReroll.cmd. No emulator or game task was started.'
        if ($moved.Count) { Write-Host "Previous managed files are recoverable in: $backup" }
        if ($Launch) { Start-Process -FilePath (Join-Path $root 'MFWSide.exe') -WorkingDirectory $root -WindowStyle Hidden }
    } catch {
        if ($previousState) { [IO.File]::WriteAllText($statePath, $previousState, (New-Object Text.UTF8Encoding($false))) }
        throw
    } finally {
        # Only remove the unique, installer-created staging directory, never user data.
        $checkedStage = [IO.Path]::GetFullPath($stage)
        if ($checkedStage.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -and
            [IO.Path]::GetFileName($checkedStage) -match '^\.setup-stage-[a-f0-9]{32}$') {
            Assert-NoReparse $checkedStage
            Remove-Item -LiteralPath $checkedStage -Recurse -Force
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $savedProgress = $ProgressPreference
    $savedOutputEncoding = [Console]::OutputEncoding
    $ProgressPreference = 'SilentlyContinue'
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
    try { Install-ANReroll }
    catch { Write-Error $_; exit 1 }
    finally { $ProgressPreference = $savedProgress; [Console]::OutputEncoding = $savedOutputEncoding }
}
