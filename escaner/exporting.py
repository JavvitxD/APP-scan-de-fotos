"""Exportar el libro a PDF buscable, Word y texto plano."""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from .ocr import OcrLine, OcrResult, ends_sentence
from .project import Page, Project

Progress = Callable[[int, int], None]

PDF_DPI = 300  # resolución que se asume para calcular el tamaño de la hoja
PDF_MAX_HEIGHT = 2400  # píxeles; mantiene el PDF de 300 páginas en un tamaño razonable


# ------------------------------------------------------------------ texto corrido

def join_lines(text: str) -> list[str]:
    """Convierte las líneas de la página en párrafos corridos y une palabras cortadas con guion."""
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        if paragraphs and not ends_sentence(paragraphs[-1]) and lines[0][:1].islower():
            out = paragraphs.pop()  # el párrafo anterior seguía en este
        else:
            out = lines.pop(0)
        for line in lines:
            if re.search(r"\w-$", out) and line[:1].islower():
                out = out[:-1] + line
            else:
                out += " " + line
        paragraphs.append(out)
    return paragraphs


def _pages_with_text(project: Project) -> list[tuple[Page, str]]:
    return [(p, project.page_text(p)) for p in project.pages]


def export_txt(project: Project, dest: Path, flow: bool = True, page_marks: bool = False,
               progress: Progress | None = None) -> None:
    parts: list[str] = []
    items = _pages_with_text(project)
    for i, (page, text) in enumerate(items, 1):
        if page_marks:
            parts.append(f"--- Página {i} ---")
        body = "\n\n".join(join_lines(text)) if flow else text.strip()
        parts.append(body)
        if progress:
            progress(i, len(items))
    dest.write_text("\n\n".join(parts).strip() + "\n", encoding="utf-8-sig")


def export_docx(project: Project, dest: Path, flow: bool = True, page_breaks: bool = True,
                progress: Progress | None = None) -> None:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    doc.add_heading(project.name, level=0)

    items = _pages_with_text(project)
    for i, (page, text) in enumerate(items, 1):
        paragraphs = join_lines(text) if flow else [b for b in re.split(r"\n\s*\n", text.strip()) if b]
        for para in paragraphs:
            doc.add_paragraph(para)
        if page_breaks and i < len(items):
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        if progress:
            progress(i, len(items))
    doc.save(str(dest))


# ------------------------------------------------------------------ PDF buscable

def _text_lines_for_layer(ocr: OcrResult | None, text: str, img_w: int, img_h: int) -> list[OcrLine]:
    """Decide dónde va cada línea de texto invisible sobre la imagen.

    Si el texto no se corrigió, se usan las posiciones exactas del OCR. Si se corrigió,
    se reparten las líneas corregidas sobre las líneas detectadas (o sobre la zona de texto).
    """
    wanted = [l.strip() for l in text.splitlines() if l.strip()]
    if not wanted:
        return []
    detected = ocr.lines if ocr else []
    if detected and [l.text for l in detected] == wanted:
        return detected
    if len(detected) == len(wanted):
        return [OcrLine(t, l.bbox) for t, l in zip(wanted, detected)]
    if detected:
        x0 = min(l.bbox[0] for l in detected)
        y0 = min(l.bbox[1] for l in detected)
        x1 = max(l.bbox[2] for l in detected)
        y1 = max(l.bbox[3] for l in detected)
    else:
        x0, y0, x1, y1 = int(img_w * 0.1), int(img_h * 0.08), int(img_w * 0.9), int(img_h * 0.92)
    step = (y1 - y0) / len(wanted)
    return [OcrLine(t, (x0, int(y0 + i * step), x1, int(y0 + (i + 0.8) * step))) for i, t in enumerate(wanted)]


def _pdf_safe(text: str) -> str:
    # Las fuentes estándar del PDF usan WinAnsi: tildes y ñ funcionan; otros símbolos raros no.
    return text.encode("cp1252", "replace").decode("cp1252")


def export_pdf(project: Project, dest: Path, progress: Progress | None = None) -> list[int]:
    """Crea un PDF con la imagen de cada página y el texto invisible encima (se puede buscar y copiar).

    Devuelve los números de las páginas que se omitieron por no estar procesadas.
    """
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(dest))
    c.setTitle(project.name)
    c.setCreator("Escáner de Libros")
    skipped: list[int] = []
    total = len(project.pages)
    font = "Helvetica"

    for n, page in enumerate(project.pages, 1):
        img_path = project.processed_path(page)
        if not img_path.exists():
            skipped.append(n)
            if progress:
                progress(n, total)
            continue
        ocr, text = project.load_page_data(page)
        with Image.open(img_path) as im:
            im = im.convert("L")
            w_px, h_px = im.size
            factor = min(1.0, PDF_MAX_HEIGHT / h_px)
            if factor < 1.0:
                im = im.resize((int(w_px * factor), int(h_px * factor)), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=72, optimize=True)
        buf.seek(0)

        page_w = w_px * 72.0 / PDF_DPI
        page_h = h_px * 72.0 / PDF_DPI
        k = 72.0 / PDF_DPI  # píxeles → puntos
        c.setPageSize((page_w, page_h))
        c.drawImage(ImageReader(buf), 0, 0, width=page_w, height=page_h)

        for line in _text_lines_for_layer(ocr, text, w_px, h_px):
            s = _pdf_safe(line.text)
            x0, y0, x1, y1 = line.bbox
            height_pt = max(1.0, (y1 - y0) * k)
            size = height_pt * 0.85
            natural = stringWidth(s, font, size)
            if natural <= 0:
                continue
            t = c.beginText()
            t.setTextRenderMode(3)  # invisible
            t.setFont(font, size)
            t.setHorizScale(100.0 * (x1 - x0) * k / natural)
            t.setTextOrigin(x0 * k, page_h - y1 * k + height_pt * 0.2)
            t.textOut(s)
            c.drawText(t)
        c.showPage()
        if progress:
            progress(n, total)
    c.save()
    return skipped
