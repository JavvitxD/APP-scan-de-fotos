"""Tareas largas en segundo plano para que la ventana no se congele."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .. import exporting, processing
from ..ocr import OcrEngine
from ..project import Page, Project, Source


def worker_count() -> int:
    return max(1, min(6, (os.cpu_count() or 2) - 1))


class Job(QThread):
    progress = Signal(int, int)  # hechos, total
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    @property
    def cancelled(self) -> bool:
        return self._cancel


class ImportJob(Job):
    """Copia las fotos al proyecto, detecta giro y páginas dobles y crea miniaturas."""

    imported = Signal(list)  # [(Source, [Page])]

    def __init__(self, project: Project, files: list[Path], engine: OcrEngine | None, parent=None):
        super().__init__(parent)
        self.project, self.files, self.engine = project, files, engine

    def run(self) -> None:
        try:
            sources = self.project.import_files(self.files)
        except Exception as exc:
            self.failed.emit(f"No se pudieron copiar las fotos: {exc}")
            return
        results: list[tuple[Source, list[Page]]] = []
        total = len(sources)

        def work(source: Source) -> tuple[Source, list[Page]]:
            processing.analyze_source(self.project, source, self.engine)
            pages = self.project.make_pages(source)
            for page in pages:
                processing.save_thumbnail(self.project, page, processing.preview(self.project, page, 600))
            return source, pages

        done = 0
        with ThreadPoolExecutor(worker_count()) as pool:
            futures = {pool.submit(work, s): i for i, s in enumerate(sources)}
            ordered: dict[int, tuple[Source, list[Page]]] = {}
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    ordered[i] = fut.result()
                except Exception:
                    src = sources[i]
                    ordered[i] = (src, self.project.make_pages(src))
                done += 1
                self.progress.emit(done, total)
        results = [ordered[i] for i in sorted(ordered)]
        self.imported.emit(results)


class ProcessJob(Job):
    """Limpia y transcribe páginas, varias a la vez."""

    page_done = Signal(str)

    def __init__(self, project: Project, pages: list[Page], engine: OcrEngine, parent=None):
        super().__init__(parent)
        self.project, self.pages, self.engine = project, pages, engine

    def run(self) -> None:
        total = len(self.pages)
        done = 0
        pool = ThreadPoolExecutor(worker_count())
        try:
            futures = {pool.submit(self._one, p): p for p in self.pages}
            for fut in as_completed(futures):
                page = futures[fut]
                if fut.cancelled():
                    continue
                done += 1
                self.page_done.emit(page.id)
                self.progress.emit(done, total)
                if self._cancel:
                    for f in futures:
                        f.cancel()
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def _one(self, page: Page) -> None:
        if not self._cancel:
            processing.process_page(self.project, page, self.engine)


class ExportJob(Job):
    exported = Signal(str, list)  # ruta, páginas omitidas

    def __init__(self, project: Project, kind: str, dest: Path, options: dict, parent=None):
        super().__init__(parent)
        self.project, self.kind, self.dest, self.options = project, kind, dest, options

    def run(self) -> None:
        try:
            skipped: list[int] = []
            if self.kind == "pdf":
                skipped = exporting.export_pdf(self.project, self.dest, progress=self.progress.emit)
            elif self.kind == "docx":
                exporting.export_docx(self.project, self.dest, progress=self.progress.emit, **self.options)
            else:
                exporting.export_txt(self.project, self.dest, progress=self.progress.emit, **self.options)
            self.exported.emit(str(self.dest), skipped)
        except PermissionError:
            self.failed.emit("No se pudo guardar el archivo. ¿Está abierto en otro programa (Word, lector de PDF)?")
        except Exception as exc:
            self.failed.emit(f"Error al exportar: {exc}")
