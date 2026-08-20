# 🏛️ JIBAYAT — Guide d'Installation & Licence Développeur

---

## 👨‍💻 Informations Développeur & Support Officiel

| Champ | Information |
| :--- | :--- |
| **Développeur & Auteur** | **YOUSSEF** |
| **Téléphone / WhatsApp** | **[+212 662-082795](https://wa.me/212662082795)** |
| **Email de Support** | **[yomix90@gmail.com](mailto:yomix90@gmail.com)** |
| **Dépôt GitHub** | **[https://github.com/Yomix90/JIBAYAT](https://github.com/Yomix90/JIBAYAT)** |
| **Clé Licence Développeur (Master)** | `JBYT-LFFF-FF0D-B795-5F03` *(Illimitée / À vie)* |

---

## 🚀 1. Procédure d'Installation Rapide (Windows)

### Option A : Installation Automatique en 1 Clic (Recommandé)
1. Double-cliquez sur le fichier **`INSTALLER.bat`**.
2. Le programme d'installation effectue automatiquement :
   - La vérification de Python et des prérequis.
   - L'installation de toutes les dépendances requises (`cryptography`, `flask`, `openpyxl`, `reportlab`, etc.).
   - L'initialisation sécurisée de la base de données locale `fiscalite.db`.
   - La création automatique du raccourci **JIBAYAT** sur votre Bureau.

### Option B : Installation Manuelle (Ligne de commande)
```bash
# 1. Ouvrir le terminal dans le dossier JIBAYAT
cd "C:\Users\...\JIBAYAT APP"

# 2. Installer les dépendances Python
pip install -r requirements.txt

# 3. Initialiser la structure de la base de données
python -c "from database import init_db; init_db()"

# 4. Lancer l'application
python app.py
```

---

## 🔑 2. Activation du Logiciel & Licences

### Période d'Essai Gratuite
- À la première installation, le logiciel offre une **période d'essai gratuite de 30 jours** durant laquelle toutes les fonctionnalités sont pleinement opérationnelles sans obligation d'activation.

### Activation de la Licence
- Rendez-vous sur la page **`http://localhost:5050/activation`** ou dans **Paramètres Système > 🔑 Licence & Activation**.
- Saisissez la clé d'activation officielle :
  - Clé Développeur / Master : **`JBYT-LFFF-FF0D-B795-5F03`**
- Cliquez sur **Valider la Clé d'Activation**.

---

## 🛠️ 3. Génération de Clés pour les Communes Clientes

Pour générer des clés de produit pour vos communes clientes :
1. Lancez l'application bureau autonome : **`dist\JIBAYAT_Keygen.exe`** (ou lancez `python keygen_app.py`).
2. Choisissez la durée (30 jours, 90 jours, 1 an, À vie, ou personnalisée).
3. Cliquez sur **⚡ Générer la Clé** et copiez le code pour votre client.

---

## 📊 4. Liaison Google Sheets (Suivi des Déploiements)

Pour recevoir en temps réel la liste des communes qui installent JIBAYAT et leurs suggestions :
1. Ouvrez [sheets.new](https://sheets.new).
2. Dans **Extensions > Apps Script**, collez le code du fichier `google_apps_script_template.js`.
3. Déployez en tant qu'**Application Web** (*Accès: Tout le monde*) et copiez l'URL.
4. Dans JIBAYAT, collez l'URL dans **Paramètres Système > ✉️ Support & Avis** et cliquez sur **Enregistrer**.
