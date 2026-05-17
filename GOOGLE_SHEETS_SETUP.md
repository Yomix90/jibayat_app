# 📊 Configuration Google Sheets — Réception des Rapports

## Étape 1 — Créer le Google Sheet

1. Allez sur https://sheets.google.com
2. Créez un nouveau classeur nommé : **"JIBAYAT — Rapports Clients"**
3. Notez l'**ID du classeur** dans l'URL :
   `https://docs.google.com/spreadsheets/d/1bUws5EDVXVXXEOqFsOwvSAdPCUdMoOVMXIhKbnjZYLM/edit`

## Étape 2 — Créer le Google Apps Script

1. Dans le classeur, menu **Extensions → Apps Script**
2. Supprimez le code existant et collez ce code :

```javascript
const SHEET_ID = "1bUws5EDVXVXXEOqFsOwvSAdPCUdMoOVMXIhKbnjZYLM"; // ← Remplacez par votre ID

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const sheet = SpreadsheetApp.openById(SHEET_ID).getActiveSheet();

    // Ajouter l'en-tête si la feuille est vide
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(["Date", "Commune", "Type", "Module", "Description", "Version"]);
      sheet.getRange(1, 1, 1, 6).setFontWeight("bold").setBackground("#1e3a5f").setFontColor("#ffffff");
    }

    // Ajouter la ligne de données
    sheet.appendRow([
      data.date || new Date().toISOString(),
      data.commune || "—",
      data.type || "—",
      data.module || "—",
      data.description || "—",
      data.version || "—"
    ]);

    // Notification email (optionnel)
    // MailApp.sendEmail("votre@email.com", "Nouveau rapport GFC", JSON.stringify(data));

    return ContentService
      .createTextOutput(JSON.stringify({ status: "ok" }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: "error", message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
```

## Étape 3 — Déployer comme Web App

1. Cliquez **Déployer → Nouveau déploiement**
2. Type : **Application Web**
3. Exécuter en tant que : **Moi**
4. Qui a accès : **Tout le monde** (anonymous)
5. Cliquez **Déployer** et **Autorisez** les permissions
6. **Copiez l'URL** qui ressemble à :
   `https://script.google.com/macros/s/AKfycby.../exec`

## Étape 4 — Configurer launcher.py

Ouvrez `launcher.py` et remplacez la ligne :

```python
GSHEET_WEBHOOK = "https://script.google.com/macros/s/VOTRE_SCRIPT_ID/exec"
```

Par l'URL copiée à l'étape 3.

---

✅ **Terminé !** Les rapports des clients apparaîtront automatiquement dans votre Google Sheet.
