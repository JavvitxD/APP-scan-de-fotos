"""Ubicaciones de archivos: carpeta de la app, Tesseract incluido y proyectos."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Carpeta donde vive el programa (junto al .exe cuando está empaquetado)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _exe(name: str) -> str:
    return name + ".exe" if os.name == "nt" else name


def find_tesseract() -> Path | None:
    """Busca el ejecutable de Tesseract, dando prioridad al que viene con la app."""
    candidates: list[Path] = []
    env = os.environ.get("ESCANER_TESSERACT")
    if env:
        candidates.append(Path(env))
    candidates.append(app_dir() / "tesseract" / _exe("tesseract"))
    candidates.append(app_dir() / "vendor" / "tesseract" / _exe("tesseract"))
    which = shutil.which("tesseract")
    if which:
        candidates.append(Path(which))
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                candidates.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
    for c in candidates:
        if c.is_file():
            return c
    return None


def tessdata_for(tesseract: Path) -> Path | None:
    """Carpeta tessdata que acompaña a un Tesseract incluido (None = usar la del sistema)."""
    local = tesseract.parent / "tessdata"
    return local if local.is_dir() else None


def _is_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".prueba_escritura"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def default_projects_dir() -> Path:
    """Por defecto los proyectos se guardan dentro de la carpeta de la app, para que viajen con ella."""
    portable = app_dir() / "Proyectos"
    if _is_writable(portable):
        return portable
    docs = Path.home() / "Documents"
    if not docs.is_dir():
        docs = Path.home()
    fallback = docs / "Escaner de Libros"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def resource(name: str) -> Path:
    """Archivo incluido con la app (ícono, muestra): dentro del paquete o en packaging/."""
    bundle = Path(getattr(sys, "_MEIPASS", app_dir()))
    for c in (bundle / name, app_dir() / "packaging" / name):
        if c.exists():
            return c
    return bundle / name
