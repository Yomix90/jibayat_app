import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .config import COMMUNE_CONFIG

_NAVY = colors.HexColor('#1e3a5f')
_GOLD = colors.HexColor('#c8a84b')
_LIGHT_GRAY = colors.HexColor('#f0f2f5')

# Try to register an Arabic-capable font; fall back if unavailable
_AR_FONT = 'Helvetica'
for _path, _name in [
    ('C:\\Windows\\Fonts\\arial.ttf', 'Arial'),
    ('C:\\Windows\\Fonts\\times.ttf', 'TimesNewRoman'),
]:
    if os.path.exists(_path):
        try:
            pdfmetrics.registerFont(TTFont(_name, _path))
            _AR_FONT = _name
        except Exception:
            pass

def format_dh(val):
    return f"{val:,.2f}".replace(",", " ")

def _colored_table(header_row, data_rows, col_widths, total_idx=None):
    """Build a table with navy header row and gold accent bottom border."""
    all_rows = [header_row] + data_rows
    t = Table(all_rows, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.Color(0.8,0.8,0.8)),
        ('BACKGROUND', (0,0), (-1,0), _NAVY),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]
    # Alternating row colors
    for i in range(1, len(all_rows)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0,i), (-1,i), _LIGHT_GRAY))
    # Gold bottom border on total row
    if total_idx is not None and total_idx < len(all_rows):
        style_cmds.append(('LINEABOVE', (0,total_idx), (-1,total_idx), 1.5, _GOLD))
        style_cmds.append(('FONTNAME', (0,total_idx), (-1,total_idx), 'Helvetica-Bold'))
    t.setStyle(TableStyle(style_cmds))
    return t

def export_bordereau_pdf(be: dict, date_str: str, output_path: str):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30
    )

    elements = []
    styles = getSampleStyleSheet()

    # Color constants
    navy = _NAVY
    gold = _GOLD

    # ── Custom ParagraphStyles ──
    ps_center = ParagraphStyle('C', parent=styles['Normal'], alignment=TA_CENTER, fontName='Helvetica', fontSize=9)
    ps_center_bold = ParagraphStyle('CB', parent=ps_center, fontName='Helvetica-Bold')
    ps_left = ParagraphStyle('L', parent=styles['Normal'], alignment=TA_LEFT, fontName='Helvetica', fontSize=9)
    ps_left_bold = ParagraphStyle('LB', parent=ps_left, fontName='Helvetica-Bold')
    ps_left_sm = ParagraphStyle('LSm', parent=ps_left, fontSize=8, textColor=colors.HexColor('#555'))

    # ── HEADER (French, all uppercase) ──
    header_data = [
        [Paragraph(f"<b>{COMMUNE_CONFIG['pays']}</b>", ps_left_bold),
         Paragraph(f"<b>{COMMUNE_CONFIG['ministere']}</b>", ps_right := ParagraphStyle('R', parent=ps_left, alignment=TA_RIGHT, fontName='Helvetica-Bold', fontSize=10))],
    ]
    hdr_table = Table(header_data, colWidths=[260, 260])
    hdr_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(hdr_table)

    # Gold line
    elements.append(HRFlowable(width="100%", thickness=1, color=_GOLD, spaceBefore=4, spaceAfter=4))

    # Province & Commune — each on its own line, all uppercase
    prefecture_label = COMMUNE_CONFIG.get('prefecture', 'PRÉFECTURE DE').upper()
    elements.append(Paragraph(f"{prefecture_label} ..........", ps_left))
    elements.append(Paragraph(COMMUNE_CONFIG['province'].upper(), ps_left))
    elements.append(Paragraph(COMMUNE_CONFIG['nom'].upper(), ps_left_bold))

    elements.append(Spacer(1, 12))

    # ── TITLE ──
    title_style = ParagraphStyle('Title', parent=ps_center_bold, fontSize=14, textColor=navy, spaceAfter=4)
    elements.append(Paragraph(f"BORDEREAU D'EMISSION N° {be['numero_bordereau']}", title_style))
    elements.append(HRFlowable(width="40%", thickness=0.5, color=gold, spaceBefore=2, spaceAfter=8))

    elements.append(Paragraph("Ordres de Recettes (1) &nbsp;&nbsp;&nbsp; Titres D'Annulation (1)", ps_center))
    elements.append(Spacer(1, 16))

    # ── RUBRIQUE BUDGETAIRE ──
    elements.append(Paragraph("<b>RUBRIQUE BUDGETAIRE</b>", ps_left_bold))
    elements.append(Spacer(1, 6))

    code = be.get('code_budgetaire', '')
    chap = code[:2] if len(code) >= 2 else ''
    art = code[2:4] if len(code) >= 4 else ''
    par = code[4:] if len(code) >= 5 else ''

    rubrique_rows = [['1', 'Partie section', f'Chap: {chap}', f'Art: {art}', par]]
    t_rub = Table(rubrique_rows, colWidths=[30, 100, 100, 100, 100])
    t_rub.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.Color(0.8,0.8,0.8)),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.Color(0.8,0.8,0.8)),
        ('BACKGROUND', (0,0), (-1,0), _LIGHT_GRAY),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(t_rub)
    elements.append(Spacer(1, 6))

    t_int = Table([['Intitulé:', be['intitule']]], colWidths=[80, 370])
    t_int.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,0), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,0), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    elements.append(t_int)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("(1) Ordres De Recettes N° .........................................", ps_left))
    elements.append(Paragraph("(1) Titre D'annulation N° .........................................", ps_left))
    elements.append(Spacer(1, 14))

    # ── FIRST TABLE ──
    col_widths = [180, 100, 110, 110]
    t1_header = ['', 'Montant De La\nRubrique', 'Montant Total Des\nEmissions Collectives', '']
    t1_data = [
        ['Report Des Antérieurs', format_dh(be['report_anterieurs']), format_dh(be['report_global']), ''],
        ['Montant Du Présent Bordereau', format_dh(be['montant_present']), format_dh(be['total_present_global']), ''],
        ['TOTAL', format_dh(be['total']), format_dh(be['report_global'] + be['total_present_global']), ''],
    ]
    t1 = _colored_table(t1_header, t1_data, col_widths, total_idx=3)
    t1.setStyle(TableStyle([
        ('SPAN', (2,0), (3,0)),
        ('SPAN', (0,0), (1,0)),
    ]))
    elements.append(t1)
    elements.append(Spacer(1, 8))

    # ── SECOND TABLE ──
    t2_header = ['Libellé', 'Montant', '1ère Partie', '2ème Partie']
    t2_data = [
        ['Montant Brut Du Présent Bordereau', format_dh(be['total']), 'xxxxxxxxxxxx', 'xxxxxxxxxxxx'],
        ['Montant Net Des Antérieurs', 'xxxxxxxxxxxx', format_dh(be['report_global']), ''],
        ['TITRE REJETS', '........................', '', ''],
        ['N° ....................................', '........................', '', ''],
        ['N° ....................................', '........................', '', ''],
        ['N° ....................................', '........................', '', ''],
        ['N° ....................................', '........................', '', ''],
        ['N° ....................................', '........................', '', ''],
        ['Total Rejeté', '........................', '', ''],
        ['Montant Net Admis', format_dh(be['total']), format_dh(be['total_present_global']), ''],
        ['Total Général Admis', 'xxxxxxxxxxxx', format_dh(be['report_global'] + be['total_present_global']), ''],
    ]
    t2 = _colored_table(t2_header, t2_data, col_widths, total_idx=None)
    elements.append(t2)

    elements.append(Spacer(1, 8))

    # ── TOTAL box ──
    total_val = be['report_global'] + be['total_present_global']
    total_rows = [
        ['', 'TOTAL GÉNÉRAL ADMIS', format_dh(total_val), ''],
    ]
    t_total = Table(total_rows, colWidths=[180, 100, 110, 110])
    t_total.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (1,0), (2,0), 'CENTER'),
        ('ALIGN', (0,0), (0,0), 'RIGHT'),
        ('BOX', (0,0), (-1,-1), 1.5, _GOLD),
        ('BACKGROUND', (1,0), (2,0), _NAVY),
        ('TEXTCOLOR', (1,0), (2,0), colors.white),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(t_total)

    # ── SIGNATURE ──
    elements.append(Spacer(1, 18))

    sig_data = [
        [f"A {COMMUNE_CONFIG['nom'].replace('Commune ', '').upper()} LE ................",
         "",
         "Vu Pour Confirmation\nDe La Prise En Charge"],
        ["",
         "",
         "(1) Receveur Des Finances"]
    ]
    t_sig = Table(sig_data, colWidths=[200, 60, 250])
    t_sig.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTSIZE', (2,1), (2,1), 8),
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (2,0), (2,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOX', (2,0), (2,1), 1, _NAVY),
        ('LINEBELOW', (2,0), (2,0), 0.5, _GOLD),
        ('BACKGROUND', (2,0), (2,1), _LIGHT_GRAY),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(t_sig)

    elements.append(Spacer(1, 14))
    elements.append(Paragraph("(1) Barrer La Mention Inutile", ps_left_sm))

    doc.build(elements)
