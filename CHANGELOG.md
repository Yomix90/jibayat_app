# JIBAYAT — Historique des Versions (CHANGELOG)

## v1.5.0 — 2026-08-20

### 🔒 Sécurité
- **CRITIQUE** : Suppression du mot de passe `admin123` hardcodé dans le formulaire de login et la base de données
- **CRITIQUE** : Ajout de `config.json` au `.gitignore` pour protéger les secrets (clé Flask, licence, webhook)
- **CRITIQUE** : Le `MASTER_SIGN_SECRET` des licences est maintenant chargé depuis la config/env au lieu d'être hardcodé
- Suppression de l'affichage du mot de passe admin dans la console
- Ajout de `SESSION_COOKIE_SECURE` pour les cookies de session HTTPS
- Export DB changé de GET → POST pour protéger le mot de passe
- Vérification des permissions admin sur les routes de gestion des utilisateurs
- Télémétrie restreinte à HTTPS uniquement
- Minimum mot de passe DB augmenté de 4 à 8 caractères

### 🔄 Mises à Jour Automatiques (OTA)
- **NOUVEAU** : Module de mise à jour automatique OTA (`modules/updater.py`)
- Vérification périodique des mises à jour via GitHub Releases (toutes les 6h)
- Téléchargement sécurisé avec vérification SHA-256
- Sauvegarde automatique des données (DB, config, uploads) avant mise à jour
- Protection des fichiers utilisateur : jamais écrasés lors d'une MAJ
- Migration automatique du schéma DB après MAJ
- Rollback automatique en cas d'échec
- Barre de notification dans l'interface web pour les administrateurs
- API REST : `/api/updater/check`, `/api/updater/apply`, `/api/updater/status`

### 🐛 Corrections
- Correction de fuite de descripteur de fichier lors du chargement de `config.json`
- Suppression des appels `conn.close()` manuels dangereux dans les helpers DB
- Correction du mode d'écriture des logs du launcher (`w` → `a`)
- Correction du `bare except` dans `app.py`

### 📁 Fichiers
- **NOUVEAU** : `config.example.json` — template de configuration sans secrets
- **NOUVEAU** : `modules/updater.py` — module de mise à jour automatique
- **NOUVEAU** : `CHANGELOG.md` — historique des versions

---

## v1.4.9 — Versions précédentes

Version initiale avec les modules de gestion fiscale :
- TNB, Débits de Boissons, Stationnement, Fourrière
- Occupation Domaine Public, Location Locaux, Souks
- Régie & État Civil
- Système de licences et d'activation
- Sauvegardes locales et cloud Google Drive
