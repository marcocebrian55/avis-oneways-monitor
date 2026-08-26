# Contexto para un agente que vaya a tocar esto

Léelo entero antes del primer cambio. Está escrito para un asistente de IA que
llega sin historia; recoge lo que **no** se deduce leyendo el código.

## Qué es esto, en cuatro líneas

Vigila los **ONEWAYS** de AVIS Canarias: reservas o contratos que se entregan en
una oficina y se devuelven en **otra**. Cada 2 horas entra en Rentway
(`aviscanarias.jimpisoft.pt`) con Playwright, descarga 6 informes en Excel,
compara con la pasada anterior y avisa **solo si hay cambios**, por Telegram y
por correo.

## LO PRIMERO: esto manda correos a 32 personas reales

No es un entorno de pruebas. Cada pasada con cambios escribe a oficinas de
cuatro islas. Antes de tocar la comparación o el envío, asume que un error tuyo
llega a 32 buzones y que **nadie puede des-enviarlo**.

Reglas que el usuario ha pedido explícitamente:

- **Los correos de prueba, SOLO a `mcebrian@aviscanarias.es`.** Nunca a la lista.
  `--probar-correo` **sin argumento manda a los 32**; pon siempre la dirección.
- Los avisos de **error** van solo a esa misma dirección, jamás a las oficinas.
- Antes de desplegar algo que cambie qué se avisa, **simúlalo** contra los datos
  reales y enseña el resultado. Hay ejemplos más abajo.

## Dónde está todo

| | |
|---|---|
| Servidor | Hetzner `oneways-avis`, **91.99.185.207**, Ubuntu 24.04, zona `Atlantic/Canary` |
| Entrar | `ssh -i ~/.ssh/id_ed25519_oneways root@91.99.185.207` |
| Código | `/opt/oneways/repo` (rama `main`, solo lectura) |
| Python | `/opt/oneways/venv` |
| **Estado y configuración** | **`/var/lib/oneways`** |
| Log | `/var/lib/oneways/avis_oneways.log` |
| Informes descargados | `/home/oneways/Downloads` |

`docs/OPERACION.md` es la referencia operativa completa. Esto es el porqué.

## La regla de oro

**El código se cambia en el repositorio. La configuración, en el servidor.**

```
CÓDIGO          editar → commit → push a main → git pull en el servidor
CONFIGURACIÓN   editar /var/lib/oneways/configuracion.json → se relee sola
```

Un fichero editado a mano en `/opt/oneways/repo` lo borra el siguiente `git
pull` y nadie sabrá por qué estaba así.

## Secretos: qué NO debe salir de aquí

- La clave SSH privada vive **solo en el portátil de Marco**. No la copies a
  ningún sitio, no la pegues en un chat, no la subas a una nube.
- `/var/lib/oneways/configuracion.json` lleva **en claro** la contraseña de
  Rentway, el token del bot de Telegram y una contraseña de aplicación de
  Gmail. No la vuelques en un mensaje ni en un fichero del repositorio.
- El repositorio es privado y su historial se reescribió a propósito para que
  no queden credenciales. **No las devuelvas ahí.**

## Decisiones de diseño que parecen raras y no lo son

Si algo de esto te parece mejorable, lee el porqué antes: casi todo son
cicatrices de un fallo real.

**Una reserva y su contrato son el MISMO oneway.** Cuando el cliente recoge el
coche, la reserva no desaparece: pasa a estado `Confirmed with RA` y nace un
contrato con número distinto. El informe de Abiertos trae una columna
`N.º Reserva` que los enlaza y por eso se fusionan en la clave `RES-<n>`. Si
creas una entrada `CON-` aparte, un solo coche saliendo del mostrador produce
dos avisos que se contradicen ("NUEVO ONEWAY" y "YA NO ES ONEWAY") y cuenta dos
veces en el total de activos.

**El contrato manda sobre la reserva, pero solo con datos completos.** Si al
recoger cambia la oficina de devolución a la de salida, deja de ser oneway y se
da de baja. Pero si **falta** cualquiera de las dos oficinas no se decide nada:
dar por hecho que no es oneway daría de baja coches vivos por un hueco en los
datos.

**`_de_contrato` no es basura.** Apunta qué campos puso el contrato, para poder
devolverlos exactos las noches en que el informe de Abiertos no baja
(`arrastrar_contratos`). Sin esa lista habría que adivinar cuáles eran, y
adivinar mal significa avisar de un cambio que no ha existido.

**Nunca releas un `open_*.xlsx` de otra pasada.** `encontrar_excels()` coge el
más reciente de `Downloads`, así que devuelve el de hace horas sin decirlo.
Usa siempre lo que ha devuelto `descargar_informes()` en **esta** pasada.

**El reparto por islas agrupa por PERSONA, no por isla.** Parece natural mandar
un correo por isla, pero quien cubre dos —`moalvarez@` lleva Fuerteventura y
Lanzarote— recibiría dos veces el mismo aviso justo en el caso más común, un
oneway que va de una a otra.

**Lo desconocido va a TODO EL MUNDO, nunca a nadie.** Una oficina que no esté en
`src/oficinas_islas.json`, o una isla sin lista, manda ese oneway a los 32 y
dispara un aviso de error. Un correo de más se ve; un silencio no se nota hasta
que alguien pregunta por un coche que no esperaba.

**"Las Palmas" se comprueba ANTES que "la palma"** al generar el mapa de islas.
Si no, los oneways de Gran Canaria acaban en La Palma por una letra.

**El aviso de fallo sale por Telegram Y por correo.** Telegram se cae a ratos
desde el servidor (varios timeouts al día). Un aviso de avería que viaja solo
por el canal que se puede averiar no es fiable.

**El parte diario de las 07:00 depende de dos cosas a la vez:** `HORA_PARTE` en
`avis_monitor.py` y un disparador explícito a esa hora en
`oneways-pasada.timer`. Las pasadas van a horas **pares**; si cambias una cosa,
cambia la otra.

## Cómo verificar un cambio sin molestar a nadie

Copia los ficheros a `/tmp` y pruébalos ahí contra los datos reales, **sin**
tocar `/opt/oneways/repo`:

```bash
scp -i ~/.ssh/id_ed25519_oneways src/avis_monitor.py root@91.99.185.207:/tmp/
ssh -i ~/.ssh/id_ed25519_oneways root@91.99.185.207 \
  'sudo -u oneways ONEWAYS_DATOS=/var/lib/oneways /opt/oneways/venv/bin/python - <<PY
import sys; sys.path.insert(0, "/tmp")
import avis_monitor as am
# ... tu prueba ...
PY'
```

Para simular el reparto sin enviar nada, usa `am.repartir(...)` con la
configuración real: devuelve `[(destinatarios, cambios)]` y no manda un correo.

Y después de desplegar, una pasada de verdad:

```bash
systemctl start oneways-pasada.service
tail -20 /var/lib/oneways/avis_oneways.log
```

## Estado y trabajo pendiente

Lo abierto está en la sección **PENDIENTE** de este documento y en el historial
de commits, que es deliberadamente explicativo: cada mensaje cuenta *por qué*,
no *qué*. `git log` es la mejor fuente de contexto que hay aquí.

Lo más importante sin resolver: **el informe de Abiertos se cuelga de madrugada**
(00:00–07:00) y funciona a partir de las 08:00. Solo ése; los otros cinco bajan
siempre. Hay diagnóstico instrumentado: mira `/var/lib/oneways/diagnostico/*.png`
y el resumen que llega a las 07:30.

## Cómo se escribe aquí

El código está comentado en español, explicando **por qué**, no qué. Los
comentarios largos suelen contar un fallo real y su fecha. Mantén ese estilo: si
arreglas algo sutil, deja escrito cómo se manifestaba, o alguien lo "simplificará"
dentro de seis meses.
