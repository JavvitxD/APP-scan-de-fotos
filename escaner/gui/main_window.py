"""Ventana principal del Escáner de Libros."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPixmap, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__, imaging, paths, processing
from ..ocr import OcrEngine, OcrError
from ..project import DONE, ERROR, IMAGE_EXTS, PDF_EXTS, PENDING, PROJECT_FILE, REVIEWED, Page, Project
from .dialogs import ExportOptionsDialog, HelpDialog, NewProjectDialog, SettingsDialog
from .viewer import ImageViewer
from .workers import ExportJob, ImportJob, Job, ProcessJob

STATUS_LABEL = {PENDING: "Pendiente", DONE: "Transcrita", REVIEWED: "Revisada ✓", ERROR: "Error"}
STATUS_COLOR = {PENDING: "#7a7a7a", DONE: "#1f5fbf", REVIEWED: "#1e8a3a", ERROR: "#c0392b"}
ID_ROLE = Qt.ItemDataRole.UserRole


def natural_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def open_in_explorer(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class PageList(QListWidget):
    """Lista de miniaturas que se puede reordenar arrastrando."""

    reordered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(72, 96))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSpacing(2)
        self.setMinimumWidth(190)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 860)
        self.setAcceptDrops(True)

        self.project: Project | None = None
        self.current: Page | None = None
        self.job: Job | None = None
        self.engine: OcrEngine | None = None
        self.engine_error = ""
        try:
            self.engine = OcrEngine()
            if "spa" not in self.engine.languages():
                self.engine_error = "Falta el idioma español (spa.traineddata) en la carpeta tesseract\\tessdata."
                self.engine = None
        except OcrError as exc:
            self.engine_error = str(exc)

        self._loading_text = False
        self.save_timer = QTimer(self, singleShot=True, interval=700, timeout=self._save_text)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._build_actions()
        self.welcome = self._build_welcome()
        self.workspace = self._build_workspace()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.workspace)
        self._build_menu()
        self._build_statusbar()
        self._show_welcome()

        if self.engine is None:
            QTimer.singleShot(300, lambda: QMessageBox.warning(
                self, APP_NAME,
                "No se podrá leer el texto de las páginas:\n\n" + self.engine_error +
                "\n\nPuede seguir agregando fotos, pero para transcribir necesita la carpeta "
                "«tesseract» completa junto al programa."))

    # ================================================================ construcción
    def _icon(self, name: str) -> QIcon:
        return self.style().standardIcon(getattr(QStyle.StandardPixmap, name))

    def _action(self, text: str, slot, icon: str | None = None, shortcut=None, tip: str = "") -> QAction:
        act = QAction(text, self)
        if icon:
            act.setIcon(self._icon(icon))
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.setToolTip(tip or text)
        act.triggered.connect(slot)
        return act

    def _build_actions(self) -> None:
        a = self._action
        self.act_new = a("Nuevo libro…", self.new_project, "SP_FileIcon", QKeySequence.StandardKey.New)
        self.act_open = a("Abrir libro…", self.open_project_dialog, "SP_DirOpenIcon", QKeySequence.StandardKey.Open)
        self.act_close = a("Cerrar libro", self.close_project, None)
        self.act_folder = a("Abrir carpeta del libro", self.open_project_folder, "SP_DirIcon")
        self.act_add = a("Agregar fotos", self.add_photos_dialog, "SP_FileDialogNewFolder", "Ctrl+I",
                         "Agregar fotos o PDF de páginas al final del libro")
        self.act_process = a("Procesar pendientes", self.process_pending, "SP_MediaPlay", "F5",
                             "Limpiar y leer el texto de todas las páginas pendientes")
        self.act_reprocess = a("Volver a procesar", self.reprocess_selected, "SP_BrowserReload", None,
                               "Volver a leer las páginas seleccionadas")
        self.act_rot_left = a("Girar ⟲", lambda: self.rotate_selected(270), "SP_ArrowBack", None,
                              "Girar la foto 90° a la izquierda")
        self.act_rot_right = a("Girar ⟳", lambda: self.rotate_selected(90), "SP_ArrowForward", None,
                               "Girar la foto 90° a la derecha")
        self.act_split = a("Una / dos páginas", self.toggle_split, "SP_TitleBarNormalButton", None,
                           "Partir la foto en dos páginas, o unirla en una sola")
        self.act_delete = a("Eliminar", self.delete_selected, "SP_TrashIcon", QKeySequence.StandardKey.Delete,
                            "Quitar las páginas seleccionadas del libro")
        self.act_original = a("Ver foto original", self._show_current_image, "SP_FileDialogContentsView")
        self.act_original.setCheckable(True)
        self.act_settings = a("Ajustes", self.edit_settings, "SP_FileDialogDetailedView")
        self.act_help = a("Ayuda", lambda: HelpDialog(self).exec(), "SP_DialogHelpButton", "F1")
        self.act_export_pdf = a("PDF buscable…", lambda: self.export("pdf"))
        self.act_export_docx = a("Documento de Word…", lambda: self.export("docx"))
        self.act_export_txt = a("Texto plano (.txt)…", lambda: self.export("txt"))
        self.act_quit = a("Salir", self.close, None, QKeySequence.StandardKey.Quit)
        self.structural = [self.act_add, self.act_process, self.act_reprocess, self.act_rot_left,
                           self.act_rot_right, self.act_split, self.act_delete, self.act_settings,
                           self.act_export_pdf, self.act_export_docx, self.act_export_txt,
                           self.act_close, self.act_new, self.act_open]

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&Archivo")
        for act in (self.act_new, self.act_open, self.act_folder, self.act_close):
            m.addAction(act)
        m.addSeparator()
        exp = m.addMenu("Exportar")
        for act in (self.act_export_pdf, self.act_export_docx, self.act_export_txt):
            exp.addAction(act)
        m.addSeparator()
        m.addAction(self.act_quit)
        m = self.menuBar().addMenu("&Páginas")
        for act in (self.act_add, self.act_process, self.act_reprocess, self.act_rot_left, self.act_rot_right,
                    self.act_split, self.act_delete, self.act_original):
            m.addAction(act)
        m = self.menuBar().addMenu("A&yuda")
        m.addAction(self.act_help)
        m.addAction(self._action("Acerca de…", self.about))

    def _build_welcome(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(60, 40, 60, 40)
        title = QLabel(APP_NAME)
        f = QFont()
        f.setPointSize(26)
        f.setBold(True)
        title.setFont(f)
        outer.addWidget(title)
        sub = QLabel("Convierta las fotos de un libro en una copia digital. Todo se hace en este computador, "
                     "sin internet.")
        sub.setWordWrap(True)
        outer.addWidget(sub)
        outer.addSpacing(20)
        row = QHBoxLayout()
        for act in (self.act_new, self.act_open, self.act_help):
            b = QPushButton(act.icon(), act.text().replace("…", ""))
            b.setMinimumHeight(44)
            b.setIconSize(QSize(22, 22))
            b.clicked.connect(act.trigger)
            row.addWidget(b)
        row.addStretch()
        outer.addLayout(row)
        outer.addSpacing(20)
        outer.addWidget(QLabel("<b>Libros guardados</b> (doble clic para abrir):"))
        self.recent = QListWidget()
        self.recent.itemActivated.connect(lambda it: self.open_project(Path(it.data(ID_ROLE))))
        outer.addWidget(self.recent, 1)
        self.projects_label = QLabel()
        self.projects_label.setStyleSheet("color: gray")
        outer.addWidget(self.projects_label)
        return w

    def _build_workspace(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        tb = QToolBar()
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(22, 22))
        for act in (self.act_add, self.act_process, self.act_reprocess):
            tb.addAction(act)
        tb.addSeparator()
        for act in (self.act_rot_left, self.act_rot_right, self.act_split, self.act_delete, self.act_original):
            tb.addAction(act)
        tb.addSeparator()
        export_btn = QToolButton()
        export_btn.setText("Exportar")
        export_btn.setIcon(self._icon("SP_DialogSaveButton"))
        export_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        export_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(export_btn)
        for act in (self.act_export_pdf, self.act_export_docx, self.act_export_txt):
            menu.addAction(act)
        export_btn.setMenu(menu)
        tb.addWidget(export_btn)
        tb.addAction(self.act_settings)
        tb.addAction(self.act_help)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en el libro (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.search.returnPressed.connect(self.find_next)
        tb.addWidget(self.search)
        layout.addWidget(tb)

        split = QSplitter()
        self.page_list = PageList()
        self.page_list.currentItemChanged.connect(self._on_current_item)
        self.page_list.reordered.connect(self._on_reordered)
        split.addWidget(self.page_list)

        self.viewer = ImageViewer()
        split.addWidget(self.viewer)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)
        self.page_title = QLabel()
        tf = QFont()
        tf.setPointSize(12)
        tf.setBold(True)
        self.page_title.setFont(tf)
        rl.addWidget(self.page_title)
        self.page_info = QLabel()
        self.page_info.setWordWrap(True)
        self.page_info.setStyleSheet("color: gray")
        rl.addWidget(self.page_info)
        self.editor = QPlainTextEdit()
        ef = QFont("Georgia")
        ef.setPointSize(12)
        self.editor.setFont(ef)
        self.editor.textChanged.connect(self._on_text_changed)
        rl.addWidget(self.editor, 1)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Anterior")
        self.btn_prev.clicked.connect(lambda: self.go(-1))
        self.btn_review = QPushButton("Revisada ✓")
        self.btn_review.setToolTip("Marcar esta página como revisada y pasar a la siguiente (Ctrl+Enter)")
        self.btn_review.clicked.connect(self.mark_reviewed)
        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_next.clicked.connect(lambda: self.go(1))
        for b in (self.btn_prev, self.btn_review, self.btn_next):
            b.setMinimumHeight(34)
            nav.addWidget(b)
        rl.addLayout(nav)
        split.addWidget(right)
        split.setSizes([210, 640, 550])
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 1)
        layout.addWidget(split, 1)

        QShortcut(QKeySequence("Ctrl+Return"), w, self.mark_reviewed)
        QShortcut(QKeySequence("Ctrl+Enter"), w, self.mark_reviewed)
        QShortcut(QKeySequence(Qt.Key.Key_PageDown), w, lambda: self.go(1))
        QShortcut(QKeySequence(Qt.Key.Key_PageUp), w, lambda: self.go(-1))
        QShortcut(QKeySequence.StandardKey.Find, w, lambda: (self.search.setFocus(), self.search.selectAll()))
        return w

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.counts_label = QLabel()
        sb.addWidget(self.counts_label, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(320)
        self.progress.setFormat("%v de %m")
        self.progress.hide()
        sb.addPermanentWidget(self.progress)
        self.btn_cancel = QPushButton("Detener")
        self.btn_cancel.clicked.connect(self.cancel_job)
        self.btn_cancel.hide()
        sb.addPermanentWidget(self.btn_cancel)

    # ================================================================ proyectos
    def _show_welcome(self) -> None:
        self.recent.clear()
        base = paths.default_projects_dir()
        self.projects_label.setText(f"Carpeta de libros: {base}")
        folders = [p for p in base.iterdir() if (p / PROJECT_FILE).is_file()] if base.is_dir() else []
        folders.sort(key=lambda p: (p / PROJECT_FILE).stat().st_mtime, reverse=True)
        for f in folders:
            try:
                proj = Project.open(f)
                label = f"{proj.name}   —   {len(proj.pages)} páginas"
            except Exception:
                label = f"{f.name}   (no se pudo leer)"
            it = QListWidgetItem(self._icon("SP_DirIcon"), label)
            it.setData(ID_ROLE, str(f))
            self.recent.addItem(it)
        if not folders:
            it = QListWidgetItem("Todavía no hay libros. Pulse «Nuevo libro» para empezar.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(it)
        self.stack.setCurrentWidget(self.welcome)
        self.setWindowTitle(APP_NAME)
        self.counts_label.clear()
        for act in (self.act_close, self.act_folder):
            act.setEnabled(False)

    def new_project(self) -> None:
        if not self._confirm_idle():
            return
        dlg = NewProjectDialog(self)
        if not dlg.exec():
            return
        proj = Project.create(paths.default_projects_dir(), dlg.name.text())
        proj.settings.page_mode = dlg.mode.value()
        proj.save()
        self.open_project(proj.folder)
        QTimer.singleShot(100, self.add_photos_dialog)

    def open_project_dialog(self) -> None:
        if not self._confirm_idle():
            return
        folder = QFileDialog.getExistingDirectory(self, "Elija la carpeta del libro", str(paths.default_projects_dir()))
        if folder:
            self.open_project(Path(folder))

    def open_project(self, folder: Path) -> None:
        if not (folder / PROJECT_FILE).is_file():
            QMessageBox.warning(self, APP_NAME, "Esa carpeta no es un libro del Escáner de Libros.")
            return
        try:
            self.project = Project.open(folder)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"No se pudo abrir el libro:\n{exc}")
            return
        self.current = None
        self.setWindowTitle(f"{self.project.name} — {APP_NAME}")
        self.stack.setCurrentWidget(self.workspace)
        for act in (self.act_close, self.act_folder):
            act.setEnabled(True)
        self._fill_list()
        if self.page_list.count():
            self.page_list.setCurrentRow(0)
        else:
            self._show_page(None)

    def close_project(self) -> None:
        if not self._confirm_idle():
            return
        self._save_text()
        self.project = None
        self.current = None
        self.page_list.clear()
        self._show_welcome()

    def open_project_folder(self) -> None:
        if self.project:
            open_in_explorer(self.project.folder)

    def edit_settings(self) -> None:
        if not self.project:
            return
        dlg = SettingsDialog(self.project.settings, self)
        if dlg.exec():
            dlg.apply_to(self.project.settings)
            self.project.save()

    # ================================================================ lista de páginas
    def _fill_list(self) -> None:
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for page in self.project.pages:
            it = QListWidgetItem()
            it.setData(ID_ROLE, page.id)
            self.page_list.addItem(it)
        self._refresh_items()
        self.page_list.blockSignals(False)

    def _refresh_items(self) -> None:
        for row in range(self.page_list.count()):
            self._refresh_item(self.page_list.item(row), row + 1)
        self._update_counts()

    def _refresh_item(self, it: QListWidgetItem, number: int) -> None:
        page = self.project.page(it.data(ID_ROLE))
        side = {"left": " (izq.)", "right": " (der.)"}.get(page.part, "")
        it.setText(f"Página {number}{side}\n{STATUS_LABEL[page.status]}")
        it.setForeground(QColor(STATUS_COLOR[page.status]))
        thumb = self.project.thumb_path(page)
        it.setIcon(QIcon(QPixmap(str(thumb))) if thumb.exists() else self._icon("SP_FileIcon"))

    def _item_for(self, page_id: str) -> tuple[int, QListWidgetItem] | None:
        for row in range(self.page_list.count()):
            it = self.page_list.item(row)
            if it.data(ID_ROLE) == page_id:
                return row, it
        return None

    def _update_counts(self) -> None:
        if not self.project:
            return
        c = self.project.counts()
        total = len(self.project.pages)
        text = (f"{total} páginas  ·  {c[PENDING]} pendientes  ·  {c[DONE]} transcritas  ·  "
                f"{c[REVIEWED]} revisadas")
        if c[ERROR]:
            text += f"  ·  {c[ERROR]} con error"
        self.counts_label.setText(text)

    def _on_reordered(self) -> None:
        ids = [self.page_list.item(r).data(ID_ROLE) for r in range(self.page_list.count())]
        self.project.reorder(ids)
        self.project.save()
        self._refresh_items()
        self._show_page(self.current)

    def _selected_pages(self) -> list[Page]:
        if not self.project:
            return []
        ids = {it.data(ID_ROLE) for it in self.page_list.selectedItems()}
        pages = [p for p in self.project.pages if p.id in ids]
        if not pages and self.current:
            pages = [self.current]
        return pages

    def _on_current_item(self, item: QListWidgetItem | None, _prev=None) -> None:
        self._save_text()
        self._show_page(self.project.page(item.data(ID_ROLE)) if item and self.project else None)

    def go(self, delta: int) -> None:
        row = self.page_list.currentRow() + delta
        if 0 <= row < self.page_list.count():
            self.page_list.setCurrentRow(row)

    # ================================================================ página actual
    def _show_page(self, page: Page | None) -> None:
        self.current = page
        self._loading_text = True
        if page is None:
            self.page_title.setText("Sin páginas")
            self.page_info.setText("Pulse «Agregar fotos» o arrastre las fotos del libro a esta ventana.")
            self.editor.setPlainText("")
            self.editor.setReadOnly(True)
            self.viewer.show_gray(None)
            self._loading_text = False
            return
        n = self.project.page_number(page)
        self.page_title.setText(f"Página {n} de {len(self.project.pages)}  —  {STATUS_LABEL[page.status]}")
        source = self.project.source(page.source_id)
        info = f"Foto: {source.original_name}"
        if page.status == PENDING:
            info += "\nEsta página todavía no se ha procesado. Pulse «Procesar pendientes» (F5)."
        elif page.status == ERROR:
            info += f"\nNo se pudo procesar: {page.error}"
        else:
            ocr, _ = self.project.load_page_data(page)
            if ocr and ocr.confidence:
                info += f"   ·   Confianza de lectura: {ocr.confidence:.0f}%"
            if ocr is not None and ocr.confidence and ocr.confidence < 75:
                info += "\nLectura dudosa: revise con cuidado o tome una foto mejor."
        self.page_info.setText(info)
        text = self.project.page_text(page) if page.status in (DONE, REVIEWED) else ""
        self.editor.setPlainText(text)
        self.editor.setReadOnly(page.status not in (DONE, REVIEWED))
        self._loading_text = False
        self.btn_review.setText("Quitar revisada" if page.status == REVIEWED else "Revisada ✓")
        self._show_current_image()

    def _show_current_image(self) -> None:
        page = self.current
        if page is None or not self.project:
            return
        try:
            if self.act_original.isChecked():
                src = self.project.source(page.source_id)
                gray = imaging.rotate90(imaging.downscale(imaging.load_gray(self.project.original_path(src)), 2200)[0],
                                        src.rotation)
            elif self.project.processed_path(page).exists():
                gray = imaging.load_gray(self.project.processed_path(page))
            else:
                gray = processing.preview(self.project, page)
            self.viewer.show_gray(gray)
        except Exception as exc:
            self.viewer.show_gray(None)
            self.page_info.setText(f"No se pudo mostrar la imagen: {exc}")

    def _on_text_changed(self) -> None:
        if not self._loading_text:
            self.save_timer.start()

    def _save_text(self) -> None:
        self.save_timer.stop()
        page = self.current
        if not self.project or page is None or page.status not in (DONE, REVIEWED):
            return
        try:
            self.project.save_text(page, self.editor.toPlainText())
            self.project.save()
        except OSError as exc:
            self.statusBar().showMessage(f"No se pudo guardar el texto: {exc}", 8000)

    def mark_reviewed(self) -> None:
        page = self.current
        if page is None or page.status not in (DONE, REVIEWED):
            return
        self._save_text()
        page.status = DONE if page.status == REVIEWED else REVIEWED
        self.project.save()
        found = self._item_for(page.id)
        if found:
            self._refresh_item(found[1], found[0] + 1)
        self._update_counts()
        if page.status == REVIEWED:
            self.go(1)
        if self.current is page:
            self._show_page(page)

    def find_next(self) -> None:
        needle = self.search.text().strip().lower()
        if not needle or not self.project or not self.project.pages:
            return
        self._save_text()
        start = self.page_list.currentRow()
        pos = self.editor.textCursor().selectionEnd() if start >= 0 else 0
        n = len(self.project.pages)
        for step in range(n + 1):
            row = (max(start, 0) + step) % n
            page = self.project.pages[row]
            text = self.project.page_text(page).lower() if page.status in (DONE, REVIEWED) else ""
            idx = text.find(needle, pos if step == 0 else 0)
            if idx >= 0:
                if row != self.page_list.currentRow():
                    self.page_list.setCurrentRow(row)
                cur = self.editor.textCursor()
                cur.setPosition(idx)
                cur.setPosition(idx + len(needle), QTextCursor.MoveMode.KeepAnchor)
                self.editor.setTextCursor(cur)
                self.editor.setFocus()
                return
        self.statusBar().showMessage(f"No se encontró «{self.search.text()}».", 5000)

    # ================================================================ acciones sobre páginas
    def add_photos_dialog(self) -> None:
        if not self.project or not self._confirm_idle():
            return
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS | PDF_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Elija las fotos de las páginas", str(Path.home()),
                                                f"Fotos y PDF ({exts});;Todos los archivos (*)")
        if files:
            self.import_files([Path(f) for f in files])

    def import_files(self, files: list[Path]) -> None:
        exts = IMAGE_EXTS | PDF_EXTS
        files = sorted([f for f in files if f.suffix.lower() in exts], key=natural_key)
        if not files or not self.project:
            return
        job = ImportJob(self.project, files, self.engine, self)
        job.imported.connect(self._on_imported)
        self._start_job(job, "Agregando fotos…")

    def _on_imported(self, results: list) -> None:
        for source, pages in results:
            self.project.append(source, pages)
        self.project.save()
        first_new = results[0][1][0].id if results and results[0][1] else None
        self._fill_list()
        if first_new:
            found = self._item_for(first_new)
            if found:
                self.page_list.setCurrentRow(found[0])
        n_pages = sum(len(p) for _, p in results)
        self.statusBar().showMessage(f"Se agregaron {len(results)} fotos ({n_pages} páginas). "
                                     "Pulse «Procesar pendientes» para leer el texto.", 10000)

    def process_pending(self) -> None:
        if not self.project:
            return
        pages = [p for p in self.project.pages if p.status in (PENDING, ERROR)]
        if not pages:
            QMessageBox.information(self, APP_NAME, "No hay páginas pendientes.")
            return
        self._process(pages)

    def reprocess_selected(self) -> None:
        pages = self._selected_pages()
        if not pages:
            return
        touched = [p for p in pages if p.edited or p.status == REVIEWED]
        if touched and QMessageBox.question(
                self, APP_NAME,
                f"{len(touched)} de las páginas seleccionadas ya fueron corregidas o revisadas. "
                "Si las vuelve a procesar se perderán esas correcciones. ¿Continuar?") != QMessageBox.StandardButton.Yes:
            return
        self._save_text()
        for p in pages:
            self.project.reset_page(p)
        self._process(pages)

    def _process(self, pages: list[Page]) -> None:
        if self.engine is None:
            QMessageBox.warning(self, APP_NAME, "No se puede leer el texto:\n\n" + self.engine_error)
            return
        if not self._confirm_idle():
            return
        self._save_text()
        job = ProcessJob(self.project, pages, self.engine, self)
        job.page_done.connect(self._on_page_done)
        self._start_job(job, "Procesando páginas…")

    def _on_page_done(self, page_id: str) -> None:
        self.project.save()
        found = self._item_for(page_id)
        if found:
            self._refresh_item(found[1], found[0] + 1)
        self._update_counts()
        if self.current and self.current.id == page_id:
            self._show_page(self.current)

    def rotate_selected(self, degrees: int) -> None:
        pages = self._selected_pages()
        if not pages or not self._confirm_idle() or not self._confirm_discard(pages, "girar"):
            return
        for sid in dict.fromkeys(p.source_id for p in pages):
            source = self.project.source(sid)
            self.project.rotate_source(source, degrees)
            for p in self.project.pages_of(sid):
                processing.save_thumbnail(self.project, p, processing.preview(self.project, p, 600))
        self.project.save()
        self._refresh_items()
        self._show_page(self.current)

    def toggle_split(self) -> None:
        pages = self._selected_pages()
        if not pages or not self._confirm_idle() or not self._confirm_discard(pages, "partir o unir"):
            return
        self._save_text()
        new_ids = []
        for sid in dict.fromkeys(p.source_id for p in pages):
            source = self.project.source(sid)
            for p in self.project.set_two_pages(source, not source.two_pages):
                processing.save_thumbnail(self.project, p, processing.preview(self.project, p, 600))
                new_ids.append(p.id)
        self.project.save()
        self._fill_list()
        if new_ids:
            found = self._item_for(new_ids[0])
            if found:
                self.page_list.setCurrentRow(found[0])

    def delete_selected(self) -> None:
        pages = self._selected_pages()
        if not pages or not self._confirm_idle():
            return
        msg = f"¿Quitar {len(pages)} página(s) del libro? Las fotos originales en su computador no se borran."
        if QMessageBox.question(self, APP_NAME, msg) != QMessageBox.StandardButton.Yes:
            return
        row = self.page_list.currentRow()
        self.save_timer.stop()
        self.current = None
        self.project.delete_pages(pages)
        self.project.save()
        self._fill_list()
        if self.page_list.count():
            self.page_list.setCurrentRow(min(max(row, 0), self.page_list.count() - 1))
        else:
            self._show_page(None)

    def _confirm_discard(self, pages: list[Page], verb: str) -> bool:
        affected = [p for sid in {p.source_id for p in pages} for p in self.project.pages_of(sid)
                    if p.status in (DONE, REVIEWED)]
        if not affected:
            return True
        return QMessageBox.question(
            self, APP_NAME,
            f"Al {verb} la foto, {len(affected)} página(s) ya transcrita(s) quedarán pendientes y "
            "se perderá su texto. ¿Continuar?") == QMessageBox.StandardButton.Yes

    # ================================================================ exportar
    def export(self, kind: str) -> None:
        if not self.project or not self.project.pages or not self._confirm_idle():
            return
        self._save_text()
        pending = sum(1 for p in self.project.pages if p.status not in (DONE, REVIEWED))
        if pending and QMessageBox.question(
                self, APP_NAME,
                f"Hay {pending} página(s) sin transcribir; quedarán vacías o se omitirán. ¿Exportar de todos modos?"
        ) != QMessageBox.StandardButton.Yes:
            return
        options: dict = {}
        if kind in ("docx", "txt"):
            dlg = ExportOptionsDialog(kind, self)
            if not dlg.exec():
                return
            options = dlg.options()
        names = {"pdf": ("PDF (*.pdf)", ".pdf"), "docx": ("Documento de Word (*.docx)", ".docx"),
                 "txt": ("Texto (*.txt)", ".txt")}
        filt, ext = names[kind]
        default = self.project.folder / f"{self.project.folder.name}{ext}"
        dest, _ = QFileDialog.getSaveFileName(self, "Guardar como", str(default), filt)
        if not dest:
            return
        dest_path = Path(dest)
        if dest_path.suffix.lower() != ext:
            dest_path = dest_path.with_suffix(ext)
        job = ExportJob(self.project, kind, dest_path, options, self)
        job.exported.connect(self._on_exported)
        self._start_job(job, "Exportando…")

    def _on_exported(self, dest: str, skipped: list) -> None:
        msg = f"Listo. Se guardó en:\n{dest}"
        if skipped:
            msg += f"\n\nSe omitieron {len(skipped)} página(s) sin procesar."
        box = QMessageBox(QMessageBox.Icon.Information, APP_NAME, msg, parent=self)
        open_btn = box.addButton("Abrir archivo", QMessageBox.ButtonRole.AcceptRole)
        folder_btn = box.addButton("Abrir carpeta", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cerrar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            open_in_explorer(Path(dest))
        elif box.clickedButton() is folder_btn:
            open_in_explorer(Path(dest).parent)

    # ================================================================ tareas en segundo plano
    def _confirm_idle(self) -> bool:
        if self.job and self.job.isRunning():
            QMessageBox.information(self, APP_NAME, "Espere a que termine la tarea en curso (o pulse «Detener»).")
            return False
        return True

    def _start_job(self, job: Job, label: str) -> None:
        self.job = job
        self.progress.setRange(0, 0)
        self.progress.show()
        self.btn_cancel.setVisible(not isinstance(job, ExportJob))
        self.btn_cancel.setEnabled(True)
        self.statusBar().showMessage(label)
        for act in self.structural:
            act.setEnabled(False)
        self.page_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        job.progress.connect(self._on_progress)
        job.failed.connect(lambda msg: QMessageBox.warning(self, APP_NAME, msg))
        job.finished.connect(self._on_job_finished)
        job.start()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)

    def cancel_job(self) -> None:
        if self.job:
            self.job.cancel()
            self.btn_cancel.setEnabled(False)
            self.statusBar().showMessage("Deteniendo… (se termina la página en curso)")

    def _on_job_finished(self) -> None:
        cancelled = self.job.cancelled if self.job else False
        self.job = None
        self.progress.hide()
        self.btn_cancel.hide()
        for act in self.structural:
            act.setEnabled(True)
        self.page_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        if self.project:
            self.project.save()
            self._refresh_items()
        self.statusBar().showMessage("Detenido." if cancelled else "Terminado.", 6000)

    # ================================================================ ventana
    def dragEnterEvent(self, event):
        if self.project and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        expanded: list[Path] = []
        for f in files:
            expanded.extend(sorted(f.iterdir()) if f.is_dir() else [f])
        if self._confirm_idle():
            self.import_files(expanded)

    def about(self) -> None:
        QMessageBox.about(self, APP_NAME,
                          f"<b>{APP_NAME}</b> versión {__version__}<br><br>"
                          "Convierte fotos de páginas en texto, sin internet.<br>"
                          "Reconocimiento de texto: Tesseract OCR (licencia Apache 2.0).")

    def closeEvent(self, event):
        self._save_text()
        if self.job and self.job.isRunning():
            if QMessageBox.question(self, APP_NAME, "Hay una tarea en curso. ¿Detenerla y salir?") \
                    != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.job.cancel()
            self.job.wait()
        if self.project:
            self.project.save()
        event.accept()
