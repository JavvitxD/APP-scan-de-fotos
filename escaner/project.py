"""Un proyecto es una carpeta con las fotos originales, las páginas procesadas y el texto.

    MiLibro/
      proyecto.json      orden de las páginas, estados y ajustes
      originales/        copias intactas de las fotos que se importaron
      procesadas/        páginas limpias (PNG)
      paginas/           texto y posiciones de cada página (JSON)
      miniaturas/        vistas pequeñas para la lista
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .ocr import OcrResult

PROJECT_FILE = "proyecto.json"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXTS = {".pdf"}

PENDING, DONE, REVIEWED, ERROR = "pendiente", "transcrita", "revisada", "error"


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _atomic_write(path: Path, data: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def safe_folder_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().rstrip(".")
    return name or "Proyecto"


@dataclass
class Settings:
    page_mode: str = "auto"  # auto | una | dos
    clean: bool = True
    auto_rotate: bool = True
    lang: str = "spa"


@dataclass
class Source:
    id: str
    file: str  # nombre dentro de originales/
    original_name: str
    rotation: int = 0
    two_pages: bool = False


@dataclass
class Page:
    id: str
    source_id: str
    part: str = "full"  # full | left | right
    status: str = PENDING
    edited: bool = False
    error: str = ""


@dataclass
class Project:
    folder: Path
    name: str
    created: str = ""
    settings: Settings = field(default_factory=Settings)
    sources: list[Source] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # ----------------------------------------------------------- carpetas
    @property
    def originals_dir(self) -> Path:
        return self.folder / "originales"

    @property
    def processed_dir(self) -> Path:
        return self.folder / "procesadas"

    @property
    def pages_dir(self) -> Path:
        return self.folder / "paginas"

    @property
    def thumbs_dir(self) -> Path:
        return self.folder / "miniaturas"

    def _ensure_dirs(self) -> None:
        for d in (self.originals_dir, self.processed_dir, self.pages_dir, self.thumbs_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------- crear / abrir / guardar
    @classmethod
    def create(cls, parent: Path, name: str) -> "Project":
        base = safe_folder_name(name)
        folder = parent / base
        n = 2
        while folder.exists():
            folder = parent / f"{base} ({n})"
            n += 1
        folder.mkdir(parents=True)
        proj = cls(folder=folder, name=name.strip() or base, created=datetime.now().isoformat(timespec="seconds"))
        proj._ensure_dirs()
        proj.save()
        return proj

    @classmethod
    def open(cls, folder: Path) -> "Project":
        data = json.loads((folder / PROJECT_FILE).read_text(encoding="utf-8"))
        proj = cls(
            folder=folder,
            name=data.get("nombre", folder.name),
            created=data.get("creado", ""),
            settings=Settings(**data.get("ajustes", {})),
            sources=[Source(**s) for s in data.get("fotos", [])],
            pages=[Page(**p) for p in data.get("paginas", [])],
        )
        proj._ensure_dirs()
        return proj

    def save(self) -> None:
        with self._lock:
            data = {
                "version": 1,
                "nombre": self.name,
                "creado": self.created,
                "ajustes": asdict(self.settings),
                "fotos": [asdict(s) for s in self.sources],
                "paginas": [asdict(p) for p in self.pages],
            }
            _atomic_write(self.folder / PROJECT_FILE, json.dumps(data, ensure_ascii=False, indent=1))

    # ----------------------------------------------------------- búsquedas
    def source(self, source_id: str) -> Source:
        return next(s for s in self.sources if s.id == source_id)

    def page(self, page_id: str) -> Page:
        return next(p for p in self.pages if p.id == page_id)

    def pages_of(self, source_id: str) -> list[Page]:
        return [p for p in self.pages if p.source_id == source_id]

    def original_path(self, source: Source) -> Path:
        return self.originals_dir / source.file

    def processed_path(self, page: Page) -> Path:
        return self.processed_dir / f"{page.id}.png"

    def thumb_path(self, page: Page) -> Path:
        return self.thumbs_dir / f"{page.id}.jpg"

    def data_path(self, page: Page) -> Path:
        return self.pages_dir / f"{page.id}.json"

    def page_number(self, page: Page) -> int:
        return self.pages.index(page) + 1

    # ----------------------------------------------------------- importar
    def import_files(self, files: list[Path]) -> list[Source]:
        """Copia las fotos (o las páginas de un PDF) a originales/. No modifica los archivos del usuario."""
        self._ensure_dirs()
        new: list[Source] = []
        for f in files:
            ext = f.suffix.lower()
            if ext in IMAGE_EXTS:
                sid = _new_id()
                dest = self.originals_dir / f"{sid}{ext}"
                shutil.copy2(f, dest)
                new.append(Source(id=sid, file=dest.name, original_name=f.name))
            elif ext in PDF_EXTS:
                new.extend(self._import_pdf(f))
        return new

    def _import_pdf(self, pdf: Path) -> list[Source]:
        import pypdfium2 as pdfium

        out: list[Source] = []
        doc = pdfium.PdfDocument(str(pdf))
        try:
            for i in range(len(doc)):
                page = doc[i]
                image = page.render(scale=300 / 72, grayscale=True).to_pil()
                sid = _new_id()
                dest = self.originals_dir / f"{sid}.png"
                image.save(dest)
                out.append(Source(id=sid, file=dest.name, original_name=f"{pdf.name} (pág. {i + 1})"))
                page.close()
        finally:
            doc.close()
        return out

    def append(self, source: Source, pages: list[Page]) -> None:
        """Agrega al final del libro una foto ya analizada y sus páginas."""
        self.sources.append(source)
        self.pages.extend(pages)

    def make_pages(self, source: Source) -> list[Page]:
        if source.two_pages:
            return [Page(id=_new_id(), source_id=source.id, part="left"),
                    Page(id=_new_id(), source_id=source.id, part="right")]
        return [Page(id=_new_id(), source_id=source.id)]

    # ----------------------------------------------------------- editar
    def _discard_page_files(self, page: Page) -> None:
        for p in (self.processed_path(page), self.thumb_path(page), self.data_path(page)):
            p.unlink(missing_ok=True)

    def set_two_pages(self, source: Source, two: bool) -> list[Page]:
        """Parte una foto en dos páginas o la vuelve a unir. Devuelve las páginas nuevas."""
        old = self.pages_of(source.id)
        index = self.pages.index(old[0]) if old else len(self.pages)
        for p in old:
            self._discard_page_files(p)
            self.pages.remove(p)
        source.two_pages = two
        new = self.make_pages(source)
        self.pages[index:index] = new
        return new

    def rotate_source(self, source: Source, degrees: int) -> None:
        source.rotation = (source.rotation + degrees) % 360
        for p in self.pages_of(source.id):
            self.reset_page(p)

    def reset_page(self, page: Page) -> None:
        self._discard_page_files(page)
        page.status, page.edited, page.error = PENDING, False, ""

    def delete_pages(self, pages: list[Page]) -> None:
        for p in pages:
            self._discard_page_files(p)
            self.pages.remove(p)
        used = {p.source_id for p in self.pages}
        for s in [s for s in self.sources if s.id not in used]:
            self.original_path(s).unlink(missing_ok=True)
            self.sources.remove(s)

    def reorder(self, page_ids: list[str]) -> None:
        by_id = {p.id: p for p in self.pages}
        self.pages = [by_id[i] for i in page_ids if i in by_id]

    # ----------------------------------------------------------- texto
    def load_page_data(self, page: Page) -> tuple[OcrResult | None, str]:
        path = self.data_path(page)
        if not path.exists():
            return None, ""
        data = json.loads(path.read_text(encoding="utf-8"))
        ocr = OcrResult.from_dict(data["ocr"]) if data.get("ocr") else None
        return ocr, data.get("texto", ocr.text if ocr else "")

    def save_ocr(self, page: Page, ocr: OcrResult) -> None:
        payload = {"ocr": ocr.to_dict(), "texto": ocr.text}
        _atomic_write(self.data_path(page), json.dumps(payload, ensure_ascii=False))

    def save_text(self, page: Page, text: str) -> None:
        ocr, current = self.load_page_data(page)
        if text == current:
            return
        payload = {"ocr": ocr.to_dict() if ocr else None, "texto": text}
        _atomic_write(self.data_path(page), json.dumps(payload, ensure_ascii=False))
        page.edited = ocr is None or text != ocr.text

    def page_text(self, page: Page) -> str:
        return self.load_page_data(page)[1]

    def counts(self) -> dict[str, int]:
        c = {PENDING: 0, DONE: 0, REVIEWED: 0, ERROR: 0}
        for p in self.pages:
            c[p.status] = c.get(p.status, 0) + 1
        return c
