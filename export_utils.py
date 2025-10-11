# export_utils.py
from __future__ import annotations
from io import BytesIO
from pathlib import Path
from typing import List, Tuple

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image


def _logo_bytes() -> bytes | None:
    # Cherche le logo à la racine ou dans assets
    candidates = [
        Path(__file__).parent / "Logo_atelierPOF.png",
        Path(__file__).parent / "logo_atelierpof.png",
        Path(__file__).parent / "assets" / "Logo_atelierPOF.png",
    ]
    for p in candidates:
        if p.exists():
            return p.read_bytes()
    return None


def build_recipe_pdf(
    recipe_name: str,
    category: str,
    servings: int,
    items: List[Tuple[str, float, str, str, float]],  # [(ing_name, qty, unit, supplier, price_per_base)]
    instructions: str,
    cost_total: float,
    cost_per_serving: float,
) -> bytes:
    """
    Construit un PDF de fiche recette et retourne les bytes.
    items: liste de tuples (Ingrédient, Quantité, Unité, Fournisseur, PrixBase).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Fiche Recette - {recipe_name}",
    )

    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 20
    title_style.textColor = colors.HexColor("#2f3a3a")
    h2 = styles["Heading2"]
    h2.fontName = "Helvetica-Bold"
    h2.textColor = colors.HexColor("#2f3a3a")
    normal = styles["BodyText"]
    normal.fontName = "Helvetica"
    normal.leading = 14

    small = ParagraphStyle(
        "small",
        parent=normal,
        fontSize=9,
        textColor=colors.HexColor("#596066"),
    )

    flow = []

    # En-tête avec logo
    logo_data = _logo_bytes()
    if logo_data:
        img = Image(BytesIO(logo_data), width=28 * mm, height=28 * mm)
        flow.append(img)
        flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph(f"Fiche recette — {recipe_name}", title_style))
    meta = f"Catégorie : <b>{category or 'Général'}</b> &nbsp;&nbsp;•&nbsp;&nbsp; Portions : <b>{servings}</b>"
    flow.append(Paragraph(meta, small))
    flow.append(Spacer(1, 6 * mm))

    # Tableau des ingrédients
    if items:
        flow.append(Paragraph("Ingrédients", h2))
        data = [["Ingrédient", "Quantité", "Unité", "Fournisseur", "Prix base ($/u)"]]
        for n, q, u, s, pb in items:
            data.append([n, f"{q:,.2f}", u, (s or ""), f"{pb:,.4f}"])

        tbl = Table(data, hAlign="LEFT", colWidths=[60*mm, 25*mm, 18*mm, 45*mm, 27*mm])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF0EA")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2f3a3a")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C8CEC2")),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("ALIGN", (4, 1), (4, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
        ]))
        flow.append(tbl)
        flow.append(Spacer(1, 6 * mm))
    else:
        flow.append(Paragraph("Ingrédients : (aucun)", normal))

    # Étapes de préparation
    flow.append(Paragraph("Étapes de préparation", h2))
    steps = [ln.strip() for ln in (instructions or "").splitlines() if ln.strip()]
    if steps:
        # Liste numérotée simple
        for i, line in enumerate(steps, 1):
            flow.append(Paragraph(f"{i}. {line}", normal))
    else:
        flow.append(Paragraph("(Aucune étape renseignée)", small))
    flow.append(Spacer(1, 6 * mm))

    # Coûts
    flow.append(Paragraph("Coûts", h2))
    flow.append(Paragraph(f"Coût total : <b>{cost_total:,.2f} $</b>", normal))
    flow.append(Paragraph(f"Coût par portion : <b>{cost_per_serving:,.2f} $</b>", normal))
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph("Généré par Atelier Culinaire — POF", small))

    doc.build(flow)
    return buf.getvalue()
