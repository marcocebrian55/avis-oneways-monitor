# AVIS — Monitor de Oneways

Vigila los **oneways** de Rentway (AVIS Canarias): reservas y contratos que se
**entregan y devuelven en oficinas distintas**. Descarga los informes de Rentway,
detecta los oneways, los compara con la pasada anterior y **avisa de todo cambio**
por Telegram y correo.

Corre desatendido en un equipo Windows: una tarea programada lanza una pasada
cada 2 horas y un proceso de escucha atiende comandos de Telegram (`/revisar`).

> **Este repositorio no contiene ninguna credencial.** Las claves de Rentway, el
> token del bot y la contraseña del correo se introducen al instalar y se guardan
> **cifradas con DPAPI** en el propio equipo. Ver [Configuración](#configuración).

---

## Instalar (uso normal)

Para dejarlo vigilando en un equipo Windows. **No hace falta Python, ni instalar
nada como administrador.**

**1. Descarga la última versión**

Ve a **[Releases](../../releases/latest)** y baja `AvisMonitorOneways.zip`. Trae
dentro el `.exe`, el navegador (`ms-playwright`) y los scripts de instalación.

**2. Descomprime y ejecuta `INSTALAR.bat`**

> Descomprime la carpeta **entera** antes de ejecutarlo: el `.bat` necesita los
> ficheros que tiene al lado. Y ejecútalo con doble clic normal, **sin** «ejecutar
> como administrador».

Instala en `%LOCALAPPDATA%\AvisMonitorOneways`, crea los accesos directos, deja la
tarea programada (12 pasadas al día) y arranca la escucha de Telegram.

**3. Mete las credenciales**

Abre *AVIS Monitor de Oneways* → botón **⚙ Configuración** y rellena Rentway,
Telegram y, si lo quieres, el correo. Se guardan cifradas y no hay que repetirlo.

**4. Comprueba que vive**

Escribe **`/estado`** en el grupo de Telegram. Si contesta, está funcionando.
`/revisar` fuerza una pasada en el momento.

### Actualizar — **a mano**

Baja el `.zip` de la última release y vuelve a ejecutar `INSTALAR.bat`. La
configuración y el historial **no se tocan**: viven fuera de la carpeta del
programa, en `%LOCALAPPDATA%\AvisMonitorOneways`.

> **La auto-actualización está implementada pero hoy NO funciona, porque este
> repositorio es privado.** `actualizacion.py` descarga con `urllib` sin
> credenciales, y las URLs de assets de un repo privado responden **404 si no
> vas autenticado** (comprobado: 404 anónimo, 200 con token). Los equipos
> instalados no se enterarían de que hay versión nueva.
>
> Para activarla habría que hacer el repositorio público, o darle al
> actualizador un token de solo lectura. Mientras tanto **no pongas un
> `actualizacion.txt` apuntando a GitHub**: no haría nada. Sin ese fichero, el
> programa sencillamente no busca actualizaciones, que es lo que queremos ahora.

---

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
- **Solo se avisa si hay cambios.** Además, un **parte diario** ✅ en la primera
  pasada correcta de cada jornada, para que el silencio no sea ambiguo, y un
  aviso ⚠️ si una pasada falla (con 6 h de cooldown).

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
- **El puerto SMTP 587 no funciona en la red de AVIS**: empieza en claro y el
  cortafuegos lo corta. **El 465 sí** (cifrado desde el primer byte).
- **`powercfg /query` informa en segundos, `powercfg /change` espera minutos.**
- **`Copy-Item -Recurse` anida** si el destino ya existe: borra el destino antes.
- **`Set-ScheduledTask` y `schtasks /Create /XML` dan acceso denegado** en tareas de
  la raíz. Lo que funciona sin admin es `Register-ScheduledTask` de PowerShell.

## Limitación conocida

Hace falta una **sesión de Windows abierta**. Tras un reinicio o un corte de luz,
alguien tiene que iniciar sesión una vez: el auto-logon requiere escribir en `HKLM`
y `-LogonType S4U` da acceso denegado. La señal de que ha pasado es la **ausencia
del parte diario**.

## Nota sobre la carpeta de entrega

`AVIS_Monitor_Oneways_PARA_OTRO_PORTATIL` es un **artefacto de compilación** (429 MB
con el `.exe` y `ms-playwright`), no fuente. Los scripts de instalación que sí son
fuente viven aquí en `instalador/`; al preparar una entrega se copian allí.
