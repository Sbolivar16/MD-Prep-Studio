# MD-Prep Studio - Windows installer logic (called by the setup .exe; Windows PowerShell 5.1 compatible)
#
# GROMACS and AmberTools have no native Windows builds. MD-Prep therefore runs inside its own small Linux system
# (a WSL distribution called "MD-Prep", based on the official Ubuntu Base image). The user only sees a desktop icon
# that opens the platform in the browser.
#
# Exit codes: 0 = OK, 3010 = Windows must be restarted (WSL was just enabled), 1 = error (see install.log)
param(
    [string]$Lang = "en",
    [string]$InstDir = (Join-Path $env:LOCALAPPDATA "MD-Prep"),
    [int]$Port = 8642
)
$ErrorActionPreference = "Continue"   # native tools write progress to stderr; errors are checked explicitly
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:WSL_UTF8 = "1"
$Distro = "MD-Prep"
$Log = Join-Path $InstDir "install.log"
$Dl = Join-Path $InstDir "downloads"
New-Item -ItemType Directory -Force -Path $InstDir, $Dl | Out-Null

function M([string]$es, [string]$en) { if ($Lang -eq "es") { return $es } else { return $en } }
function Log([string]$t) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $t
    Write-Output $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}
function Clean([object]$o) { return (($o | Out-String) -replace "`0", "").Trim() }

function Test-Wsl {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return $false }
    try { $null = & wsl.exe --status 2>&1; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
function Get-Distros {
    try { return (Clean (& wsl.exe --list --quiet 2>&1)) -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
    catch { return @() }
}
function Enable-Wsl {
    Log (M "Activando WSL (Subsistema de Windows para Linux). Windows pedirá permiso de administrador..." `
           "Enabling WSL (Windows Subsystem for Linux). Windows will ask for administrator permission...")
    try {
        $p = Start-Process -FilePath "wsl.exe" -ArgumentList "--install", "--no-distribution" -Verb RunAs -Wait -PassThru -ErrorAction Stop
        Log ("wsl --install --no-distribution -> " + $p.ExitCode)
    } catch {
        Log ((M "No se pudo activar WSL automáticamente: " "WSL could not be enabled automatically: ") + $_)
        Log (M "Actívalo a mano: abre PowerShell como administrador y ejecuta  wsl --install --no-distribution" `
               "Enable it manually: open PowerShell as administrator and run  wsl --install --no-distribution")
        exit 1
    }
    Log (M "WSL quedó activado. REINICIA Windows y vuelve a ejecutar este instalador." `
           "WSL has been enabled. RESTART Windows and run this installer again.")
    exit 3010
}
function Download([string]$url, [string]$dest) {
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 1MB)) { Log ((M "Ya descargado: " "Already downloaded: ") + (Split-Path $dest -Leaf)); return }
    Log ((M "Descargando " "Downloading ") + $url)
    for ($i = 1; $i -le 3; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile "$dest.part" -ErrorAction Stop; Move-Item -Force "$dest.part" $dest -ErrorAction Stop; return }
        catch { Log ("  " + $_.Exception.Message); Start-Sleep -Seconds (5 * $i) }
    }
    throw ((M "No se pudo descargar " "Could not download ") + $url + (M ". Revisa la conexión a internet." ". Check your internet connection."))
}
function To-WslPath([string]$p) { return "/mnt/" + $p.Substring(0, 1).ToLower() + $p.Substring(2).Replace("\", "/") }

try {
    Log "=== MD-Prep Studio - $(M 'instalación en Windows' 'Windows installation') ($(Get-Date -Format 'yyyy-MM-dd HH:mm')) ==="
    Log ("Windows " + [Environment]::OSVersion.Version + " · " + $InstDir)

    # ------------------------------------------------------------------ 1. WSL
    Log (M "[1/5] Comprobando WSL..." "[1/5] Checking WSL...")
    if (-not (Test-Wsl)) { Enable-Wsl }

    # ------------------------------------------------------------------ 2. Linux system for MD-Prep
    Log (M "[2/5] Sistema Linux de MD-Prep (Ubuntu Base 24.04)..." "[2/5] MD-Prep Linux system (Ubuntu Base 24.04)...")
    if ((Get-Distros) -contains $Distro) {
        Log (M "Ya existe; se actualizará." "Already present; it will be updated.")
    } else {
        $base = "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/"
        $file = "ubuntu-base-24.04.3-base-amd64.tar.gz"
        try {
            $html = (Invoke-WebRequest -UseBasicParsing -Uri $base -ErrorAction Stop).Content
            $found = [regex]::Matches($html, 'ubuntu-base-24\.04(\.\d+)?-base-amd64\.tar\.gz') | ForEach-Object { $_.Value } | Sort-Object -Unique
            if ($found) { $file = $found | Sort-Object { if ($_ -match '24\.04\.(\d+)') { [int]$Matches[1] } else { 0 } } | Select-Object -Last 1 }
        } catch { Log ("  " + $_.Exception.Message) }
        $rootfs = Join-Path $Dl $file
        Download ($base + $file) $rootfs
        $vm = Join-Path $InstDir "wsl"
        New-Item -ItemType Directory -Force -Path $vm | Out-Null
        $ok = $false
        foreach ($v in @("2", "1")) {
            Log ("wsl --import $Distro (WSL $v)")
            $out = Clean (& wsl.exe --import $Distro $vm $rootfs --version $v 2>&1)
            if ($out) { Log $out }
            if ($LASTEXITCODE -eq 0 -and ((Get-Distros) -contains $Distro)) { $ok = $true; break }
        }
        if (-not $ok) {
            Log (M "No se pudo crear el sistema Linux. Puede faltar un componente de WSL o la virtualización." `
                   "The Linux system could not be created. A WSL component or virtualization may be missing.")
            Enable-Wsl
        }
    }

    # ------------------------------------------------------------------ 3. Miniforge
    Log (M "[3/5] Descargando Miniforge (conda)..." "[3/5] Downloading Miniforge (conda)...")
    Download "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh" (Join-Path $InstDir "Miniforge3-Linux-x86_64.sh")

    # ------------------------------------------------------------------ 4. environment inside WSL
    Log (M "[4/5] Instalando GROMACS, AmberTools, ACPYPE, PDBFixer, PDB2PQR y RDKit (10-20 minutos)..." `
           "[4/5] Installing GROMACS, AmberTools, ACPYPE, PDBFixer, PDB2PQR and RDKit (10-20 minutes)...")
    $env:MDPREP_PORT = "$Port"
    $env:WSLENV = "MDPREP_PORT"
    $src = To-WslPath $InstDir
    & wsl.exe -d $Distro -u root -e bash "$src/wsl_setup.sh" "$src" 2>&1 | ForEach-Object { Log (($_ | Out-String) -replace "`0", "").TrimEnd() }
    if ($LASTEXITCODE -ne 0) { throw (M "Falló la instalación dentro de WSL (código $LASTEXITCODE)." "The installation inside WSL failed (code $LASTEXITCODE).") }

    # ------------------------------------------------------------------ 5. launchers
    Log (M "[5/5] Creando accesos directos y el comando prepmd..." "[5/5] Creating shortcuts and the prepmd command...")
    $url = "http://localhost:$Port"
    $openPs = @"
# Waits until MD-Prep Studio answers and opens it in the default browser
for (`$i = 0; `$i -lt 180; `$i++) {
    try { Invoke-WebRequest -UseBasicParsing -Uri '$url/_stcore/health' -TimeoutSec 2 -ErrorAction Stop | Out-Null; Start-Process '$url'; exit 0 }
    catch { Start-Sleep -Seconds 1 }
}
"@
    Set-Content -Path (Join-Path $InstDir "open_browser.ps1") -Value $openPs -Encoding UTF8
    $l1 = M "Abriendo MD-Prep Studio en el navegador: $url" "Opening MD-Prep Studio in your browser: $url"
    $l2 = M "Deja esta ventana abierta mientras trabajas. Ciérrala para apagar la plataforma." "Keep this window open while you work. Close it to stop the platform."
    $cmd = @"
@echo off
chcp 65001 >nul
title MD-Prep Studio
echo.
echo   MD-Prep Studio
echo   $l1
echo   $l2
echo.
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0open_browser.ps1"
wsl.exe -d $Distro -u root -e /opt/mdprep/start.sh

"@
    $utf8 = New-Object System.Text.UTF8Encoding $false     # .cmd files must not start with a BOM
    [IO.File]::WriteAllText((Join-Path $InstDir "MD-Prep.cmd"), ($cmd -replace "`r?`n", "`r`n"), $utf8)
    $apps = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
    if (Test-Path $apps) {
        [IO.File]::WriteAllText((Join-Path $apps "prepmd.cmd"), "@call `"%LOCALAPPDATA%\MD-Prep\MD-Prep.cmd`"`r`n", $utf8)
    }
    Log (M "=== Instalación terminada. Abre MD-Prep Studio desde el icono del escritorio o escribe  prepmd  en una terminal. ===" `
           "=== Installation finished. Open MD-Prep Studio from the desktop icon or type  prepmd  in a terminal. ===")
    exit 0
} catch {
    Log ("ERROR: " + $_.Exception.Message)
    Log ((M "Registro completo: " "Full log: ") + $Log)
    exit 1
}
