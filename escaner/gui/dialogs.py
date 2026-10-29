"""Ventanas pequeñas: nuevo libro, ajustes, exportar y ayuda."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..project import Settings

PAGE_MODES = [
    ("auto", "Detectar automáticamente"),
    ("una", "Una página por foto"),
    ("dos", "Dos páginas por foto (libro abierto)"),
]


class PageModeBox(QGroupBox):
    def __init__(self, current: str, parent=None):
        super().__init__("¿Cuántas páginas trae cada foto?", parent)
        layout = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        for key, label in PAGE_MODES:
            b = QRadioButton(label)
            self.group.addButton(b)
            self.buttons[key] = b
            layout.addWidget(b)
            b.setChecked(key == current)

    def value(self) -> str:
        return next(k for k, b in self.buttons.items() if b.isChecked())


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuevo libro")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Por ejemplo: Libro de historia")
        form.addRow("Nombre del libro:", self.name)
        layout.addLayout(form)
        self.mode = PageModeBox("auto")
        layout.addWidget(self.mode)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Crear")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if self.name.text().strip():
            self.accept()
        else:
            self.name.setFocus()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes del libro")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        self.mode = PageModeBox(settings.page_mode)
        layout.addWidget(self.mode)
        note = QLabel("Esto aplica a las fotos que agregue de ahora en adelante. "
                      "Para cambiar una foto ya agregada use el botón «Una / dos páginas».")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.clean = QCheckBox("Limpiar la imagen (quitar fondo gris, sombras y manchas)")
        self.clean.setChecked(settings.clean)
        self.rotate = QCheckBox("Enderezar automáticamente las fotos que estén de lado o al revés")
        self.rotate.setChecked(settings.auto_rotate)
        layout.addWidget(self.clean)
        layout.addWidget(self.rotate)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_to(self, settings: Settings) -> None:
        settings.page_mode = self.mode.value()
        settings.clean = self.clean.isChecked()
        settings.auto_rotate = self.rotate.isChecked()


class ExportOptionsDialog(QDialog):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opciones de exportación")
        layout = QVBoxLayout(self)
        self.flow = QCheckBox("Unir las líneas en párrafos corridos (recomendado)")
        self.flow.setChecked(True)
        layout.addWidget(self.flow)
        self.breaks = QCheckBox("Empezar cada página del libro en una página nueva" if kind == "docx"
                                else "Marcar dónde empieza cada página («--- Página 5 ---»)")
        self.breaks.setChecked(kind == "docx")
        layout.addWidget(self.breaks)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continuar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.kind = kind

    def options(self) -> dict:
        if self.kind == "docx":
            return {"flow": self.flow.isChecked(), "page_breaks": self.breaks.isChecked()}
        return {"flow": self.flow.isChecked(), "page_marks": self.breaks.isChecked()}


HELP_HTML = """
<h2>Cómo usar el Escáner de Libros</h2>
<ol>
<li><b>Nuevo libro</b>: póngale un nombre y diga si cada foto trae una o dos páginas.</li>
<li><b>Agregar fotos</b>: elija las fotos (o arrástrelas a la ventana). Se agregan en orden
    alfabético; si las tomó con el celular en orden, quedarán bien. Puede reordenar arrastrando
    las miniaturas de la izquierda.</li>
<li><b>Procesar</b>: la app limpia cada foto y lee el texto. Todo ocurre en este computador,
    sin internet.</li>
<li><b>Revisar</b>: a la izquierda ve la página y a la derecha el texto. Corrija lo que haga falta
    (se guarda solo) y pulse <b>Revisada ✓</b> para pasar a la siguiente.</li>
<li><b>Exportar</b>: PDF buscable (se ve como el libro y se puede buscar texto), Word o texto plano.</li>
</ol>
<h3>Consejos para las fotos</h3>
<ul>
<li>Hoja plana, luz de día pareja, sin flash ni sombras.</li>
<li>Celular derecho, justo encima de la hoja, que la hoja ocupe casi toda la foto.</li>
<li>Si una página sale mal, tómele otra foto, agréguela y borre la mala.</li>
</ul>
<h3>Atajos de teclado</h3>
<ul>
<li><b>Re Pág / Av Pág</b>: página anterior / siguiente.</li>
<li><b>Ctrl + Enter</b>: marcar como revisada y pasar a la siguiente.</li>
<li><b>Ctrl + F</b>: buscar una palabra en todo el libro.</li>
<li><b>Rueda del ratón</b> sobre la imagen: acercar o alejar.</li>
</ul>
<p>Sus libros se guardan en la carpeta <b>Proyectos</b>, junto al programa. Para llevarlos a otro
computador basta con copiar toda la carpeta del programa.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ayuda")
        self.resize(620, 620)
        layout = QVBoxLayout(self)
        view = QTextBrowser()
        view.setHtml(HELP_HTML)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
