"""燧镜「模组」页。

只认 .sjmod 包：安装 / 启停 / 卸载 / 打开目录 / 拖拽装。
外层程序（exe、网页）不走这里，还留在「工具」页。

页面本身不碰业务，全部交给 core.mod_api 的 ModRegistry。
"""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from core.mod_api import (
    KIND_EXTERNAL,
    MOD_SUFFIX,
    ModRegistry,
    ModRuntime,
    mods_root,
)


class _Card(QtWidgets.QFrame):
    """一个模组包一行。"""

    def __init__(self, rt: ModRuntime, page: "ModPage") -> None:
        super().__init__()
        self.rt = rt
        self.page = page
        self.setObjectName("ModCard")
        self.setProperty("off", not rt.running)
        self.setProperty("glass", True)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 9, 10, 9)
        row.setSpacing(10)

        text = QtWidgets.QVBoxLayout()
        text.setSpacing(2)

        title_row = QtWidgets.QHBoxLayout()
        title_row.setSpacing(6)
        name = QtWidgets.QLabel(rt.spec.name)
        name.setStyleSheet("font-weight:600;")
        title_row.addWidget(name)

        ver = QtWidgets.QLabel(f"v{rt.spec.version}")
        ver.setObjectName("Small")
        title_row.addWidget(ver)

        if rt.spec.builtin:
            tag = QtWidgets.QLabel("内置")
            tag.setObjectName("Tag")
            title_row.addWidget(tag)

        kind_tag = QtWidgets.QLabel(rt.spec.kind_label)
        kind_tag.setObjectName("Small")
        title_row.addWidget(kind_tag)
        title_row.addStretch(1)
        text.addLayout(title_row)

        sub = f"{rt.spec.author} · {rt.spec.id}"
        if rt.spec.permissions:
            sub += " · 权限 " + "、".join(rt.spec.permissions)
        desc = QtWidgets.QLabel(sub + (f"\n{rt.spec.description}" if rt.spec.description else ""))
        desc.setObjectName("Small")
        desc.setWordWrap(True)
        text.addWidget(desc)

        if rt.error:
            err = QtWidgets.QLabel("加载失败：" + rt.error.strip().splitlines()[-1][:120])
            err.setObjectName("Small")
            err.setStyleSheet("color:#ff7b7b;")
            err.setWordWrap(True)
            text.addWidget(err)

        row.addLayout(text, 1)

        self.switch = QtWidgets.QCheckBox("启用")
        self.switch.setChecked(rt.running)
        self.switch.setCursor(QtCore.Qt.PointingHandCursor)
        self.switch.toggled.connect(self._on_toggle)
        row.addWidget(self.switch)

        more = QtWidgets.QPushButton("⋯")
        more.setObjectName("Ghost")
        more.setFixedWidth(32)
        more.setCursor(QtCore.Qt.PointingHandCursor)
        more.clicked.connect(self._menu)
        row.addWidget(more)

    # ---------- 交互 ----------
    def _on_toggle(self, on: bool) -> None:
        if on:
            ok = self.page.registry.enable(self.rt.spec.id)
            if not ok:
                self.switch.blockSignals(True)
                self.switch.setChecked(False)
                self.switch.blockSignals(False)
                self.page.main.toast(f"{self.rt.spec.name} 启用失败，看 logs\\mods.log", False)
        else:
            self.page.registry.disable(self.rt.spec.id)
        self.setProperty("off", not self.rt.running)
        self.style().unpolish(self)
        self.style().polish(self)
        self.page.refresh_count()

    def _menu(self) -> None:
        m = QtWidgets.QMenu(self)
        m.addAction("详情…", self._detail)
        m.addAction("打开所在文件夹", self._open_dir)
        if not self.rt.spec.builtin:
            m.addSeparator()
            act = m.addAction("卸载", self._uninstall)
            act.setEnabled(True)
        m.exec(self.mapToGlobal(QtCore.QPoint(self.width() - 120, self.height())))

    def _detail(self) -> None:
        spec = self.rt.spec
        lines = [
            f"名称：{spec.name}",
            f"id：{spec.id}",
            f"版本：{spec.version}",
            f"apiVersion：{spec.api_version}",
            f"作者：{spec.author}",
            f"类型：{spec.kind_label}",
            f"权限：{'、'.join(spec.permissions) or '无'}",
            f"来源：{spec.source_label}",
            f"目录：{spec.root}",
        ]
        if spec.kind == KIND_EXTERNAL:
            lines.append(f"外部程序：{spec.resolved_external}")
        if spec.description:
            lines.append(f"说明：{spec.description}")
        if self.rt.error:
            lines.append("\n加载错误：\n" + self.rt.error.strip()[:600])
        QtWidgets.QMessageBox.information(self, spec.name, "\n".join(lines))

    def _open_dir(self) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.rt.spec.root)))

    def _uninstall(self) -> None:
        name = self.rt.spec.name
        ok = QtWidgets.QMessageBox.question(
            self, "卸载模组", f"把「{name}」从模组目录里删掉？\n\n配置文件会保留在 mods_data 里。"
        )
        if ok != QtWidgets.QMessageBox.Yes:
            return
        good, msg = self.page.registry.uninstall(self.rt.spec.id)
        self.page.main.toast(msg, good)
        self.page.reload()


class _DropZone(QtWidgets.QFrame):
    """空模组时显示的引导 + 拖拽落点。"""

    dropped = QtCore.Signal(Path)

    def __init__(self, page: "ModPage") -> None:
        super().__init__()
        self.page = page
        self.setObjectName("Card")
        self.setAcceptDrops(True)
        self.setMinimumHeight(220)

        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(20, 28, 20, 28)
        col.setSpacing(8)
        col.addStretch(1)

        t = QtWidgets.QLabel("还没有模组")
        t.setObjectName("Section")
        t.setAlignment(QtCore.Qt.AlignCenter)
        col.addWidget(t)

        hint = QtWidgets.QLabel(
            "模组是 .sjmod 包，拖进来就能装。\n"
            "和工具页那种「直接启动一个 exe」不一样，模组只能在这个软件里跑。"
        )
        hint.setObjectName("Hint")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        hint.setWordWrap(True)
        col.addWidget(hint)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        b1 = QtWidgets.QPushButton("安装模组文件")
        b1.setObjectName("Ghost")
        b1.clicked.connect(page.install_dialog)
        btn_row.addWidget(b1)
        b2 = QtWidgets.QPushButton("打开模组文件夹")
        b2.setObjectName("Ghost")
        b2.clicked.connect(page.open_folder)
        btn_row.addWidget(b2)
        btn_row.addStretch(1)
        col.addLayout(btn_row)

        folder = QtWidgets.QLabel(str(mods_root()))
        folder.setObjectName("Small")
        folder.setAlignment(QtCore.Qt.AlignCenter)
        folder.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        col.addWidget(folder)

        col.addStretch(1)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.exists():
                self.page.install_file(p)
                break


class ModPage(QtWidgets.QWidget):
    def __init__(self, main, app_version: str = "", parent=None) -> None:
        super().__init__(parent)
        self.main = main
        self.setObjectName("Page")
        self.setAcceptDrops(True)

        self.registry = ModRegistry(
            ui_register=None,
            hotkey_register=None,
            notify=self._notify,
            app_version=app_version,
        )

        self._cards: list[_Card] = []
        self._build()
        self.reload()
        self._watch()

    # ---------- 搭界面 ----------
    def _build(self) -> None:
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(18, 4, 18, 12)
        col.setSpacing(10)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("模组")
        title.setObjectName("Section")
        head.addWidget(title)

        self.count = QtWidgets.QLabel("")
        self.count.setObjectName("Small")
        head.addWidget(self.count)
        head.addStretch(1)

        refresh = QtWidgets.QPushButton("刷新")
        refresh.setObjectName("Ghost")
        refresh.setToolTip("重新扫描模组目录")
        refresh.clicked.connect(self.reload)
        head.addWidget(refresh)

        open_btn = QtWidgets.QPushButton("打开模组文件夹")
        open_btn.setObjectName("Ghost")
        open_btn.setToolTip("往里面丢 .sjmod 也行，程序会自动识别")
        open_btn.clicked.connect(self.open_folder)
        head.addWidget(open_btn)

        install_btn = QtWidgets.QPushButton("+ 安装模组文件")
        install_btn.setObjectName("Ghost")
        install_btn.clicked.connect(self.install_dialog)
        head.addWidget(install_btn)
        col.addLayout(head)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.host = QtWidgets.QWidget()
        self.host.setAcceptDrops(True)
        self.box = QtWidgets.QVBoxLayout(self.host)
        self.box.setContentsMargins(0, 0, 4, 0)
        self.box.setSpacing(8)
        self.scroll.setWidget(self.host)
        col.addWidget(self.scroll, 1)

        foot = QtWidgets.QLabel(
            "把 .sjmod 文件拖进这个页面也能装。装坏的包会扔进 mods\\_invalid，不占地方。"
        )
        foot.setObjectName("Hint")
        foot.setWordWrap(True)
        col.addWidget(foot)

    # ---------- 刷新 ----------
    def reload(self) -> None:
        self.registry.scan()
        while self.box.count():
            item = self.box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()

        runtimes = self.registry.all()
        if not runtimes:
            self.box.addWidget(_DropZone(self))
            self.box.addStretch(1)
        else:
            for rt in runtimes:
                card = _Card(rt, self)
                self._cards.append(card)
                self.box.addWidget(card)
            for name, why in self.registry.invalid:
                bad = QtWidgets.QLabel(f"✗ {name}：{why}")
                bad.setObjectName("Small")
                bad.setStyleSheet("color:#ff7b7b;")
                bad.setWordWrap(True)
                self.box.addWidget(bad)
            self.box.addStretch(1)

        self.refresh_count()

    def refresh_count(self) -> None:
        total = len(self.registry.all())
        on = sum(1 for rt in self.registry.all() if rt.running)
        self.count.setText(f"{on} / {total} 已启用" if total else "还没有模组")

    # ---------- 安装 ----------
    def install_dialog(self) -> None:
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择模组文件",
            str(mods_root()),
            f"燧镜模组 (*{MOD_SUFFIX});;压缩包 (*.zip)",
        )
        if path:
            self.install_file(Path(path))

    def install_file(self, pkg: Path) -> None:
        good, msg = self.registry.install(pkg)
        self.main.toast(msg, good)
        if good:
            self.reload()

    def open_folder(self) -> None:
        root = mods_root()
        root.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(root)))

    # ---------- 目录监听 ----------
    def _watch(self) -> None:
        root = mods_root()
        root.mkdir(parents=True, exist_ok=True)
        self._watcher = QtCore.QFileSystemWatcher([str(root)], self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self.reload)

    def _on_dir_changed(self, *_a) -> None:
        self._timer.start()

    # ---------- 拖拽（整页） ----------
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file():
                self.install_file(p)
                break
            if p.is_dir():
                self.main.toast("拖的是文件夹，请把它打成 .sjmod 再拖（用 tool\\make_sjmod.py）", False)
                break

    # ---------- 通知 ----------
    def _notify(self, title: str, text: str, level: str = "info") -> None:
        try:
            self.main.toast(f"{title}：{text}", level != "error")
        except Exception:
            pass
