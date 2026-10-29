"""Punto de entrada del Escáner de Libros.

    EscanerLibros.exe                       abre la aplicación
    EscanerLibros.exe --autotest INFORME    prueba sin ventana (la usa la compilación automática)
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path


def autotest(report: Path) -> int:
    """Procesa una página de muestra de principio a fin y escribe el resultado en un archivo."""
    lines: list[str] = []
    ok = False
    try:
        from escaner import exporting, paths, processing
        from escaner.ocr import OcrEngine
        from escaner.project import DONE, Project

        sample = paths.resource("muestra.jpg")
        engine = OcrEngine()
        lines.append(f"tesseract: {engine.tesseract}")
        lines.append(f"idiomas: {engine.languages()}")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proj = Project.create(tmp_path, "Prueba ñandú")
            for source in proj.import_files([sample]):
                processing.analyze_source(proj, source, engine)
                proj.append(source, proj.make_pages(source))
            for page in proj.pages:
                processing.process_page(proj, page, engine)
            proj.save()
            text = "\n".join(proj.page_text(p) for p in proj.pages)
            lines.append(f"paginas: {len(proj.pages)} estados: {[p.status for p in proj.pages]}")
            lines.append("texto:\n" + text)
            exporting.export_pdf(proj, tmp_path / "libro.pdf")
            exporting.export_docx(proj, tmp_path / "libro.docx")
            exporting.export_txt(proj, tmp_path / "libro.txt")
            sizes = {f: (tmp_path / f).stat().st_size for f in ("libro.pdf", "libro.docx", "libro.txt")}
            lines.append(f"exportados: {sizes}")
            ok = (all(p.status == DONE for p in proj.pages)
                  and "biblioteca" in text.lower()
                  and "español" in text.lower()
                  and all(v > 0 for v in sizes.values()))
    except Exception:
        lines.append(traceback.format_exc())
    lines.append("RESULTADO: " + ("OK" if ok else "FALLO"))
    report.write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--autotest":
        return autotest(Path(sys.argv[2]))

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from escaner import APP_NAME, paths
    from escaner.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(paths.resource("icono.ico"))))
    win = MainWindow()
    win.show()
    if "--smoke" in sys.argv:  # abrir y cerrar: comprueba que la ventana arranca
        QTimer.singleShot(1500, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
