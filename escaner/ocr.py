"""Reconocimiento de texto con Tesseract, ejecutado localmente (sin internet)."""

from __future__ import annotations

import csv
import io
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import paths


class OcrError(RuntimeError):
    pass


@dataclass
class OcrLine:
    text: str
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1 en píxeles de la imagen
    paragraph: int = 0


@dataclass
class OcrResult:
    text: str
    lines: list[OcrLine] = field(default_factory=list)
    width: int = 0
    height: int = 0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
            "lines": [{"text": l.text, "bbox": list(l.bbox), "paragraph": l.paragraph} for l in self.lines],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OcrResult":
        return cls(
            text=d.get("text", ""),
            width=d.get("width", 0),
            height=d.get("height", 0),
            confidence=d.get("confidence", 0.0),
            lines=[OcrLine(l["text"], tuple(l["bbox"]), l.get("paragraph", 0)) for l in d.get("lines", [])],
        )


def _png_bytes(gray: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(gray).save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


class OcrEngine:
    def __init__(self, tesseract: Path | None = None, lang: str = "spa"):
        self.tesseract = tesseract or paths.find_tesseract()
        if self.tesseract is None:
            raise OcrError(
                "No se encontró el programa de reconocimiento de texto (Tesseract). "
                "Revise que la carpeta 'tesseract' esté junto a EscanerLibros.exe."
            )
        self.tessdata = paths.tessdata_for(self.tesseract)
        self.lang = lang

    def _run(self, args: list[str], image: bytes, timeout: int = 300) -> str:
        env = os.environ.copy()
        env["OMP_THREAD_LIMIT"] = "1"  # procesamos varias páginas en paralelo
        if self.tessdata:
            env["TESSDATA_PREFIX"] = str(self.tessdata)
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        # La imagen va por la entrada estándar: así no importan las tildes en las rutas
        proc = subprocess.run(
            [str(self.tesseract), "stdin", "stdout", *args],
            input=image,
            capture_output=True,
            env=env,
            timeout=timeout,
            **kwargs,
        )
        if proc.returncode != 0:
            raise OcrError(proc.stderr.decode("utf-8", "replace").strip() or "Tesseract falló")
        return proc.stdout.decode("utf-8", "replace")

    def languages(self) -> list[str]:
        env = os.environ.copy()
        if self.tessdata:
            env["TESSDATA_PREFIX"] = str(self.tessdata)
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        proc = subprocess.run([str(self.tesseract), "--list-langs"], capture_output=True, env=env, **kwargs)
        out = proc.stdout.decode("utf-8", "replace").splitlines()
        return [l.strip() for l in out[1:] if l.strip()]

    def detect_rotation(self, gray: np.ndarray) -> int:
        """Grados (horario) que hay que girar la imagen para que el texto quede derecho."""
        try:
            out = self._run(["--psm", "0", "-l", "osd"], _png_bytes(gray), timeout=60)
        except (OcrError, subprocess.TimeoutExpired):
            return 0
        rot = re.search(r"Rotate:\s*(\d+)", out)
        conf = re.search(r"Orientation confidence:\s*([\d.]+)", out)
        if not rot or not conf or float(conf.group(1)) < 2.0:
            return 0
        return int(rot.group(1)) % 360

    def recognize(self, gray: np.ndarray) -> OcrResult:
        tsv = self._run(["-l", self.lang, "--psm", "3", "tsv"], _png_bytes(gray))
        return parse_tsv(tsv, gray.shape[1], gray.shape[0])


_SENTENCE_END = re.compile(r"[.!?:;…»\"”')\]]$")


def ends_sentence(line: str) -> bool:
    return bool(_SENTENCE_END.search(line.strip())) or not line.strip()


def parse_tsv(tsv: str, width: int, height: int) -> OcrResult:
    """Convierte la salida TSV de Tesseract en líneas y párrafos."""
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    lines: dict[tuple[int, int, int], dict] = {}
    confs: list[float] = []
    for row in reader:
        try:
            level = int(row["level"])
        except (KeyError, TypeError, ValueError):
            continue
        if level != 5:
            continue
        word = (row.get("text") or "").strip()
        if not word:
            continue
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        conf = float(row.get("conf") or -1)
        if conf >= 0:
            confs.append(conf)
        entry = lines.setdefault(key, {"words": [], "box": [x, y, x + w, y + h]})
        entry["words"].append(word)
        b = entry["box"]
        b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)

    out_lines: list[OcrLine] = []
    paragraph_ids: dict[tuple[int, int], int] = {}
    text_parts: list[str] = []
    prev_par = None
    for key in sorted(lines):
        par_key = key[:2]
        pid = paragraph_ids.setdefault(par_key, len(paragraph_ids))
        line_text = " ".join(lines[key]["words"])
        out_lines.append(OcrLine(line_text, tuple(lines[key]["box"]), pid))
        # Línea en blanco entre párrafos, salvo que Tesseract haya cortado una frase a la mitad
        if prev_par is not None and par_key != prev_par and ends_sentence(text_parts[-1]):
            text_parts.append("")
        text_parts.append(line_text)
        prev_par = par_key

    return OcrResult(
        text="\n".join(text_parts),
        lines=out_lines,
        width=width,
        height=height,
        confidence=round(sum(confs) / len(confs), 1) if confs else 0.0,
    )
