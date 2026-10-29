# Configuración de PyInstaller: crea la carpeta portátil dist/EscanerLibros/
# Uso (en Windows):  pyinstaller packaging/EscanerLibros.spec --noconfirm
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ROOT, "packaging", "icono.ico"), "."),
        (os.path.join(ROOT, "packaging", "muestra.jpg"), "."),
    ],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EscanerLibros",
    icon=os.path.join(ROOT, "packaging", "icono.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="EscanerLibros", upx=False)
