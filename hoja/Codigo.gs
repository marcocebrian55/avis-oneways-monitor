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
// Casilla que marcan a mano los responsables de flota. El servidor la manda
// vacia; lo marcado se conserva aqui, por reserva (o contrato si no la hay).
const COL_REVISADO = 'REVISADO';

/**
 * PASO 1, a mano desde el editor: pide los permisos y comprueba hoja y
 * servidor sin tocar nada. Si falla con "error desconocido" antes de escribir
 * nada en el registro, casi siempre es el navegador con VARIAS cuentas de
 * Google abiertas: repetir en una ventana de incognito solo con la de empresa.
 */
function paso1_probar() {
  const ss = SpreadsheetApp.getActive();
  console.log('1) Hoja OK: ' + ss.getName());
  const r = UrlFetchApp.fetch(URL_DATOS, { muteHttpExceptions: true });
  console.log('2) Servidor: HTTP ' + r.getResponseCode() + ', ' + r.getContentText().length + ' bytes');
  console.log('3) Disparadores actuales: ' + ScriptApp.getProjectTriggers().length);
}

/**
 * PASO 2, una vez a mano desde el editor: crea las pestañas, programa el
 * disparador y hace la primera carga.
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
    // Cualquier valor de ERROR (tambien el '1' de la version anterior) obliga a
    // repintar, que es lo que borra el aviso de la fila 1.
    const avisoPuesto = !!props.getProperty('ERROR');
    props.deleteProperty('FALLOS');
    props.deleteProperty('ERROR');
    if (props.getProperty('SELLO') === String(d.sello) && !avisoPuesto) return;

    pintarOneways_(hoja_(ss, HOJA_ONEWAYS), d, d.oneways);
    pintarTabla_(hoja_(ss, HOJA_COMPLETADOS), d.completados);
    pintarTabla_(hoja_(ss, HOJA_ALERTAS), d.alertas);
    // Las mismas tres por marca ('Oneways Xtravans'...). Las crea solas la
    // primera vez; el servidor decide que marcas hay (src/hoja.py, MARCAS).
    (d.marcas || []).forEach(function (m) {
      pintarOneways_(hoja_(ss, HOJA_ONEWAYS + ' ' + m.nombre), d, m.oneways);
      pintarTabla_(hoja_(ss, HOJA_COMPLETADOS + ' ' + m.nombre), m.completados);
      pintarTabla_(hoja_(ss, HOJA_ALERTAS + ' ' + m.nombre), m.alertas);
    });
    props.setProperty('SELLO', String(d.sello));
    props.setProperty('ACTUALIZADO', d.actualizado);
  } catch (err) {
    // Un fallo suelto (p.ej. "DNS error" de Google, visto el 17/09/2026 a las
    // 11:41) se arregla solo en la siguiente vuelta: no se avisa hasta que
    // fallan 3 seguidas, unos 30 minutos. Los datos anteriores se quedan.
    const fallos = Number(props.getProperty('FALLOS') || 0) + 1;
    props.setProperty('FALLOS', String(fallos));
    if (fallos < 3) return;
    props.setProperty('ERROR', 'aviso');
    const ahora = Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'dd/MM HH:mm');
    // NUNCA la URL en la celda: lleva el token y la hoja se comparte.
    const motivo = String(err.message || err).split(URL_DATOS).join('servidor').slice(0, 60);
    hoja_(ss, HOJA_ONEWAYS).getRange(1, 1)
      .setValue('⚠ Sin conexión con el servidor desde hace ' + (fallos * CADA_MINUTOS) + ' min (' +
                ahora + ': ' + motivo + ')  ·  datos de ' + (props.getProperty('ACTUALIZADO') || '—'))
      .setFontWeight('bold').setBackground('#F8CBCB');
  } finally {
    lock.releaseLock();
  }
}

/** Pestaña Oneways (o la de una marca, con su tabla `t`). Fila 1 =
 *  actualizado + leyenda, fila 2 = cabecera. */
function pintarOneways_(sh, d, t) {
  const ancho = Math.max(sh.getMaxColumns(), t.cabecera.length);
  // ANTES de reescribir: cada repintado cambia el orden de las filas.
  const revisados = leerRevisados_(sh, 2);
  sh.getRange(1, 1, 1, ancho).clearContent().setBackground(null).setFontWeight('normal');
  sh.getRange(1, 1).setValue('Actualizado: ' + d.actualizado + '  ·  ' + t.filas.length + ' oneway(s)')
    .setFontWeight('bold');
  (d.leyenda || []).forEach(function (l, i) {
    sh.getRange(1, 6 + i).setValue(l[0]).setBackground(l[1]).setHorizontalAlignment('center');
  });
  escribir_(sh, 2, t);
  marcarRevisados_(sh, 2, t, revisados);
}

/** Oneway de cada fila: la reserva, o el contrato si es de mostrador. Se
 *  compara como texto porque la hoja convierte '900' en el numero 900. */
function clave_(reserva, contrato) {
  return reserva !== '' && reserva != null ? 'R' + String(reserva).trim() : 'C' + String(contrato).trim();
}

/** {clave: true} de las filas con la casilla REVISADO marcada. Busca las
 *  columnas por su nombre: si la cabecera cambia, no se cruzan datos. */
function leerRevisados_(sh, filaCab) {
  const out = {}, ultima = sh.getLastRow(), ancho = sh.getLastColumn();
  if (ultima <= filaCab || !ancho) return out;
  const v = sh.getRange(filaCab, 1, ultima - filaCab + 1, ancho).getValues();
  const cR = v[0].indexOf('Reserva'), cC = v[0].indexOf('Contrato'), cX = v[0].indexOf(COL_REVISADO);
  if (cR < 0 || cC < 0 || cX < 0) return out;
  for (let i = 1; i < v.length; i++) {
    if (v[i][cX] === true) out[clave_(v[i][cR], v[i][cC])] = true;
  }
  return out;
}

/** Pone las casillas y vuelve a marcar las que ya estaban. */
function marcarRevisados_(sh, filaCab, t, revisados) {
  const filas = t.filas || [], cX = t.cabecera.indexOf(COL_REVISADO);
  if (cX < 0 || !filas.length) return;
  const cR = t.cabecera.indexOf('Reserva'), cC = t.cabecera.indexOf('Contrato');
  sh.getRange(filaCab + 1, cX + 1, filas.length, 1).insertCheckboxes()
    .setValues(filas.map(function (f) { return [!!revisados[clave_(f[cR], f[cC])]]; }))
    .setHorizontalAlignment('center');
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
  // Si la tabla tiene menos columnas que antes, fuera las cabeceras que sobran.
  if (ancho > n) sh.getRange(filaCab, n + 1, 1, ancho - n).clearContent().setBackground(null);
  sh.getRange(filaCab, 1, 1, n).setValues([t.cabecera])
    .setFontWeight('bold').setBackground('#3A3A40').setFontColor('#FFFFFF');
  sh.setFrozenRows(filaCab);

  const ultima = sh.getLastRow();
  if (ultima >= primera) {
    // Tambien las casillas: si hay menos filas, no deben quedar sueltas.
    sh.getRange(primera, 1, ultima - filaCab, ancho).clearContent().clearDataValidations()
      .setBackground(null).setFontWeight('normal').setFontColor('#000000');
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
