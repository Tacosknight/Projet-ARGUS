"""
Module de pré-traitement d'images de factures.
Détection de document, redressement par homographie (4 points) et binarisation adaptative.
"""

from pathlib import Path
from typing import Optional, Tuple, Union
import cv2
import numpy as np


def order_points(pts: np.ndarray) -> np.ndarray:
    """
    Ordonne 4 points dans le sens horaire :
    [top-left, top-right, bottom-right, bottom-left].

    Args:
        pts (np.ndarray): Tableau numpy de forme (4, 2) contenant les coordonnées (x, y).

    Returns:
        np.ndarray: Tableau réordonné de forme (4, 2) de type float32.
    """
    pts = pts.reshape(4, 2).astype(np.float32)
    rect = np.zeros((4, 2), dtype=np.float32)

    # Le point en haut à gauche (top-left) a la plus petite somme (x + y)
    # Le point en bas à droite (bottom-right) a la plus grande somme (x + y)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    # Le point en haut à droite (top-right) a la plus petite différence (y - x)
    # Le point en bas à gauche (bottom-left) a la plus grande différence (y - x)
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]

    return rect


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    Applique une transformation de perspective (homographie) pour redresser
    le document photographié à plat.

    Args:
        image (np.ndarray): Image source.
        pts (np.ndarray): Coordonnées des 4 sommets du document.

    Returns:
        np.ndarray: Image redressée en vue du dessus (vue orthogonale).
    """
    rect = order_points(pts)
    (tl, tr, br, bl) = rect

    # Calcul de la largeur maximale du document
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = max(int(round(width_a)), int(round(width_b)))

    # Calcul de la hauteur maximale du document
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = max(int(round(height_a)), int(round(height_b)))

    # Garde-fou contre des dimensions dégénérées
    if max_width < 100 or max_height < 100:
        return image

    # Coordonnées cibles de destination
    dst = np.array(
        [
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ],
        dtype=np.float32,
    )

    # Calcul de la matrice de transformation de perspective
    matrix = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(
        image, matrix, (max_width, max_height), flags=cv2.INTER_CUBIC
    )
    return warped


def is_already_flat_document(image: np.ndarray, border_thickness: int = 15) -> bool:
    """
    Vérifie si l'image est déjà un document scanné plein cadre ou à fond uniforme clair,
    évitant ainsi de confondre un tableau interne avec le contour externe du document.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    h, w = gray.shape[:2]
    # Échantillonnage des 4 bordures extérieures
    top_edge = gray[:border_thickness, :]
    bottom_edge = gray[h - border_thickness :, :]
    left_edge = gray[:, :border_thickness]
    right_edge = gray[:, w - border_thickness :]

    edges_mean = (
        np.mean(top_edge) + np.mean(bottom_edge) + np.mean(left_edge) + np.mean(right_edge)
    ) / 4.0

    # Si tous les bords sont très clairs (> 230), l'image est déjà une page entière sans table autour
    return bool(edges_mean > 230)


def find_document_contour(
    image: np.ndarray,
    min_area_ratio: float = 0.35,
    max_area_ratio: float = 0.98,
) -> Optional[np.ndarray]:
    """
    Détecte le contour polygonal à 4 sommets d'une feuille de document
    posée sur une surface (bureau, table, etc.).

    Args:
        image (np.ndarray): Image en entrée.
        min_area_ratio (float): L'aire minimale requise par rapport à l'image (défaut 35%).
        max_area_ratio (float): L'aire maximale (défaut 98%).

    Returns:
        Optional[np.ndarray]: Les 4 sommets du contour de forme (4, 2), ou None si non trouvé.
    """
    # Si le document est déjà plein cadre sur fond blanc, pas besoin de chercher un contour interne
    if is_already_flat_document(image):
        return None

    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # Flou gaussien pour éliminer le bruit haute fréquence
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Détection des contours de Canny avec seuils adaptés
    edged = cv2.Canny(blurred, 50, 150)

    # Dilatation morphologique pour fermer les bords discontinus
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edged = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Recherche des contours externes
    contours, _ = cv2.findContours(
        edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None

    # Tri par aire décroissante
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    img_h, img_w = image.shape[:2]
    img_area = float(img_h * img_w)

    for c in contours:
        area = cv2.contourArea(c)
        area_ratio = area / img_area
        if area_ratio < min_area_ratio:
            break
        if area_ratio > max_area_ratio:
            continue

        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)

        # Si le polygone a 4 sommets et est convexe
        if len(approx) == 4 and cv2.isContourConvex(approx):
            pts = approx.reshape(4, 2)
            # Vérification du ratio d'aspect (doit ressembler à un document A4 / lettre)
            rect = order_points(pts)
            w = max(np.linalg.norm(rect[1] - rect[0]), np.linalg.norm(rect[2] - rect[3]))
            h = max(np.linalg.norm(rect[3] - rect[0]), np.linalg.norm(rect[2] - rect[1]))
            aspect_ratio = max(w, h) / (min(w, h) + 1e-5)

            # Un document A4 a un ratio ~ 1.41. On tolère entre 1.05 et 1.85
            if 1.05 <= aspect_ratio <= 1.85:
                return pts

    return None


def resize_to_target_height(
    image: np.ndarray, target_height: int = 1600
) -> Tuple[np.ndarray, float]:
    """
    Redimensionne une image pour atteindre la hauteur cible tout en conservant
    le ratio d'aspect.

    Args:
        image (np.ndarray): Image source.
        target_height (int): Hauteur cible en pixels (défaut 1600).

    Returns:
        Tuple[np.ndarray, float]: (image redimensionnée, ratio d'échelle appliqué).
    """
    h, w = image.shape[:2]
    if h == 0 or w == 0:
        raise ValueError("L'image possède des dimensions nulles.")

    ratio = target_height / float(h)
    target_width = int(round(w * ratio))
    interpolation = cv2.INTER_AREA if ratio < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(image, (target_width, target_height), interpolation=interpolation)
    return resized, ratio


def apply_adaptive_filter(
    image: np.ndarray, block_size: int = 35, c_constant: int = 11
) -> np.ndarray:
    """
    Applique un seuillage adaptatif pour éliminer les dégradés d'ombres
    et maximiser le contraste texte/arrière-plan.

    Args:
        image (np.ndarray): Image source BGR ou niveaux de gris.
        block_size (int): Taille de la fenêtre locale (doit être impaire).
        c_constant (int): Constante soustraite de la moyenne pondérée.

    Returns:
        np.ndarray: Image binarisée convertie en 3 canaux BGR (compatible OCR).
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    if block_size % 2 == 0:
        block_size += 1
    block_size = max(3, block_size)

    # Filtrage adaptatif gaussien pour éliminer les ombrages de prise de vue
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        c_constant,
    )

    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def preprocess_image(
    image_path: Union[str, Path, np.ndarray],
    target_height: int = 2400,
    apply_threshold: bool = False,
) -> np.ndarray:
    """
    Pipeline complet de pré-traitement d'une photo de facture :
    1. Chargement robuste de l'image (chemins UTF-8 / espaces).
    2. Redimensionnement initial à la hauteur cible (1600 px).
    3. Détection des 4 sommets du document et redressement par homographie.
       (Conserve l'image d'origine redimensionnée en cas d'échec ou si déjà plane).
    4. Binarisation adaptative pour effacer les ombres et maximiser le contraste.

    Args:
        image_path: Chemin du fichier image ou matrice numpy.
        target_height: Hauteur cible en pixels (défaut 1600).
        apply_threshold: Appliquer le filtre adaptatif final.

    Returns:
        np.ndarray: Image pré-traitée prête pour l'OCR (format BGR).
    """
    if isinstance(image_path, np.ndarray):
        img = image_path.copy()
    else:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"L'image source est introuvable : {image_path}")

        data = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Impossible de décoder le fichier en tant qu'image : {image_path}")

    # 1. Redimensionnement initial pour normaliser l'échelle
    resized, _ = resize_to_target_height(img, target_height=target_height)

    # 2. Détection du document et homographie 4 points
    contour_pts = find_document_contour(resized)
    if contour_pts is not None:
        warped = four_point_transform(resized, contour_pts)
        if warped.shape[0] != target_height and warped.shape[0] > 0:
            warped, _ = resize_to_target_height(warped, target_height=target_height)
    else:
        warped = resized

    # 3. Filtre adaptatif pour gommer les ombres
    if apply_threshold:
        processed = apply_adaptive_filter(warped)
    else:
        processed = warped

    return processed
