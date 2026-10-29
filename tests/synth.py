"""Genera páginas de libro falsas, con defectos de fotocopia y de foto, para las pruebas."""

from __future__ import annotations

import textwrap
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "C:/Windows/Fonts/times.ttf",
]

TEXT_A = (
    "Capítulo uno. La biblioteca del pueblo estaba en una casa vieja, junto a la plaza. "
    "Allí aprendí a leer en español con los libros que nadie pedía prestados. "
    "Cada tarde, después de la escuela, la señora Begoña abría la puerta y me dejaba "
    "quedarme hasta que oscurecía. Recuerdo el olor del papel y el ruido de la lluvia "
    "sobre el tejado. Aquellos años me enseñaron que la paciencia también es una forma "
    "de valentía, y que un buen libro puede acompañarnos toda la vida."
)

TEXT_B = (
    "Muchos años después volví a la ciudad y busqué la casa. Ya no estaba: en su lugar "
    "habían construido un edificio de oficinas. Pregunté por los libros y nadie supo "
    "decirme qué había pasado con ellos. Entonces comprendí que la memoria es frágil y "
    "que vale la pena guardar lo que amamos, aunque sea en una copia sencilla, para que "
    "otros puedan encontrarlo algún día."
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    raise RuntimeError("No hay fuente para generar páginas de prueba")


def render_page(text: str, width: int = 1700, height: int = 2400, font_size: int = 44, number: int = 1) -> np.ndarray:
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    font = _font(font_size)
    margin = int(width * 0.12)
    chars = int((width - 2 * margin) / (font_size * 0.47))
    y = int(height * 0.1)
    for para in [text, text]:
        for line in textwrap.wrap(para, chars):
            draw.text((margin, y), line, fill=0, font=font)
            y += int(font_size * 1.5)
        y += font_size
    draw.text((width // 2, height - int(height * 0.06)), str(number), fill=0, font=font)
    return np.array(img)


def photocopy(gray: np.ndarray, seed: int = 0) -> np.ndarray:
    """Fondo gris desigual, tóner suelto y un borde negro, como una fotocopia vieja."""
    rng = np.random.default_rng(seed)
    h, w = gray.shape
    yy, xx = np.mgrid[0:h, 0:w]
    shade = 200 + 35 * (xx / w) - 20 * (yy / h)
    out = (gray.astype(np.float32) / 255.0) * shade
    specks = rng.random((h, w)) > 0.9993
    out[specks] = 40
    out[:, : int(w * 0.02)] = 30  # borde negro de la fotocopiadora
    return np.clip(out, 0, 255).astype(np.uint8)


def spread(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Dos páginas lado a lado con la sombra del lomo en medio."""
    h = max(left.shape[0], right.shape[0])
    gutter = np.full((h, 60), 255, np.uint8)
    gutter[:, 20:40] = 90
    return np.hstack([left[:h], gutter, right[:h]])


def photograph(sheet: np.ndarray, angle: float = 3.0, table: int = 60, seed: int = 0) -> np.ndarray:
    """Pone la hoja sobre una mesa oscura, un poco girada y en perspectiva."""
    rng = np.random.default_rng(seed)
    h, w = sheet.shape
    pad = int(max(h, w) * 0.12)
    canvas = np.full((h + 2 * pad, w + 2 * pad), table, np.uint8)
    canvas[pad:pad + h, pad:pad + w] = sheet
    ch, cw = canvas.shape
    m = cv2.getRotationMatrix2D((cw / 2, ch / 2), angle, 1.0)
    canvas = cv2.warpAffine(canvas, m, (cw, ch), borderValue=table)
    d = int(min(ch, cw) * 0.03)
    src = np.float32([[0, 0], [cw, 0], [cw, ch], [0, ch]])
    dst = np.float32([[d, 0], [cw - d, d // 2], [cw, ch], [0, ch - d // 2]])
    canvas = cv2.warpPerspective(canvas, cv2.getPerspectiveTransform(src, dst), (cw, ch), borderValue=table)
    noise = rng.normal(0, 4, canvas.shape)
    return np.clip(canvas + noise, 0, 255).astype(np.uint8)


def save(gray: np.ndarray, path: Path, quality: int = 90) -> Path:
    Image.fromarray(gray).save(path, quality=quality)
    return path
