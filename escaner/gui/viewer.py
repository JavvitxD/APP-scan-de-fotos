"""Visor de imágenes con zoom (rueda del ratón) y arrastre."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


def gray_to_pixmap(gray: np.ndarray) -> QPixmap:
    gray = np.ascontiguousarray(gray)
    h, w = gray.shape[:2]
    img = QImage(gray.data, w, h, w, QImage.Format.Format_Grayscale8)
    return QPixmap.fromImage(img.copy())


class ImageViewer(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._item)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self._fit = True

    def show_gray(self, gray: np.ndarray | None) -> None:
        if gray is None:
            self._item.setPixmap(QPixmap())
            return
        self._item.setPixmap(gray_to_pixmap(gray))
        self.scene().setSceneRect(self._item.boundingRect())
        self.fit()

    def fit(self) -> None:
        self._fit = True
        self.resetTransform()
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor: float) -> None:
        self._fit = False
        self.scale(factor, factor)

    def wheelEvent(self, event):
        self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit:
            self.fit()
