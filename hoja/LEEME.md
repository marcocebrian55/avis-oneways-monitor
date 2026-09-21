# Hoja de Google de los oneways

Una hoja de Google en el Drive de empresa con los oneways, puesta al día sola.
Pestañas:

- **Oneways**: futuros y en curso, por colores, lo urgente arriba.
- **Completados**: devueltos, anulados y sin recoger. Últimos 30 días.
- **Alertas**: cada aviso enviado a las oficinas. Últimos 30 días.

| Color | Estado |
|---|---|
| rojo | **Atrasado**: contrato abierto y la devolución ya pasó |
| naranja | **Se devuelve hoy** |
| amarillo | **Sale hoy** (aún sin contrato) |
| verde | **En curso**: coche entregado |
| azul | **Futuro** |
| gris | completado (pestaña Completados) |

**Columna REVISADO** (pestaña *Oneways*, a la derecha de Matrícula): casilla que
marcan a mano los responsables de flota. El servidor la manda siempre vacía y
es el script el que, antes de repintar, lee las casillas marcadas y las vuelve
a poner en su oneway (por nº de reserva, o de contrato si no hay reserva),
aunque la fila haya cambiado de sitio. Cuando el oneway pasa a *Completados*,
su marca se pierde con él. Para marcar hace falta permiso de **edición** en la
hoja.

## Cómo funciona

```
pasada (cada 2 h) ──> /var/lib/oneways/publica/hoja_datos.json
                                   │
                  Tailscale Funnel │ HTTPS, ruta con token
                                   ▼
Apps Script de la hoja, cada 10 min ──> repinta si ha cambiado
```

**La hoja va a buscar los datos, no se los mandamos.** Primero se intentó que el
servidor los enviara a una aplicación web de Apps Script, pero el Google
Workspace del grupo solo deja publicarlas para "cualquiera de domingoalonso" o
"solo yo", y el servidor no tiene cuenta de Google (17/09/2026).

- Estados, colores, orden y el historial de 30 días los decide
  `src/hoja.py`, que tiene pruebas. `Codigo.gs` solo descarga y pinta.
- La hoja va **como mucho 10 minutos** por detrás de cada pasada.
- Si una descarga falla, la fila 1 de *Oneways* se pone en rojo diciendo desde
  cuándo no hay datos nuevos, y los datos anteriores se quedan. La siguiente
  descarga buena lo trae todo.

## Lo único abierto a internet

Funnel sirve **un solo fichero** en una ruta con un token de 48 caracteres:

```
https://oneways-avis.tail0a2ef7.ts.net/<token>/oneways.json
```

El token es la `clave` de la sección `hoja` de
`/var/lib/oneways/configuracion.json`. No se sirve nada más del servidor: ni
carpetas, ni el log, ni la configuración.

```bash
tailscale funnel status          # que esta publicado
# abrirlo (lo ejecuta una persona, no un agente):
T=$(python3 -c "import json;print(json.load(open('/var/lib/oneways/configuracion.json'))['hoja']['clave'])")
tailscale funnel --bg --set-path /$T/oneways.json /var/lib/oneways/publica/hoja_datos.json
# cerrarlo:
tailscale funnel reset
```

**Si el token se filtra**, se cambia: nueva `clave` en la configuración,
`tailscale funnel reset`, volver a abrir con el token nuevo y cambiar
`URL_DATOS` en el script de la hoja.

## Montar la hoja (una vez, con la cuenta de empresa)

1. En Drive: **Nuevo → Hojas de cálculo de Google** (o usa una ya creada).
2. **Extensiones → Apps Script**. Borra lo que haya y pega `Codigo.gs` **con
   `URL_DATOS` rellena** (esa copia NO está en el repositorio). Guarda.
3. En el desplegable de funciones elige **`instalar`** y pulsa **Ejecutar**.
   Acepta los permisos (hojas de cálculo, conectarse a un servicio externo y
   ejecutarse solo). Crea las pestañas, programa el disparador cada 10 minutos
   y hace la primera carga.

No hace falta **ninguna implementación** ni aplicación web.

Para forzar una actualización sin esperar: ejecuta **`actualizar`** en el
editor. Si Google avisa por correo de fallos del disparador, suele ser que el
servidor no ha respondido en ese momento; mira la fila 1 de *Oneways*.
