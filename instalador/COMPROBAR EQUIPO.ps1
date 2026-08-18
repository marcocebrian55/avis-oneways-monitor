# ============================================================
#  AVIS - Monitor de Oneways :  COMPROBACION PREVIA
#  Ejecutar ESTO en el portatil nuevo ANTES de instalar.
#  Solo LEE, no cambia nada. No pide permisos de administrador.
# ============================================================
$ErrorActionPreference = "Continue"

function T($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function OK($t)   { Write-Host "  [OK]    $t" -ForegroundColor Green }
function MAL($t)  { Write-Host "  [MAL]   $t" -ForegroundColor Red }
function OJO($t)  { Write-Host "  [OJO]   $t" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  AVIS - MONITOR DE ONEWAYS" -ForegroundColor Red
Write-Host "  Comprobacion previa del equipo" -ForegroundColor Red

# ---------- quien soy ----------
T "Usuario y equipo"
Write-Host ("  Equipo  : " + $env:COMPUTERNAME)
Write-Host ("  Usuario : " + $env:USERDOMAIN + "\" + $env:USERNAME)
$cs = Get-CimInstance Win32_ComputerSystem
Write-Host ("  Dominio : " + $cs.Domain)

# ---------- LO MAS IMPORTANTE: quien inicia sesion solo ----------
T "Inicio de sesion automatico  (LO MAS IMPORTANTE)"
$w = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
try {
    $p = Get-ItemProperty $w -ErrorAction Stop
    if ($p.AutoAdminLogon -eq 1 -and $p.DefaultUserName) {
        Write-Host ("  Este equipo arranca solo con el usuario: " + $p.DefaultUserName)
        if ($p.DefaultUserName -eq $env:USERNAME) {
            OK "Es el MISMO usuario con el que estas ahora. Perfecto: instala aqui."
        } else {
            OJO ("Es OTRO usuario distinto del tuyo (" + $env:USERNAME + ").")
            Write-Host ""
            Write-Host "     Tras un reinicio, el equipo arranca con '$($p.DefaultUserName)'" -ForegroundColor Yellow
            Write-Host "     y TU sesion no existe, asi que el monitor NO arrancaria." -ForegroundColor Yellow
            Write-Host ""
            Write-Host "     QUE HACER: inicia sesion como '$($p.DefaultUserName)' e instala"  -ForegroundColor Yellow
            Write-Host "     el monitor AHI. Es la sesion que siempre va a existir."           -ForegroundColor Yellow
        }
    } else {
        MAL "NO hay inicio de sesion automatico configurado."
        Write-Host "     Tras un reinicio o corte de luz, el equipo se queda en la"
        Write-Host "     pantalla de contrasena y el monitor NO corre hasta que"
        Write-Host "     alguien entre a mano."
        Write-Host "     Activarlo necesita permisos de administrador: hay que pedirlo."
    }
} catch {
    OJO "No puedo leer la configuracion de inicio automatico."
}

# ---------- suspension ----------
T "Suspension del equipo"
$q = powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
$hex = [regex]::Matches($q, "0x[0-9a-fA-F]{8}")
if ($hex.Count -ge 2) {
    $seg = [Convert]::ToInt32($hex[$hex.Count-2].Value, 16)
    if ($seg -eq 0) { OK "Enchufado NO se suspende. Es lo que queremos." }
    else { OJO ("Enchufado se suspende a los " + ($seg/60) + " min. El instalador lo quitara si dices que es equipo dedicado.") }
}
$puedo = powercfg /change standby-timeout-ac ([int]($seg/60)) 2>&1
if ($LASTEXITCODE -eq 0) { OK "Puedo cambiar la energia sin ser administrador." }
else { MAL "NO puedo cambiar la energia. Habra que pedirlo a IT." }

T "Tipo de suspension del equipo"
$a = (powercfg /a) -join " "
if ($a -match "S0") { OJO "Tiene Modern Standby (S0). Por eso es CRITICO que no se suspenda." }
else { OK "Suspension clasica: se comporta mejor con las tareas programadas." }

# ---------- tareas programadas ----------
T "Puedo crear la tarea programada?"
try {
    $ac = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c exit"
    $tr = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(3))
    $pr = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName "ZZZ_PRUEBA_AVIS" -Action $ac -Trigger $tr -Principal $pr -Force -ErrorAction Stop | Out-Null
    OK "Si. La vigilancia cada 2 horas se podra programar."
    Unregister-ScheduledTask -TaskName "ZZZ_PRUEBA_AVIS" -Confirm:$false
} catch {
    MAL ("No puedo crear tareas programadas: " + $_.Exception.Message)
}

# ---------- red ----------
T "Acceso a lo que necesita"
foreach ($d in @(@("aviscanarias.jimpisoft.pt",443,"Rentway"),
                 @("api.telegram.org",443,"Telegram"),
                 @("smtp.gmail.com",465,"Correo (puerto 465)"),
                 @("smtp.gmail.com",587,"Correo (puerto 587)"))) {
    $r = Test-NetConnection -ComputerName $d[0] -Port $d[1] -WarningAction SilentlyContinue
    if ($r.TcpTestSucceeded) { OK ($d[2] + " alcanzable") } else { MAL ($d[2] + " NO alcanzable") }
}

T "Resumen"
Write-Host "  Lo que DE VERDAD decide si esto funciona:"
Write-Host "   1. Que el monitor se instale en la sesion que arranca sola."
Write-Host "   2. Que el equipo no se suspenda estando enchufado."
Write-Host "   3. Que se puedan crear tareas programadas."
Write-Host ""
Read-Host "  Pulsa Enter para cerrar"
