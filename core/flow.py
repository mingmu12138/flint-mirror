"""流式（自动换行）布局。

原来写在 gui.py 里给「工具」页的图标视图用；「模组」页也要宫格排布，
抽到这里，两边共用一份，免得改一处漏一处。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt


class FlowPage(QtWidgets.QWidget):
    """图标视图的容器：高度跟着内容行数走，内容不满一屏就不出滚动条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow: Optional[FlowLayout] = None
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.flow is None:
            return
        h = self.flow.heightForWidth(self.width())
        if h > 0 and abs(self.height() - h) > 1:
            self.setFixedHeight(h)


class FlowLayout(QtWidgets.QLayout):
    """自动换行布局：面板拉宽就多排一列，窄了就自动少一列。"""

    def __init__(self, parent=None, margin=0, hspacing=8, vspacing=8):
        super().__init__(parent)
        self._items: List[QtWidgets.QLayoutItem] = []
        self._hspacing = hspacing
        self._vspacing = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        base = self.minimumSize()
        pw = self.parentWidget()
        w = pw.width() if pw is not None else 0
        if w > base.width():
            return QtCore.QSize(base.width(), max(base.height(), self.heightForWidth(w)))
        return base

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            w, h = hint.width(), hint.height()
            if x + w > eff.right() and line_h > 0:
                x = eff.x()
                y += line_h + self._vspacing
                line_h = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(x, y, w, h))
            x += w + self._hspacing
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()
