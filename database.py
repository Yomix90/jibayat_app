"""
database.py — Connexion DB, init_db, et helpers partagés
"""
import sqlite3, json, os, logging
from datetime import datetime, date

_logger = logging.getLogger('jibayat.db')

DB = 'fiscalite.db'

def get_db():
    conn = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode: permet lectures concurrentes pendant une ecriture
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
    except Exception:
        pass
    return conn

# ── Système de versions de schéma ───────────────────────────
SCHEMA_VERSION = 3

def _get_schema_version(conn):
    try:
        row = conn.execute('SELECT val FROM schema_meta WHERE key="version"').fetchone()
        return int(row['val']) if row else 0
    except Exception:
        return 0

def _set_schema_version(conn, version):
    conn.execute(
        'INSERT OR REPLACE INTO schema_meta (key, val) VALUES ("version", ?)',
        (str(version),)
    )
    conn.commit()

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY, val TEXT
    )''')
    conn.commit()
    current_ver = _get_schema_version(conn)

    # ── Création initiale du schéma (version 0→1) ─────────────
    if current_ver < 1:
        c.executescript('''
CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY, nom TEXT UNIQUE,
        peut_ajouter INTEGER DEFAULT 0, peut_modifier INTEGER DEFAULT 0,
        peut_supprimer INTEGER DEFAULT 0, peut_voir INTEGER DEFAULT 1,
        peut_valider_paiement INTEGER DEFAULT 0, peut_config INTEGER DEFAULT 0,
        peut_creer_bulletin INTEGER DEFAULT 0
    );
CREATE TABLE IF NOT EXISTS app_modules (
        code TEXT PRIMARY KEY,
        nom TEXT,
        description TEXT,
        actif INTEGER DEFAULT 1,
        ordre INTEGER DEFAULT 10
    );
CREATE TABLE IF NOT EXISTS role_module_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
        module_code TEXT REFERENCES app_modules(code) ON DELETE CASCADE,
        peut_voir INTEGER DEFAULT 1,
        peut_ajouter INTEGER DEFAULT 0,
        peut_modifier INTEGER DEFAULT 0,
        peut_supprimer INTEGER DEFAULT 0,
        UNIQUE(role_id, module_code)
    );
CREATE TABLE IF NOT EXISTS utilisateurs (
        id INTEGER PRIMARY KEY, nom TEXT, prenom TEXT,
        email TEXT UNIQUE, mot_de_passe TEXT, role_id INTEGER,
        actif INTEGER DEFAULT 1, commune_id INTEGER
    );
CREATE TABLE IF NOT EXISTS communes (
        id INTEGER PRIMARY KEY, nom TEXT, nom_ar TEXT,
        president_fr TEXT, president_ar TEXT,
        region TEXT, region_ar TEXT, province TEXT, province_ar TEXT, logo TEXT,
        code TEXT, actif INTEGER DEFAULT 1
    );
CREATE TABLE IF NOT EXISTS contribuables (
        id INTEGER PRIMARY KEY, numero TEXT UNIQUE,
        type_personne TEXT DEFAULT "physique",
        nom TEXT, prenom TEXT, nom_ar TEXT, prenom_ar TEXT,
        raison_sociale TEXT, raison_sociale_ar TEXT,
        cin TEXT, ice TEXT, rc TEXT,
        adresse TEXT, adresse_ar TEXT, ville TEXT, code_postal TEXT,
        telephone TEXT, email TEXT, commune_id INTEGER, actif INTEGER DEFAULT 1,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS rubriques (
        id INTEGER PRIMARY KEY, code TEXT, libelle TEXT, libelle_ar TEXT,
        module TEXT UNIQUE, commune_id INTEGER, actif INTEGER DEFAULT 1, description TEXT
    );
CREATE TABLE IF NOT EXISTS parametres_calcul (
        id INTEGER PRIMARY KEY, module TEXT, code TEXT,
        libelle TEXT, valeur TEXT, unite TEXT, description TEXT, commune_id INTEGER,
        UNIQUE(module, code)
    );
CREATE TABLE IF NOT EXISTS terrains (
        id INTEGER PRIMARY KEY, numero_terrain TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        adresse TEXT, adresse_ar TEXT, quartier TEXT, arrondissement TEXT,
        superficie REAL, zone TEXT DEFAULT "B",
        titre_foncier TEXT, num_parcelle TEXT,
        statut TEXT DEFAULT "non_bati", date_acquisition TEXT,
        actif INTEGER DEFAULT 1, date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS permis (
        id INTEGER PRIMARY KEY, terrain_id INTEGER,
        type_permis TEXT, numero_permis TEXT,
        date_depot TEXT, date_delivrance TEXT, statut TEXT DEFAULT "en_cours",
        description TEXT, date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS transferts_terrain (
        id INTEGER PRIMARY KEY, terrain_id INTEGER,
        ancien_contribuable_id INTEGER, nouveau_contribuable_id INTEGER,
        date_transfert TEXT, motif TEXT, acte_notarie TEXT, agent_id INTEGER
    );
CREATE TABLE IF NOT EXISTS etablissements_boissons (
        id INTEGER PRIMARY KEY, numero TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        nom_etablissement TEXT, type_etablissement TEXT,
        adresse TEXT, superficie REAL,
        numero_autorisation TEXT, date_autorisation TEXT,
        statut TEXT DEFAULT "actif", actif INTEGER DEFAULT 1,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS vehicules (
        id INTEGER PRIMARY KEY, numero TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        immatriculation TEXT, type_vehicule TEXT,
        num_autorisation TEXT, date_autorisation TEXT,
        nombre_sieges INTEGER DEFAULT 0,
        statut TEXT DEFAULT "actif", actif INTEGER DEFAULT 1,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS occupations (
        id INTEGER PRIMARY KEY, numero TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        type_occupation TEXT, localisation TEXT, superficie REAL,
        num_autorisation TEXT, date_debut TEXT, date_fin TEXT,
        statut TEXT DEFAULT "actif", actif INTEGER DEFAULT 1,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS dossiers_fourriere (
        id INTEGER PRIMARY KEY, numero TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        immatriculation TEXT, type_vehicule TEXT,
        date_mise_fourriere TEXT, motif TEXT, nb_jours INTEGER DEFAULT 0,
        frais_remorquage REAL DEFAULT 0,
        statut TEXT DEFAULT "en_fourriere", date_restitution TEXT,
        actif INTEGER DEFAULT 1, date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    , num_depot TEXT, numero_immat TEXT, deposant TEXT, nom_proprietaire TEXT, cin_proprietaire TEXT, telephone_prop TEXT, tarif_journalier REAL DEFAULT 0, numero_bulletin TEXT, date_paiement TEXT, agent_paiement_id INTEGER, date_sortie_validee TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS baux (
        id INTEGER PRIMARY KEY, numero TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        ref_local TEXT, adresse TEXT, superficie REAL,
        loyer_mensuel REAL, date_debut TEXT, date_fin TEXT,
        statut TEXT DEFAULT "actif", actif INTEGER DEFAULT 1,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    , secteur_id INTEGER REFERENCES loc_secteurs(id), boutique_id INTEGER REFERENCES loc_boutiques(id), tarif_id INTEGER REFERENCES loc_tarifs(id));
CREATE TABLE IF NOT EXISTS affermages (
        id INTEGER PRIMARY KEY, numero TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        nom_souk TEXT, num_emplacement TEXT, type_activite TEXT,
        redevance_annuelle REAL, date_debut TEXT,
        statut TEXT DEFAULT "actif", actif INTEGER DEFAULT 1,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    , date_fin TEXT, duree_contrat INTEGER DEFAULT 1, taux_augmentation REAL DEFAULT 5.0, redevance_mensuelle REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS declarations (
        id INTEGER PRIMARY KEY, numero TEXT UNIQUE,
        module TEXT, reference_id INTEGER,
        contribuable_id INTEGER, commune_id INTEGER,
        annee INTEGER, trimestre INTEGER DEFAULT 0,
        base_calcul REAL DEFAULT 0, taux REAL DEFAULT 0,
        montant_principal REAL DEFAULT 0,
        penalite_retard REAL DEFAULT 0, majoration REAL DEFAULT 0,
        amende_non_declaration REAL DEFAULT 0, montant_total REAL DEFAULT 0,
        statut TEXT DEFAULT "emis",
        date_declaration TEXT, date_echeance TEXT, date_paiement TEXT,
        agent_id INTEGER, notes TEXT,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS bulletins (
        id INTEGER PRIMARY KEY, numero_bulletin TEXT UNIQUE,
        declaration_id INTEGER, contribuable_id INTEGER, commune_id INTEGER,
        montant REAL, mode_paiement TEXT DEFAULT "especes",
        date_paiement TEXT, statut TEXT DEFAULT "en_attente",
        agent_id INTEGER, regisseur_id INTEGER, notes TEXT,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    , numero_quittance TEXT, date_quittance TEXT, motif_rejet TEXT, numero_versement TEXT, date_encaissement TEXT);
CREATE TABLE IF NOT EXISTS avis_non_paiement (
        id INTEGER PRIMARY KEY, numero_avis TEXT UNIQUE,
        declaration_id INTEGER, contribuable_id INTEGER, commune_id INTEGER,
        montant_du REAL, date_emission TEXT, delai_jours INTEGER DEFAULT 30,
        lot_id TEXT, statut TEXT DEFAULT "emis"
    , lettre_id INTEGER);
CREATE TABLE IF NOT EXISTS arretes_fiscaux (
        id INTEGER PRIMARY KEY,
        numero TEXT UNIQUE,
        titre TEXT,
        date_effet TEXT NOT NULL,
        date_fin TEXT,
        statut TEXT DEFAULT 'actif',
        notes TEXT,
        agent_id INTEGER,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS tarifs (
        id INTEGER PRIMARY KEY,
        rubrique_id INTEGER NOT NULL,
        arrete_id INTEGER,
        code_tarif TEXT,
        libelle TEXT NOT NULL,
        valeur REAL NOT NULL,
        unite TEXT DEFAULT 'DH',
        date_debut TEXT NOT NULL,
        date_fin TEXT,
        actif INTEGER DEFAULT 1
    );
CREATE TABLE IF NOT EXISTS declarations_annuelles_tdb (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE,
    etablissement_id INTEGER,
    contribuable_id INTEGER,
    commune_id INTEGER DEFAULT 1,
    annee INTEGER,
    base_t1 REAL DEFAULT 0,
    base_t2 REAL DEFAULT 0,
    base_t3 REAL DEFAULT 0,
    base_t4 REAL DEFAULT 0,
    total_base REAL DEFAULT 0,
    taux REAL DEFAULT 10,
    montant_du REAL DEFAULT 0,
    date_declaration TEXT,
    agent_id INTEGER,
    statut TEXT DEFAULT 'soumise',
    date_creation TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tnb_terrains (
        id INTEGER PRIMARY KEY, numero_fiscal TEXT UNIQUE NOT NULL,
        contribuable_id INTEGER, commune_id INTEGER,
        superficie REAL, zone TEXT, adresse TEXT, statut TEXT DEFAULT 'non_bati',
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS tnb_declarations (
        id INTEGER PRIMARY KEY, terrain_id INTEGER, annee INTEGER,
        superficie_declaree REAL, zone TEXT, tarif REAL,
        montant_calcule REAL, montant_paye REAL DEFAULT 0,
        statut TEXT DEFAULT 'emis', date_emission TEXT, date_paiement TEXT,
        agent_id INTEGER, commune_id INTEGER
    );
CREATE TABLE IF NOT EXISTS tdb_etablissements (
        id INTEGER PRIMARY KEY, numero_licence TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        nom_etablissement TEXT, nom_etablissement_ar TEXT,
        type_etablissement TEXT, categorie TEXT,
        adresse TEXT, date_ouverture TEXT, statut TEXT DEFAULT 'actif',
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS tdb_declarations (
        id INTEGER PRIMARY KEY, etablissement_id INTEGER, annee INTEGER,
        chiffre_affaires REAL, taux REAL, montant_calcule REAL,
        montant_paye REAL DEFAULT 0, statut TEXT DEFAULT 'emis',
        date_emission TEXT, date_paiement TEXT, agent_id INTEGER, commune_id INTEGER
    );
CREATE TABLE IF NOT EXISTS sta_vehicules (
        id INTEGER PRIMARY KEY, numero_immatriculation TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        type_vehicule TEXT, categorie TEXT,
        marque TEXT, capacite INTEGER, statut TEXT DEFAULT 'actif',
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS sta_declarations (
        id INTEGER PRIMARY KEY, vehicule_id INTEGER, annee INTEGER,
        tarif REAL, montant_calcule REAL, montant_paye REAL DEFAULT 0,
        statut TEXT DEFAULT 'emis', date_emission TEXT, date_paiement TEXT,
        agent_id INTEGER, commune_id INTEGER
    );
CREATE TABLE IF NOT EXISTS odp_occupations (
        id INTEGER PRIMARY KEY, numero_autorisation TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        type_occupation TEXT, superficie REAL, emplacement TEXT,
        date_debut TEXT, date_fin TEXT, tarif REAL, statut TEXT DEFAULT 'actif',
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS odp_declarations (
        id INTEGER PRIMARY KEY, occupation_id INTEGER, annee INTEGER,
        superficie REAL, tarif REAL, montant_calcule REAL,
        montant_paye REAL DEFAULT 0, statut TEXT DEFAULT 'emis',
        date_emission TEXT, date_paiement TEXT, agent_id INTEGER, commune_id INTEGER
    );
CREATE TABLE IF NOT EXISTS fou_dossiers (
        id INTEGER PRIMARY KEY, numero_pv TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        vehicule_immat TEXT, type_vehicule TEXT,
        date_mise_en_fourriere TEXT, date_sortie TEXT,
        nb_jours INTEGER, statut TEXT DEFAULT 'en_fourriere',
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS fou_declarations (
        id INTEGER PRIMARY KEY, dossier_id INTEGER,
        tarif_journalier REAL, frais_remorquage REAL DEFAULT 0,
        montant_calcule REAL, montant_paye REAL DEFAULT 0,
        statut TEXT DEFAULT 'emis', date_emission TEXT, date_paiement TEXT,
        agent_id INTEGER, commune_id INTEGER
    );
CREATE TABLE IF NOT EXISTS loc_locaux (
        id INTEGER PRIMARY KEY, numero_contrat TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        designation TEXT, adresse TEXT, superficie REAL,
        loyer_mensuel REAL, date_debut TEXT, date_fin TEXT, statut TEXT DEFAULT 'actif',
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS loc_paiements (
        id INTEGER PRIMARY KEY, local_id INTEGER, mois TEXT,
        montant REAL, montant_paye REAL DEFAULT 0,
        statut TEXT DEFAULT 'en_attente', date_paiement TEXT,
        agent_id INTEGER, commune_id INTEGER
    );
CREATE TABLE IF NOT EXISTS sou_contrats (
        id INTEGER PRIMARY KEY, numero_contrat TEXT UNIQUE,
        contribuable_id INTEGER, commune_id INTEGER,
        nom_souk TEXT, emplacement TEXT, superficie REAL,
        redevance_annuelle REAL, date_debut TEXT, date_fin TEXT, statut TEXT DEFAULT 'actif',
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS sou_paiements (
        id INTEGER PRIMARY KEY, contrat_id INTEGER, annee INTEGER,
        montant REAL, montant_paye REAL DEFAULT 0,
        statut TEXT DEFAULT 'en_attente', date_paiement TEXT,
        agent_id INTEGER, commune_id INTEGER
    );
CREATE TABLE IF NOT EXISTS paiements_bulletins (
        id INTEGER PRIMARY KEY, module TEXT, reference_id INTEGER,
        commune_id INTEGER, contribuable_id INTEGER,
        montant REAL, date_paiement TEXT, mode_paiement TEXT DEFAULT 'espece',
        reference_paiement TEXT, statut TEXT DEFAULT 'en_attente',
        agent_id INTEGER, valideur_id INTEGER, date_validation TEXT,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE IF NOT EXISTS avis_imposition (
        id INTEGER PRIMARY KEY, module TEXT, reference_id INTEGER,
        contribuable_id INTEGER, commune_id INTEGER,
        annee INTEGER, montant REAL, statut TEXT DEFAULT 'emis',
        date_emission TEXT, date_echeance TEXT, date_reglement TEXT,
        agent_id INTEGER
    );
CREATE TABLE IF NOT EXISTS affermage_docs (id INTEGER PRIMARY KEY, affermage_id INTEGER, nom_fichier TEXT, chemin TEXT, type_doc TEXT, date_upload TEXT DEFAULT CURRENT_TIMESTAMP, agent_id INTEGER);
CREATE TABLE IF NOT EXISTS ctb_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contribuable_id INTEGER NOT NULL,
    type_doc TEXT NOT NULL DEFAULT 'autre',
    nom_fichier TEXT,
    chemin TEXT,
    taille INTEGER,
    date_upload TEXT,
    agent_id INTEGER,
    notes TEXT,
    FOREIGN KEY(contribuable_id) REFERENCES contribuables(id)
);
CREATE TABLE IF NOT EXISTS fou_parametres (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    categorie  TEXT NOT NULL,   -- 'deposant' | 'etat_vehicule' | 'motif'
    code       TEXT NOT NULL,
    libelle    TEXT NOT NULL,
    ordre      INTEGER DEFAULT 0,
    actif      INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS fou_types_vehicule (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT UNIQUE NOT NULL,
    libelle          TEXT NOT NULL,
    tarif_journalier REAL DEFAULT 0,
    actif            INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS fou_groupes_enchere (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero          TEXT UNIQUE NOT NULL,
    libelle         TEXT NOT NULL,
    date_creation   TEXT,
    date_enchere    TEXT,
    lieu            TEXT,
    prix_ouverture  REAL DEFAULT 0,
    type_vehicule   TEXT,   -- filtre par type
    statut          TEXT DEFAULT 'ouvert',  -- ouvert | vendu | annule
    notes           TEXT,
    agent_id        INTEGER
);
CREATE TABLE IF NOT EXISTS fou_vehicules_enchere (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    groupe_id       INTEGER NOT NULL REFERENCES fou_groupes_enchere(id),
    dossier_id      INTEGER NOT NULL REFERENCES dossiers_fourriere(id),
    etat_vehicule   TEXT DEFAULT 'moyen',  -- bien | moyen | mauvais
    ordre           INTEGER DEFAULT 0,
    notes           TEXT
);
CREATE TABLE IF NOT EXISTS fou_ventes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    groupe_id         INTEGER REFERENCES fou_groupes_enchere(id),
    dossier_id        INTEGER REFERENCES dossiers_fourriere(id),
    nom_acheteur      TEXT,
    cin_acheteur      TEXT,
    telephone_acheteur TEXT,
    prix_adjudication REAL DEFAULT 0,
    numero_quittance  TEXT,
    date_vente        TEXT,
    pv_chemin         TEXT,  -- upload PV de vente
    pv_nom            TEXT,
    agent_id          INTEGER,
    notes             TEXT
);
CREATE TABLE IF NOT EXISTS loc_secteurs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    libelle TEXT NOT NULL,
    description TEXT,
    type_tarif TEXT NOT NULL DEFAULT 'fixe',  -- 'fixe' = DH/mois, 'm2' = DH/m²/mois
    tarif_mensuel REAL NOT NULL DEFAULT 0,
    unite TEXT NOT NULL DEFAULT 'DH/mois',
    actif INTEGER NOT NULL DEFAULT 1,
    date_creation TEXT DEFAULT (datetime('now')),
    ordre INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS loc_tarifs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    secteur_id INTEGER NOT NULL REFERENCES loc_secteurs(id),
    libelle TEXT NOT NULL,
    type_tarif TEXT NOT NULL DEFAULT 'fixe',
    valeur REAL NOT NULL DEFAULT 0,
    unite TEXT NOT NULL DEFAULT 'DH/mois',
    actif INTEGER NOT NULL DEFAULT 1,
    date_creation TEXT DEFAULT (datetime('now'))
, tarif_fiscal_id INTEGER REFERENCES tarifs(id));
CREATE TABLE IF NOT EXISTS loc_boutiques (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tarif_id INTEGER NOT NULL REFERENCES loc_tarifs(id),
    numero TEXT NOT NULL,
    libelle TEXT,
    superficie REAL DEFAULT 0,
    statut TEXT NOT NULL DEFAULT 'disponible',
    notes TEXT,
    date_creation TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS lettres_notification (
    id INTEGER PRIMARY KEY,
    numero_lettre TEXT UNIQUE,
    lot_id TEXT,
    module TEXT,
    type_lettre TEXT DEFAULT "relance",
    statut TEXT DEFAULT "brouillon",
    date_generation TEXT,
    date_envoi TEXT,
    agent_id INTEGER,
    nb_redevables INTEGER DEFAULT 0,
    montant_total REAL DEFAULT 0,
    notes TEXT,
    date_creation TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS lettres_details (
    id INTEGER PRIMARY KEY,
    lettre_id INTEGER,
    avis_id INTEGER,
    declaration_id INTEGER,
    contribuable_id INTEGER,
    montant_du REAL,
    statut_envoi TEXT DEFAULT "inclus"
);

CREATE TABLE IF NOT EXISTS regie_valeurs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_valeur TEXT DEFAULT 'timbre',
    designation TEXT NOT NULL,
    valeur_unitaire REAL NOT NULL,
    nb_unites_carnet INTEGER NOT NULL,
    actif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS regie_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    actif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS regie_employes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    matricule TEXT,
    nom TEXT NOT NULL,
    prenom TEXT,
    service_id INTEGER REFERENCES regie_services(id),
    actif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS regie_paquets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    valeur_id INTEGER REFERENCES regie_valeurs(id),
    numero_paquet TEXT UNIQUE,
    num_premier TEXT,
    num_dernier TEXT,
    quantite_vignettes INTEGER,
    date_reception TEXT,
    statut TEXT DEFAULT 'recu',
    agent_id INTEGER,
    date_creation TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS regie_bordereaux (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE,
    date_versement TEXT,
    montant_total REAL DEFAULT 0,
    agent_id INTEGER,
    date_creation TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS regie_carnets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paquet_id INTEGER REFERENCES regie_paquets(id),
    valeur_id INTEGER REFERENCES regie_valeurs(id),
    numero_carnet TEXT UNIQUE,
    num_premier INTEGER,
    num_dernier INTEGER,
    statut TEXT DEFAULT 'en_stock',
    service_id INTEGER REFERENCES regie_services(id),
    employe_id INTEGER REFERENCES regie_employes(id),
    date_affectation TEXT,
    date_versement_employe TEXT,
    date_versement_percepteur TEXT,
    bordereau_id INTEGER REFERENCES regie_bordereaux(id),
    montant_verse REAL DEFAULT 0,
    ecart REAL DEFAULT 0,
    observation TEXT
);
CREATE TABLE IF NOT EXISTS bordereaux_versement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mois INTEGER NOT NULL,
    annee INTEGER NOT NULL,
    fichier_source TEXT,
    date_import DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_general REAL,
    UNIQUE(mois, annee)
);

CREATE TABLE IF NOT EXISTS lignes_recettes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bordereau_id INTEGER REFERENCES bordereaux_versement(id) ON DELETE CASCADE,
    code_budgetaire TEXT,
    nature_recette TEXT,
    montant REAL,
    feuille_emission TEXT
);

CREATE TABLE IF NOT EXISTS bordereaux_emission (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bordereau_id INTEGER REFERENCES bordereaux_versement(id) ON DELETE CASCADE,
    numero_bordereau INTEGER,
    rubrique TEXT,
    code_budgetaire TEXT,
    intitule TEXT,
    montant_present REAL,
    report_anterieurs REAL,
    total REAL,
    chemin_pdf TEXT,
    chemin_xlsx TEXT,
    date_generation DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS emission_config (
    annee INTEGER PRIMARY KEY,
    premiere_partie_mode TEXT DEFAULT 'auto',
    premiere_partie_valeur REAL DEFAULT 0.0,
    deuxieme_partie_mode TEXT DEFAULT 'vide',
    deuxieme_partie_valeur REAL DEFAULT 0.0,
    notes TEXT,
    date_modification TEXT DEFAULT CURRENT_TIMESTAMP
);

    ''')
        conn.commit()
        _set_schema_version(conn, 1)

    # -- Migrations version 1→2 : colonnes manquantes bulletins etc.
    if current_ver < 2:
        # -- Migrations colonnes bulletins
        for _col, _typ in [('numero_quittance','TEXT'), ('date_quittance','TEXT'), ('motif_rejet','TEXT'), ('numero_versement','TEXT'), ('date_encaissement','TEXT')]:
            try:
                c.execute(f'ALTER TABLE bulletins ADD COLUMN {_col} {_typ}')
                conn.commit()
                _logger.info(f'Colonne bulletins.{_col} ajoutée')
            except Exception as e:
                _logger.debug(f'Colonne bulletins.{_col} existe déjà: {e}')

        # -- Migrations tarifs TNB surface
        for _col, _typ in [('surface_min', 'REAL DEFAULT 0'), ('surface_max', 'REAL')]:
            try:
                c.execute(f'ALTER TABLE tarifs ADD COLUMN {_col} {_typ}')
                conn.commit()
                _logger.info(f'Colonne tarifs.{_col} ajoutée')
            except Exception as e:
                _logger.debug(f'Colonne tarifs.{_col} existe déjà: {e}')

        # -- Migrations communes config
        for _col, _typ in [('president_fr', 'TEXT'), ('president_ar', 'TEXT'), ('region_ar', 'TEXT'), ('province_ar', 'TEXT'), ('logo', 'TEXT')]:
            try:
                c.execute(f'ALTER TABLE communes ADD COLUMN {_col} {_typ}')
                conn.commit()
                _logger.info(f'Colonne communes.{_col} ajoutée')
            except Exception as e:
                _logger.debug(f'Colonne communes.{_col} existe déjà: {e}')

        # -- Migrations bordereaux_emission
        try:
            c.execute('ALTER TABLE bordereaux_emission ADD COLUMN code_budgetaire TEXT')
            conn.commit()
            _logger.info('Colonne bordereaux_emission.code_budgetaire ajoutée')
        except Exception as e:
            _logger.debug(f'Colonne bordereaux_emission.code_budgetaire existe déjà: {e}')

        _set_schema_version(conn, 2)

    # -- Migrations version 2→3 : table emission_config
    if current_ver < 3:
        try:
            c.execute('''
                CREATE TABLE IF NOT EXISTS emission_config (
                    annee INTEGER PRIMARY KEY,
                    premiere_partie_mode TEXT DEFAULT 'auto',
                    premiere_partie_valeur REAL DEFAULT 0.0,
                    deuxieme_partie_mode TEXT DEFAULT 'vide',
                    deuxieme_partie_valeur REAL DEFAULT 0.0,
                    notes TEXT,
                    date_modification TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
            _logger.info('Table emission_config créée')
        except Exception as e:
            _logger.error(f"Erreur lors de la création de la table emission_config: {e}")

        _set_schema_version(conn, 3)

    # ── Données initiales (uniquement si version 0) ──────────────
    import hashlib as _h
    _DEFAULT_CONFIG = 'config.json'
    cfg = None
    if os.path.exists(_DEFAULT_CONFIG):
        with open(_DEFAULT_CONFIG, 'r', encoding='utf-8') as f:
            cfg = json.load(f)

    # Rôles
    roles_default = [
        ('super_admin',1,1,1,1,1,1,1),('admin',1,1,1,1,1,1,1),
        ('agent_assiette',1,1,0,1,0,0,0),('regisseur',0,0,0,1,1,0,1),
        ('consultant',0,0,0,1,0,0,0),
    ]
    for r in roles_default:
        c.execute('''INSERT OR IGNORE INTO roles
            (nom,peut_ajouter,peut_modifier,peut_supprimer,peut_voir,
             peut_valider_paiement,peut_config,peut_creer_bulletin)
            VALUES (?,?,?,?,?,?,?,?)''', r)
    conn.commit()

    # App Modules par défaut
    app_modules_default = [
        ('TNB', 'Taxe sur les Terrains Urbains Non Bâtis', '', 1, 10),
        ('DEBITS_BOISSONS', 'Taxe sur les Débits de Boissons', '', 1, 20),
        ('STATIONNEMENT', 'Taxe de Stationnement / TPV', '', 1, 30),
        ('OCCUPATION_DOMAINE', 'Occupation du Domaine Public', '', 1, 40),
        ('FOURRIERE', 'Droits de Fourrière', '', 1, 50),
        ('LOCATION_LOCAUX', 'Location des Locaux Commerciaux', '', 1, 60),
        ('AFFERMAGE_SOUKS', 'Affermage des Souks', '', 1, 70),
        ('REGIE', 'Régie & État Civil', '', 1, 80)
    ]
    for m in app_modules_default:
        c.execute('INSERT OR IGNORE INTO app_modules (code, nom, description, actif, ordre) VALUES (?,?,?,?,?)', m)
    conn.commit()

    # Commune depuis config.json
    if cfg and cfg.get('commune'):
        cm = cfg['commune']
        c.execute('''INSERT OR IGNORE INTO communes (nom,nom_ar,region,region_ar,province,province_ar,logo)
            VALUES (?,?,?,?,?,?,?)''',
            (cm.get('nom','Commune'), cm.get('nom_ar',''), cm.get('region',''),
             cm.get('region_ar',''), cm.get('province',''), cm.get('province_ar',''),
             cm.get('logo', '')))
        conn.commit()
    else:
        c.execute("INSERT OR IGNORE INTO communes (nom) VALUES ('Ma Commune')")
        conn.commit()

    # Admin par défaut
    pwd = _h.sha256('admin123'.encode()).hexdigest()
    admin_role = c.execute("SELECT id FROM roles WHERE nom='super_admin'").fetchone()
    if admin_role:
        c.execute('''INSERT OR IGNORE INTO utilisateurs (nom,prenom,email,mot_de_passe,role_id,commune_id)
            VALUES (?,?,?,?,?,1)''', ('Admin','Super','admin@commune.ma',pwd,admin_role[0]))
        conn.commit()

    # Rubriques avec codes budgétaires officiels
    rubriques_default = [
        ('30101014','Taxe sur les Terrains Urbains Non Bâtis','رسوم الأراضي الحضرية غير المبنية','TNB'),
        ('40101011','Taxe sur les Débits de Boissons','رسوم محلات بيع المشروبات','DEBITS_BOISSONS'),
        ('40201016','Taxe sur le Transport Public des Voyageurs','رسوم النقل العام للمسافرين','TRANSPORT_VOYAGEURS'),
        ('40203033','Droit de Stationnement sur les Véhicules TPV','رسوم الوقوف','STATIONNEMENT'),
        ('40102038','Redevance Occupation Temporaire Domaine Public','إتاوة احتلال الملك العام','OCCUPATION_DOMAINE'),
        ('10403032','Droits de Fourrière','حقوق الحجز','FOURRIERE'),
        ('40102026','Produit de Location des Locaux à Usage Commercial','إيرادات كراء المحلات','LOCATION_LOCAUX'),
        ('40102027','Produit d\'Affermage des Souks Communaux','إيرادات كراء الأسواق','AFFERMAGE_SOUKS'),
    ]
    for r in rubriques_default:
        if cfg and r[3] not in cfg.get('modules', [r[3]]):
            continue
        c.execute('INSERT OR IGNORE INTO rubriques (code,libelle,libelle_ar,module) VALUES (?,?,?,?)', r)
    conn.commit()

    # Arrêté fiscal initial
    c.execute('''INSERT OR IGNORE INTO arretes_fiscaux (id,numero,titre,date_effet,statut,notes)
        VALUES (1,'AF-2020-001','Arrêté Fiscal Initial','2020-01-01','actif','Tarifs initiaux par défaut')''')
    conn.commit()

    # Tarifs initiaux si table vide
    if c.execute('SELECT COUNT(*) FROM tarifs').fetchone()[0] == 0:
        tarifs_data = {
            'TNB': [('Zone A — Bien équipée',20,'DH/m²'),('Zone B — Moyennement équipée',8,'DH/m²'),('Zone C — Peu équipée',1,'DH/m²')],
            'DEBITS_BOISSONS': [('Café / Salon de thé',6,'%'),('Bar / Brasserie',10,'%'),('Restaurant',5,'%'),('Hôtel-Bar',8,'%')],
            'STATIONNEMENT': [('Grand Taxi',300,'DH/an'),('Petit Taxi',200,'DH/an'),('Autocar / Minibus',500,'DH/an')],
            'OCCUPATION_DOMAINE': [('Terrasse / Étalage',50,'DH/m²/an'),('Kiosque',80,'DH/m²/an'),('Chantier',30,'DH/m²/mois')],
            'FOURRIERE': [('Voiture particulière / jour',25,'DH/jour'),('Moto / Scooter / jour',15,'DH/jour'),('Camion / jour',50,'DH/jour'),('Frais de remorquage',150,'DH')],
        }
        for module, items in tarifs_data.items():
            rub = c.execute('SELECT id FROM rubriques WHERE module=?',(module,)).fetchone()
            if rub:
                for libelle, valeur, unite in items:
                    c.execute('INSERT INTO tarifs (rubrique_id,arrete_id,libelle,valeur,unite,date_debut) VALUES (?,1,?,?,?,?)',
                              (rub[0],libelle,valeur,unite,'2020-01-01'))
        conn.commit()

    # Paramètres par défaut
    params = [
        ('TNB','DATE_LIMITE','Date limite déclaration/paiement','31/03','date','Art.45 Loi 47-06: avant le 31 Mars'),
        ('DEBITS_BOISSONS','DATE_LIMITE','Date limite paiement','31/03','date','Avant le 31 Mars'),
        ('STATIONNEMENT','DATE_LIMITE','Date limite paiement','31/01','date','Avant le 31 Janvier'),
        ('TNB','ANNEES_DEBUT','Année de début TNB','2020','annee','Première année de taxation'),
        ('DEBITS_BOISSONS','ANNEES_DEBUT','Année de début TDB','2022','annee','Première année de taxation'),
        ('STATIONNEMENT','ANNEES_DEBUT','Année de début Stationnement','2020','annee','Première année de taxation'),
        ('OCCUPATION_DOMAINE','ANNEES_DEBUT','Année de début ODP','2020','annee','Première année de taxation'),
        ('LOCATION_LOCAUX','ANNEES_DEBUT','Année de début Location','2020','annee','Première année de taxation'),
        ('AFFERMAGE_SOUKS','ANNEES_DEBUT','Année de début Souks','2020','annee','Première année de taxation'),
    ]
    for p in params:
        c.execute('INSERT OR IGNORE INTO parametres_calcul (module,code,libelle,valeur,unite,description) VALUES (?,?,?,?,?,?)', p)
    conn.commit()

    # ── Migrations TNB v3 ────────────────────────────────────────
    # Table dossiers_tnb (1 dossier par contribuable)
    c.execute('''CREATE TABLE IF NOT EXISTS dossiers_tnb (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_dossier INTEGER UNIQUE NOT NULL,
        contribuable_id INTEGER NOT NULL REFERENCES contribuables(id),
        archive INTEGER DEFAULT 0,
        date_creation TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()

    # Table tnb_documents (pièces jointes terrain)
    c.execute('''CREATE TABLE IF NOT EXISTS tnb_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        terrain_id INTEGER NOT NULL REFERENCES terrains(id),
        nom_fichier TEXT,
        chemin TEXT,
        type_doc TEXT DEFAULT "autre",
        taille INTEGER,
        date_upload TEXT DEFAULT CURRENT_TIMESTAMP,
        agent_id INTEGER
    )''')
    conn.commit()

    # Table terrain_coproprietaires
    c.execute('''CREATE TABLE IF NOT EXISTS terrain_coproprietaires (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        terrain_id INTEGER NOT NULL REFERENCES terrains(id),
        contribuable_id INTEGER NOT NULL REFERENCES contribuables(id),
        part_indivision REAL DEFAULT 0,
        date_ajout TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(terrain_id, contribuable_id)
    )''')
    conn.commit()

    # Colonnes manquantes sur terrains
    for _col, _typ in [
        ('lotissement', 'TEXT DEFAULT ""'),
        ('archive',     'INTEGER DEFAULT 0'),
    ]:
        try:
            c.execute(f'ALTER TABLE terrains ADD COLUMN {_col} {_typ}')
            conn.commit()
            _logger.info(f'Colonne terrains.{_col} ajoutée')
        except Exception as e:
            _logger.debug(f'Colonne terrains.{_col} existe déjà: {e}')

    # Colonnes manquantes sur permis
    for _col, _typ in [
        ('date_autorisation',      'TEXT'),
        ('annee_debut_exoneration','INTEGER'),
        ('annee_fin_exoneration',  'INTEGER'),
    ]:
        try:
            c.execute(f'ALTER TABLE permis ADD COLUMN {_col} {_typ}')
            conn.commit()
            _logger.info(f'Colonne permis.{_col} ajoutée')
        except Exception as e:
            _logger.debug(f'Colonne permis.{_col} existe déjà: {e}')

    # Paramètre AMENDE_NON_DECLARATION pour TNB
    c.execute('''INSERT OR IGNORE INTO parametres_calcul
        (module, code, libelle, valeur, unite, description)
        VALUES ("TNB","AMENDE_NON_DECLARATION",
                "Amende non-déclaration (%)","15","%",
                "Pourcentage amende pour non-déclaration dans les délais")''')
    conn.commit()
    # ── Fin migrations TNB v3 ────────────────────────────────────
    # ---- Regie modules setup ----
    if c.execute('SELECT COUNT(*) FROM regie_valeurs').fetchone()[0] == 0:
        c.execute("INSERT INTO regie_valeurs (type_valeur, designation, valeur_unitaire, nb_unites_carnet) VALUES ('timbre', 'Timbre État Civil', 2, 500)")
        c.execute("INSERT INTO regie_valeurs (type_valeur, designation, valeur_unitaire, nb_unites_carnet) VALUES ('timbre', 'Timbre Légalisation', 50, 200)")
        conn.commit()
    if c.execute('SELECT COUNT(*) FROM regie_services').fetchone()[0] == 0:
        c.execute("INSERT INTO regie_services (nom) VALUES ('Légalisation des documents')")
        c.execute("INSERT INTO regie_services (nom) VALUES ('État Civil')")
        conn.commit()

    conn.close()


def get_tarif_at_date(rubrique_id: int, query_date: str) -> dict | None:
    """
    Retourne le tarif actif pour une rubrique à une date donnée.
    Supporte l'historique : si un tarif a été modifié, utilise le bon en fonction de la période.
    """
    conn = get_db()
    row = conn.execute('''
        SELECT * FROM tarifs
        WHERE rubrique_id = ?
          AND date_debut <= ?
          AND (date_fin IS NULL OR date_fin >= ?)
          AND actif = 1
        ORDER BY date_debut DESC
        LIMIT 1
    ''', (rubrique_id, query_date, query_date)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_tarifs_for_period(rubrique_id: int, date_debut: str, date_fin: str) -> list:
    """
    Retourne tous les tarifs applicables sur une période (pour calculs proratisés).
    Utile quand un tarif a changé en cours de période.
    """
    conn = get_db()
    rows = conn.execute('''
        SELECT * FROM tarifs
        WHERE rubrique_id = ?
          AND date_debut <= ?
          AND (date_fin IS NULL OR date_fin >= ?)
          AND actif = 1
        ORDER BY date_debut ASC
    ''', (rubrique_id, date_fin, date_debut)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
