/**
 * ====================================================================
 * JIBAYAT — Google Apps Script Webhook (Télémétrie & Suggestions)
 * ====================================================================
 * 
 * INSTRUCTIONS D'INSTALLATION :
 * 1. Ouvrez Google Sheets (https://sheets.new)
 * 2. Renommez le classeur en "JIBAYAT — Suivi Déploiements & Retours"
 * 3. Créez 2 feuilles :
 *    - Feuille 1 : "Communes"
 *    - Feuille 2 : "Suggestions"
 * 4. Allez dans le menu : Extensions > Apps Script
 * 5. Effacez le code existant et collez ce script complet.
 * 6. Cliquez sur "Déployer" (en haut à droite) > "Nouveau déploiement".
 * 7. Type : "Application Web".
 *    - Exécuter en tant que : "Moi"
 *    - Qui a accès : "Tout le monde" (Important pour permettre la réception des requêtes)
 * 8. Cliquez sur "Déployer", autorisez les accès, puis copiez l'URL de l'application Web.
 * 9. Collez cette URL dans JIBAYAT (Paramètres Système ou config.json sous "telemetry_webhook_url").
 * ====================================================================
 */

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var action = data.action || 'ping';
    var ss = SpreadsheetApp.getActiveSpreadsheet();

    if (action === 'ping' || action === 'install' || action === 'activate') {
      return handleCommunePing(ss, data);
    } else if (action === 'feedback' || action === 'suggestion') {
      return handleFeedback(ss, data);
    }

    return ContentService.createTextOutput(JSON.stringify({ status: 'ok', msg: 'Action non gérée' }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({ status: 'error', error: error.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({ status: 'online', service: 'JIBAYAT Telemetry Server' }))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Gestion des installations et statuts de licence des communes
 */
function handleCommunePing(ss, data) {
  var sheet = ss.getSheetByName('Communes');
  if (!sheet) {
    sheet = ss.insertSheet('Communes');
  }

  // En-têtes si feuille vide
  if (sheet.getLastRow() === 0) {
    sheet.appendRow([
      'Commune ID / Code',
      'Nom Commune',
      'Province',
      'Région',
      'Version App',
      'État Licence',
      'Clé d\'Activation',
      'Date Expiration',
      'Jours Restants',
      'Date 1ère Installation',
      'Dernier Contact (Date/Heure)',
      'Adresse IP / Hôte'
    ]);
    sheet.getRange(1, 1, 1, 12).setFontWeight('bold').setBackground('#1e293b').setFontColor('#ffffff');
  }

  var communeName = (data.commune_nom || 'Commune Inconnue').trim().toUpperCase();
  var communeCode = (data.commune_code || communeName);
  var rows = sheet.getDataRange().getValues();
  var foundRow = -1;

  // Chercher si la commune existe déjà (par nom ou code)
  for (var i = 1; i < rows.length; i++) {
    if (rows[i][0] == communeCode || (rows[i][1] && rows[i][1].toString().trim().toUpperCase() === communeName)) {
      foundRow = i + 1;
      break;
    }
  }

  var now = new Date();
  var rowData = [
    communeCode,
    communeName,
    data.province || '',
    data.region || '',
    data.version || '1.0.0',
    data.license_state || (data.is_activated ? 'Activé' : (data.in_trial ? 'Période d\'essai' : 'Expiré')),
    data.license_key || '',
    data.license_expiry || '',
    data.days_left !== undefined ? data.days_left : '',
    data.install_date || Utilities.formatDate(now, Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss'),
    Utilities.formatDate(now, Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss'),
    data.client_ip || ''
  ];

  if (foundRow > 0) {
    sheet.getRange(foundRow, 1, 1, rowData.length).setValues([rowData]);
  } else {
    sheet.appendRow(rowData);
  }

  return ContentService.createTextOutput(JSON.stringify({ status: 'ok', updated: communeName }))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Gestion des retours d'expérience et suggestions
 */
function handleFeedback(ss, data) {
  var sheet = ss.getSheetByName('Suggestions');
  if (!sheet) {
    sheet = ss.insertSheet('Suggestions');
  }

  if (sheet.getLastRow() === 0) {
    sheet.appendRow([
      'Date / Heure',
      'Commune',
      'Expéditeur',
      'Email / Contact',
      'Type de Retour',
      'Note / Évaluation',
      'Message / Suggestion'
    ]);
    sheet.getRange(1, 1, 1, 7).setFontWeight('bold').setBackground('#0f766e').setFontColor('#ffffff');
  }

  var now = new Date();
  var rowData = [
    Utilities.formatDate(now, Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss'),
    data.commune_nom || 'Non spécifiée',
    data.nom || 'Anonyme',
    data.email || '',
    data.type_feedback || 'Suggestion',
    data.note || '',
    data.message || ''
  ];

  sheet.appendRow(rowData);

  return ContentService.createTextOutput(JSON.stringify({ status: 'ok', msg: 'Suggestion enregistrée' }))
    .setMimeType(ContentService.MimeType.JSON);
}
