# ============================================================
#  PUBLICAR UNA VERSION NUEVA  (esto lo ejecutas TU, nadie mas)
#
#  Coge el .exe recien compilado, calcula su huella, escribe el
#  manifiesto version.json y lo deja todo en la carpeta de OneDrive.
#  A partir de ese momento, los demas equipos lo detectan solos en su
#  siguiente pasada, se lo descargan y lo aplican al reiniciar.
#
#  Uso:
#     .\PUBLICAR_VERSION.ps1 -Version "1.2.0" -Notas "Que cambia"
# ============================================================
param(
    [Parameter(Mandatory=$true)][string]$Version,
    [string]$Notas = "",
    [string]$Exe = "$env:LOCALAPPDATA\AvisMonitorOneways\AvisMonitorOneways.exe",
    # Donde se publica: una carpeta (unidad de red, UNC o local). Para GitHub
    # se publica en el Release y en actualizacion.txt se pone la URL del
    # version.json; este script sirve igual para preparar los ficheros.
    [string]$Canal = "$env:USERPROFILE\Desktop\PUBLICACION_AvisMonitorOneways",
    [string]$UrlBase = "",
    [switch]$Obligatoria
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Exe)) { throw "No encuentro el ejecutable: $Exe" }
$canal = $Canal
New-Item -ItemType Directory -Force $canal | Out-Null

Write-Host ""
Write-Host "  PUBLICANDO LA VERSION $Version" -ForegroundColor Red
Write-Host ""

# 1) copiar el ejecutable al canal
$destinoExe = Join-Path $canal "AvisMonitorOneways.exe"
Copy-Item $Exe $destinoExe -Force
$mb = [math]::Round((Get-Item $destinoExe).Length / 1MB, 1)
Write-Host "  Ejecutable copiado ($mb MB)"

# 2) huella: es lo que impide que alguien cuele otro fichero por el camino
$sha = (Get-FileHash $destinoExe -Algorithm SHA256).Hash.ToLower()
Write-Host "  SHA256: $sha"

# 3) manifiesto
#    Si se indica -UrlBase (por ejemplo la de un Release de GitHub) se pone esa
#    direccion; si no, la ruta del propio canal.
if ($UrlBase) {
    $url = ($UrlBase.TrimEnd('/')) + "/AvisMonitorOneways.exe"
} else {
    $url = "file:///" + ($destinoExe -replace '\\','/')
}
$man = [ordered]@{
    version     = $Version
    url         = $url
    sha256      = $sha
    notas       = $Notas
    obligatoria = [bool]$Obligatoria
    publicado   = (Get-Date).ToString("yyyy-MM-dd HH:mm")
}
# OJO: 'Set-Content -Encoding UTF8' escribe un BOM que rompe el analisis del
# JSON en el otro extremo. Se escribe UTF-8 SIN BOM a proposito.
[System.IO.File]::WriteAllText((Join-Path $canal "version.json"),
    ($man | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "  Manifiesto escrito en $canal\version.json"

Write-Host ""
Write-Host "  LISTO." -ForegroundColor Green
Write-Host "  Los equipos que tengan el canal 'onedrive' configurado se la"
Write-Host "  descargaran en su siguiente pasada (como mucho en 2 horas) y la"
Write-Host "  aplicaran la proxima vez que se abra el programa."
Write-Host ""
Write-Host "  Recuerda subir tambien el numero de VERSION en el codigo antes"
Write-Host "  de compilar, o los demas no veran que hay novedad." -ForegroundColor Yellow
Write-Host ""
