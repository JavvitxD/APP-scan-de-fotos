# Escáner de Libros

Aplicación de escritorio para Windows que convierte fotos de las páginas de un libro (o de sus
fotocopias) en una copia digital: texto corregible, **PDF buscable**, Word y texto plano.

Todo funciona **sin internet**: la limpieza de imagen se hace con OpenCV y el reconocimiento de
texto con [Tesseract OCR](https://github.com/tesseract-ocr/tesseract), que viene incluido en la
carpeta del programa.

## Descargar el programa para Windows

1. Entre a la pestaña **Actions** del repositorio en GitHub, abra la última ejecución verde de
   «Construir para Windows» y descargue **EscanerLibros-Windows** (abajo, en *Artifacts*).
2. Descomprima el zip en una carpeta llamada `C:\EscanerLibros` y abra `EscanerLibros.exe`.
3. Las instrucciones completas para el usuario están en [INSTRUCCIONES.txt](INSTRUCCIONES.txt).

Si se publica una etiqueta `v1.0.0`, el zip aparece también en la sección **Releases**, sin fecha
de caducidad.

## Qué hace

- Importa fotos (JPG, PNG, TIFF…) o PDF escaneados, en orden natural (`IMG_2` antes de `IMG_10`).
- Detecta si la foto está girada y si trae una o dos páginas, y las separa.
- Recorta la hoja, corrige la perspectiva, endereza el texto, quita el fondo gris, las sombras,
  los bordes negros y los puntos de tóner de la fotocopia.
- Transcribe en español y procesa varias páginas a la vez.
- Pantalla de revisión: imagen y texto lado a lado, estado por página, búsqueda en todo el libro.
- Exporta a PDF con capa de texto invisible (se puede buscar y copiar), Word y TXT, uniendo las
  líneas en párrafos y las palabras cortadas con guion.

## Estructura

```
main.py                  punto de entrada (también --autotest y --smoke para la compilación)
escaner/imaging.py       limpieza de imagen
escaner/ocr.py           Tesseract (la imagen va por stdin: no hay problemas con tildes en rutas)
escaner/project.py       proyecto en disco: originales/, procesadas/, paginas/, proyecto.json
escaner/processing.py    análisis al importar y proceso de cada página
escaner/exporting.py     PDF buscable, Word, TXT
escaner/gui/             ventana (PySide6)
packaging/               PyInstaller, script de construcción, ícono, página de muestra
tests/                   pruebas con páginas sintéticas «fotocopiadas y fotografiadas»
```

## Desarrollo

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q tests
.venv/bin/python main.py
```

Necesita Tesseract con el idioma `spa` instalado (en Ubuntu: `apt install tesseract-ocr-spa`).

Para construir la carpeta portátil en Windows (con Tesseract instalado, por ejemplo con
`choco install tesseract`):

```powershell
pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File packaging\construir.ps1
```

El resultado queda en `dist\EscanerLibros\` y `dist\EscanerLibros-Windows.zip`. GitHub Actions
hace lo mismo en cada push, prueba el `.exe` con una página de muestra y publica la carpeta.
