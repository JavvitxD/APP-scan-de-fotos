from __future__ import annotations

import difflib
import shutil
from pathlib import Path

import numpy as np
import pytest

from escaner import exporting, imaging, paths, processing
from escaner.ocr import OcrEngine, parse_tsv
from escaner.project import DONE, PENDING, Project

from . import synth

HAS_TESSERACT = paths.find_tesseract() is not None
needs_ocr = pytest.mark.skipif(not HAS_TESSERACT, reason="Tesseract no está instalado")


def similarity(a: str, b: str) -> float:
    norm = lambda s: " ".join(s.split()).lower()
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


@pytest.fixture(scope="module")
def engine():
    if not HAS_TESSERACT:
        pytest.skip("Tesseract no está instalado")
    return OcrEngine()


@pytest.fixture
def project(tmp_path):
    return Project.create(tmp_path, "Libro de prueba")


# ---------------------------------------------------------------- imagen

def test_estimate_skew_recovers_angle():
    page = synth.render_page(synth.TEXT_A)
    tilted = imaging.rotate_by(page, -3.0)
    assert imaging.estimate_skew(tilted) == pytest.approx(3.0, abs=0.3)


def test_crop_to_paper_removes_table():
    sheet = synth.photocopy(synth.render_page(synth.TEXT_A))
    photo = synth.photograph(sheet, angle=0)
    cropped = imaging.crop_to_paper(photo)
    assert cropped.shape[0] < photo.shape[0] * 0.92
    assert cropped.shape[1] < photo.shape[1] * 0.92


def test_two_page_detection():
    left = synth.render_page(synth.TEXT_A, number=10)
    right = synth.render_page(synth.TEXT_B, number=11)
    assert imaging.looks_like_two_pages(synth.photocopy(synth.spread(left, right)))
    assert not imaging.looks_like_two_pages(synth.photocopy(left))


def test_gutter_is_near_center():
    left = synth.render_page(synth.TEXT_A)
    right = synth.render_page(synth.TEXT_B)
    s = synth.spread(left, right)
    x = imaging.find_gutter(s)
    assert abs(x - (left.shape[1] + 30)) < 80


def test_cleaning_whitens_background():
    sheet = synth.photocopy(synth.render_page(synth.TEXT_A))
    clean = imaging.remove_borders_and_specks(imaging.normalize_background(sheet))
    assert np.median(clean) > 245
    assert clean[:, :20].mean() > 240  # borde negro eliminado


def test_unicode_paths(tmp_path):
    folder = tmp_path / "Fotos de José Ñúñez"
    folder.mkdir()
    p = synth.save(synth.render_page(synth.TEXT_A), folder / "página 1.jpg")
    assert imaging.load_gray(p).shape == (2400, 1700)


# ---------------------------------------------------------------- OCR

def test_parse_tsv_paragraphs():
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t95\tHola\n"
        "5\t1\t1\t1\t1\t2\t70\t10\t50\t20\t93\tmundo\n"
        "5\t1\t1\t1\t2\t1\t10\t40\t50\t20\t90\tadiós.\n"
        "5\t1\t1\t2\t1\t1\t10\t70\t50\t20\t88\tsigue\n"
        "5\t1\t1\t3\t1\t1\t10\t90\t50\t20\t88\tsin punto\n"
        "5\t1\t1\t4\t1\t1\t10\t120\t50\t20\t88\tFin\n"
    )
    r = parse_tsv(tsv, 200, 200)
    # Blanco tras «adiós.», pero no tras «sigue» ni «sin punto» (frase cortada por Tesseract)
    assert r.text == "Hola mundo\nadiós.\n\nsigue\nsin punto\nFin"
    assert r.lines[0].bbox == (10, 10, 120, 30)


@needs_ocr
def test_full_pipeline_photocopy_photo(engine):
    sheet = synth.photocopy(synth.render_page(synth.TEXT_A), seed=1)
    photo = synth.photograph(sheet, angle=2.5, seed=1)
    page = imaging.process_page(photo, rotation=0, part="full")
    text = engine.recognize(page).text
    expected = "\n".join([synth.TEXT_A, synth.TEXT_A])
    assert similarity(text.replace("\n1", ""), expected) > 0.93, text


@needs_ocr
def test_detect_rotation(engine):
    page = synth.render_page(synth.TEXT_A)
    sideways = imaging.rotate90(page, 90)  # el celular dejó la foto de lado
    fix = engine.detect_rotation(sideways)
    assert imaging.rotate90(sideways, fix).shape == page.shape
    assert (90 + fix) % 360 == 0


@needs_ocr
def test_project_two_page_spread_end_to_end(project, engine, tmp_path):
    left = synth.render_page(synth.TEXT_A, number=10)
    right = synth.render_page(synth.TEXT_B, number=11)
    photo = synth.photograph(synth.photocopy(synth.spread(left, right), seed=2), angle=-2, seed=2)
    f = synth.save(photo, tmp_path / "IMG_0001.jpg")

    for source in project.import_files([f]):
        processing.analyze_source(project, source, engine)
        project.append(source, project.make_pages(source))
    assert [p.part for p in project.pages] == ["left", "right"]

    for page in project.pages:
        processing.process_page(project, page, engine)
    assert all(p.status == DONE for p in project.pages), [p.error for p in project.pages]
    t_left, t_right = (project.page_text(p) for p in project.pages)
    assert "biblioteca" in t_left.lower() and "edificio" not in t_left.lower()
    assert "edificio" in t_right.lower() and "biblioteca" not in t_right.lower()

    # Corrección manual y exportación
    project.save_text(project.pages[0], t_left + "\nNOTA AÑADIDA")
    assert project.pages[0].edited
    pdf = tmp_path / "libro.pdf"
    assert exporting.export_pdf(project, pdf) == []
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    assert len(reader.pages) == 2
    assert "NOTA AÑADIDA" in reader.pages[0].extract_text()
    assert "edificio" in reader.pages[1].extract_text().lower()

    docx_path = tmp_path / "libro.docx"
    exporting.export_docx(project, docx_path)
    from docx import Document

    body = "\n".join(p.text for p in Document(str(docx_path)).paragraphs)
    assert "biblioteca" in body.lower() and "NOTA AÑADIDA" in body

    txt = tmp_path / "libro.txt"
    exporting.export_txt(project, txt, page_marks=True)
    content = txt.read_text(encoding="utf-8-sig")
    assert "--- Página 2 ---" in content

    # Reabrir el proyecto conserva todo
    project.save()
    again = Project.open(project.folder)
    assert [p.status for p in again.pages] == [DONE, DONE]
    assert again.page_text(again.pages[0]).endswith("NOTA AÑADIDA")


# ---------------------------------------------------------------- proyecto

def test_project_edit_operations(project, tmp_path):
    files = [synth.save(synth.render_page(synth.TEXT_A, 400, 560, 12), tmp_path / f"f{i}.png") for i in range(3)]
    sources = project.import_files(files)
    for s in sources:
        project.append(s, project.make_pages(s))
    assert len(project.pages) == 3

    new = project.set_two_pages(sources[1], True)
    assert [p.source_id for p in project.pages] == [sources[0].id, sources[1].id, sources[1].id, sources[2].id]
    assert [p.part for p in new] == ["left", "right"]

    ids = [p.id for p in project.pages]
    project.reorder(list(reversed(ids)))
    assert [p.id for p in project.pages] == list(reversed(ids))

    project.delete_pages(project.pages_of(sources[0].id))
    assert sources[0] not in project.sources
    assert not project.original_path(sources[0]).exists()

    project.rotate_source(sources[2], 270)
    assert sources[2].rotation == 270
    assert all(p.status == PENDING for p in project.pages)

    project.save()
    again = Project.open(project.folder)
    assert [p.id for p in again.pages] == [p.id for p in project.pages]
    assert again.source(sources[2].id).rotation == 270


def test_project_import_pdf(project, tmp_path):
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "escaneo.pdf"
    c = canvas.Canvas(str(pdf))
    for i in range(2):
        c.drawString(100, 700, f"Pagina {i + 1}")
        c.showPage()
    c.save()
    sources = project.import_files([pdf])
    assert len(sources) == 2
    assert all(project.original_path(s).exists() for s in sources)


def test_safe_project_names(tmp_path):
    a = Project.create(tmp_path, 'Mi libro: "historia"?')
    b = Project.create(tmp_path, 'Mi libro: "historia"?')
    assert a.folder.name == "Mi libro historia"
    assert b.folder.name == "Mi libro historia (2)"


# ---------------------------------------------------------------- exportar

def test_join_lines_dehyphenates():
    text = "La biblio-\nteca estaba\nabierta.\n\nOtro párrafo\nAquí."
    assert exporting.join_lines(text) == ["La biblioteca estaba abierta.", "Otro párrafo Aquí."]


def test_join_lines_merges_paragraph_cut_mid_sentence():
    assert exporting.join_lines("Allí aprendí a leer\n\nlos libros viejos.\n\nNuevo.") == [
        "Allí aprendí a leer los libros viejos.", "Nuevo."]


def test_join_lines_keeps_real_hyphens():
    assert exporting.join_lines("Fue en 1990-\n1995 cuando") == ["Fue en 1990- 1995 cuando"]
