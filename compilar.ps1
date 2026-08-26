# Compila AvisMonitorOneways.exe
# Se ejecuta DESDE la carpeta del proyecto: PyInstaller se niega a correr desde system32.
$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $raiz

$py = "C:\Users\mcebrian\AppData\Local\Python\pythoncore-3.14-64\python.exe"

# Las rutas de --add-data se resuelven contra el --specpath, NO contra el cwd:
# por eso van absolutas (trampa ya documentada en el README).
$assets = Join-Path $raiz "src\assets"
# El mapa oficina->isla tiene que viajar DENTRO del .exe. Si falta,
# resource() no lo encuentra en un --onefile y el reparto por islas se cae
# al lado seguro: todos reciben todo. No da error, solo correos de mas.
$islas  = Join-Path $raiz "src\oficinas_islas.json"
$icono  = Join-Path $assets "avis.ico"

Write-Host "Compilando desde $raiz"

# PyInstaller escribe sus INFO por STDERR. En PowerShell 5.1 eso se convierte en
# ErrorRecord y con ErrorActionPreference='Stop' aborta la compilacion en la
# primera linea, aunque no haya ningun error. Por eso aqui se relaja: el exito
# NO se juzga por el codigo de salida sino por si el .exe existe al final.
$ErrorActionPreference = 'Continue'

& $py -m PyInstaller `
    --onefile --windowed --noconfirm `
    --name AvisMonitorOneways `
    --icon $icono `
    --add-data "$assets;assets" `
    --add-data "$islas;." `
    --collect-all playwright `
    --hidden-import rentway_export `
    --paths src `
    src\avis_monitor.py

# PyInstaller DEVUELVE 0 AUNQUE FALLE: hay que comprobar que el .exe existe.
$exe = Join-Path $raiz "dist\AvisMonitorOneways.exe"
if (-not (Test-Path $exe)) {
    Write-Host "FALLO: no se ha generado el .exe"
    exit 1
}
$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "OK: $exe ($mb MB)"
