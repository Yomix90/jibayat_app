# JIBAYAT — Historique des Versions (CHANGELOG)

## v1.5.2 — 2026-08-21

### 📐 Calculs Fiscaux & TNB
- **Calcul précis des pénalités de retard (0.5% / mois)** : Correction du décompte des mois de retard selon la Loi 47-06 (calcul calendaire exact, prise en compte intégrale de l'année 2025).
- **Majoration au centime supérieur** : Arrondi automatique au centime supérieur pour tous les montants après la virgule (ex: `945.721 -> 945.73`).
- **Nettoyage automatique & Sauvegardes isolées** : Sauvegardes pré-MAJ rangées proprement dans le sous-dossier `sauvegardes/` avec rotation automatique.
- **Verrou d'instance unique (Mutex)** : Empêche le lancement multiple de l'application et la duplication des icônes dans la barre des tâches.

## v1.5.1 — 2026-08-20

### 🎨 Interface & UX
- **Correctif bouton** : Suppression de l'ombre jaune décalée au survol des boutons
- **Badge de mise à jour dynamique** : Affichage d'une pastille animée à côté de la version dans la barre latérale avec lien direct vers la mise à jour
- **Mises à jour intelligentes** : Support du téléchargement direct des fichiers d'installation `.exe` (JIBAYAT_Setup.exe)
- **Dépôt public dédié** : Vérification autonome des mises à jour via `Yomix90/jibayat-releases` sans exposition du code source
