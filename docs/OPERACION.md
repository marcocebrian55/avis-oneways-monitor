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

## El panel web

**https://oneways-avis.tail0a2ef7.ts.net** — desde el móvil o cualquier equipo
**que esté en la red de Tailscale**. Sin puerto y con candado: certificado real
de Let's Encrypt, emitido por Tailscale.

Tiene tres pestañas: **Estado** (oneways activos con las mismas columnas que la
ventana del `.exe`, cambios de la última revisión y un botón para forzar una),
**Registro** (las últimas 300 líneas del log) y **Ajustes** (editar los
destinatarios del correo y mandar un correo de prueba).

### Por qué no pide contraseña

El panel escucha **sólo en `127.0.0.1`** — ni siquiera en la interfaz de
Tailscale. La única puerta es `tailscale serve`, que sólo atiende a miembros
del tailnet. Quien llega ahí ya ha demostrado ante Tailscale quién es, así que
montarle encima un login propio sería poner una cerradura peor que la que ya
hay.

Comprobado el 24/08/2026: por la IP pública no responde **nada**, ni en el 8000
ni en el 443.

> **No cambies el `--host 127.0.0.1`** de
> `/etc/systemd/system/oneways-panel.service`. Si alguien lo pone en `0.0.0.0`
> y abre el puerto en ufw, el panel queda expuesto al mundo y con él las
> credenciales de Rentway.

**Para que alguien entre**, tiene que instalar Tailscale en su móvil o PC e
iniciar sesión en el tailnet (cuenta `mcebrian@domingoalonsogroup.com`). No hay
otra vía, y ése es el trato: se cambia comodidad por no tener nada abierto.

```bash
systemctl status oneways-panel.service    # el panel
tailscale serve status                    # la puerta HTTPS
```

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
- **Correo**: 27 destinatarios de las cuatro islas. La mayoría **no está en
  Telegram**, y por eso el correo dejó de mandar sólo los oneways nuevos.

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

## Copias de seguridad

Hetzner hace backups del disco entero (activados). Lo irreemplazable cabe en
una carpeta:

```bash
tar czf ~/oneways-respaldo-$(date +%F).tgz -C /var/lib oneways
```

Ahí van las credenciales, los snapshots y las marcas de estado.
