# Operar el Monitor de Oneways

Todo lo que hace falta para tocar el sistema en producción. Si sólo vas a leer
una página de este repositorio, que sea ésta.

## Dónde está todo

| | |
|---|---|
| Servidor | Hetzner `oneways-avis`, Falkenstein — **91.99.185.207** |
| Entrar | `ssh -i ~/.ssh/id_ed25519_oneways root@91.99.185.207` |
| Código | `/opt/oneways/repo` (rama `main`, deploy key de solo lectura) |
| Python | `/opt/oneways/venv` |
| **Estado y configuración** | **`/var/lib/oneways`** |
| Log | `/var/lib/oneways/avis_oneways.log` |
| Informes descargados | `/home/oneways/Downloads` |

> La clave SSH privada está **sólo en el portátil de Marco**
> (`~/.ssh/id_ed25519_oneways`). Si se pierde, hay que añadir otra clave desde
> la consola de Hetzner (Rescue/Console), no hay otra puerta.

## La regla de oro

**El código se cambia en el repositorio. La configuración, en el servidor.**

El servidor consume el repo, nunca es la fuente. Un fichero editado a mano en
`/opt/oneways/repo` lo borra el siguiente `git pull` y nadie sabrá por qué
estaba así.

```
CÓDIGO          editar → commit → push a main → git pull en el servidor → reiniciar
CONFIGURACIÓN   editar /var/lib/oneways/configuracion.json → se relee sola
```

## Cambiar el código

```bash
# en el servidor
sudo -u oneways bash -c "cd /opt/oneways/repo && git pull"
systemctl restart oneways-escucha.service
```

La pasada no hace falta reiniciarla: cada una arranca un proceso nuevo y ya
coge el código nuevo.

**Antes de subir nada, las pruebas** (en `/tmp`, sin tocar el repo del servidor,
o en cualquier equipo con Python y openpyxl):

```bash
python -m unittest discover -s tests -v
```

Cada prueba es un aviso equivocado que ya llegó a las oficinas alguna vez.

**Si el cambio amplía lo que se ve** (más oneways, una clave distinta), la
primera pasada tras el `git pull` avisaría de golpe como "nuevos" de oneways
que no lo son. Esa primera pasada se hace **sin avisos**: guarda la foto de
referencia y sólo escribe en el log lo que habría mandado.

```bash
sudo -u oneways ONEWAYS_DATOS=/var/lib/oneways /opt/oneways/venv/bin/python \
  /opt/oneways/repo/src/avis_monitor.py --desatendido --sin-avisos
```

Hazlo justo después de una pasada normal, para que no se cuele otra en medio.

## Cambiar la configuración

```bash
nano /var/lib/oneways/configuracion.json
```

Lleva usuario y clave de Rentway, token y chat de Telegram, y el SMTP con la
lista de destinatarios. **No hay que reiniciar nada**: el fichero queda más
nuevo que los `.dat` y el programa lo reimporta solo al arrancar la siguiente
pasada. Se puede comprobar en el acto:

```bash
sudo -u oneways ONEWAYS_DATOS=/var/lib/oneways /opt/oneways/venv/bin/python \
  /opt/oneways/repo/src/avis_monitor.py --probar-correo tu@correo.com
```

`--probar-correo` sin dirección manda a **toda** la lista; con una dirección
detrás, sólo a ésa. Úsalo siempre que añadas gente: es la única forma de saber
que una dirección no rebota sin esperar a que aparezca un oneway.

## Comprobar que está vivo

```bash
systemctl status oneways-escucha.service     # la escucha de Telegram
systemctl list-timers 'oneways-*'            # cuándo fue y cuándo será
tail -40 /var/lib/oneways/avis_oneways.log
```

Desde fuera, sin entrar al servidor: escribe **`/estado`** en el grupo de
Telegram. Si contesta, la escucha vive. Ojo, eso **no** prueba que el
temporizador exista: para eso mira la línea *"Última revisión"*.

Y todas las mañanas, **entre las 07:00 y las 07:02**, debe llegar el **parte
diario ✅**. Si no llega, algo pasa.

> **El parte y la hora, ojo si lo tocas.** Se manda en la primera pasada
> correcta del día a partir de `HORA_PARTE` (`avis_monitor.py`, hoy las 7).
> Como las pasadas van a horas **pares**, una hora impar ahí no adelanta nada
> por sí sola: las 07:00 funcionan porque el temporizador tiene un disparador
> **explícito** a esa hora, puesto para que el parte llegue cuando abren las
> oficinas. Si cambias una cosa, cambia la otra.

## Forzar una pasada

- Desde Telegram: **`/revisar`** (admite `/revisar 15` días).
- Desde el servidor: `systemctl start oneways-pasada.service`

## Cambiar cada cuánto pasa, o los días de previsión

Están en las unidades, no en el código:

```bash
nano /etc/systemd/system/oneways-pasada.timer     # OnCalendar (horas pares + 07:00)
nano /etc/systemd/system/oneways-pasada.service   # --dias N
systemctl daemon-reload
```

## Qué se avisa y por dónde

Desde el 24/08/2026 **los dos canales llevan lo mismo**: altas, bajas,
anulaciones y modificaciones.

- **Telegram** (grupo AVISOS ONEWAYS DAG): además, el parte diario ✅ y los
  fallos ⚠️ con 6 h de cooldown.
- **Correo**: los cambios, a la lista `destinatarios`. La mayoría **no está en
  Telegram**, y por eso el correo dejó de mandar sólo los oneways nuevos.

### Qué es un aviso y qué no (desde la v2.3.0, 17/09/2026)

| Pasa esto | Aviso |
|---|---|
| Aparece un oneway activo | 🆕 NUEVO |
| Aparece una reserva **ya anulada** | nada |
| Se anula o se elimina | ❌ ONEWAY ANULADO |
| El cliente recoge el coche (hay contrato) | 🚗 EN CURSO, **con matrícula** |
| Cambia grupo, oficinas, fechas o estado | ✏️ CAMBIO |
| Cambia la matrícula **antes** de la entrega | nada (es una pre-asignación) |
| Cambia la matrícula **con contrato** | ✏️ CAMBIO |
| El contrato pasa a devolver en la misma oficina | ❌ YA NO ES ONEWAY — misma oficina |
| Desaparece una reserva que sale hoy o después | ❌ YA NO ES ONEWAY |
| Se cierra el contrato (coche devuelto) | nada |
| La fecha de salida ya pasó y sale de la ventana | nada |
| Una anulada sale de la ventana | nada (ya se avisó) |

Lo que no se avisa queda en el log como `(sin aviso) ...`. Repasando las 321
fotos del 24/08 al 17/09/2026: 193 avisos con las reglas viejas, 120 con éstas.

**Grupo antes que matrícula.** Petición de las oficinas del 17/09/2026. Cada
aviso lleva el **grupo reservado** (`ID de grupo` del informe de reservas) con
su descripción (`src/grupos.json`, p.ej. `SC (Economic 4)`). La matrícula sólo
aparece cuando ya hay contrato; si el coche entregado es de otro grupo, se dice
(`coche de grupo SG`). Si aparece un grupo nuevo, el aviso sale con el código
solo; para añadir la descripción: `herramientas/mapa_grupos.py`.

### La hoja de Google (desde la v2.4.0)

Además de los avisos, cada pasada pone al día una hoja de Google en el Drive de
empresa: pestaña **Oneways** (futuros y en curso, por colores), **Completados**
(devueltos, anulados, sin recoger; 30 días) y **Alertas** (lo enviado; 30 días).
Petición de las oficinas del 17/09/2026; la ve solo quien Marco comparta.

La hoja **viene a buscar** los datos: cada pasada escribe
`/var/lib/oneways/publica/hoja_datos.json`, Tailscale Funnel sirve ese único
fichero por HTTPS en una ruta con token, y el Apps Script de la hoja lo descarga
cada 10 minutos. **Es lo único del servidor abierto a internet.** El workspace
del grupo no deja publicar aplicaciones web para fuera del dominio, por eso no
se empuja. Montaje, token y cómo cerrarlo: `hoja/LEEME.md`. Un fallo de la hoja
**nunca** para los avisos.

**Rentway cambia un informe de formato → aviso de error.** En cada pasada se
comprueba que están las columnas de las que vive el programa
(`COLUMNAS_ESPERADAS` en `avis_monitor.py`). Si falta alguna, llega un aviso a
`avisos_fallo` diciendo cuál.

> **Desde el 25/08/2026 la lista son las 28 direcciones de las cuatro islas.**
> Las 24 que estaban aparcadas en `_en_espera` se activaron ese día y se les
> mandó el correo de prueba. `_en_espera` quedó vacío; la copia previa está en
> `/var/lib/oneways/configuracion.json.bak-antes-de-activar-24`.
>
> Si algún día se vuelve a tocar la lista: `_en_espera` **no** manda correos, es
> solo un cajón. Para que una dirección reciba hay que ponerla en
> `destinatarios`, y después `--probar-correo` — es la única forma de saber que
> no rebota sin esperar a que aparezca un oneway.

Los avisos a las oficinas van en **Bcc**: en el `To:` sólo se ve el buzón
emisor (`aucc.rentway@`) y las 28 direcciones viajan ocultas. Con 28 personas en
el `To:` se ven todas entre sí y cualquiera puede darle a "Responder a todos" y
convertir un aviso automático en un hilo de 28. El `To:` al buzón emisor no es
adorno: un mensaje **sin** cabecera `To:` parece correo masivo y se lo comen los
filtros de spam. Lo hace `correo.enviar(..., oculto=True)`.

### El reparto por islas

Desde el 26/08/2026 cada oneway va **a sus dos islas**: la de la oficina que
suelta el coche y la de la que lo recibe. Pueden ser la misma —un `TFN→TFS` es
cosa de Tenerife y de nadie más—, porque oneway significa oficina distinta, no
isla distinta.

| | |
|---|---|
| `correo.destinatarios` | el grupo que lo recibe **todo** (9 personas) |
| `correo.por_isla` | Fuerteventura 4 · Lanzarote 4 · Gran Canaria 7 · Tenerife 7 · La Palma 2 |
| Mapa oficina→isla | `src/oficinas_islas.json`, 1915 oficinas |

Se agrupa **por persona, no por isla**. Quien cubre dos —`moalvarez@` lleva
Fuerteventura y Lanzarote— recibiría dos veces el mismo aviso justo en el caso
más común, un oneway que va de una a otra.

> **Un hueco tiene que hacer ruido, no silencio.** Una oficina que no esté en el
> mapa, o una isla sin lista (hoy **El Hierro** y **La Gomera**), manda ese
> oneway a **todo el mundo** y dispara un aviso a `avisos_fallo`. Nunca al revés:
> un correo de más se ve, un silencio no se nota hasta que alguien pregunta por
> un coche que no esperaba.

Sin `por_isla` configurado se comporta como siempre, todo a todos. Es el defecto
a propósito: nadie debe descubrir esta función porque un día dejaron de llegarle
avisos.

**Si cambia el catálogo de oficinas**, se regenera el mapa (Rentway >
Configuraciones empresariales > Operaciones > Oficina > exportar):

```bash
py -3 herramientas/mapa_islas.py oficinas.xlsx
```

### Los errores van aparte

Un fallo (⚠️) no se manda a las oficinas: va **sólo** a la dirección
`correo.avisos_fallo` de `configuracion.json` — hoy `mcebrian@aviscanarias.es`—
y al grupo de Telegram. Un timeout de Chromium no le sirve de nada a un
mostrador, y un aviso que no se puede accionar sólo enseña a ignorar los avisos.

Se avisa cuando la pasada entera revienta y cuando **falta el informe de
Abiertos**. Este segundo caso es el que motivó el correo: el 25/08/2026 se
colgó en cinco pasadas seguidas (00:00 a 07:00) y sólo quedó constancia en el
log. Ojo, cuando falta ese informe el programa **no** se queda sin datos de
contratos: `encontrar_excels()` coge el `open_*.xlsx` más reciente de
`Downloads`, que es el de una pasada anterior, así que compara contra datos
viejos sin que se note.

Sigue habiendo **6 h de cooldown** compartido entre los dos canales, y la marca
sólo se escribe si el aviso salió por alguno: si no, un corte de red silenciaría
los avisos justo cuando más falta hacen.

Sólo se avisa **si hay cambios**. Con 12 pasadas al día, avisar siempre sería
ruido.

## Trampas propias del servidor

- **SMTP: aquí funciona el 587 y están bloqueados el 465 y el 25.** Es justo al
  revés que en la red de AVIS, donde el cortafuegos cortaba el 587 y había que
  usar el 465. Si algún día se mueve el sistema, esto se revisa **primero**.
- **El navegador tiene que pedir la página en español.** Rentway sirve la
  interfaz en el idioma del navegador y el código busca los elementos por su
  texto en español. Ya está fijado (`locale="es-ES"`), pero si alguna vez
  vuelve a fallar el login con un timeout que habla de credenciales, mira el
  idioma antes que la contraseña.
- **Si tocas el idioma, borra el perfil**: `rm -rf /home/oneways/chrome-rentway-profile2`.
  El perfil guarda el idioma y la SPA sigue usando el viejo.
- **Una sola escucha en el mundo.** Telegram entrega cada comando a una sola;
  con dos, ninguna recibe nada (error 409). El portátil quedó desinstalado el
  24/08/2026 y no debe volver a arrancar su escucha.

## El resumen de la noche (TEMPORAL)

Todos los días a las **07:30** llega a `avisos_fallo` un correo con una tabla
pasada a pasada del día: en cuáles bajó el informe de Abiertos y en cuáles no.
Lo manda `oneways-resumen.timer` → `src/resumen_abiertos.py`.

Existe sólo para entender por qué ese informe se cuelga de madrugada. **Cuando
se sepa, se quita** — no debe quedarse ahí para siempre.

> **Causa encontrada el 17/09/2026** (captura de las 06:03): no se colgaba.
> El intervalo de Abiertos filtra por la **fecha de salida del contrato**, y se
> pedía desde hoy a las 00:00. De madrugada aún no hay contratos de hoy, Rentway
> saca un cuadro "Sin resultados" y la pasada esperaba 180 s dos veces a una
> página que no iba a llegar. Desde la v2.3.0 Abiertos se pide **desde 60 días
> atrás** (trae todos los contratos abiertos) y un "Sin resultados" se detecta
> en segundos. Queda comprobar una noche entera sin fallos y quitar el resumen:

```bash
systemctl disable --now oneways-resumen.timer
rm /etc/systemd/system/oneways-resumen.{timer,service}
systemctl daemon-reload
```

Se puede pedir el de cualquier día a mano:

```bash
sudo -u oneways ONEWAYS_DATOS=/var/lib/oneways /opt/oneways/venv/bin/python   /opt/oneways/repo/src/resumen_abiertos.py 2026-08-25
```

## Copias de seguridad

Hetzner hace backups del disco entero (activados). Lo irreemplazable cabe en
una carpeta:

```bash
tar czf ~/oneways-respaldo-$(date +%F).tgz -C /var/lib oneways
```

Ahí van las credenciales, los snapshots y las marcas de estado.
