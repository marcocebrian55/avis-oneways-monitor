/**
 * AVIS · Monitor de Oneways — la hoja de Google.
 *
 * Va DENTRO de la hoja (Extensiones > Apps Script). Cada 10 minutos descarga
 * del servidor los datos que deja la ultima pasada y, si han cambiado,
 * reescribe las tres pestañas. Estados, colores y orden los decide el servidor
 * (src/hoja.py), que tiene pruebas; este script solo pinta.
 *
 * VA A BUSCAR LOS DATOS en vez de recibirlos porque el Google Workspace del
 * grupo no deja publicar aplicaciones web para "Cualquier usuario", y el
 * servidor no tiene cuenta de Google (17/09/2026).
 *
 * Pasos para montarlo: hoja/LEEME.md del repositorio.
 *
 * OJO: URL_DATOS lleva el token secreto de la ruta. En el repositorio va VACIA
 * a proposito; la copia con la URL no se sube a ningun sitio.
 */
const URL_DATOS = '';

const HOJA_ONEWAYS = 'Oneways';
const HOJA_COMPLETADOS = 'Completados';
const HOJA_ALERTAS = 'Alertas';
const FORMATO_FECHA = 'dd/mm/yyyy hh:mm';
const CADA_MINUTOS = 10;

/**
 * Se ejecuta UNA vez a mano desde el editor: pide permisos, crea las pestañas,
 * programa el disparador y hace la primera carga.
 */
function instalar() {
  const ss = SpreadsheetApp.getActive();
  PropertiesService.getScriptProperties().setProperty('HOJA', ss.getId());
  [HOJA_ONEWAYS, HOJA_COMPLETADOS, HOJA_ALERTAS].forEach(function (n) { hoja_(ss, n); });
  // Un solo disparador aunque se ejecute instalar() varias veces.
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'actualizar') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('actualizar').timeBased().everyMinutes(CADA_MINUTOS).create();
  PropertiesService.getScriptProperties().deleteProperty('SELLO');
  actualizar();
  console.log('Listo: la hoja se actualiza sola cada ' + CADA_MINUTOS + ' minutos.');
}

/** Lo que ejecuta el disparador. Tambien se puede lanzar a mano para forzar. */
function actualizar() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('HOJA');
  const ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActive();
  try {
    if (!URL_DATOS) throw new Error('falta URL_DATOS en el script');
    const r = UrlFetchApp.fetch(URL_DATOS, { muteHttpExceptions: true, followRedirects: true });
    if (r.getResponseCode() !== 200) throw new Error('el servidor contesto HTTP ' + r.getResponseCode());
    const d = JSON.parse(r.getContentText());
    if (props.getProperty('SELLO') === String(d.sello) && !props.getProperty('ERROR')) return;

    pintarOneways_(hoja_(ss, HOJA_ONEWAYS), d);
    pintarTabla_(hoja_(ss, HOJA_COMPLETADOS), d.completados);
    pintarTabla_(hoja_(ss, HOJA_ALERTAS), d.alertas);
    props.setProperty('SELLO', String(d.sello));
    props.setProperty('ACTUALIZADO', d.actualizado);
    props.deleteProperty('ERROR');
  } catch (err) {
    // Los datos anteriores se quedan; solo se avisa arriba de que no son frescos.
    props.setProperty('ERROR', '1');
    const ahora = Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'dd/MM HH:mm');
    hoja_(ss, HOJA_ONEWAYS).getRange(1, 1)
      .setValue('⚠ Sin datos nuevos (' + ahora + '): ' + String(err.message || err).slice(0, 80) +
                '  ·  datos de ' + (props.getProperty('ACTUALIZADO') || '—'))
      .setFontWeight('bold').setBackground('#F8CBCB');
  } finally {
    lock.releaseLock();
  }
}

/** Pestaña Oneways. Fila 1 = actualizado + leyenda, fila 2 = cabecera. */
function pintarOneways_(sh, d) {
  const t = d.oneways, ancho = Math.max(sh.getMaxColumns(), t.cabecera.length);
  sh.getRange(1, 1, 1, ancho).clearContent().setBackground(null).setFontWeight('normal');
  sh.getRange(1, 1).setValue('Actualizado: ' + d.actualizado + '  ·  ' + t.filas.length + ' oneway(s)')
    .setFontWeight('bold');
  (d.leyenda || []).forEach(function (l, i) {
    sh.getRange(1, 6 + i).setValue(l[0]).setBackground(l[1]).setHorizontalAlignment('center');
  });
  escribir_(sh, 2, t);
}

/** Completados y Alertas: cabecera en la fila 1 y columna id oculta. */
function pintarTabla_(sh, t) {
  escribir_(sh, 1, t);
  const colId = t.cabecera.indexOf('id');
  if (colId >= 0 && !sh.isColumnHiddenByUser(colId + 1)) sh.hideColumns(colId + 1);
}

/** Cabecera en `filaCab`, datos debajo. Reescribe todo lo que hubiera. */
function escribir_(sh, filaCab, t) {
  const n = t.cabecera.length, primera = filaCab + 1;
  const ancho = Math.max(sh.getMaxColumns(), n);
  sh.getRange(filaCab, 1, 1, n).setValues([t.cabecera])
    .setFontWeight('bold').setBackground('#3A3A40').setFontColor('#FFFFFF');
  sh.setFrozenRows(filaCab);

  const ultima = sh.getLastRow();
  if (ultima >= primera) {
    sh.getRange(primera, 1, ultima - filaCab, ancho).clearContent().setBackground(null)
      .setFontWeight('normal').setFontColor('#000000');
  }
  const filas = t.filas || [];
  if (!filas.length) return;
  const faltan = primera + filas.length - 1 - sh.getMaxRows();
  if (faltan > 0) sh.insertRowsAfter(sh.getMaxRows(), faltan);
  const rango = sh.getRange(primera, 1, filas.length, n);
  rango.setValues(filas).setFontWeight('normal').setFontColor('#000000');
  if (t.colores) {
    rango.setBackgrounds(t.colores.map(function (c) { return filaDe_(c, n); }));
  } else {
    rango.setBackground(t.gris || null);
  }
  (t.fechas || []).forEach(function (c) {
    sh.getRange(primera, c + 1, filas.length, 1).setNumberFormat(FORMATO_FECHA);
  });
}

function hoja_(ss, nombre) {
  return ss.getSheetByName(nombre) || ss.insertSheet(nombre);
}

function filaDe_(color, n) {
  const f = [];
  for (let i = 0; i < n; i++) f.push(color);
  return f;
}
