# ============================================================
#  AVIS â€” Monitor de Oneways : INSTALADOR
#  Instala en el usuario actual (NO pide permisos de administrador),
#  crea acceso directo y deja la vigilancia diaria programada.
# ============================================================
$ErrorActionPreference = "Stop"
$origen  = Split-Path -Parent $MyInvocation.MyCommand.Path
$destino = Join-Path $env:LOCALAPPDATA "AvisMonitorOneways"
$tarea   = "AVIS - Monitor de Oneways (diario)"

function Titulo($t) {
    Write-Host ""
    Write-Host "=== $t ===" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "  AVIS - MONITOR DE ONEWAYS" -ForegroundColor Red
Write-Host "  Instalador" -ForegroundColor Red
Write-Host ""

# ---------- 1) Â¿ya hay otro equipo vigilando? ----------
Titulo "Comprobando si otro equipo ya esta vigilando"
# La señal es LOCAL salvo que exista senal.txt con una carpeta compartida.
# (Antes se miraba en OneDrive; se quito porque no se usa OneDrive en este proyecto.)
$carpetaSenal = $destino
$txt = Join-Path $origen "senal.txt"
if (Test-Path $txt) {
    $d = (Get-Content $txt -Raw).Trim()
    if ($d) { $carpetaSenal = $d }
}
$senal = Join-Path $carpetaSenal "motor_activo.json"
$otro = $null
if (Test-Path $senal) {
    try {
        $d = Get-Content $senal -Raw | ConvertFrom-Json
        $edad = ((Get-Date) - [datetime]$d.ultima_senal).TotalMinutes
        if ($d.equipo -ne $env:COMPUTERNAME -and $edad -le 15) { $otro = $d }
    } catch {}
}
if ($otro) {
    Write-Host ""
    Write-Host "  !! ATENCION: el monitor YA esta corriendo en otro equipo:" -ForegroundColor Yellow
    Write-Host ("     Equipo : " + $otro.equipo)
    Write-Host ("     IP     : " + $otro.ip)
    Write-Host ("     Usuario: " + $otro.usuario)
    Write-Host ""
    Write-Host "  Debe vigilar UN SOLO equipo: si corren dos se DUPLICAN los avisos" -ForegroundColor Yellow
    Write-Host "  y cada uno compara contra su propio historico." -ForegroundColor Yellow
    Write-Host ""
    $r = Read-Host "  Instalar igualmente pero SIN activar la vigilancia diaria? (S/N)"
    if ($r -notmatch '^[SsYy]') { Write-Host "  Instalacion cancelada."; Read-Host "  Pulsa Enter"; exit 1 }
    $script:sinTarea = $true
} else {
    Write-Host "  No hay otro equipo vigilando. Adelante."
    $script:sinTarea = $false
}

# ---------- 2) copiar ficheros ----------
Titulo "Copiando el programa a $destino"
Get-Process AvisMonitorOneways -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
New-Item -ItemType Directory -Force $destino | Out-Null
Copy-Item (Join-Path $origen "AvisMonitorOneways.exe") $destino -Force
if (Test-Path (Join-Path $origen "LEEME.txt")) { Copy-Item (Join-Path $origen "LEEME.txt") $destino -Force }
if (Test-Path (Join-Path $origen "ms-playwright")) {
    Write-Host "  Copiando el navegador incluido (tarda un poco)..."
    # OJO: si la carpeta destino ya existe, Copy-Item -Recurse la ANIDA dentro
    # en vez de reemplazarla (queda ms-playwright\ms-playwright y el navegador
    # viejo). Hay que borrarla antes.
    $mpDest = Join-Path $destino "ms-playwright"
    if (Test-Path $mpDest) { [System.IO.Directory]::Delete($mpDest, $true) }
    Copy-Item (Join-Path $origen "ms-playwright") $mpDest -Recurse -Force
} elseif (Test-Path (Join-Path $env:LOCALAPPDATA "ms-playwright")) {
    Write-Host "  Uso el navegador ya instalado en este equipo."
} else {
    Write-Host "  !! No hay navegador (ms-playwright). El programa no podra descargar." -ForegroundColor Yellow
}
Write-Host "  Ficheros copiados."

# ---------- 3) accesos directos ----------
Titulo "Creando accesos directos"
$ws = New-Object -ComObject WScript.Shell
foreach ($sitio in @([Environment]::GetFolderPath("Desktop"),
                     (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnk = $ws.CreateShortcut((Join-Path $sitio "AVIS Monitor de Oneways.lnk"))
    $lnk.TargetPath = Join-Path $destino "AvisMonitorOneways.exe"
    $lnk.WorkingDirectory = $destino
    $lnk.Description = "Vigilancia de oneways de Rentway"
    $lnk.Save()
}
Write-Host "  Acceso directo en el Escritorio y en el menu Inicio."

# ---------- 3b) escucha de comandos de Telegram ----------
Titulo "Escucha de comandos de Telegram"
if ($script:sinTarea) {
    Write-Host "  OMITIDA: debe escuchar UN SOLO equipo (Telegram solo entrega" -ForegroundColor Yellow
    Write-Host "  los comandos a un proceso; con dos, ninguno los recibe)." -ForegroundColor Yellow
} else {
    # Proceso residente que atiende /revisar, /estado y /lista. Va en la carpeta
    # de Inicio (no en una tarea programada) porque tiene que estar SIEMPRE
    # escuchando, no despertarse cada 2 horas.
    $inicio = [Environment]::GetFolderPath("Startup")
    $lnk = $ws.CreateShortcut((Join-Path $inicio "AVIS Monitor - escucha Telegram.lnk"))
    $lnk.TargetPath = Join-Path $destino "AvisMonitorOneways.exe"
    $lnk.Arguments = "--escucha"
    $lnk.WorkingDirectory = $destino
    $lnk.Description = "Atiende los comandos de Telegram (/revisar, /estado)"
    $lnk.Save()
    Write-Host "  Arrancara sola al iniciar sesion."
    Start-Process (Join-Path $destino "AvisMonitorOneways.exe") -ArgumentList "--escucha"
    Write-Host "  Arrancada ahora tambien. Prueba a escribir /estado en el grupo."
}

# ---------- 4) tarea programada diaria ----------
Titulo "Programando la vigilancia diaria"
if ($script:sinTarea) {
    Write-Host "  OMITIDA a peticion tuya (ya vigila otro equipo)." -ForegroundColor Yellow
} else {
    $previo = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    cmd /c "schtasks /Delete /TN ""$tarea"" /F" > $null 2>&1
    $exe = Join-Path $destino "AvisMonitorOneways.exe"

    # Se registra con Register-ScheduledTask (NO con 'schtasks /Create'):
    #   - 'schtasks /Create' simple no permite tocar los ajustes que importan en
    #     un portatil, y luego 'Set-ScheduledTask' da ACCESO DENEGADO sobre
    #     tareas de la raiz; registrarla por XML tambien da acceso denegado.
    #   - Register-ScheduledTask SI funciona como usuario normal y deja poner:
    #       repeticion CADA 2 HORAS, funcionar a bateria, recuperar la pasada
    #       perdida si el equipo estaba apagado, y despertar el equipo.
    $codigo = 1
    try {
        $accion = New-ScheduledTaskAction -Execute $exe `
            -Argument "--desatendido --dias 7" -WorkingDirectory $destino
        # 12 disparadores diarios, uno cada 2 h. NO se usa "repeticion" porque
        # Windows despierta el equipo para un DISPARADOR pero no para las
        # repeticiones de ese disparador: con repeticion solo corria 1-2 veces
        # al dia en un portatil que se suspende.
        $disp = @()
        foreach ($h in 0,2,4,6,8,10,12,14,16,18,20,22) {
            $disp += New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours($h))
        }
        # Ademas, AL INICIAR SESION: tras un reinicio o un corte de luz no se
        # espera a la siguiente hora par, se revisa enseguida. Y de paso la
        # pasada levanta la escucha si no estuviera corriendo.
        $disp += New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        $ajustes = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -WakeToRun `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
            -MultipleInstances IgnoreNew
        $princ = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $tarea -Action $accion -Trigger $disp `
            -Settings $ajustes -Principal $princ -Force | Out-Null
        $codigo = 0
    } catch {
        Write-Host ("  detalle: " + $_.Exception.Message) -ForegroundColor DarkGray
    }
    $ErrorActionPreference = $previo
    if ($codigo -eq 0) {
        Write-Host "  Programada CADA 2 HORAS (a partir de las 08:00)."
        Write-Host "  Funciona a bateria, recupera la pasada si el equipo estaba"
        Write-Host "  apagado, y se ejecuta sin abrir ventanas."
    } else {
        Write-Host "  !! No pude crear la tarea programada." -ForegroundColor Yellow
    }
}

# ---------- 4b) equipo dedicado: que no se duerma ----------
Titulo "Suspension del equipo"
Write-Host "  AUDITORIA DEL 10/08/2026: en un portatil normal esto NO funciona bien."
Write-Host "  Windows lo suspende y NO lo despierta para la tarea: de 32 revisiones"
Write-Host "  previstas en un fin de semana solo se ejecutaron 9, y todas de"
Write-Host "  madrugada (cuando Windows despierta solo para su mantenimiento)."
Write-Host ""
Write-Host "  Si este va a ser un EQUIPO DEDICADO a vigilar, hay que quitarle la"
Write-Host "  suspension mientras este enchufado. La bateria NO se toca, asi que"
Write-Host "  si se desenchufa sigue ahorrando." -ForegroundColor Yellow
Write-Host ""
$r = Read-Host "  Es un equipo dedicado? Quitar la suspension con enchufe? (S/N)"
if ($r -match '^[SsYy]') {
    $previo = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    # NO necesita admin (comprobado). El valor va en MINUTOS; 0 = nunca.
    powercfg /change standby-timeout-ac 0   | Out-Null
    powercfg /change hibernate-timeout-ac 0 | Out-Null
    powercfg /change monitor-timeout-ac 10  | Out-Null   # la pantalla si puede apagarse
    $ErrorActionPreference = $previo
    # marca para que el programa VUELVA a quitar la suspension en cada pasada si
    # una directiva de empresa la repone (el equipo esta gestionado con Puppet)
    Set-Content -Path (Join-Path $destino "equipo_dedicado.txt") `
                -Value "Equipo dedicado a la vigilancia. No debe suspenderse con enchufe." `
                -Encoding UTF8
    $v = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE | Select-String "alterna").Line
    Write-Host "  Hecho. Suspension con enchufe desactivada." -ForegroundColor Green
    Write-Host "  ($($v.Trim()))  -> 0x0 significa 'nunca'"
    Write-Host "  Ademas, el programa lo revisara en CADA pasada y lo volvera a"
    Write-Host "  quitar si una directiva de empresa lo repone."
    Write-Host ""
    Write-Host "  QUEDA UNA COSA QUE NO PUEDO HACER YO:" -ForegroundColor Yellow
    Write-Host "  configura el INICIO DE SESION AUTOMATICO en este equipo. La tarea"
    Write-Host "  necesita la sesion abierta; con la pantalla bloqueada funciona, pero"
    Write-Host "  si hay un corte de luz y nadie escribe la contrasena, se para todo."
} else {
    Write-Host "  No se toca la energia. OJO: si el equipo se suspende, las revisiones"
    Write-Host "  se perderan y los comandos de Telegram no responderan." -ForegroundColor Yellow
}

# ---------- 5) fin ----------
Titulo "Instalacion terminada"
Write-Host ""
Write-Host "  QUEDA UN PASO, y hay que hacerlo a mano:" -ForegroundColor Yellow
Write-Host "   1. Abre 'AVIS Monitor de Oneways' desde el Escritorio."
Write-Host "   2. Escribe tu usuario y contrasena de Rentway y pulsa"
Write-Host "      'Guardar credenciales'."
Write-Host ""
Write-Host "  Sin ese paso la tarea diaria fallara en cuanto caduque la sesion"
Write-Host "  (se ha comprobado que caduca en pocos dias)."
Write-Host ""
Write-Host "  La contrasena se guarda cifrada con DPAPI de Windows: queda atada"
Write-Host "  a este equipo y a este usuario, no sirve en otro ordenador."
Write-Host ""
$abrir = Read-Host "  Abrir el programa ahora para configurarlo? (S/N)"
if ($abrir -match '^[SsYy]') { Start-Process (Join-Path $destino "AvisMonitorOneways.exe") }
Read-Host "  Pulsa Enter para cerrar"

