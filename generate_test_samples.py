"""
Générateur d'échantillons réalistes pour Facture-Checker.
Inclut le scénario audioprothétique avec corrélation Dépenses Fabricants ↔ Refacturations Patients via S/N :
1. Fournisseur Achat Phonak (S/N: SN-2409PH892)
2. Client Vente Patient (S/N: SN-2409PH892) -> RAPPROCHÉ
3. Fournisseur Achat Oticon (S/N: SN-2311OT451) -> NON REFACTURÉ (Dépense orpheline)
4. Client Vente Widex (S/N: SN-2208WD704) -> ACHAT FABRICANT MANQUANT
"""

from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def draw_hearing_aid_invoice(
    filepath: str,
    invoice_type: str,  # 'FOURNISSEUR' ou 'CLIENT'
    tiers_title: str,
    siret: str,
    num_facture: str,
    date_str: str,
    device_model: str,
    serial_number: str,
    ht: float,
    tva: float,
    ttc: float,
    patient_name: str = "",
) -> None:
    img = Image.new("RGB", (1200, 1600), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    f_title = get_font(32, bold=True)
    f_h2 = get_font(23, bold=True)
    f_reg = get_font(21, bold=False)
    f_bold = get_font(21, bold=True)
    f_small = get_font(18, bold=False)

    # 1. En-tête
    if invoice_type == "FOURNISSEUR":
        draw.text((80, 60), tiers_title.upper(), fill=(20, 20, 20), font=f_title)
        draw.text((80, 105), "Fabricant de Systèmes et Prothèses Auditives", fill=(80, 80, 80), font=f_small)
        draw.text((80, 135), f"SIRET : {siret}", fill=(0, 0, 0), font=f_bold)
        draw.text((80, 165), "TVA Intracommunautaire : FR 39 356000000", fill=(0, 0, 0), font=f_reg)
    else:
        draw.text((80, 60), "CENTRE D'AUDIOPROTHÈSE & AUDITION SAS", fill=(20, 20, 20), font=f_title)
        draw.text((80, 105), "Appareillage et Réhabilitation Auditive Adulte & Enfant", fill=(80, 80, 80), font=f_small)
        draw.text((80, 135), f"SIRET : {siret}", fill=(0, 0, 0), font=f_bold)
        draw.text((80, 165), "TVA Intracommunautaire : FR 39 356000000", fill=(0, 0, 0), font=f_reg)

    # 2. Encadré Facture
    draw.rectangle([80, 220, 1120, 320], outline=(180, 180, 180), width=2)
    titre_fac = f"FACTURE FOURNISSEUR N° : {num_facture}" if invoice_type == "FOURNISSEUR" else f"FACTURE PATIENT N° : {num_facture}"
    draw.text((110, 250), titre_fac, fill=(0, 0, 0), font=f_h2)
    draw.text((700, 250), f"Date de facture : {date_str}", fill=(0, 0, 0), font=f_h2)

    # 3. Bloc Destinataire
    if invoice_type == "FOURNISSEUR":
        draw.text((700, 350), "DESTINATAIRE / LIVRAISON :", fill=(100, 100, 100), font=f_small)
        draw.text((700, 380), "CENTRE AUDITION EXPERT", fill=(0, 0, 0), font=f_bold)
        draw.text((700, 410), "15 Place Bellecour, 69002 Lyon", fill=(70, 70, 70), font=f_reg)
    else:
        draw.text((700, 350), "PATIENT / ASSURÉ SOCIAL :", fill=(100, 100, 100), font=f_small)
        draw.text((700, 380), f"Patient : {patient_name.upper()}", fill=(0, 0, 0), font=f_bold)
        draw.text((700, 410), "Sécurité Sociale : Prise en charge 100% Santé", fill=(70, 70, 70), font=f_small)

    # 4. Tableau des articles avec Numéro de Série S/N
    draw.rectangle([80, 490, 1120, 950], outline=(150, 150, 150), width=2)
    draw.rectangle([80, 490, 1120, 550], fill=(240, 242, 245), outline=(150, 150, 150), width=2)

    draw.text((110, 510), "Désignation de la Prothèse Auditive", fill=(0, 0, 0), font=f_bold)
    draw.text((640, 510), "Qté", fill=(0, 0, 0), font=f_bold)
    draw.text((780, 510), "P.U. HT", fill=(0, 0, 0), font=f_bold)
    draw.text((950, 510), "Total HT", fill=(0, 0, 0), font=f_bold)

    # Ligne 1 : Appareil
    draw.text((110, 580), f"Aide auditive : {device_model}", fill=(20, 20, 20), font=f_bold)
    draw.text((110, 620), f"Numéro de série S/N : {serial_number}", fill=(0, 50, 160), font=f_bold)
    draw.text((110, 660), "Dispositif Médical de Classe IIa - Marquage CE", fill=(100, 100, 100), font=f_small)

    draw.text((650, 580), "1", fill=(30, 30, 30), font=f_reg)
    draw.text((785, 580), f"{ht:.2f} €", fill=(30, 30, 30), font=f_reg)
    draw.text((955, 580), f"{ht:.2f} €", fill=(30, 30, 30), font=f_reg)

    # 5. Cadre des Totaux
    draw.rectangle([640, 1030, 1120, 1260], fill=(248, 249, 250), outline=(180, 180, 180), width=2)
    draw.text((670, 1055), "Total HT :", fill=(0, 0, 0), font=f_bold)
    draw.text((940, 1055), f"{ht:.2f} €", fill=(0, 0, 0), font=f_bold)

    draw.text((670, 1115), "Montant TVA (20%) :", fill=(0, 0, 0), font=f_bold)
    draw.text((940, 1115), f"{tva:.2f} €", fill=(0, 0, 0), font=f_bold)

    draw.line([670, 1170, 1090, 1170], fill=(180, 180, 180), width=2)

    draw.text((670, 1195), "Net à payer :", fill=(0, 0, 0), font=f_h2)
    draw.text((940, 1195), f"{ttc:.2f} €", fill=(0, 0, 0), font=f_h2)

    # Pied de page
    draw.text(
        (220, 1470),
        "Conditions de règlement : 30 jours net. Traçabilité des numéros de série assurée.",
        fill=(120, 120, 120),
        font=f_small,
    )

    doc_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    cv2.imwrite(filepath, doc_cv)


def generate_all_samples(output_folder: Path) -> None:
    output_folder.mkdir(parents=True, exist_ok=True)

    # 1. Achat Fabricant Phonak (Appareil S/N: SN-2409PH892) -> Coût TTC: 960.00 €
    draw_hearing_aid_invoice(
        filepath=str(output_folder / "01_fournisseur_phonak_achat.png"),
        invoice_type="FOURNISSEUR",
        tiers_title="Sonova France SAS (Phonak)",
        siret="356 000 000 00014",
        num_facture="FAC-PHONAK-892",
        date_str="10/01/2024",
        device_model="Phonak Audéo Lumity L90-R",
        serial_number="SN-2409PH892",
        ht=800.00,
        tva=160.00,
        ttc=960.00,
    )

    # 2. Vente Patient Jean Dupont (Même appareil S/N: SN-2409PH892) -> Refacturation TTC: 960.00 €
    # RAPPROCHEMENT PARFAIT (Dépense = Refacturation)
    draw_hearing_aid_invoice(
        filepath=str(output_folder / "02_client_patient_vente_reconciliee.png"),
        invoice_type="CLIENT",
        tiers_title="Centre Audition Expert",
        siret="356 000 000 00014",
        num_facture="FC-PATIENT-2024-041",
        date_str="25/01/2024",
        device_model="Phonak Audéo Lumity L90-R",
        serial_number="SN-2409PH892",
        ht=800.00,
        tva=160.00,
        ttc=960.00,
        patient_name="Jean Dupont",
    )

    # 3. Achat Fabricant Oticon (Appareil S/N: SN-2311OT451) -> Coût TTC: 900.00 €
    # NON REFACTURÉ (Dépense engagée sans facture patient en face !)
    draw_hearing_aid_invoice(
        filepath=str(output_folder / "03_fournisseur_oticon_non_refacture.png"),
        invoice_type="FOURNISSEUR",
        tiers_title="Oticon France SAS",
        siret="356 000 000 00014",
        num_facture="FAC-OTICON-451",
        date_str="05/02/2024",
        device_model="Oticon Real 1 miniRITE R",
        serial_number="SN-2311OT451",
        ht=750.00,
        tva=150.00,
        ttc=900.00,
    )

    # 4. Vente Patient Sophie Bernard (Appareil S/N: SN-2208WD704) -> Prix TTC: 1080.00 €
    # ACHAT FABRICANT NON TROUVÉ EN BASE
    draw_hearing_aid_invoice(
        filepath=str(output_folder / "04_client_widex_achat_manquant.png"),
        invoice_type="CLIENT",
        tiers_title="Centre Audition Expert",
        siret="356 000 000 00014",
        num_facture="FC-PATIENT-2024-058",
        date_str="12/02/2024",
        device_model="Widex Moment sRIC 440",
        serial_number="SN-2208WD704",
        ht=900.00,
        tva=180.00,
        ttc=1080.00,
        patient_name="Sophie Bernard",
    )

    print(f"Échantillons prothèses auditives générés dans {output_folder}")


if __name__ == "__main__":
    generate_all_samples(Path("facture-checker/input_photos"))
