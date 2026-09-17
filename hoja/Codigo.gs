/**
 * AVIS · Monitor de Oneways — la hoja de Google.
 *
 * Va DENTRO de la hoja (Extensiones > Apps Script) y se publica como aplicacion
 * web que se ejecuta como su dueño. El servidor le manda un POST en cada
 * pasada; este script solo escribe y pinta lo que le llega. Estados, colores
 * y orden se deciden en el servidor (src/hoja.py), que tiene pruebas.
 *
 * Pasos para montarlo: hoja/LEEME.md del repositorio.
 *
 * OJO: la CLAVE de abajo es la que el servidor tiene en la seccion "hoja" de
 * /var/lib/oneways/configuracion.json. En el repositorio va VACIA a proposito.
 */
const CLAVE = '';

const HOJA_ONEWAYS = 'Oneways';
const HOJA_COMPLETADOS = 'Completados';
const HOJA_ALERTAS = 'Alertas';
const FORMATO_FECHA = 'dd/mm/yyyy hh:mm';

/** Se ejecuta UNA vez a mano desde el editor: crea las pestañas y pide permisos. */
function instalar() {
  const ss = SpreadsheetApp.getActive();
  PropertiesService.getScriptProperties().setProperty('HOJA', ss.getId());
  [HOJA_ONEWAYS, HOJA_COMPLETADOS, HOJA_ALERTAS].forEach(function (n) { hoja_(ss, n); });
  console.log('Listo. Ahora: Implementar > Nueva implementacion > Aplicacion web.');
}

/** Abrir la URL /exec en el navegador sirve para comprobar que esta publicada. */
function doGet() {
  return ContentService.createTextOutput('AVIS · Monitor de Oneways: la hoja esta publicada.');
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(60000)) return json_({ ok: false, error: 'hoja ocupada' });
  try {
    const d = JSON.parse(e.postData.contents);
    if (!CLAVE || d.clave !== CLAVE) return json_({ ok: false, error: 'clave incorrecta' });
    return json_(procesar_(d));
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function procesar_(d) {
  const id = PropertiesService.getScriptProperties().getProperty('HOJA');
  const ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActive();
  pintarOneways_(hoja_(ss, HOJA_ONEWAYS), d);
  const tz = ss.getSpreadsheetTimeZone();
  const nc = anadir_(hoja_(ss, HOJA_COMPLETADOS), d.completados, d.limite, tz);
  const na = anadir_(hoja_(ss, HOJA_ALERTAS), d.alertas, d.limite, tz);
  return { ok: true, completados: nc, alertas: na };
}

/** Pestaña Oneways: se reescribe entera. Fila 1 = actualizado + leyenda, fila 2 = cabecera. */
function pintarOneways_(sh, d) {
  const t = d.oneways, n = t.cabecera.length, ancho = Math.max(sh.getMaxColumns(), n);
  sh.getRange(1, 1, 1, ancho).clearContent().setBackground(null).setFontWeight('normal');
  sh.getRange(1, 1).setValue('Actualizado: ' + d.actualizado + '  ·  ' + t.filas.length + ' oneway(s)')
    .setFontWeight('bold');
  (d.leyenda || []).forEach(function (l, i) {
    sh.getRange(1, 6 + i).setValue(l[0]).setBackground(l[1]).setHorizontalAlignment('center');
  });
  cabecera_(sh, 2, t.cabecera);

  const ultima = sh.getLastRow();
  if (ultima >= 3) sh.getRange(3, 1, ultima - 2, ancho).clearContent().setBackground(null);
  if (t.filas.length) {
    sh.getRange(3, 1, t.filas.length, n).setValues(t.filas)
      .setBackgrounds(t.colores.map(function (c) { return filaDe_(c, n); }));
    t.fechas.forEach(function (c) {
      sh.getRange(3, c + 1, t.filas.length, 1).setNumberFormat(FORMATO_FECHA);
    });
  }
  sh.setFrozenRows(2);
}

/**
 * Completados y Alertas: se AÑADEN arriba (lo mas nuevo primero), sin repetir
 * ids (el servidor reenvia lo que no llego), y se borra lo anterior a `limite`.
 */
function anadir_(sh, t, limite, tz) {
  const n = t.cabecera.length, colId = t.cabecera.indexOf('id');
  cabecera_(sh, 1, t.cabecera);
  sh.setFrozenRows(1);
  if (colId >= 0 && !sh.isColumnHiddenByUser(colId + 1)) sh.hideColumns(colId + 1);

  let ultima = sh.getLastRow();
  const ya = {};
  if (ultima >= 2) {
    sh.getRange(2, colId + 1, ultima - 1, 1).getValues()
      .forEach(function (v) { ya[String(v[0])] = true; });
  }
  const nuevas = (t.filas || []).filter(function (f) { return !ya[String(f[colId])]; });
  if (nuevas.length) {
    sh.insertRowsAfter(1, nuevas.length);
    // las filas insertadas heredan el formato de la cabecera: se deja normal
    sh.getRange(2, 1, nuevas.length, n).setValues(nuevas)
      .setFontWeight('normal').setFontColor('#000000').setBackground(t.gris || null);
    t.fechas.forEach(function (c) {
      sh.getRange(2, c + 1, nuevas.length, 1).setNumberFormat(FORMATO_FECHA);
    });
  }

  // Poda: la columna A es la fecha. Desde abajo, que es donde esta lo viejo.
  ultima = sh.getLastRow();
  if (limite && ultima >= 2) {
    const fechas = sh.getRange(2, 1, ultima - 1, 1).getValues();
    for (let i = fechas.length - 1; i >= 0; i--) {
      const s = serial_(fechas[i][0], tz);
      if (s && s < limite) {
        try {
          sh.deleteRow(i + 2);
        } catch (err) {
          // Sheets no deja borrar la ultima fila libre: se vacia en su lugar.
          sh.getRange(i + 2, 1, 1, n).clearContent().setBackground(null);
        }
      }
    }
  }
  return nuevas.length;
}

/** Fecha de la hoja -> numero de serie, en la zona horaria DE LA HOJA (como la manda el servidor). */
function serial_(v, tz) {
  if (typeof v === 'number') return v;
  if (!(v instanceof Date)) return 0;
  const p = Utilities.formatDate(v, tz, 'yyyy,MM,dd,HH,mm,ss').split(',').map(Number);
  return (Date.UTC(p[0], p[1] - 1, p[2], p[3], p[4], p[5]) - Date.UTC(1899, 11, 30)) / 86400000;
}

function cabecera_(sh, fila, cab) {
  sh.getRange(fila, 1, 1, cab.length).setValues([cab])
    .setFontWeight('bold').setBackground('#3A3A40').setFontColor('#FFFFFF');
}

function hoja_(ss, nombre) {
  return ss.getSheetByName(nombre) || ss.insertSheet(nombre);
}

function filaDe_(color, n) {
  const f = [];
  for (let i = 0; i < n; i++) f.push(color);
  return f;
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
