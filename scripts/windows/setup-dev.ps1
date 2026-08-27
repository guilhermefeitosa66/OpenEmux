<#
.SYNOPSIS
    Take a bare Windows 11 machine to a running OpenEmux development checkout.

.DESCRIPTION
    OpenEmux is a GTK4/libadwaita app driven by PyGObject. On Windows the only
    practical source of that stack is MSYS2's MINGW64 environment: GTK 4,
    libadwaita, Python and the GObject bindings all come from one pacman
    repository -- and it is the same repository the shipped Windows bundle is
    assembled from, so what runs here and what we ship share one ABI.

    This is a BOOTSTRAP, not the long-term workflow. Development happens on
    Linux; this environment exists to prove the stack works on Windows and to
    give a fast edit-run loop while the port is written. Once the portable .zip
    exists it carries its own GTK4 and Python, and a clean Windows machine with
    no MSYS2 is the better test target.

    Every step is idempotent -- re-running the script is safe and cheap.

    Deliberately NOT installed:
      * Docker      - Windows artifacts are built in a Linux container, on Linux.
      * Inno Setup  - the installer is produced on Linux too.
      * Python      - a Windows-native Python cannot import MSYS2's PyGObject.
      * make        - MSYS2 supplies it; a second one on PATH is the classic
                      "works in cmd, fails in mingw64" bug.

    Nothing here needs winget, and the system PATH is never modified. The only
    thing installed outside the repository is MSYS2 itself, under $Msys2Root.

.PARAMETER Msys2Root
    Where MSYS2 lives. Defaults to the winget install location, C:\msys64.

.PARAMETER SkipVendor
    Skip downloading the vendored RetroArch (~193 MiB). The app will not be able
    to launch a game until `make vendor-retroarch` is run.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\setup-dev.ps1
#>
[CmdletBinding()]
param(
    [string] $Msys2Root = 'C:\msys64',
    [switch] $SkipVendor
)

$ErrorActionPreference = 'Stop'

# --- MSYS2 installer ---------------------------------------------------------
#
# Fetched straight from the msys2-installer releases rather than through winget.
# Two reasons, in order of importance:
#
#   1. It is pinned and verifiable. MSYS2 publishes a .sha256 next to every
#      asset, so the download is checked before a single byte is executed --
#      which winget's own MSYS2 manifest does not give us control over.
#   2. winget is not dependable here. The build shipped with older Windows 11
#      installs (v1.2.10691) crashes with an access violation on this manifest,
#      and telling a developer to first update the Microsoft Store is a worse
#      first step than a 50 MB download.
#
# The 'base' self-extracting archive is used, not the graphical installer: it is
# a plain 7-Zip SFX, so it needs no Qt installer framework and no UI to run
# headless. To bump the version, change all three values together -- the sha256
# comes from <url>.sha256.
$Msys2Release = '2026-06-11'
$Msys2SfxName = "msys2-base-x86_64-$($Msys2Release -replace '-', '').sfx.exe"
$Msys2SfxUrl = "https://github.com/msys2/msys2-installer/releases/download/$Msys2Release/$Msys2SfxName"
$Msys2Sha256 = 'C105946E64E08F099AC0E4647461CE762B95333AD211777666476A9A41451D65'

# --- Package set -------------------------------------------------------------
#
# Kept in sync with docs/DEVELOPMENT.md and, for the runtime half, with the seed
# list in packaging/windows/msys2_bundle.py. Versions are whatever the rolling
# repository holds; the shipped bundle pins them with a lockfile, a development
# checkout does not need to.

# MSYS (POSIX layer) packages. `make` must be this one, not
# mingw-w64-x86_64-make: the Makefile recipes are POSIX sh, and only the MSYS
# build runs them through /bin/sh.
$MsysPackages = @(
    'make',
    'git'
)

# MINGW64 packages -- the native Windows DLLs the app actually loads.
$MingwPackages = @(
    # GTK stack
    'gtk4',                            # toolkit
    'libadwaita',                      # app requires >= 1.5
    'gobject-introspection-runtime',   # the typelibs PyGObject reads
    'librsvg',                         # Rsvg-2.0 typelib -> cartridge frames
    'adwaita-icon-theme',              # symbolic icons
    'hicolor-icon-theme',              # base theme
    'gsettings-desktop-schemas',       # libadwaita reads org.gnome.desktop.interface
    'shared-mime-info',                # file type detection
    'webp-pixbuf-loader',              # WebP cover art

    # Python and bindings
    'python',                          # 3.14.x
    'python-gobject',                  # cannot be pip-installed here
    'python-cairo',                    # the gi-cairo bridge cartridge_render needs
    'python-yaml',                     # matches requirements.lock
    'python-coverage',                 # make coverage
    'ca-certificates',                 # OpenSSL CA bundle, for urllib over HTTPS

    # Tooling
    'SDL2',                            # gamepad backend (issue #118, later PR)
    '7zip'                             # RetroArch.7z uses BCJ2; py7zr cannot read it
)
# Note: python-xlib is absent on purpose (X11-only), and so are python-requests
# and python-pillow -- the app uses urllib and cairo, not those.

# --- Helpers -----------------------------------------------------------------

function Write-Step {
    param([string] $Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Skip {
    param([string] $Message)
    Write-Host "    (already done) $Message" -ForegroundColor DarkGray
}

function Get-FreshPath {
    # winget writes to the machine/user environment, which the *current* process
    # does not see. Re-read both so a tool installed a moment ago is findable
    # without asking the user to open a new terminal.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    return ($machine, $user | Where-Object { $_ }) -join ';'
}

function Test-Tool {
    param([string] $Name)
    $env:Path = Get-FreshPath
    return [bool] (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Msys {
    <#
      Run a command inside MSYS2 and propagate its exit code.

      `bash -lc` rather than msys2_shell.cmd: the launcher does not reliably
      hand back the command's exit status, and we need to fail loudly.
      MSYSTEM selects the environment (MINGW64 puts /mingw64/bin first) and
      CHERE_INVOKING keeps the working directory instead of jumping to $HOME.
    #>
    param(
        [Parameter(Mandatory)] [string] $Command,
        [string] $Msystem = 'MINGW64',
        [string] $WorkingDirectory,
        [switch] $AllowFailure
    )

    $bash = Join-Path $Msys2Root 'usr\bin\bash.exe'
    if (-not (Test-Path $bash)) {
        throw "MSYS2 bash not found at $bash. Is MSYS2 installed under $Msys2Root?"
    }

    $previousMsystem = $env:MSYSTEM
    $previousChere = $env:CHERE_INVOKING
    $previousCwd = Get-Location
    try {
        $env:MSYSTEM = $Msystem
        $env:CHERE_INVOKING = '1'
        if ($WorkingDirectory) { Set-Location $WorkingDirectory }

        & $bash -lc $Command
        $code = $LASTEXITCODE
    }
    finally {
        Set-Location $previousCwd
        $env:MSYSTEM = $previousMsystem
        $env:CHERE_INVOKING = $previousChere
    }

    if ($code -ne 0 -and -not $AllowFailure) {
        throw "MSYS2 command failed (exit $code): $Command"
    }
    return $code
}

# --- 0. Preflight ------------------------------------------------------------

Write-Step 'Preflight'

if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'OpenEmux for Windows is x86_64 only. 32-bit Windows is out of scope (issue #118).'
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not (Test-Path (Join-Path $RepoRoot 'pyproject.toml'))) {
    throw "Expected the OpenEmux checkout at $RepoRoot but found no pyproject.toml there."
}
Write-Host "    repo: $RepoRoot"

# --- 1. MSYS2 ----------------------------------------------------------------

Write-Step 'MSYS2'

if (Test-Path (Join-Path $Msys2Root 'usr\bin\bash.exe')) {
    Write-Skip "MSYS2 present at $Msys2Root"
}
else {
    $parent = Split-Path -Parent $Msys2Root
    $leaf = Split-Path -Leaf $Msys2Root
    if ($leaf -ne 'msys64') {
        # The self-extracting archive always creates a directory called
        # msys64; it offers no way to rename it.
        throw "-Msys2Root must end in 'msys64' (got '$leaf'). Try -Msys2Root D:\msys64."
    }

    $cache = Join-Path $env:TEMP 'openemux-setup'
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $sfx = Join-Path $cache $Msys2SfxName

    if ((Test-Path $sfx) -and (Get-FileHash $sfx -Algorithm SHA256).Hash -eq $Msys2Sha256) {
        Write-Host "    reusing verified download $sfx"
    }
    else {
        Write-Host "    downloading $Msys2SfxName (~50 MB)..."
        # Invoke-WebRequest's progress bar makes a 50 MB download several times
        # slower in Windows PowerShell 5.1; suppressing it is not cosmetic.
        $previousProgress = $ProgressPreference
        try {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $Msys2SfxUrl -OutFile $sfx -UseBasicParsing -TimeoutSec 900
        }
        finally {
            $ProgressPreference = $previousProgress
        }

        $actual = (Get-FileHash $sfx -Algorithm SHA256).Hash
        if ($actual -ne $Msys2Sha256) {
            Remove-Item $sfx -Force -ErrorAction SilentlyContinue
            throw ("checksum mismatch for $Msys2SfxName`n" +
                "  expected $Msys2Sha256`n" +
                "  actual   $actual`n" +
                '  Do not proceed until you know why.')
        }
        Write-Host '    sha256 verified'
    }

    Write-Host "    extracting to $Msys2Root ..."
    # -y accept all, -o<dir> extract into <dir>; the archive supplies the
    # msys64/ directory itself, so the target is the PARENT of $Msys2Root.
    & $sfx -y "-o$parent" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "MSYS2 self-extractor failed (exit $LASTEXITCODE)."
    }
    if (-not (Test-Path (Join-Path $Msys2Root 'usr\bin\bash.exe'))) {
        throw "Extraction finished but $Msys2Root\usr\bin\bash.exe is missing."
    }

    # First run generates /etc/passwd, the pacman keyring and the user's home.
    # Doing it here means the failure surfaces now, with context, rather than
    # inside the first pacman call.
    Write-Host '    initialising (first run builds the pacman keyring)...'
    Invoke-Msys -Msystem 'MSYS' -Command 'true' | Out-Null
}

# git and gh are expected to be on the machine already; say so rather than
# silently installing a second copy.
foreach ($tool in 'git', 'gh') {
    if (Test-Tool $tool) {
        Write-Skip "$tool on PATH"
    }
    else {
        $id = 'Git.Git'
        if ($tool -eq 'gh') { $id = 'GitHub.cli' }
        Write-Warning "$tool is not on PATH. Install it with: winget install --id $id"
    }
}

# --- 2. Bootstrap pacman -----------------------------------------------------

Write-Step 'Updating the MSYS2 core (pacman -Syu, twice)'

# The first pass may replace pacman and its runtime and then terminate the shell
# mid-transaction -- expected, and documented upstream -- so its exit code is not
# treated as failure. The second pass completes the update and must succeed.
Invoke-Msys -Msystem 'MSYS' -Command 'pacman -Syu --noconfirm' -AllowFailure | Out-Null
Invoke-Msys -Msystem 'MSYS' -Command 'pacman -Syu --noconfirm' | Out-Null

# --- 3. Packages -------------------------------------------------------------

Write-Step 'Installing the GTK4 / Python stack'

$mingwPrefixed = $MingwPackages | ForEach-Object { "mingw-w64-x86_64-$_" }
$allPackages = @($MsysPackages) + @($mingwPrefixed)

Write-Host "    $($allPackages.Count) packages"
# --needed is what makes this idempotent: pacman skips what is already current.
Invoke-Msys -Command "pacman -S --needed --noconfirm $($allPackages -join ' ')" | Out-Null

# --- 4. Vendored RetroArch ---------------------------------------------------

Write-Step 'Vendoring RetroArch for Windows'

if ($SkipVendor) {
    Write-Host '    skipped (-SkipVendor). Run `make vendor-retroarch` before launching a game.'
}
else {
    Write-Host '    ~193 MiB on first run; verified against vendors/manifest.json, then reused.'
    # --record only does anything when the manifest has no sha256 yet, which is
    # the case exactly once per upstream version: libretro publishes no
    # checksums, so the first fetch records what it saw for review and commit.
    # Every later run verifies against that and fails hard on a mismatch.
    Invoke-Msys -WorkingDirectory $RepoRoot `
        -Command 'python scripts/vendor_retroarch.py win64 --record' | Out-Null
}

# --- 5. Verify ---------------------------------------------------------------

Write-Step 'Verifying the toolchain'

# Import the exact bindings the app needs before trusting the environment, so a
# missing typelib fails here with a clear message instead of at first paint.
# Delegated to a script rather than a `python -c` one-liner: this command
# crosses PowerShell and then bash, and a Python one-liner does not survive
# both layers of quoting.
Invoke-Msys -WorkingDirectory $RepoRoot -Command 'make setup' | Out-Null

# The suite is allowed to fail here without failing the setup. Until the
# platform abstraction lands (issue #118), Linux-only assumptions in the tests
# are expected to trip on Windows -- that result is the signal this bootstrap
# exists to produce, not a reason to discard a working toolchain.
$testExit = Invoke-Msys -WorkingDirectory $RepoRoot -Command 'make test' -AllowFailure
if ($testExit -ne 0) {
    Write-Warning "make test exited $testExit. The toolchain is installed; the failures above are the porting work."
}

# --- Done --------------------------------------------------------------------

Write-Host ''
Write-Host 'OpenEmux is ready.' -ForegroundColor Green
Write-Host ''
Write-Host '  Open the development shell:  scripts\windows\dev-shell.cmd'
Write-Host '  Then, inside it:             make run'
Write-Host ''
Write-Host '  The system PATH was left alone on purpose: putting mingw64\bin on it'
Write-Host '  would shadow system DLLs for every process on the machine. dev-shell.cmd'
Write-Host '  sets up the environment for that one shell instead.'
Write-Host ''
