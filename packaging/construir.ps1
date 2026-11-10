# Construye la carpeta portátil del Escáner de Libros en Windows.
#
# Requisitos: Python 3.12 con las dependencias de requirements-dev.txt instaladas, y
# Tesseract OCR instalado (por ejemplo con:  choco install tesseract).
#
# Uso:  powershell -ExecutionPolicy Bypass -File packaging\construir.ps1
param(
    [string]$TesseractDir = "C:\Program Files\Tesseract-OCR"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path "$TesseractDir\tesseract.exe")) {
    throw "No se encontró Tesseract en $TesseractDir"
}

# 1. Idiomas: español (texto) y osd (detectar páginas giradas)
$tessdata = Join-Path $TesseractDir "tessdata"
foreach ($lang in @("spa", "osd")) {
    $file = Join-Path $tessdata "$lang.traineddata"
    if (-not (Test-Path $file)) {
        Write-Host "Descargando $lang.traineddata..."
        Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata/raw/main/$lang.traineddata" -OutFile $file
    }
}

# 2. Programa
pyinstaller packaging\EscanerLibros.spec --noconfirm --clean --distpath dist --workpath build
$out = Join-Path $Root "dist\EscanerLibros"

# 3. Tesseract portátil, solo con los idiomas necesarios
$dest = Join-Path $out "tesseract"
Copy-Item $TesseractDir $dest -Recurse -Force
Get-ChildItem (Join-Path $dest "tessdata") -Filter *.traineddata |
    Where-Object { $_.BaseName -notin @("spa", "osd", "eng") } | Remove-Item -Force
foreach ($junk in @("unins000.exe", "unins000.dat", "doc")) {
    $p = Join-Path $dest $junk
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

# 4. Instrucciones
Copy-Item (Join-Path $Root "INSTRUCCIONES.txt") $out -Force
Copy-Item (Join-Path $Root "INSTRUCCIONES_COWORK.md") $out -Force

# 5. Zip listo para copiar a otro computador
$zip = Join-Path $Root "dist\EscanerLibros-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $out -DestinationPath $zip
Write-Host "Listo: $zip"
