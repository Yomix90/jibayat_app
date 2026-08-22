"""
modules/config.py — Blueprint : Rubriques, Arrêtés Fiscaux, Tarifs, Paramètres
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, date
from database import get_db

from modules.helpers import login_required, get_current_user, permission_required

bp = Blueprint('config', __name__)


# ════════════════════════════════════════════════════════════
#  RUBRIQUES
# ════════════════════════════════════════════════════════════

@bp.route('/rubriques')
@login_required
@permission_required('config')
def rubriques():
    user = get_current_user()
    conn = get_db()
    items = conn.execute('SELECT * FROM rubriques ORDER BY module').fetchall()
    conn.close()
    return render_template('admin/rubriques.html', user=user, items=items)

@bp.route('/rubriques/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def ajouter_rubrique():
    f = request.form
    conn = get_db()
    conn.execute('INSERT OR IGNORE INTO rubriques (code,libelle,libelle_ar,module,description) VALUES (?,?,?,?,?)',
        (f['code'], f['libelle'], f.get('libelle_ar',''), f['module'], f.get('description','')))
    conn.commit(); conn.close()
    flash('Rubrique ajoutée ✅', 'success')
    return redirect(url_for('config.rubriques'))

@bp.route('/rubriques/<int:id>/toggle', methods=['POST'])
@login_required
@permission_required('config')
def toggle_rubrique(id):
    conn = get_db()
    conn.execute('UPDATE rubriques SET actif = CASE WHEN actif=1 THEN 0 ELSE 1 END WHERE id=?', (id,))
    conn.commit(); conn.close()
    flash('Statut rubrique mis à jour', 'info')
    return redirect(url_for('config.rubriques'))

@bp.route('/rubriques/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def modifier_rubrique(id):
    f = request.form
    conn = get_db()
    conn.execute('UPDATE rubriques SET libelle=?,libelle_ar=?,description=? WHERE id=?',
        (f['libelle'], f.get('libelle_ar',''), f.get('description',''), id))
    conn.commit(); conn.close()
    flash('Rubrique modifiée ✅', 'success')
    return redirect(url_for('config.rubriques'))


# ════════════════════════════════════════════════════════════
#  ARRÊTÉS FISCAUX
# ════════════════════════════════════════════════════════════

@bp.route('/arretes-fiscaux')
@login_required
@permission_required('config')
def arretes_fiscaux():
    user = get_current_user()
    conn = get_db()
    arretes = conn.execute('SELECT * FROM arretes_fiscaux ORDER BY date_effet DESC').fetchall()
    rubriques_list = conn.execute('SELECT * FROM rubriques WHERE actif=1 ORDER BY module').fetchall()
    conn.close()
    return render_template('admin/arretes.html', user=user, arretes=arretes,
                           rubriques=rubriques_list, today=date.today().isoformat())

@bp.route('/arretes-fiscaux/creer', methods=['POST'])
@login_required
@permission_required('config')
def creer_arrete():
    user = get_current_user()
    f = request.form
    conn = get_db()
    n = conn.execute('SELECT COUNT(*) as c FROM arretes_fiscaux').fetchone()['c'] + 1
    num = f"AF-{datetime.now().year}-{n:03d}"
    date_effet = f['date_effet']
    # Fermer l'arrêté précédent
    conn.execute("UPDATE arretes_fiscaux SET statut='remplace' WHERE statut='actif'")
    conn.execute('''INSERT INTO arretes_fiscaux (numero,titre,date_effet,notes,agent_id)
        VALUES (?,?,?,?,?)''',
        (num, f.get('titre', f'Arrêté Fiscal {datetime.now().year}'),
         date_effet, f.get('notes',''), user['id']))
    arrete_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit(); conn.close()
    flash(f'Arrêté fiscal {num} créé ✅', 'success')
    return redirect(url_for('config.arretes_detail', id=arrete_id))

@bp.route('/arretes-fiscaux/<int:id>')
@login_required
@permission_required('config')
def arretes_detail(id):
    user = get_current_user()
    conn = get_db()
    arrete = conn.execute('SELECT * FROM arretes_fiscaux WHERE id=?', (id,)).fetchone()
    if not arrete:
        flash('Arrêté introuvable', 'danger')
        return redirect(url_for('config.arretes_fiscaux'))
    tarifs_list = conn.execute('''SELECT t.*, r.module, r.libelle as rub_libelle, r.code as rub_code
        FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
        WHERE t.arrete_id=? ORDER BY r.module, t.libelle''', (id,)).fetchall()
    rubriques_list = [dict(r) for r in conn.execute('SELECT * FROM rubriques WHERE actif=1 ORDER BY module').fetchall()]
    historique = conn.execute('''SELECT t.*, r.module, r.libelle as rub_libelle,
        af.numero as arrete_num, af.date_effet
        FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
        JOIN arretes_fiscaux af ON t.arrete_id=af.id
        WHERE t.arrete_id != ? ORDER BY r.module, t.date_debut DESC''', (id,)).fetchall()

    # Rubriques non encore dans cet arrete
    mods_presents = {t['module'] for t in tarifs_list}
    rubriques_manquantes = [dict(r) for r in rubriques_list if r['module'] not in mods_presents]

    conn.close()
    return render_template('admin/arretes_detail.html', user=user, arrete=arrete,
                           tarifs=tarifs_list, rubriques=rubriques_list,
                           historique=historique, today=date.today().isoformat(),
                           rubriques_manquantes=rubriques_manquantes)


@bp.route('/arretes-fiscaux/<int:id>/ajouter-rubrique', methods=['POST'])
@login_required
@permission_required('config')
def ajouter_rubrique_arrete(id):
    """Ajoute une rubrique (et ses derniers tarifs) a un arrete fiscal."""
    f = request.form
    rubrique_id = f.get('rubrique_id')
    copier_tarifs = f.get('copier_tarifs') == '1'
    today = date.today().isoformat()

    if not rubrique_id:
        flash('Aucune rubrique selectionnee', 'danger')
        return redirect(url_for('config.arretes_detail', id=id))

    conn = get_db()
    rub = conn.execute('SELECT * FROM rubriques WHERE id=?', (rubrique_id,)).fetchone()
    if not rub:
        flash('Rubrique introuvable', 'danger')
        conn.close()
        return redirect(url_for('config.arretes_detail', id=id))

    # Verifier si deja presente dans cet arrete
    existing = conn.execute(
        'SELECT COUNT(*) as c FROM tarifs WHERE rubrique_id=? AND arrete_id=?',
        (rubrique_id, id)
    ).fetchone()['c']
    if existing > 0:
        flash(f'La rubrique {rub["module"]} est deja presente dans cet arrete.', 'warning')
        conn.close()
        return redirect(url_for('config.arretes_detail', id=id))

    nb_cree = 0
    if copier_tarifs:
        # Copier les derniers tarifs de cette rubrique (tous arretes confondus)
        anciens_tarifs = conn.execute(
            """SELECT t1.* FROM tarifs t1
               WHERE t1.rubrique_id=?
                 AND t1.date_debut = (
                     SELECT MAX(t2.date_debut) FROM tarifs t2
                     WHERE t2.rubrique_id = t1.rubrique_id
                       AND t2.libelle = t1.libelle
                 )
               GROUP BY t1.libelle
               ORDER BY t1.libelle""",
            (rubrique_id,)
        ).fetchall()

        for t in anciens_tarifs:
            rub_code = rub['code']
            mots = [m[:3].upper() for m in t['libelle'].split()[:2] if m]
            code_tarif = f"{rub_code}-{''.join(mots)}"
            conn.execute(
                """INSERT INTO tarifs
                   (rubrique_id, arrete_id, code_tarif, libelle, valeur, unite, date_debut, actif)
                   VALUES (?,?,?,?,?,?,?,1)""",
                (rubrique_id, id, code_tarif, t['libelle'], t['valeur'], t['unite'], today)
            )
            nb_cree += 1

    if nb_cree == 0:
        # Creer un tarif placeholder (valeur 0) pour que la rubrique apparaisse
        rub_code = rub['code']
        libelle_def = rub['libelle']
        mots = [m[:3].upper() for m in libelle_def.split()[:2] if m]
        code_tarif = f"{rub_code}-{''.join(mots)}"
        conn.execute(
            """INSERT INTO tarifs
               (rubrique_id, arrete_id, code_tarif, libelle, valeur, unite, date_debut, actif)
               VALUES (?,?,?,?,0,'DH',?,1)""",
            (rubrique_id, id, code_tarif, libelle_def, today)
        )
        conn.commit()
        flash(f'Rubrique « {rub["libelle"]} » ajoutée (tarif à modifier). Pensez à mettre la bonne valeur.', 'info')
    else:
        conn.commit()
        flash(f'Rubrique « {rub["libelle"]} » ajoutée avec {nb_cree} tarif(s) copié(s).', 'success')

    conn.close()
    return redirect(url_for('config.arretes_detail', id=id))


@bp.route('/arretes-fiscaux/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def supprimer_arrete(id):
    """Supprime un arrete fiscal avec verification de la question math."""
    f = request.form
    # Verification de la reponse math
    try:
        attendu = int(f.get('math_answer_expected', '-99'))
        fourni  = int(f.get('math_answer', '0'))
    except (ValueError, TypeError):
        flash('Reponse invalide.', 'danger')
        return redirect(url_for('config.arretes_detail', id=id))
    if fourni != attendu:
        flash('Mauvaise reponse de securite ! Suppression annulee.', 'danger')
        return redirect(url_for('config.arretes_detail', id=id))
    motif = f.get('motif', '').strip()
    if not motif:
        flash('Vous devez saisir un motif de suppression.', 'danger')
        return redirect(url_for('config.arretes_detail', id=id))
    conn = get_db()
    arrete = conn.execute('SELECT * FROM arretes_fiscaux WHERE id=?', (id,)).fetchone()
    if not arrete:
        flash('Arrete introuvable.', 'danger')
        conn.close()
        return redirect(url_for('config.arretes_fiscaux'))
    nb_tarifs = conn.execute('SELECT COUNT(*) as c FROM tarifs WHERE arrete_id=?', (id,)).fetchone()['c']
    conn.execute('DELETE FROM tarifs WHERE arrete_id=?', (id,))
    conn.execute('DELETE FROM arretes_fiscaux WHERE id=?', (id,))
    if arrete['statut'] == 'actif':
        dernier = conn.execute(
            "SELECT id FROM arretes_fiscaux ORDER BY date_effet DESC LIMIT 1"
        ).fetchone()
        if dernier:
            conn.execute("UPDATE arretes_fiscaux SET statut='actif' WHERE id=?", (dernier['id'],))
    conn.commit(); conn.close()
    flash(f"Arrete {arrete['numero']} supprime ({nb_tarifs} tarif(s) effaces). Motif: {motif}", 'warning')
    return redirect(url_for('config.arretes_fiscaux'))

@bp.route('/tarifs')
@login_required
@permission_required('config')
def tarifs():
    return redirect(url_for('config.arretes_fiscaux'))

@bp.route('/tarifs/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def ajouter_tarif():
    f = request.form
    libelle = f['libelle'].strip()
    rub_code = f.get('rub_code', '')
    # Code tarif auto-généré
    mots = [m[:3].upper() for m in libelle.split()[:2] if m]
    code_tarif = f"{rub_code}-{''.join(mots)}" if rub_code else '-'.join(mots)
    date_debut = f['date_debut']
    conn = get_db()
    # Fermer le tarif précédent pour ce libellé
    conn.execute('''UPDATE tarifs SET date_fin=?, actif=0
        WHERE rubrique_id=? AND libelle=? AND date_fin IS NULL AND actif=1''',
        (date_debut, f['rubrique_id'], libelle))
    conn.execute('''INSERT INTO tarifs (rubrique_id,arrete_id,code_tarif,libelle,valeur,unite,date_debut,date_fin,surface_min,surface_max)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (f['rubrique_id'], f.get('arrete_id') or None, code_tarif, libelle,
         f['valeur'], f.get('unite','DH'), date_debut, f.get('date_fin') or None,
         f.get('surface_min') or 0, f.get('surface_max') or None))

    conn.commit(); conn.close()
    flash('Tarif ajouté ✅', 'success')
    arrete_id = f.get('arrete_id')
    return redirect(url_for('config.arretes_detail', id=arrete_id) if arrete_id else url_for('config.arretes_fiscaux'))

@bp.route('/tarifs/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def modifier_tarif(id):
    f = request.form
    conn = get_db()
    date_debut = f.get('date_debut') or None
    conn.execute(
        'UPDATE tarifs SET valeur=?, unite=?, date_debut=?, date_fin=?, actif=?, surface_min=?, surface_max=? WHERE id=?',
        (f['valeur'], f.get('unite', 'DH'),
         date_debut,
         f.get('date_fin') or None,
         1 if not f.get('date_fin') else 0,
         f.get('surface_min') or 0, f.get('surface_max') or None,
         id)
    )
    conn.commit(); conn.close()
    flash('Tarif modifié ✅', 'success')
    return redirect(url_for('config.arretes_detail', id=f['arrete_id']))

@bp.route('/tarifs/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def supprimer_tarif(id):
    f = request.form
    conn = get_db()
    conn.execute('DELETE FROM tarifs WHERE id=?', (id,))
    conn.commit(); conn.close()
    return redirect(url_for('config.arretes_detail', id=f.get('arrete_id', 1)))


# ════════════════════════════════════════════════════════════
#  PARAMÈTRES DE CALCUL
# ════════════════════════════════════════════════════════════

@bp.route('/parametres')
@login_required
@permission_required('config')
def parametres():
    user = get_current_user()
    conn = get_db()
    items = conn.execute('SELECT * FROM parametres_calcul ORDER BY module, code').fetchall()
    grouped = {}
    for p in items:
        m = p['module']
        if m not in grouped:
            grouped[m] = []
        grouped[m].append(p)
    conn.close()
    return render_template('admin/parametres.html', user=user, grouped=grouped)

@bp.route('/parametres/modifier', methods=['POST'])
@login_required
@permission_required('config')
def modifier_parametres():
    conn = get_db()
    for key, value in request.form.items():
        if key.startswith('param_'):
            param_id = key.replace('param_', '')
            conn.execute('UPDATE parametres_calcul SET valeur=? WHERE id=?', (value, param_id))
    conn.commit(); conn.close()
    flash('Paramètres mis à jour ✅', 'success')
    return redirect(url_for('config.parametres'))
