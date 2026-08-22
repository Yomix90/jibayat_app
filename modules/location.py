"""modules/location.py — Blueprint Location Locaux Commerciaux"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from database import get_db
from modules.helpers import login_required, get_current_user, gen_num, get_next_seq_num, permission_required

bp = Blueprint('loc', __name__)


# ════════════════════════════════════════════════════════════
#  SYNCHRONISATION ARRÊTÉ FISCAL
# ════════════════════════════════════════════════════════════

def _sync_tarif_fiscal(conn, loc_tarif_id):
    """Synchronise un loc_tarif dans la table 'tarifs' de l'arrete fiscal actif.
    Crée le tarif s'il n'existe pas, le met à jour s'il existe deja.
    Retourne l'id du tarif fiscal créé/mis à jour.
    """
    lt = conn.execute(
        '''SELECT lt.*, s.code as sec_code, s.libelle as sec_libelle
           FROM loc_tarifs lt JOIN loc_secteurs s ON s.id=lt.secteur_id
           WHERE lt.id=?''', (loc_tarif_id,)
    ).fetchone()
    if not lt:
        return None

    # Rubrique LOCATION_LOCAUX
    rub = conn.execute(
        "SELECT id FROM rubriques WHERE module='LOCATION_LOCAUX' LIMIT 1"
    ).fetchone()
    if not rub:
        return None

    # Arrêté fiscal actif
    arrete = conn.execute(
        "SELECT id FROM arretes_fiscaux WHERE statut='actif' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not arrete:
        # Pas d'arrêté actif — on tente 'en_preparation'
        arrete = conn.execute(
            "SELECT id FROM arretes_fiscaux ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not arrete:
        return None

    # Code unique pour ce tarif : SEC-SECTEUR-CODE_TARIF_ID
    code_tarif = f"{lt['sec_code']}-T{loc_tarif_id}"
    libelle = f"{lt['sec_libelle']} — {lt['libelle']}"
    unite   = lt['unite']
    valeur  = float(lt['valeur'])
    today   = date.today().isoformat()

    # Vérifier si un tarif fiscal est déjà lié
    existing_fiscal_id = lt['tarif_fiscal_id']
    if existing_fiscal_id:
        # Mettre à jour
        conn.execute(
            '''UPDATE tarifs SET libelle=?, valeur=?, unite=?, code_tarif=? WHERE id=?''',
            (libelle, valeur, unite, code_tarif, existing_fiscal_id)
        )
        return existing_fiscal_id
    else:
        # Désactiver l'ancien tarif avec ce code s'il existe
        conn.execute(
            '''UPDATE tarifs SET actif=0, date_fin=? 
               WHERE rubrique_id=? AND code_tarif=? AND actif=1''',
            (today, rub['id'], code_tarif)
        )
        # Créer le nouveau tarif dans l'arrêté
        conn.execute(
            '''INSERT INTO tarifs 
               (rubrique_id, arrete_id, code_tarif, libelle, valeur, unite, date_debut, actif)
               VALUES (?,?,?,?,?,?,?,1)''',
            (rub['id'], arrete['id'], code_tarif, libelle, valeur, unite, today)
        )
        fiscal_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        # Lier dans loc_tarifs
        conn.execute(
            'UPDATE loc_tarifs SET tarif_fiscal_id=? WHERE id=?',
            (fiscal_id, loc_tarif_id)
        )
        return fiscal_id


def _sync_all_tarifs_fiscal():
    """Synchronise tous les loc_tarifs existants sans tarif_fiscal_id."""
    conn = get_db()
    tarifs = conn.execute(
        'SELECT id FROM loc_tarifs WHERE tarif_fiscal_id IS NULL'
    ).fetchall()
    count = 0
    for t in tarifs:
        result = _sync_tarif_fiscal(conn, t['id'])
        if result:
            count += 1
    conn.commit()
    conn.close()
    return count


# ════════════════════════════════════════════════════════════
#  HELPERS TARIF — Priorité : Boutique/Tarif > Secteur > Arrêté > Bail
# ════════════════════════════════════════════════════════════

def _get_tarif_boutique(boutique_id=None, tarif_id=None):
    """Retourne le loc_tarif depuis boutique ou tarif_id."""
    conn = get_db()
    row = None
    if boutique_id:
        row = conn.execute(
            'SELECT t.* FROM loc_tarifs t JOIN loc_boutiques b ON b.tarif_id=t.id WHERE b.id=?',
            (boutique_id,)
        ).fetchone()
    elif tarif_id:
        row = conn.execute('SELECT * FROM loc_tarifs WHERE id=?', (tarif_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _get_valeur_tarif_arrete(tarif_fiscal_id, mois_date=None):
    """Retourne la valeur du tarif depuis l'arrete fiscal.
    Si mois_date est fourni, cherche le tarif en vigueur pour ce mois.
    Sinon retourne le tarif actif (actif=1).
    """
    conn = get_db()
    if mois_date:
        # Tarif en vigueur a cette date: chercher par code_tarif du tarif lie
        ref_tarif = conn.execute('SELECT code_tarif, rubrique_id FROM tarifs WHERE id=?',
                                 (tarif_fiscal_id,)).fetchone()
        if ref_tarif:
            row = conn.execute(
                '''SELECT t.valeur FROM tarifs t
                   WHERE t.rubrique_id=? AND t.code_tarif=?
                     AND t.date_debut <= ?
                     AND (t.date_fin IS NULL OR t.date_fin > ?)
                   ORDER BY t.date_debut DESC LIMIT 1''',
                (ref_tarif['rubrique_id'], ref_tarif['code_tarif'],
                 mois_date.isoformat(), mois_date.isoformat())
            ).fetchone()
            if not row:
                # Fallback: le plus recent avant cette date
                row = conn.execute(
                    '''SELECT t.valeur FROM tarifs t
                       WHERE t.rubrique_id=? AND t.code_tarif=?
                         AND t.date_debut <= ?
                       ORDER BY t.date_debut DESC LIMIT 1''',
                    (ref_tarif['rubrique_id'], ref_tarif['code_tarif'],
                     mois_date.isoformat())
                ).fetchone()
            conn.close()
            return float(row['valeur']) if row else None
        conn.close()
        return None
    else:
        row = conn.execute('SELECT valeur FROM tarifs WHERE id=?', (tarif_fiscal_id,)).fetchone()
        conn.close()
        return float(row['valeur']) if row else None


def _get_historique_tarif_bail(bail):
    """Retourne l'historique des tarifs fiscaux pour ce bail (par arretes).
    Liste de dicts: {date_debut, date_fin, valeur, source}
    """
    conn = get_db()
    tarif_fiscal_id = None
    type_tarif = 'fixe'
    superficie = float(bail.get('superficie') or 0)

    # Recuperer le loc_tarif lie
    loc_t = None
    if bail.get('boutique_id'):
        loc_t = conn.execute(
            'SELECT t.* FROM loc_tarifs t JOIN loc_boutiques b ON b.tarif_id=t.id WHERE b.id=?',
            (bail['boutique_id'],)
        ).fetchone()
    elif bail.get('tarif_id'):
        loc_t = conn.execute('SELECT * FROM loc_tarifs WHERE id=?', (bail['tarif_id'],)).fetchone()

    if loc_t and loc_t['tarif_fiscal_id']:
        tarif_fiscal_id = loc_t['tarif_fiscal_id']
        type_tarif = loc_t['type_tarif']
        # Recuperer tous les tarifs avec ce code dans tous les arretes
        ref = conn.execute('SELECT code_tarif, rubrique_id FROM tarifs WHERE id=?',
                           (tarif_fiscal_id,)).fetchone()
        if ref:
            rows = conn.execute(
                '''SELECT t.valeur, t.date_debut, t.date_fin,
                          af.numero as arrete_num, af.date_effet
                   FROM tarifs t
                   LEFT JOIN arretes_fiscaux af ON af.id=t.arrete_id
                   WHERE t.rubrique_id=? AND t.code_tarif=?
                   ORDER BY t.date_debut ASC''',
                (ref['rubrique_id'], ref['code_tarif'])
            ).fetchall()
            conn.close()
            result = []
            for r in rows:
                try:
                    dd = date.fromisoformat(r['date_debut'][:10])
                except Exception:
                    continue
                df = None
                if r['date_fin']:
                    try: df = date.fromisoformat(r['date_fin'][:10])
                    except Exception: pass
                valeur = float(r['valeur'])
                if type_tarif == 'm2' and superficie > 0:
                    valeur = round(valeur * superficie, 2)
                result.append({'date_debut': dd, 'date_fin': df, 'valeur': valeur,
                               'arrete': r['arrete_num'] or ''})
            return result

    conn.close()
    return []


def _calculer_loyer(bail):
    """Calcule le loyer mensuel d'un bail selon la priorité :
    Tarif arrêté fiscal actif > Boutique/loc_tarif > loyer_mensuel du bail.
    bail doit être un dict.
    """
    superficie = float(bail.get('superficie') or 0)

    # 1. Priorité: tarif de l'arrêté fiscal (via tarif_fiscal_id du loc_tarif)
    tarif_row = _get_tarif_boutique(
        boutique_id=bail.get('boutique_id'),
        tarif_id=bail.get('tarif_id')
    )
    if tarif_row and tarif_row.get('tarif_fiscal_id'):
        valeur_arrete = _get_valeur_tarif_arrete(tarif_row['tarif_fiscal_id'])
        if valeur_arrete is not None:
            if tarif_row['type_tarif'] == 'm2' and superficie > 0:
                return round(valeur_arrete * superficie, 2)
            return valeur_arrete

    # 2. Fallback: valeur brute du loc_tarif
    if tarif_row:
        if tarif_row['type_tarif'] == 'm2' and superficie > 0:
            return round(float(tarif_row['valeur']) * superficie, 2)
        return float(tarif_row['valeur'])

    # 3. Ancien secteur (compatibilité)
    if bail.get('secteur_id'):
        conn = get_db()
        s = conn.execute('SELECT * FROM loc_secteurs WHERE id=?', (bail['secteur_id'],)).fetchone()
        conn.close()
        if s:
            if s['type_tarif'] == 'm2' and superficie > 0:
                return round(float(s['tarif_mensuel']) * superficie, 2)
            return float(s['tarif_mensuel'])

    # 4. Fallback: loyer du bail
    return float(bail.get('loyer_mensuel') or 0)


def _get_tarifs_historiques_arrete(ref_local):
    """Recupere les tarifs de l'arrete fiscal pour un local (ref_local)."""
    conn = get_db()
    rows = conn.execute(
        '''SELECT t.valeur, t.date_debut, t.date_fin
           FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
           WHERE r.module='LOCATION_LOCAUX'
             AND (t.code_tarif=? OR t.libelle=? OR t.code_tarif LIKE ?)
           ORDER BY t.date_debut ASC''',
        (ref_local, ref_local, f'%{ref_local}%')
    ).fetchall()
    conn.close()
    tarifs = []
    for row in rows:
        try:
            dd = datetime.strptime(row['date_debut'][:10], '%Y-%m-%d').date()
        except Exception:
            continue
        df = None
        if row['date_fin']:
            try:
                df = datetime.strptime(row['date_fin'][:10], '%Y-%m-%d').date()
            except Exception:
                pass
        tarifs.append({'date_debut': dd, 'date_fin': df, 'valeur': float(row['valeur'])})
    return tarifs


def _get_tarif_pour_mois(tarifs_historiques, mois_date, loyer_fallback=0):
    applicable = None
    for t in tarifs_historiques:
        if t['date_debut'] <= mois_date:
            if t['date_fin'] is None or t['date_fin'] > mois_date:
                applicable = t['valeur']
    if applicable is None:
        for t in reversed(tarifs_historiques):
            if t['date_debut'] <= mois_date:
                applicable = t['valeur']
                break
    return applicable if applicable is not None else loyer_fallback


def _calculer_mois_non_payes(bail_id, date_debut_str, date_fin_str=None, bail=None):
    """Calcule les mois non payes avec le loyer applicable a chaque mois."""
    try:
        date_debut = datetime.strptime(date_debut_str[:10], '%Y-%m-%d').date()
    except Exception:
        return []

    aujourd_hui = date.today()
    if date_fin_str:
        try:
            date_fin = min(datetime.strptime(date_fin_str[:10], '%Y-%m-%d').date(), aujourd_hui)
        except Exception:
            date_fin = aujourd_hui
    else:
        date_fin = aujourd_hui

    conn = get_db()
    payes_rows = conn.execute(
        "SELECT notes FROM declarations WHERE module='LOCATION_LOCAUX' AND reference_id=? AND statut='paye'",
        (bail_id,)
    ).fetchall()
    conn.close()

    import re as _re
    PATTERN_MOIS = _re.compile(r'^\d{4}-\d{2}$')
    mois_payes = set()
    for row in payes_rows:
        if row['notes']:
            partie_mois = row['notes'].split('|')[0]
            for m in partie_mois.split(','):
                m = m.strip()
                if m and PATTERN_MOIS.match(m):
                    mois_payes.add(m)

    # Loyer mensuel depuis la hiérarchie (pour les mois sans tarif spécifique d'arrêté)
    loyer_fixe = _calculer_loyer(bail) if bail else 0
    historique_tarifs_arrete = _get_historique_tarif_bail(bail) if bail else []

    MOIS_FR = ['Janvier', 'Fevrier', 'Mars', 'Avril', 'Mai', 'Juin',
               'Juillet', 'Aout', 'Septembre', 'Octobre', 'Novembre', 'Decembre']

    mois_non_payes = []
    courant = date(date_debut.year, date_debut.month, 1)
    fin_iter = date(date_fin.year, date_fin.month, 1)

    while courant <= fin_iter:
        key = courant.strftime('%Y-%m')
        if key not in mois_payes:
            # Chercher le tarif applicable a ce mois depuis l'arrête fiscal
            tarif_mois = loyer_fixe
            tarif_source = 'bail'
            if historique_tarifs_arrete:
                for h in reversed(historique_tarifs_arrete):
                    if h['date_debut'] <= courant:
                        if h['date_fin'] is None or h['date_fin'] > courant:
                            tarif_mois = h['valeur']
                            tarif_source = f'arrete:{h["arrete"]}'
                            break
                else:
                    # Aucun tarif actif ce mois: prendre le plus recent avant
                    for h in reversed(historique_tarifs_arrete):
                        if h['date_debut'] <= courant:
                            tarif_mois = h['valeur']
                            tarif_source = f'arrete:{h["arrete"]}'
                            break
            elif bail and (bail.get('boutique_id') or bail.get('tarif_id')):
                tarif_source = 'loc_tarif'
            mois_non_payes.append({
                'mois': key,
                'label': f"{MOIS_FR[courant.month - 1]} {courant.year}",
                'tarif': tarif_mois,
                'tarif_source': tarif_source
            })
        courant = courant + relativedelta(months=1)

    return mois_non_payes


def _grouper_par_tarif(mois_list):
    if not mois_list:
        return []
    groupes = []
    current = None
    for m in mois_list:
        if current is None or m['tarif'] != current['tarif']:
            if current:
                groupes.append(current)
            current = {
                'tarif': m['tarif'], 'nb_mois': 1,
                'montant': m['tarif'],
                'mois_debut': m['mois'], 'mois_fin': m['mois'],
                'mois': [m['mois']]
            }
        else:
            current['nb_mois'] += 1
            current['montant'] = round(current['montant'] + m['tarif'], 2)
            current['mois_fin'] = m['mois']
            current['mois'].append(m['mois'])
    if current:
        groupes.append(current)
    return groupes


# ════════════════════════════════════════════════════════════
#  LISTE & CRUD BAUX
# ════════════════════════════════════════════════════════════

@bp.route('/location-locaux')
@login_required
def loc_liste():
    user = get_current_user()
    conn = get_db()
    items = conn.execute('''
        SELECT b.*, c.nom, c.prenom, c.raison_sociale, c.numero as ctb_num, c.cin, c.telephone,
               s.libelle as secteur_libelle, s.code as secteur_code,
               lt.libelle as tarif_libelle, lt.valeur as tarif_valeur, lt.type_tarif,
               bo.numero as boutique_numero, bo.libelle as boutique_libelle,
               bo.superficie as boutique_superficie
        FROM baux b
        JOIN contribuables c ON b.contribuable_id=c.id
        LEFT JOIN loc_secteurs s ON s.id=b.secteur_id
        LEFT JOIN loc_tarifs lt ON lt.id=b.tarif_id
        LEFT JOIN loc_boutiques bo ON bo.id=b.boutique_id
        WHERE b.actif=1 ORDER BY b.date_creation DESC
    ''').fetchall()
    contribuables = conn.execute(
        'SELECT id,numero,nom,prenom,raison_sociale FROM contribuables WHERE actif=1'
    ).fetchall()
    secteurs = conn.execute('SELECT * FROM loc_secteurs WHERE actif=1 ORDER BY ordre,libelle').fetchall()
    # Boutiques disponibles (non affectées à un bail actif)
    boutiques_dispo = conn.execute('''
        SELECT bo.*, lt.libelle as tarif_libelle, lt.valeur as tarif_valeur, lt.type_tarif,
               s.libelle as secteur_libelle, s.code as secteur_code
        FROM loc_boutiques bo
        JOIN loc_tarifs lt ON lt.id=bo.tarif_id
        JOIN loc_secteurs s ON s.id=lt.secteur_id
        WHERE bo.statut='disponible'
        ORDER BY s.code, bo.numero
    ''').fetchall()
    # Info commune (avant conn.close)
    commune_name = ""
    province_name = ""
    try:
        tb = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='communes'").fetchone()
        if tb:
            ci = conn.execute(
                "SELECT c.nom as commune, c.province FROM communes c JOIN utilisateurs u ON u.commune_id=c.id WHERE u.id=?",
                (user["id"],)
            ).fetchone()
            if ci:
                commune_name = ci["commune"]
                province_name = ci["province"] or ""
    except Exception:
        pass
    next_numero = get_next_seq_num('baux', 'numero', conn)
    conn.close()
    return render_template("location/loc_liste.html", user=user, items=items,
                           contribuables=contribuables, secteurs=secteurs,
                           boutiques_dispo=boutiques_dispo,
                           commune=commune_name, province=province_name, next_numero=next_numero)

@bp.route('/location-locaux/ajouter', methods=['POST'])
@login_required
@permission_required('ajouter', 'loc')
def loc_ajouter():
    f = request.form
    conn = get_db()
    num = f.get('numero', '').strip() or get_next_seq_num('baux', 'numero', conn)

    boutique_id = f.get('boutique_id') or None
    tarif_id = None
    secteur_id = None
    superficie = float(f.get('superficie') or 0)

    if boutique_id:
        # Récupérer tarif et secteur depuis la boutique
        bo = conn.execute(
            'SELECT b.*, t.secteur_id, t.id as tid FROM loc_boutiques b JOIN loc_tarifs t ON t.id=b.tarif_id WHERE b.id=?',
            (boutique_id,)
        ).fetchone()
        if bo:
            tarif_id = bo['tid']
            secteur_id = bo['secteur_id']
            if not superficie:
                superficie = float(bo['superficie'] or 0)
            # Marquer boutique comme exploitée
            conn.execute("UPDATE loc_boutiques SET statut='exploitee' WHERE id=?", (boutique_id,))
    else:
        tarif_id = f.get('tarif_id') or None
        secteur_id = f.get('secteur_id') or None

    conn.execute(
        '''INSERT INTO baux (numero,contribuable_id,commune_id,ref_local,adresse,superficie,loyer_mensuel,
           date_debut,date_fin,secteur_id,tarif_id,boutique_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (num, f['contribuable_id'], 1,
         f.get('ref_local', ''), f.get('adresse', ''),
         superficie, f.get('loyer_mensuel', 0) or 0,
         f.get('date_debut', ''), f.get('date_fin', ''),
         secteur_id, tarif_id, boutique_id)
    )
    conn.commit()
    conn.close()
    flash(f'Bail N° {num} ajouté ✅', 'success')
    return redirect(url_for('loc.loc_liste'))


@bp.route('/location-locaux/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('modifier', 'loc')
def loc_modifier(id):
    f = request.form
    conn = get_db()
    boutique_id = f.get('boutique_id') or None
    tarif_id = f.get('tarif_id') or None
    secteur_id = f.get('secteur_id') or None
    conn.execute(
        '''UPDATE baux SET ref_local=?, adresse=?, superficie=?, loyer_mensuel=?,
           date_debut=?, date_fin=?, statut=?, secteur_id=?, tarif_id=?, boutique_id=?
           WHERE id=?''',
        (f.get('ref_local', ''), f.get('adresse', ''),
         float(f.get('superficie') or 0), float(f.get('loyer_mensuel') or 0),
         f.get('date_debut', ''), f.get('date_fin', ''),
         f.get('statut', 'actif'), secteur_id, tarif_id, boutique_id, id)
    )
    conn.commit()
    conn.close()
    flash('Bail modifie', 'success')
    return redirect(url_for('loc.loc_liste'))


@bp.route('/location-locaux/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('supprimer', 'loc')
def loc_supprimer(id):
    if not get_current_user()['peut_config']:
        flash('Acces refuse', 'danger')
        return redirect(url_for('loc.loc_liste'))
    conn = get_db()
    nbull = conn.execute('SELECT COUNT(*) as c FROM bulletins b JOIN declarations d ON d.id=b.declaration_id WHERE d.reference_id=? AND d.module="LOCATION_LOCAUX"', (id,)).fetchone()['c']
    if nbull > 0:
        conn.execute('UPDATE baux SET actif=0, statut="resilie" WHERE id=?', (id,))
        conn.commit()
        flash(f'Bail archive (resilie) — {nbull} bulletin(s) conserves', 'warning')
    else:
        conn.execute('UPDATE loc_boutiques SET statut="disponible" WHERE id=(SELECT boutique_id FROM baux WHERE id=?)', (id,))
        conn.execute('DELETE FROM baux WHERE id=?', (id,))
        conn.commit()
        flash('Bail supprime', 'success')
    conn.close()
    return redirect(url_for('loc.loc_liste'))


@bp.route('/location-locaux/<int:id>')
@login_required
def loc_detail(id):
    user = get_current_user()
    conn = get_db()
    item = conn.execute(
        '''SELECT b.*, c.nom, c.prenom, c.raison_sociale, c.telephone, c.cin, c.rc, c.id as ctb_id, c.numero as ctb_num,
                  bo.numero as boutique_numero, bo.libelle as boutique_libelle, bo.statut as boutique_statut,
                  lt.libelle as tarif_libelle, lt.valeur as tarif_valeur, lt.type_tarif,
                  s.libelle as secteur_libelle, s.code as secteur_code
           FROM baux b JOIN contribuables c ON b.contribuable_id=c.id
           LEFT JOIN loc_boutiques bo ON bo.id=b.boutique_id
           LEFT JOIN loc_tarifs lt ON lt.id=b.tarif_id
           LEFT JOIN loc_secteurs s ON s.id=b.secteur_id
           WHERE b.id=?''', (id,)
    ).fetchone()
    if not item:
        flash('Bail introuvable', 'danger')
        conn.close()
        return redirect(url_for('loc.loc_liste'))

    declarations = conn.execute(
        '''SELECT d.*, b2.numero_bulletin FROM declarations d
           LEFT JOIN bulletins b2 ON b2.declaration_id=d.id
           WHERE d.module="LOCATION_LOCAUX" AND d.reference_id=? ORDER BY d.annee DESC, d.trimestre DESC''', (id,)
    ).fetchall()
    conn.close()

    return render_template('location/loc_detail.html', user=user, item=item, declarations=declarations)



# ════════════════════════════════════════════════════════════
#  PAIEMENT
# ════════════════════════════════════════════════════════════

@bp.route('/location-locaux/<int:id>/paiement', methods=['GET'])
@login_required
def loc_paiement(id):
    user = get_current_user()
    conn = get_db()
    bail = conn.execute(
        '''SELECT b.*, c.nom, c.prenom, c.raison_sociale, c.id as ctb_id, c.numero as ctb_num,
                  bo.numero as boutique_numero, bo.libelle as boutique_libelle,
                  lt.libelle as tarif_libelle, lt.valeur as tarif_valeur, lt.type_tarif,
                  s.libelle as secteur_libelle, s.code as secteur_code
           FROM baux b JOIN contribuables c ON b.contribuable_id=c.id
           LEFT JOIN loc_boutiques bo ON bo.id=b.boutique_id
           LEFT JOIN loc_tarifs lt ON lt.id=b.tarif_id
           LEFT JOIN loc_secteurs s ON s.id=b.secteur_id
           WHERE b.id=?''', (id,)
    ).fetchone()
    if not bail:
        flash('Bail introuvable', 'danger')
        conn.close()
        return redirect(url_for('loc.loc_liste'))
    bail = dict(bail)

    historique = conn.execute(
        '''SELECT d.*, b2.numero_bulletin, b2.statut as bull_statut
           FROM declarations d LEFT JOIN bulletins b2 ON b2.declaration_id=d.id
           WHERE d.module='LOCATION_LOCAUX' AND d.reference_id=?
           ORDER BY d.date_creation DESC''', (id,)
    ).fetchall()

    params = conn.execute(
        "SELECT * FROM parametres_calcul WHERE module='LOCATION_LOCAUX' ORDER BY code"
    ).fetchall()

    tarifs_historiques_rows = conn.execute(
        '''SELECT t.valeur, t.date_debut, t.date_fin, t.actif,
                  af.numero as arrete_num, af.titre as arrete_titre
           FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
           LEFT JOIN arretes_fiscaux af ON t.arrete_id=af.id
           WHERE r.module='LOCATION_LOCAUX'
             AND (t.code_tarif=? OR t.libelle=? OR t.code_tarif LIKE ?)
           ORDER BY t.date_debut ASC''',
        (bail['ref_local'], bail['ref_local'], f"%{bail['ref_local']}%")
    ).fetchall()

    tarif_arrete = conn.execute(
        '''SELECT t.valeur FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
           WHERE r.module='LOCATION_LOCAUX'
             AND (t.code_tarif=? OR t.libelle=? OR t.code_tarif LIKE ?) AND t.actif=1
           ORDER BY t.date_debut DESC LIMIT 1''',
        (bail['ref_local'], bail['ref_local'], f"%{bail['ref_local']}%")
    ).fetchone()

    secteurs_list = conn.execute('SELECT * FROM loc_secteurs WHERE actif=1 ORDER BY ordre,libelle').fetchall()
    conn.close()

    # Loyer calculé depuis la hiérarchie
    loyer_mensuel_actuel = _calculer_loyer(bail)

    mois_non_payes = _calculer_mois_non_payes(
        id, bail['date_debut'] or '', bail['date_fin'] or '', bail=bail
    )
    nb_mois = len(mois_non_payes)
    total_du = round(sum(m['tarif'] for m in mois_non_payes), 2)
    groupes_tarifs = _grouper_par_tarif(mois_non_payes)

    return render_template(
        'location/loc_paiement.html',
        user=user, bail=bail, ref_id=id,
        loyer_mensuel=loyer_mensuel_actuel,
        loyer_fallback=float(bail.get('loyer_mensuel') or 0),
        tarif_arrete=tarif_arrete,
        tarifs_historiques=list(tarifs_historiques_rows),
        mois_non_payes=mois_non_payes,
        nb_mois=nb_mois, total_du=total_du,
        groupes_tarifs=groupes_tarifs,
        historique=historique, params=params,
        secteur=None, secteurs=secteurs_list,
        today=date.today().isoformat()
    )


@bp.route('/location-locaux/<int:id>/payer', methods=['POST'])
@login_required
@permission_required('creer_bulletin')
def loc_payer(id):
    user = get_current_user()
    f = request.form
    conn = get_db()

    bail = conn.execute(
        '''SELECT b.*, c.id as ctb_id FROM baux b
           JOIN contribuables c ON b.contribuable_id=c.id WHERE b.id=?''', (id,)
    ).fetchone()
    if not bail:
        flash('Bail introuvable', 'danger')
        conn.close()
        return redirect(url_for('loc.loc_liste'))
    bail = dict(bail)

    mois_selectionnes = f.getlist('mois_selectionnes')
    mode_paiement = f.get('mode_paiement', 'especes')
    notes_extra = f.get('notes', '')

    if not mois_selectionnes:
        flash('Veuillez selectionner au moins un mois', 'warning')
        conn.close()
        return redirect(url_for('loc.loc_paiement', id=id))

    nb_mois = len(mois_selectionnes)
    loyer_mensuel = _calculer_loyer(bail)
    montant_total = round(loyer_mensuel * nb_mois, 2)

    mois_str = ', '.join(sorted(mois_selectionnes))
    numero_decl = gen_num('LOC-DECL', 'declarations')
    today_str = date.today().isoformat()
    annee = int(sorted(mois_selectionnes)[-1][:4])

    conn.execute(
        '''INSERT INTO declarations
           (numero, module, reference_id, contribuable_id, commune_id,
            annee, base_calcul, taux, montant_principal, penalite_retard,
            majoration, amende_non_declaration, montant_total,
            statut, date_declaration, date_echeance, notes)
           VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?)''',
        (numero_decl, 'LOCATION_LOCAUX', id, bail['ctb_id'], 1,
         annee, loyer_mensuel, 0, montant_total, 0, 0, 0, montant_total,
         'paye', today_str, today_str,
         mois_str + (f' | {notes_extra}' if notes_extra else ''))
    )
    decl_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    numero_bull = gen_num('BUL', 'bulletins')
    conn.execute(
        '''INSERT INTO bulletins
           (numero_bulletin, declaration_id, contribuable_id, commune_id,
            montant, mode_paiement, date_paiement, statut, agent_id, notes)
           VALUES (?,?,?,?, ?,?,?,?,?,?)''',
        (numero_bull, decl_id, bail['ctb_id'], 1,
         montant_total, mode_paiement, today_str, 'valide',
         user['id'] if user else None,
         f"Location locaux — {nb_mois} mois: {mois_str}")
    )
    conn.commit()
    conn.close()

    flash(f'Paiement enregistre — {nb_mois} mois — {montant_total:.2f} DH — Bulletin: {numero_bull}', 'success')
    return redirect(url_for('loc.loc_paiement', id=id))


# ════════════════════════════════════════════════════════════
#  SECTEURS, TARIFS, BOUTIQUES — Hiérarchie de configuration
# ════════════════════════════════════════════════════════════

@bp.route('/location-locaux/tarifs/sync-fiscal', methods=['POST'])
@login_required
@permission_required('config')
def loc_sync_tarifs_fiscal():
    count = _sync_all_tarifs_fiscal()
    flash(f"{count} tarif(s) synchronise(s) avec l'arrete fiscal.", "success")
    return redirect(url_for('loc.loc_secteurs'))

@bp.route('/location-locaux/tarifs/<int:id>/sync-fiscal', methods=['POST'])
@login_required
@permission_required('config')
def loc_sync_tarif_un(id):
    """Synchronise un seul tarif loc_tarif avec l'arrete fiscal actif."""
    if not get_current_user()['peut_config']:
        flash('Acces refuse', 'danger')
        return redirect(url_for('loc.loc_secteurs'))
    conn = get_db()
    result = _sync_tarif_fiscal(conn, id)
    if result:
        conn.commit()
        lt = conn.execute('SELECT libelle FROM loc_tarifs WHERE id=?', (id,)).fetchone()
        flash('Tarif synchronise avec arrete fiscal.', 'success')
    else:
        flash('Synchronisation impossible (verifier arrete fiscal actif).', 'danger')
    conn.close()
    return redirect(url_for('loc.loc_secteurs'))



@bp.route('/location-locaux/secteurs')
@login_required
def loc_secteurs():
    user = get_current_user()
    conn = get_db()
    secteurs = conn.execute('SELECT * FROM loc_secteurs ORDER BY ordre, libelle').fetchall()
    # Pour chaque secteur, charger ses tarifs et boutiques
    data = []
    for s in secteurs:
        tarifs = conn.execute(
            'SELECT * FROM loc_tarifs WHERE secteur_id=? ORDER BY libelle', (s['id'],)
        ).fetchall()
        tarifs_data = []
        for t in tarifs:
            boutiques = conn.execute(
                'SELECT * FROM loc_boutiques WHERE tarif_id=? ORDER BY numero', (t['id'],)
            ).fetchall()
            nb_baux = conn.execute(
                "SELECT COUNT(*) as c FROM baux WHERE tarif_id=? AND actif=1", (t['id'],)
            ).fetchone()['c']
            tarifs_data.append({
                'tarif': dict(t),
                'boutiques': [dict(b) for b in boutiques],
                'nb_baux': nb_baux
            })
        nb_baux_total = conn.execute(
            "SELECT COUNT(*) as c FROM baux WHERE secteur_id=? AND actif=1", (s['id'],)
        ).fetchone()['c']
        data.append({
            'secteur': dict(s),
            'tarifs': tarifs_data,
            'nb_baux': nb_baux_total
        })

    # Boutiques non exploitées
    boutiques_non_exploitees = conn.execute('''
        SELECT bo.*, lt.libelle as tarif_libelle, lt.valeur as tarif_valeur, lt.type_tarif,
               s.libelle as secteur_libelle, s.code as secteur_code
        FROM loc_boutiques bo
        JOIN loc_tarifs lt ON lt.id=bo.tarif_id
        JOIN loc_secteurs s ON s.id=lt.secteur_id
        WHERE bo.statut='disponible'
        ORDER BY s.code, bo.numero
    ''').fetchall()

    # Arrêté fiscal actif
    arrete_actif = conn.execute(
        "SELECT * FROM arretes_fiscaux WHERE statut='actif' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    # Enrichir les tarifs avec infos de synchro avec l'arrete
    for d in data:
        for td in d['tarifs']:
            lt = td['tarif']
            if lt.get('tarif_fiscal_id'):
                tf = conn.execute(
                    'SELECT valeur, date_debut, date_fin, actif FROM tarifs WHERE id=?',
                    (lt['tarif_fiscal_id'],)
                ).fetchone()
                if tf:
                    valeur_arrete = float(tf['valeur'])
                    valeur_loc    = float(lt['valeur'])
                    td['tarif']['valeur_arrete']       = valeur_arrete
                    td['tarif']['date_arrete']         = tf['date_debut']
                    td['tarif']['synchro_ok']          = (abs(valeur_arrete - valeur_loc) < 0.01)
                    td['tarif']['tarif_actif_arrete']  = bool(tf['actif'])
                else:
                    td['tarif']['synchro_ok'] = False
                    td['tarif']['valeur_arrete'] = None
            else:
                td['tarif']['synchro_ok'] = False
                td['tarif']['valeur_arrete'] = None

    conn.close()
    return render_template('location/loc_secteurs.html', user=user, data=data,
                           boutiques_non_exploitees=boutiques_non_exploitees,
                           arrete_actif=arrete_actif)


# ─── CRUD Secteurs ────────────────────────────────────────

@bp.route('/location-locaux/secteurs/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def loc_secteur_ajouter():
    f = request.form
    conn = get_db()
    n = conn.execute('SELECT COUNT(*) as c FROM loc_secteurs').fetchone()['c'] + 1
    code = f.get('code', '').strip().upper() or f"SEC-{n:02d}"
    try:
        conn.execute(
            'INSERT INTO loc_secteurs (code, libelle, description, type_tarif, tarif_mensuel, unite, ordre) VALUES (?,?,?,?,?,?,?)',
            (code, f['libelle'], f.get('description', ''), 'fixe', 0, 'DH/mois', int(f.get('ordre', n)))
        )
        conn.commit()
        flash(f'Secteur {code} cree', 'success')
    except Exception as e:
        flash(f'Erreur : {e}', 'danger')
    conn.close()
    return redirect(url_for('loc.loc_secteurs'))


@bp.route('/location-locaux/secteurs/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def loc_secteur_modifier(id):
    f = request.form
    conn = get_db()
    conn.execute('UPDATE loc_secteurs SET libelle=?, description=?, ordre=? WHERE id=?',
                 (f['libelle'], f.get('description', ''), int(f.get('ordre', 0)), id))
    conn.commit(); conn.close()
    flash('Secteur modifie', 'success')
    return redirect(url_for('loc.loc_secteurs'))


@bp.route('/location-locaux/secteurs/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def loc_secteur_supprimer(id):
    conn = get_db()
    n = conn.execute('SELECT COUNT(*) as c FROM baux WHERE secteur_id=? AND actif=1', (id,)).fetchone()['c']
    if n > 0:
        flash(f'Impossible : {n} bail(s) actifs dans ce secteur', 'danger')
    else:
        conn.execute('DELETE FROM loc_boutiques WHERE tarif_id IN (SELECT id FROM loc_tarifs WHERE secteur_id=?)', (id,))
        conn.execute('DELETE FROM loc_tarifs WHERE secteur_id=?', (id,))
        conn.execute('DELETE FROM loc_secteurs WHERE id=?', (id,))
        conn.commit()
        flash('Secteur supprime', 'success')
    conn.close()
    return redirect(url_for('loc.loc_secteurs'))


# ─── CRUD Tarifs ──────────────────────────────────────────

@bp.route('/location-locaux/tarifs/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def loc_tarif_ajouter():
    f = request.form
    conn = get_db()
    unite = 'DH/m2/mois' if f.get('type_tarif') == 'm2' else 'DH/mois'
    conn.execute(
        'INSERT INTO loc_tarifs (secteur_id, libelle, type_tarif, valeur, unite) VALUES (?,?,?,?,?)',
        (f['secteur_id'], f['libelle'], f.get('type_tarif', 'fixe'),
         float(f.get('valeur', 0) or 0), unite)
    )
    conn.commit()
    # Récupérer l'id du tarif créé et synchroniser dans l'arrêté fiscal
    loc_tarif_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    _sync_tarif_fiscal(conn, loc_tarif_id)
    conn.commit()
    conn.close()
    flash('Tarif ajoute et synchronise avec l\'arrete fiscal', 'success')
    return redirect(url_for('loc.loc_secteurs'))


@bp.route('/location-locaux/tarifs/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def loc_tarif_modifier(id):
    f = request.form
    conn = get_db()
    unite = 'DH/m2/mois' if f.get('type_tarif') == 'm2' else 'DH/mois'
    conn.execute(
        'UPDATE loc_tarifs SET libelle=?, type_tarif=?, valeur=?, unite=?, actif=? WHERE id=?',
        (f['libelle'], f.get('type_tarif', 'fixe'),
         float(f.get('valeur', 0) or 0), unite,
         1 if f.get('actif') else 0, id)
    )
    conn.commit()
    # Synchroniser dans l'arrêté fiscal
    _sync_tarif_fiscal(conn, id)
    conn.commit()
    conn.close()
    flash('Tarif modifie et synchronise avec l\'arrete fiscal', 'success')
    return redirect(url_for('loc.loc_secteurs'))


@bp.route('/location-locaux/tarifs/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def loc_tarif_supprimer(id):
    conn = get_db()
    n = conn.execute('SELECT COUNT(*) as c FROM baux WHERE tarif_id=? AND actif=1', (id,)).fetchone()['c']
    if n > 0:
        flash(f'Impossible : {n} bail(s) utilisent ce tarif', 'danger')
    else:
        conn.execute('DELETE FROM loc_boutiques WHERE tarif_id=?', (id,))
        conn.execute('DELETE FROM loc_tarifs WHERE id=?', (id,))
        conn.commit()
        flash('Tarif supprime', 'success')
    conn.close()
    return redirect(url_for('loc.loc_secteurs'))


# ─── CRUD Boutiques ───────────────────────────────────────

@bp.route('/location-locaux/boutiques/ajouter', methods=['POST'])
@login_required
@permission_required('modifier', 'loc')
def loc_boutique_ajouter():
    f = request.form
    conn = get_db()
    try:
        numeros = [n.strip() for n in f.get('numeros', '').split(',') if n.strip()]
        if not numeros:
            numeros = [f.get('numero', '').strip()]
        for num in numeros:
            if num:
                conn.execute(
                    'INSERT INTO loc_boutiques (tarif_id, numero, libelle, superficie, statut, notes) VALUES (?,?,?,?,?,?)',
                    (f['tarif_id'], num, f.get('libelle', ''),
                     float(f.get('superficie', 0) or 0),
                     f.get('statut', 'disponible'), f.get('notes', ''))
                )
        conn.commit()
        flash(f'{len(numeros)} boutique(s) ajoutees', 'success')
    except Exception as e:
        flash(f'Erreur : {e}', 'danger')
    conn.close()
    return redirect(url_for('loc.loc_secteurs'))


@bp.route('/location-locaux/boutiques/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('modifier', 'loc')
def loc_boutique_modifier(id):
    f = request.form
    conn = get_db()
    conn.execute(
        'UPDATE loc_boutiques SET numero=?, libelle=?, superficie=?, statut=?, notes=? WHERE id=?',
        (f['numero'], f.get('libelle', ''), float(f.get('superficie', 0) or 0),
         f.get('statut', 'disponible'), f.get('notes', ''), id)
    )
    conn.commit(); conn.close()
    flash('Boutique modifiee', 'success')
    return redirect(url_for('loc.loc_secteurs'))


@bp.route('/location-locaux/boutiques/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('modifier', 'loc')
def loc_boutique_supprimer(id):
    conn = get_db()
    n = conn.execute('SELECT COUNT(*) as c FROM baux WHERE boutique_id=? AND actif=1', (id,)).fetchone()['c']
    if n > 0:
        flash('Impossible : bail actif sur cette boutique', 'danger')
    else:
        conn.execute('DELETE FROM loc_boutiques WHERE id=?', (id,))
        conn.commit()
        flash('Boutique supprimee', 'success')
    conn.close()
    return redirect(url_for('loc.loc_secteurs'))


# ─── API ─────────────────────────────────────────────────

@bp.route('/api/loc/secteur/<int:id>/tarifs')
@login_required
def api_secteur_tarifs(id):
    """API : retourne les tarifs d'un secteur."""
    conn = get_db()
    tarifs = conn.execute(
        'SELECT id, libelle, type_tarif, valeur, unite FROM loc_tarifs WHERE secteur_id=? AND actif=1 ORDER BY libelle',
        (id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(t) for t in tarifs])


@bp.route('/api/loc/tarif/<int:id>/boutiques')
@login_required
def api_tarif_boutiques(id):
    """API : retourne les boutiques disponibles d'un tarif."""
    conn = get_db()
    # Boutiques disponibles OU déjà affectées au bail en cours (pour modification)
    boutiques = conn.execute(
        """SELECT b.id, b.numero, b.libelle, b.superficie, b.statut
           FROM loc_boutiques b
           WHERE b.tarif_id=? AND (b.statut='disponible' OR b.statut='exploitee')
           ORDER BY b.numero""",
        (id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(b) for b in boutiques])


@bp.route('/api/secteur-tarif/<int:id>')
@login_required
def api_secteur_tarif(id):
    """API legacy : tarif d'un secteur."""
    conn = get_db()
    s = conn.execute('SELECT * FROM loc_secteurs WHERE id=?', (id,)).fetchone()
    conn.close()
    if not s:
        return jsonify({'error': 'Secteur introuvable'}), 404
    superficie = float(request.args.get('superficie', 0) or 0)
    tarif = float(s['tarif_mensuel'])
    if s['type_tarif'] == 'm2' and superficie > 0:
        tarif = round(tarif * superficie, 2)
    return jsonify({'secteur_id': id, 'code': s['code'], 'libelle': s['libelle'],
                    'type_tarif': s['type_tarif'], 'tarif_mensuel_base': s['tarif_mensuel'],
                    'superficie': superficie, 'tarif_calcule': tarif, 'unite': s['unite']})
