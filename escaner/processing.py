"""Une la limpieza de imagen y el reconocimiento de texto para cada página."""

from __future__ import annotations

import traceback

import numpy as np
from PIL import Image

from . import imaging
from .ocr import OcrEngine
from .project import DONE, ERROR, Page, Project, Source


def analyze_source(project: Project, source: Source, engine: OcrEngine | None) -> None:
    """Al importar: detecta si la foto está girada y si trae una o dos páginas."""
    settings = project.settings
    gray = imaging.load_gray(project.original_path(source))
    small, _ = imaging.downscale(gray, 1600)
    if settings.auto_rotate and engine is not None:
        source.rotation = engine.detect_rotation(imaging.crop_to_paper(small))
    if settings.page_mode == "dos":
        source.two_pages = True
    elif settings.page_mode == "una":
        source.two_pages = False
    else:
        source.two_pages = imaging.looks_like_two_pages(imaging.prepare_source(small, source.rotation))


def preview(project: Project, page: Page, max_side: int = 1400) -> np.ndarray:
    """Vista rápida de una página aún sin procesar (girada y partida, sin limpiar)."""
    source = project.source(page.source_id)
    gray = imaging.load_gray(project.original_path(source))
    small, _ = imaging.downscale(gray, max_side * (2 if page.part != "full" else 1))
    return imaging.split_part(imaging.prepare_source(small, source.rotation), page.part)


def save_thumbnail(project: Project, page: Page, gray: np.ndarray) -> None:
    Image.fromarray(imaging.thumbnail(gray)).save(project.thumb_path(page), quality=80)


def process_page(project: Project, page: Page, engine: OcrEngine) -> None:
    """Limpia la página, reconoce su texto y lo guarda. Nunca lanza excepciones."""
    try:
        source = project.source(page.source_id)
        gray = imaging.load_gray(project.original_path(source))
        clean = imaging.process_page(gray, source.rotation, page.part, project.settings.clean)
        imaging.save_gray(clean, project.processed_path(page))
        save_thumbnail(project, page, clean)
        result = engine.recognize(clean)
        project.save_ocr(page, result)
        page.status, page.edited, page.error = DONE, False, ""
    except Exception as exc:  # una página mala no debe detener el libro entero
        page.status = ERROR
        page.error = f"{exc}"
        traceback.print_exc()
