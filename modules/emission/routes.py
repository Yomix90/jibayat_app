import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from werkzeug.utils import secure_filename
from datetime import datetime
import json

from database import get_db
from modules.helpers import login_required, get_current_user
from .config import MOIS_NOMS
from .parser import parse_bordereau_versement
from .generator import generer_tous_bordereaux

bp = Blueprint('emission', __name__)

EXPORT_DIR = os.path.join('static', 'exports', 'emission')
os.makedirs(EXPORT_DIR, exist_ok=True)
UPLOAD_DIR = os.path.join('uploads', 'emission')
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_emission_config(conn, annee):
    """Retrieve emission config for a given year, creating defaults if absent."""
    row = conn.execute(
        'SELECT * FROM emission_config WHERE annee=?', (annee,)
    ).fetchone()
    if row:
        return dict(row)
    return {
        'annee': annee,
        'premiere_partie_mode': 'auto',
        'premiere_partie_valeur': 0.0,
        'deuxieme_partie_mode': 'vide',
        'deuxieme_partie_valeur': 0.0,
        'notes': '',
    }


def _compute_cumul_annee(conn, annee, mois):
    """Cumul of all montant_present for the year up to given month (for display)."""
    row = conn.execute('''
        SELECT COALESCE(SUM(lr.montant), 0) as total
        FROM lignes_recettes lr
        JOIN bordereaux_versement bv ON lr.bordereau_id = bv.id
        WHERE bv.annee = ? AND bv.mois <= ?
    ''', (annee, mois)).fetchone()
    return float(row['total'] or 0.0)


@bp.route('/')
@login_required
def dashboard():
    user = get_current_user()
    conn = get_db()
    
    annee = request.args.get('annee', datetime.now().year, type=int)
    
    annees = [r['annee'] for r in conn.execute('SELECT DISTINCT annee FROM bordereaux_versement ORDER BY annee DESC').fetchall()]
    if annee not in annees:
        annees.append(annee)
        annees.sort(reverse=True)
        
    bvs = conn.execute('SELECT * FROM bordereaux_versement WHERE annee = ? ORDER BY mois ASC', (annee,)).fetchall()
    
    mois_data = {}
    for m in range(1, 13):
        mois_data[m] = {
            'mois': m,
            'nom': MOIS_NOMS.get(m),
            'statut': 'vide',
            'total': 0.0,
            'nb_rubriques': 0,
            'id': None
        }
        
    for bv in bvs:
        m = bv['mois']
        mois_data[m]['statut'] = 'importe'
        mois_data[m]['total'] = bv['total_general']
        mois_data[m]['id'] = bv['id']
        
        nb = conn.execute('SELECT COUNT(*) FROM bordereaux_emission WHERE bordereau_id=?', (bv['id'],)).fetchone()[0]
        mois_data[m]['nb_rubriques'] = nb

    # ── KPI aggregates (computed in Python — Jinja set doesn't accumulate in loops) ──
    mois_list = list(mois_data.values())
    total_annee       = sum(m['total']        for m in mois_list if m['statut'] == 'importe')
    nb_mois_importes  = sum(1                  for m in mois_list if m['statut'] == 'importe')
    nb_bordereaux     = sum(m['nb_rubriques'] for m in mois_list if m['statut'] == 'importe')

    conn.close()
    
    return render_template(
        'emission/dashboard.html',
        user=user,
        annee=annee,
        annees=annees,
        mois_data=mois_list,
        total_annee=total_annee,
        nb_mois_importes=nb_mois_importes,
        nb_bordereaux=nb_bordereaux,
    )


@bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    user = get_current_user()
    if request.method == 'POST':
        if 'fichier' not in request.files:
            flash('Aucun fichier sélectionné', 'danger')
            return redirect(request.url)
            
        file = request.files['fichier']
        if file.filename == '':
            flash('Aucun fichier sélectionné', 'danger')
            return redirect(request.url)
            
        if not file.filename.lower().endswith(('.xls', '.xlsx')):
            flash('Format non supporté. (.xls, .xlsx)', 'danger')
            return redirect(request.url)
            
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_DIR, filename)
        file.save(filepath)
        
        parsed = parse_bordereau_versement(filepath)
        
        mois = request.form.get('mois', type=int) or parsed.get('mois')
        annee = request.form.get('annee', type=int) or parsed.get('annee')
        
        if not mois or not annee:
            flash('Impossible de détecter le mois ou l\'année. Veuillez vérifier le fichier.', 'danger')
            return redirect(request.url)
            
        conn = get_db()
        existant = conn.execute('SELECT id FROM bordereaux_versement WHERE mois=? AND annee=?', (mois, annee)).fetchone()
        if existant:
            conn.close()
            flash(f"Le bordereau pour {MOIS_NOMS.get(mois)} {annee} a déjà été importé.", 'warning')
            return redirect(url_for('emission.dashboard', annee=annee))
            
        conn.execute('INSERT INTO bordereaux_versement (mois, annee, fichier_source, total_general) VALUES (?, ?, ?, ?)',
                    (mois, annee, filename, parsed['total_general']))
        bv_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        
        for l in parsed['lignes']:
            conn.execute('INSERT INTO lignes_recettes (bordereau_id, code_budgetaire, nature_recette, montant) VALUES (?, ?, ?, ?)',
                        (bv_id, l['code_budgetaire'], l['nature_recette'], l['montant']))

        # Optional: override total collectif with user-provided value
        montant_collectif = request.form.get('montant_collectif', type=float)
        if montant_collectif is not None:
            conn.execute('UPDATE bordereaux_versement SET total_general=? WHERE id=?', (montant_collectif, bv_id))

        conn.commit()
        conn.close()

        generer_tous_bordereaux(bv_id, EXPORT_DIR)

        flash(f"Import réussi pour {MOIS_NOMS.get(mois)} {annee}. {len(parsed['lignes'])} rubriques trouvées.", 'success')
        return redirect(url_for('emission.view', annee=annee, mois=mois))
        
    return render_template('emission/upload.html', user=user, today=datetime.now())

@bp.route('/<int:annee>/<int:mois>')
@login_required
def view(annee, mois):
    user = get_current_user()
    conn = get_db()
    
    bv = conn.execute('SELECT * FROM bordereaux_versement WHERE annee=? AND mois=?', (annee, mois)).fetchone()
    if not bv:
        conn.close()
        flash('Mois non trouvé', 'danger')
        return redirect(url_for('emission.dashboard', annee=annee))
        
    lignes = conn.execute('SELECT * FROM bordereaux_emission WHERE bordereau_id=? ORDER BY numero_bordereau', (bv['id'],)).fetchall()
    
    # Load emission config for this year
    em_config = _get_emission_config(conn, annee)
    
    # Compute cumul for display
    cumul_annee = _compute_cumul_annee(conn, annee, mois)

    # Compute premiere_partie display value
    if em_config['premiere_partie_mode'] == 'auto':
        # Sum of all montant_present for all previous months in this year
        row = conn.execute('''
            SELECT COALESCE(SUM(be.montant_present), 0) as total
            FROM bordereaux_emission be
            JOIN bordereaux_versement bv ON be.bordereau_id = bv.id
            WHERE bv.annee = ? AND bv.mois < ?
        ''', (annee, mois)).fetchone()
        premiere_partie_val = float(row['total'] or 0.0)
    else:
        premiere_partie_val = em_config['premiere_partie_valeur'] or 0.0

    # Compute deuxieme_partie display value
    if em_config['deuxieme_partie_mode'] == 'auto':
        deuxieme_partie_val = float(bv['total_general'] or 0.0)
    elif em_config['deuxieme_partie_mode'] == 'manuel':
        deuxieme_partie_val = em_config['deuxieme_partie_valeur'] or 0.0
    else:
        deuxieme_partie_val = None  # vide

    conn.close()
    
    return render_template(
        'emission/view.html',
        user=user,
        bv=bv,
        lignes=lignes,
        mois_nom=MOIS_NOMS.get(mois),
        em_config=em_config,
        cumul_annee=cumul_annee,
        premiere_partie_val=premiere_partie_val,
        deuxieme_partie_val=deuxieme_partie_val,
    )


@bp.route('/<int:annee>/config', methods=['GET', 'POST'])
@login_required
def save_config(annee):
    """Save emission configuration for a given year and regenerate PDFs."""
    conn = get_db()
    if request.method == 'POST':
        premiere_mode = request.form.get('premiere_partie_mode', 'auto')
        premiere_val = request.form.get('premiere_partie_valeur', 0.0, type=float)
        deuxieme_mode = request.form.get('deuxieme_partie_mode', 'vide')
        deuxieme_val = request.form.get('deuxieme_partie_valeur', 0.0, type=float)
        notes = request.form.get('notes', '')

        conn.execute('''
            INSERT INTO emission_config (annee, premiere_partie_mode, premiere_partie_valeur,
                deuxieme_partie_mode, deuxieme_partie_valeur, notes, date_modification)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(annee) DO UPDATE SET
                premiere_partie_mode=excluded.premiere_partie_mode,
                premiere_partie_valeur=excluded.premiere_partie_valeur,
                deuxieme_partie_mode=excluded.deuxieme_partie_mode,
                deuxieme_partie_valeur=excluded.deuxieme_partie_valeur,
                notes=excluded.notes,
                date_modification=CURRENT_TIMESTAMP
        ''', (annee, premiere_mode, premiere_val, deuxieme_mode, deuxieme_val, notes))
        conn.commit()

        # Regenerate all bordereaux for this year
        bvs = conn.execute('SELECT id FROM bordereaux_versement WHERE annee=?', (annee,)).fetchall()
        conn.close()

        for bv_row in bvs:
            generer_tous_bordereaux(bv_row['id'], EXPORT_DIR)

        flash(f'Configuration sauvegardée pour {annee}. PDFs régénérés.', 'success')

        # Redirect back to origin mois if provided
        mois = request.form.get('mois_redirect', type=int)
        if mois:
            return redirect(url_for('emission.view', annee=annee, mois=mois))
        return redirect(url_for('emission.dashboard', annee=annee))

    # GET: return current config as JSON
    cfg = _get_emission_config(conn, annee)
    conn.close()
    return jsonify(cfg)


@bp.route('/<int:annee>/<int:mois>/pdf')
@login_required
def download_pdf(annee, mois):
    import zipfile
    from io import BytesIO
    from flask import send_file
    
    conn = get_db()
    bv = conn.execute('SELECT * FROM bordereaux_versement WHERE annee=? AND mois=?', (annee, mois)).fetchone()
    if not bv:
        return "Not found", 404
        
    lignes = conn.execute('SELECT * FROM bordereaux_emission WHERE bordereau_id=?', (bv['id'],)).fetchall()
    conn.close()
    
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for l in lignes:
            if l['chemin_pdf'] and os.path.exists(l['chemin_pdf']):
                zf.write(l['chemin_pdf'], os.path.basename(l['chemin_pdf']))
                
    memory_file.seek(0)
    return send_file(memory_file, download_name=f"Bordereaux_{annee}_{mois:02d}.zip", as_attachment=True)

@bp.route('/<int:annee>/<int:mois>/pdf/<rubrique>')
@login_required
def download_pdf_rubrique(annee, mois, rubrique):
    from flask import make_response
    conn = get_db()
    bv = conn.execute('SELECT * FROM bordereaux_versement WHERE annee=? AND mois=?', (annee, mois)).fetchone()
    if not bv:
        return "Not found", 404
        
    ligne = conn.execute('SELECT * FROM bordereaux_emission WHERE bordereau_id=? AND rubrique=?', (bv['id'], rubrique)).fetchone()
    conn.close()
    
    if ligne and ligne['chemin_pdf'] and os.path.exists(ligne['chemin_pdf']):
        response = make_response(
            send_file(
                ligne['chemin_pdf'],
                mimetype='application/pdf',
                as_attachment=False,
            )
        )
        fname = os.path.basename(ligne['chemin_pdf'])
        response.headers['Content-Disposition'] = f'inline; filename="{fname}"'
        response.headers['Content-Type'] = 'application/pdf'
        return response
    return "File not found", 404

@bp.route('/<int:annee>/<int:mois>/edit_montant/<code>', methods=['POST'])
@login_required
def edit_montant(annee, mois, code):
    montant = request.form.get('montant', type=float)
    conn = get_db()
    bv = conn.execute('SELECT * FROM bordereaux_versement WHERE annee=? AND mois=?', (annee, mois)).fetchone()
    if bv and montant is not None:
        conn.execute('UPDATE lignes_recettes SET montant=? WHERE bordereau_id=? AND code_budgetaire=?', (montant, bv['id'], code))
        new_total = conn.execute('SELECT SUM(montant) FROM lignes_recettes WHERE bordereau_id=?', (bv['id'],)).fetchone()[0] or 0.0
        conn.execute('UPDATE bordereaux_versement SET total_general=? WHERE id=?', (new_total, bv['id']))
        conn.commit()
        conn.close()
        generer_tous_bordereaux(bv['id'], EXPORT_DIR)
        flash(f'Montant modifié pour la rubrique {code} et bordereaux régénérés.', 'success')
    return redirect(url_for('emission.view', annee=annee, mois=mois))

@bp.route('/<int:annee>/<int:mois>/delete_montant/<code>', methods=['POST'])
@login_required
def delete_montant(annee, mois, code):
    conn = get_db()
    bv = conn.execute('SELECT * FROM bordereaux_versement WHERE annee=? AND mois=?', (annee, mois)).fetchone()
    if bv:
        conn.execute('DELETE FROM lignes_recettes WHERE bordereau_id=? AND code_budgetaire=?', (bv['id'], code))
        new_total = conn.execute('SELECT SUM(montant) FROM lignes_recettes WHERE bordereau_id=?', (bv['id'],)).fetchone()[0] or 0.0
        conn.execute('UPDATE bordereaux_versement SET total_general=? WHERE id=?', (new_total, bv['id']))
        conn.commit()
        conn.close()
        generer_tous_bordereaux(bv['id'], EXPORT_DIR)
        flash(f'Ligne {code} supprimée et bordereaux régénérés.', 'success')
    return redirect(url_for('emission.view', annee=annee, mois=mois))

@bp.route('/<int:annee>/<int:mois>/add_rubrique', methods=['POST'])
@login_required
def add_rubrique(annee, mois):
    code = request.form.get('code_budgetaire', '').strip()
    montant = request.form.get('montant', type=float)
    
    if not code or montant is None:
        flash("Code budgétaire et montant sont obligatoires.", 'danger')
        return redirect(url_for('emission.view', annee=annee, mois=mois))
        
    conn = get_db()
    bv = conn.execute('SELECT * FROM bordereaux_versement WHERE annee=? AND mois=?', (annee, mois)).fetchone()
    
    if not bv:
        # Create bv if it doesn't exist
        conn.execute('INSERT INTO bordereaux_versement (mois, annee, fichier_source, total_general) VALUES (?, ?, ?, ?)',
                    (mois, annee, 'Saisie Manuelle', 0.0))
        bv_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    else:
        bv_id = bv['id']
        
    # Check if code already exists
    exists = conn.execute('SELECT id FROM lignes_recettes WHERE bordereau_id=? AND code_budgetaire=?', (bv_id, code)).fetchone()
    if exists:
        conn.close()
        flash(f"La rubrique {code} existe déjà pour ce mois.", 'warning')
        return redirect(url_for('emission.view', annee=annee, mois=mois))
        
    conn.execute('INSERT INTO lignes_recettes (bordereau_id, code_budgetaire, nature_recette, montant) VALUES (?, ?, ?, ?)',
                (bv_id, code, 'Saisie Manuelle', montant))
                
    new_total = conn.execute('SELECT SUM(montant) FROM lignes_recettes WHERE bordereau_id=?', (bv_id,)).fetchone()[0] or 0.0
    conn.execute('UPDATE bordereaux_versement SET total_general=? WHERE id=?', (new_total, bv_id))
    conn.commit()
    conn.close()
    
    generer_tous_bordereaux(bv_id, EXPORT_DIR)
    flash(f'Rubrique {code} ajoutée avec succès.', 'success')
    return redirect(url_for('emission.view', annee=annee, mois=mois))

@bp.route('/<int:annee>/<int:mois>', methods=['DELETE'])
@login_required
def delete(annee, mois):
    conn = get_db()
    bv = conn.execute('SELECT * FROM bordereaux_versement WHERE annee=? AND mois=?', (annee, mois)).fetchone()
    if bv:
        conn.execute('DELETE FROM bordereaux_versement WHERE id=?', (bv['id'],))
        conn.commit()
    conn.close()
    return jsonify({"success": True})
