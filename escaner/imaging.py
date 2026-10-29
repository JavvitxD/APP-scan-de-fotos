"""Limpieza de imágenes de páginas fotocopiadas antes de reconocer el texto.

Todo trabaja en escala de grises (numpy uint8). Las rutas se leen y escriben con
Pillow porque cv2.imread/imwrite fallan en Windows con rutas que tienen tildes.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None  # fotos de celular muy grandes no son un ataque


# --------------------------------------------------------------------------- E/S

def load_gray(path: Path | str) -> np.ndarray:
    """Abre una imagen respetando la orientación EXIF del celular."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return np.array(im.convert("L"))


def save_gray(img: np.ndarray, path: Path | str) -> None:
    Image.fromarray(img).save(path, optimize=False)


def rotate90(img: np.ndarray, degrees: int) -> np.ndarray:
    """Gira en sentido horario por múltiplos de 90°."""
    degrees %= 360
    if degrees == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def downscale(img: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale >= 1.0:
        return img, 1.0
    small = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return small, scale


# ------------------------------------------------------------- recorte de la hoja

def _order_corners(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]])


def crop_to_paper(gray: np.ndarray) -> np.ndarray:
    """Recorta la hoja de papel del fondo (mesa, piso) y corrige la perspectiva.

    Si la foto ya es solo la hoja (o es un escaneo), la devuelve igual.
    """
    small, scale = downscale(gray, 1000)
    blur = cv2.GaussianBlur(small, (7, 7), 0)
    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Cerrar huecos que deja el texto para que la hoja sea una sola mancha blanca
    k = max(5, small.shape[1] // 40)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray
    area_total = small.shape[0] * small.shape[1]
    biggest = max(contours, key=cv2.contourArea)
    frac = cv2.contourArea(biggest) / area_total
    if frac < 0.25 or frac > 0.97:
        return gray

    peri = cv2.arcLength(biggest, True)
    quad = cv2.approxPolyDP(biggest, 0.02 * peri, True)
    if len(quad) == 4 and cv2.isContourConvex(quad):
        tl, tr, br, bl = _order_corners(quad) / scale
        width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
        height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
        if width > 50 and height > 50:
            src = np.array([tl, tr, br, bl], dtype=np.float32)
            dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
            m = cv2.getPerspectiveTransform(src, dst)
            return cv2.warpPerspective(gray, m, (width, height), flags=cv2.INTER_CUBIC,
                                       borderMode=cv2.BORDER_REPLICATE)

    x, y, w, h = cv2.boundingRect(biggest)
    x, y, w, h = (int(v / scale) for v in (x, y, w, h))
    return gray[y:y + h, x:x + w]


# --------------------------------------------------------------- páginas dobles

def _ink_mask(gray: np.ndarray) -> np.ndarray:
    """Máscara de trazos de texto; ignora sombras anchas (umbral adaptativo)."""
    block = max(15, (min(gray.shape[:2]) // 40) | 1)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 15)


def _ink_profile(small: np.ndarray) -> np.ndarray:
    ink = _ink_mask(small).sum(axis=0).astype(np.float64)
    win = max(3, small.shape[1] // 100)
    return np.convolve(ink, np.ones(win) / win, mode="same")


def _blank_runs(profile: np.ndarray, lo: int, hi: int) -> list[tuple[int, int, int | None]]:
    """Tramos de columnas sin texto entre lo y hi, como (inicio, fin, raya).

    Une los tramos separados por una franja angosta: la sombra del lomo en la fotocopia se
    ve como una raya oscura, y si existe, «raya» es su columna central (el lomo exacto)."""
    text_level = float(np.percentile(profile, 75))
    if text_level <= 0:
        return []
    blank = profile[lo:hi] < 0.12 * text_level
    runs: list[list[int]] = []
    start = None
    for i, b in enumerate(blank):
        if b and start is None:
            start = i
        elif not b and start is not None:
            runs.append([lo + start, lo + i])
            start = None
    if start is not None:
        runs.append([lo + start, hi])
    max_gap = int(len(profile) * 0.03)
    merged: list[list] = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= max_gap:
            prev = merged[-1]
            if prev[2] is None or (a - prev[1]) > prev[3]:
                prev[2], prev[3] = (prev[1] + a) // 2, a - prev[1]
            prev[1] = b
        else:
            merged.append([a, b, None, 0])
    return [(a, b, stripe) for a, b, stripe, _ in merged]


def find_gutter(gray: np.ndarray) -> int:
    """Columna donde se juntan las dos páginas: el centro del canal sin texto más cercano al medio."""
    small, scale = downscale(gray, 1200)
    profile = _ink_profile(small)
    w = small.shape[1]
    runs = _blank_runs(profile, int(w * 0.3), int(w * 0.7))
    if runs:
        a, b, stripe = max(runs, key=lambda r: (r[1] - r[0]) - 0.5 * abs((r[0] + r[1]) / 2 - w / 2))
        x = stripe if stripe is not None else (a + b) // 2
    else:
        lo, hi = int(w * 0.4), int(w * 0.6)
        x = lo + int(np.argmin(profile[lo:hi]))
    return int(x / scale)


def looks_like_two_pages(gray: np.ndarray) -> bool:
    """Una página de libro es vertical; una hoja apaisada casi siempre trae dos páginas."""
    h, w = gray.shape[:2]
    if w < h * 1.15:
        return False
    small, _ = downscale(gray, 1200)
    profile = _ink_profile(small)
    sw = small.shape[1]
    left = profile[int(sw * 0.1):int(sw * 0.35)]
    right = profile[int(sw * 0.65):int(sw * 0.9)]
    # Hay texto a ambos lados y un canal sin texto cerca del medio
    has_text = min(float(np.median(left)), float(np.median(right))) > 0
    return has_text and bool(_blank_runs(profile, int(sw * 0.3), int(sw * 0.7)))


def split_part(gray: np.ndarray, part: str) -> np.ndarray:
    if part not in ("left", "right"):
        return gray
    x = find_gutter(gray)
    return gray[:, :x] if part == "left" else gray[:, x:]


# --------------------------------------------------------------- enderezado

def estimate_skew(gray: np.ndarray, max_angle: float = 8.0) -> float:
    """Ángulo (grados) que endereza las líneas de texto, buscando el perfil más nítido."""
    small, _ = downscale(gray, 1000)
    ink = _ink_mask(small)
    if ink.mean() < 0.5:  # página casi en blanco
        return 0.0
    h, w = ink.shape
    center = (w / 2, h / 2)

    def score(angle: float) -> float:
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        rot = cv2.warpAffine(ink, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        rows = rot.sum(axis=1, dtype=np.float64)
        return float(np.var(rows))

    coarse = np.arange(-max_angle, max_angle + 0.01, 0.5)
    best = max(coarse, key=score)
    fine = np.arange(best - 0.5, best + 0.51, 0.1)
    return float(max(fine, key=score))


def rotate_by(gray: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.05:
        return gray
    h, w = gray.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


# --------------------------------------------------------------- limpieza

def normalize_background(gray: np.ndarray) -> np.ndarray:
    """Quita el fondo gris, las sombras y la luz desigual: papel blanco, letra negra."""
    k = max(15, (min(gray.shape[:2]) // 25) | 1)
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    background = cv2.GaussianBlur(background, (0, 0), k / 4)
    norm = cv2.divide(gray, np.maximum(background, 1), scale=255)
    # Estirar el contraste: el 1% más oscuro a negro
    lo = float(np.percentile(norm, 1))
    hi = 255.0
    if hi - lo < 1:
        return norm
    out = np.clip((norm.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255)
    return out.astype(np.uint8)


def remove_borders_and_specks(gray: np.ndarray) -> np.ndarray:
    """Borra los bordes negros de la fotocopia y los puntitos sueltos de tóner."""
    _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    h, w = gray.shape[:2]
    speck_area = max(2, int(round((h / 3000.0) ** 2 * 6)))
    erase = np.zeros(n, dtype=bool)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches = x == 0 or y == 0 or x + bw >= w or y + bh >= h
        big = bw > 0.1 * w or bh > 0.1 * h
        if (touches and big) or area <= speck_area:
            erase[i] = True
    out = gray.copy()
    out[erase[labels]] = 255
    return out


def ensure_resolution(gray: np.ndarray, min_height: int = 1800) -> np.ndarray:
    """Tesseract lee mejor letras grandes: amplía fotos pequeñas."""
    h, w = gray.shape[:2]
    if h >= min_height:
        return gray
    f = min(3.0, min_height / h)
    return cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_CUBIC)


# --------------------------------------------------------------- procesos completos

def prepare_source(gray: np.ndarray, rotation: int) -> np.ndarray:
    """Foto original → hoja recortada y girada (antes de partirla en dos)."""
    return crop_to_paper(rotate90(gray, rotation))


def process_page(gray: np.ndarray, rotation: int, part: str, clean: bool = True) -> np.ndarray:
    """Foto original → página lista para leer."""
    sheet = prepare_source(gray, rotation)
    page = split_part(sheet, part)
    page = ensure_resolution(page)
    page = rotate_by(page, estimate_skew(page))
    if clean:
        page = normalize_background(page)
        page = remove_borders_and_specks(page)
    return page


def thumbnail(gray: np.ndarray, size: int = 220) -> np.ndarray:
    return downscale(gray, size)[0]
