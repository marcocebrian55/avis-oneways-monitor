# AVIS — Monitor de Oneways

Vigila los **oneways** de Rentway (AVIS Canarias): reservas y contratos que se
**entregan y devuelven en oficinas distintas**. Descarga los informes de Rentway,
detecta los oneways, los compara con la pasada anterior y **avisa de todo cambio**
por Telegram y correo.

**Corre en un servidor Linux, 24 horas.** Un temporizador de systemd lanza una
pasada cada 2 horas y un servicio de escucha atiende los comandos de Telegram.

> **Para operarlo — entrar, cambiar la configuración, añadir destinatarios,
> diagnosticar — está todo en [`docs/OPERACION.md`](docs/OPERACION.md).**
> Esta página explica qué hace y cómo está construido; ésa, cómo se toca.

> **Este repositorio no contiene ninguna credencial.** Las claves de Rentway, el
> token del bot y la del correo viven en `/var/lib/oneways/configuracion.json`
> **en el servidor**, con permisos 600 y fuera de git.

---

## Dónde corre

| | |
|---|---|
| Servidor | Hetzner `oneways-avis` (Falkenstein), Ubuntu 24.04, 2 vCPU / 4 GB |
| Código | `/opt/oneways/repo`, rama `main` |
| Estado | `/var/lib/oneways` — **separado del clon de git** (`ONEWAYS_DATOS`) |
| Servicios | `oneways-pasada.timer` (horas pares + 07:00) · `oneways-escucha.service` · `oneways-panel.service` |

En producción desde el **24/08/2026**. Los 6 informes tardan **~75 s**.

### Historia: por qué dejó de correr en un portátil

Vigiló desde un portátil Windows entre julio y agosto de 2026, y el problema
nunca fue el código: era el equipo. Un fin de semana debía dar 32 pasadas y dio
9, porque Windows lo suspendía a media pasada — Modern Standby, temporizadores
de reactivación capados por directiva, y el proceso **muerto desde fuera** con
`0xE0000027` sin dejar ni un evento. Se pelearon power requests, 12
disparadores explícitos y un auto-reparador de la política de energía. Un
servidor lo resuelve por no tener el problema.

Todo aquello **sigue en el código**, inerte tras `ES_WINDOWS`, y la ventana
Tkinter también: se puede seguir abriendo la app en Windows para mirar. Lo que
no debe volver es su **escucha de Telegram** — dos escuchas a la vez dan error
409 y ninguna recibe nada.

## Cómo funciona

```
Rentway (web)  --Playwright-->  6 informes .xlsx  -->  deteccion de oneways
                                                            |
                              snapshot_YYYY-MM-DD_HHMM.json  |  comparar con
                                          ^                  |  la pasada anterior
                                          +------------------+
                                                            |
                                                     cambios --> Telegram + correo
```

- **Entrada:** 6 informes de Rentway. Los 2 base son `Lista de reservas` (2126) y
  `Abiertos` (2094); los 4 ampliados añaden observaciones, anulados y contactos.
  En todos, **la cabecera está en la fila 5**.
- **Un oneway es** una reserva o contrato con `estación de salida != estación de devolución`.
- **Snapshot por pasada**, no por día: con 12 pasadas diarias, uno por día se
  pisaba a sí mismo y no se veía ningún cambio intradía.
- **Solo se avisa si hay cambios.** Además, un **parte diario** ✅ a las 07:00,
  cuando abren las oficinas, para que el silencio no sea ambiguo, y un aviso ⚠️
  si una pasada falla (con 6 h de cooldown).

## Los módulos

| Fichero | Qué hace |
|---|---|
| `src/avis_monitor.py` | GUI Tkinter + motor. `ejecutar_pasada()` es el corazón; `modo_desatendido()` y `modo_escucha()` son las dos formas de arrancarlo. |
| `src/rentway_export.py` | Playwright: login, navegación a los informes y descarga de los 6 `.xlsx`. |
| `src/avisos.py` | Telegram por HTTP con `urllib` (sin dependencias nuevas). |
| `src/escucha.py` | Long polling de `getUpdates`: comandos `/revisar`, `/estado`, `/lista`, `/ayuda`. |
| `src/correo.py` | SMTP con `smtplib`. **Puerto 465**, ver más abajo. |
| `src/credenciales.py` | Cifrado con **DPAPI** (`CryptProtectData`), atado a equipo+usuario. |
| `src/instancia.py` | Instancia única: señal entre equipos + candado local `pasada_en_curso.lock`. |
| `src/actualizacion.py` | Auto-actualización por manifiesto `version.json` con verificación sha256. |
| `src/oneway_monitor.py` | Motor suelto original (sin GUI), de la Fase 1. |
| `instalador/` | Instalación sin admin, tarea programada, escucha en Inicio y script de reparación. |

> **Que vigile un solo equipo a la vez.** Telegram entrega cada comando a una
> sola escucha, y dos activas a la vez dan error 409 y ninguna recibe nada. Si
> montas un equipo nuevo, quita antes la tarea y la escucha del anterior con
> `instalador\desinstalar.bat`.

## Desarrollo

```bash
git clone https://github.com/<usuario>/<repo>.git
cd <repo>
pip install openpyxl playwright
python -m playwright install chromium

python src/avis_monitor.py                 # ventana
python src/avis_monitor.py --desatendido   # una pasada sin ventana
python src/avis_monitor.py --escucha       # solo escuchar Telegram
```

La primera vez hay que dar las credenciales: o en el botón **⚙ Configuración**, o
copiando `configuracion.ejemplo.json` a `configuracion.json` y rellenándolo (ese
nombre está en `.gitignore`, así que no se sube por accidente).

Argumentos: `--dias N` (ventana de previsión, por defecto 7), `--sin-ampliados`
(solo los 2 informes base, ~50 s en vez de ~2 min 25 s).

## Compilar

```
pyinstaller --onefile --windowed --icon assets/avis.ico ^
            --add-data "<ruta absoluta>/assets;assets" ^
            --collect-all playwright --hidden-import rentway_export --paths src ^
            src/avis_monitor.py
```

- Las rutas de `--add-data` se resuelven contra el `--specpath`, **no** contra el
  directorio actual: usa rutas absolutas.
- PyInstaller **devuelve código 0 aunque falle** por eso. Comprueba que el `.exe`
  existe de verdad antes de publicar.
- **Sube `VERSION` en el código ANTES de compilar y publicar.** Si el binario dice
  1.1.0 y publicas 1.2.0, todos los equipos se actualizan en bucle cada pasada.
- El navegador que hay que empaquetar es **`chromium-1223`** (el que espera este
  `playwright`), no el que use otra herramienta del equipo.
- Genera el `.zip` **con Python** (`zipfile`), no con `Compress-Archive`: ver
  «Trampas».

## Publicar una versión nueva

1. Sube `VERSION` en `src/avis_monitor.py`.
2. Compila y comprueba que el `.exe` existe.
3. Arma el `.zip` con `.exe` + `ms-playwright` + `instalador/` + `docs/`.
4. Crea la release y sube **dos** ficheros: el `.zip` y el `version.json`
   (`PUBLICAR_VERSION.ps1` calcula el sha256 y escribe el manifiesto).

```powershell
gh release create v2.2.0 AvisMonitorOneways.zip version.json --title "v2.2.0" --notes "..."
```

El `version.json` se publica igualmente para tenerlo listo, pero **hoy no lo
consume nadie**: con el repositorio en privado la descarga anónima da 404 (ver
[Actualizar](#actualizar--a-mano)). Avisa por Telegram de que hay versión nueva y
que toca reinstalar.

Si algún día se activa la auto-actualización: el manifiesto lleva `sha256` y **si
no cuadra, el paquete se descarta**, así que no publiques el `version.json` antes
que el binario.

## Configuración

Se rellena desde el diálogo **⚙ Configuración** de la app, que la guarda
**cifrada con DPAPI** junto al ejecutable (`*.dat`). Como alternativa para
automatizar, copia `configuracion.ejemplo.json` a `configuracion.json`: al
arrancar se vuelca al almacén cifrado y luego puedes borrarlo.

- Usuario y contraseña de Rentway.
- Token del bot de Telegram y chat de destino. *El guion inicial del id de grupo
  forma parte del id, no lo quites.*
- SMTP: servidor, **puerto 465**, usuario, contraseña de aplicación, remitente y
  destinatarios.

**Qué se avisa y por dónde:** por Telegram, todo cambio (altas, bajas y
modificaciones) más el parte diario ✅ y los fallos ⚠️. Por correo, **solo los
oneways nuevos**, que son los que obligan a mover un coche.

> `configuracion.json` y los `*.dat` están en `.gitignore`. Los `.dat` además no
> son transferibles: DPAPI los ata al equipo y usuario que los creó.

Ficheros opcionales que se ponen al lado del `.exe`: `actualizacion.txt` (canal de
actualizaciones), `senal.txt` (carpeta compartida para la señal entre equipos),
`chats_autorizados.txt` (chats extra que pueden dar órdenes),
`equipo_dedicado.txt` (permite tocar la política de energía). Se leen con
**`utf-8-sig`**: el Bloc de notas les mete un BOM invisible.

## Trampas ya resueltas — no repetir

- **La sesión zombi de Rentway.** La sesión se queda válida para `/dashboard` pero
  no para `/reports`, y Rentway sirve su propia página `/error` en vez de mandarte
  al login. Recargar **no** lo arregla (medido: 8 veces seguidas). Lo único que
  funciona es volver a iniciar sesión. No basta con detectar «me pide login»: hay
  que detectar **«no estoy donde debería estar»**.
- **Headless necesita `channel="chromium"`.** Sin eso Playwright busca
  `chrome-headless-shell`, un binario aparte de 267 MB.
- **`SetThreadExecutionState` se ignora con Modern Standby.** Hay que usar
  **power requests**: `PowerCreateRequest` + `PowerSetRequest` con
  `PowerRequestExecutionRequired`, que es lo único que impide que el sistema
  suspenda o **mate** el proceso (moría con `0xE0000027`, sin ejecutar el `finally`).
- **Windows no despierta el equipo para las repeticiones de un disparador**, solo
  para el disparador en sí: por eso hay **12 disparadores diarios explícitos**.
- **La instalación no puede pedir admin.** Nada de `.exe` autoextraíble: un `7z.sfx`
  sin manifiesto activa la detección de instaladores de Windows y eleva. Se entrega
  una carpeta con un `.bat`, que nunca eleva.
- **Un `.ps1` que viaja por Drive o zip llega bloqueado** por la directiva de la
  empresa, incluso con `-ExecutionPolicy Bypass`. Solución: `.bat` con el script
  embebido en `-EncodedCommand`. Ojo al límite de **8191 caracteres por línea**.
- **`Compress-Archive` escribe las rutas internas con barra invertida** y algunos
  descompresores dejan los ficheros sueltos. Genera el zip con Python (`zipfile`).
- **Los puertos SMTP están al revés en cada sitio.** En la red de AVIS el 587
  empieza en claro y el cortafuegos lo corta: allí hay que usar el **465**. En
  Hetzner el **465 y el 25 están bloqueados de salida** y el que pasa es el
  **587**. Al mover el sistema, revisa esto antes que nada.
- **Rentway sirve la interfaz en el idioma que pide el navegador**, y el código
  busca los elementos por su texto en español. En Windows funcionaba de
  casualidad (Chromium heredaba el español del sistema); en Ubuntu arranca en
  `en-US` y salía `aria-label='Username'`, así que no encontraba ni el login ni
  «Generar informe». Se fija `locale="es-ES"`. **El síntoma no mencionaba el
  idioma**: hablaba de credenciales inválidas.
- **El perfil del navegador guarda el idioma.** Después de arreglar el locale
  seguía fallando porque el perfil se había creado en inglés. Si tocas el
  idioma, **borra la carpeta del perfil**.
- **`powercfg /query` informa en segundos, `powercfg /change` espera minutos.**
- **`Copy-Item -Recurse` anida** si el destino ya existe: borra el destino antes.
- **`Set-ScheduledTask` y `schtasks /Create /XML` dan acceso denegado** en tareas de
  la raíz. Lo que funciona sin admin es `Register-ScheduledTask` de PowerShell.

## Limitación conocida — resuelta al mover a servidor

Mientras corrió en Windows hacía falta una **sesión abierta**: tras un reinicio
alguien tenía que iniciar sesión a mano, porque el auto-logon exige escribir en
`HKLM` y `-LogonType S4U` daba acceso denegado. En el servidor no aplica —
systemd arranca los servicios al encender, y está **probado con un reinicio
completo**.

## Nota sobre la carpeta de entrega

`AVIS_Monitor_Oneways_PARA_OTRO_PORTATIL` es un **artefacto de compilación** (429 MB
con el `.exe` y `ms-playwright`), no fuente. Los scripts de instalación que sí son
fuente viven aquí en `instalador/`; al preparar una entrega se copian allí.
