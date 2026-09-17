# Hoja de Google de los oneways

El servidor pone al día una hoja de Google en cada pasada (cada 2 horas y con
`/revisar`). Pestañas:

- **Oneways**: futuros y en curso, por colores. Se reescribe entera cada vez.
- **Completados**: devueltos, anulados y sin recoger. Se guardan 30 días.
- **Alertas**: cada aviso enviado a las oficinas. 30 días.

| Color | Estado |
|---|---|
| rojo | **Atrasado**: contrato abierto y la devolución ya pasó |
| naranja | **Se devuelve hoy** |
| amarillo | **Sale hoy** (aún sin contrato) |
| verde | **En curso**: coche entregado |
| azul | **Futuro** |
| gris | completado (pestaña Completados) |

Estados, colores y orden los decide `src/hoja.py`; `Codigo.gs` solo pinta.

## Montarla (una vez, con la cuenta de empresa)

1. En Drive: **Nuevo → Hojas de cálculo de Google**. Ponle nombre, p.ej.
   *AVIS · Oneways*.
2. En la hoja: **Extensiones → Apps Script**. Borra lo que haya y pega
   `Codigo.gs` **con la CLAVE ya puesta** (la copia con clave NO está en el
   repositorio; la clave es la de la sección `hoja` de
   `/var/lib/oneways/configuracion.json`). Guarda (icono del disquete).
3. Arriba, en el desplegable de funciones, elige **`instalar`** y pulsa
   **Ejecutar**. Pedirá permisos: *Revisar permisos* → tu cuenta → *Permitir*.
   Crea las pestañas.
4. **Implementar → Nueva implementación**. En el engranaje, tipo
   **Aplicación web**:
   - Ejecutar como: **Yo**
   - Quién tiene acceso: **Cualquier usuario**
   
   **Implementar** y copia la **URL de la aplicación web** (acaba en `/exec`).
5. Esa URL va en `hoja.url` de `/var/lib/oneways/configuracion.json`. Desde la
   siguiente pasada la hoja se llena sola.

Si en el paso 4 no aparece "Cualquier usuario" (solo "cualquiera de tu
organización"), el administrador de Google lo tiene bloqueado y el servidor no
podrá entrar: hay que ir por el plan B (API de Sheets con OAuth).

**"Cualquier usuario" no hace pública la hoja.** Solo permite llamar al script,
y el script no hace nada sin la clave. La hoja la ve quien tú compartas.

## Si cambias el script

Tras editar `Codigo.gs` hay que publicar una versión nueva **en la misma
implementación**: *Implementar → Gestionar implementaciones → lápiz → Versión:
Nueva versión → Implementar*. Así la URL no cambia. Con *Nueva implementación*
sale otra URL y habría que cambiarla en el servidor.

## Si deja de actualizarse

La fila 1 de *Oneways* dice cuándo fue la última vez. En el servidor:

```bash
grep "Hoja de Google" /var/lib/oneways/avis_oneways.log | tail
```

- `clave incorrecta`: la CLAVE del script y la del servidor no coinciden.
- `no devolvio JSON`: la aplicación web no está publicada para "Cualquier
  usuario", o la URL no es la de `/exec`.

Lo que no llega (completados y alertas) se guarda en
`/var/lib/oneways/hoja_pendiente.json` y se reenvía solo en la siguiente pasada,
sin duplicar.
