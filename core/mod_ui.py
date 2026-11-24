"""燧镜「模组」页。

只认 .sjmod 包：安装 / 启停 / 卸载 / 打开目录 / 拖拽装。
外层程序（exe、网页）不走这里，还留在「工具」页。

页面本身不碰业务，全部交给 core.mod_api 的 ModRegistry。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from core.flow import FlowLayout, FlowPage
from core.mod_api import (
    KIND_EXTERNAL,
    MOD_SUFFIX,
    ModRegistry,
    ModRuntime,
    mods_root,
)


# ---------------------------------------------------------------------------
# 安装前把权限摊开给用户看（中文）
# ---------------------------------------------------------------------------
# 权限名 → 普通话解释。和 docs\MOD_API.md 第 5 节一一对应，加权限时两边一起改。
PERM_TEXT = {
    "notify": "弹通知（会往屏幕右下角弹提示条）",
    "ui.page": "在模组卡片菜单里加一项自己的界面",
    "hotkey": "注册全局热键（别的窗口在前台时也能按到）",
    "shell": "启动外部程序",
    "events": "收发宿主的自定义事件",
    "schedule": "注册定时任务（每次间隔自动跑）",
    "fs.data": "往自己的数据目录里写文件（下载的缓存、配置都在那儿）",
}


def _peek_manifest(pkg: Path):
    """不装、只读：从 zip 里捞出最外层那份 manifest.json，顺便把包里的条目名带回去。

    读不出来就返回 (None, 条目名)，交给 install() 去报标准错误。
    """
    try:
        with zipfile.ZipFile(pkg) as zf:
            names = zf.namelist()
            cands = [n for n in names if n.lower().endswith("manifest.json")]
            if not cands:
                return None, names
            cands.sort(key=lambda n: n.count("/"))   # 层级最浅的那份
            raw = json.loads(zf.read(cands[0]).decode("utf-8-sig"))
            return (raw if isinstance(raw, dict) else None), names
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
        return None, []


def _confirm_install(parent, raw: dict, files=None) -> bool:
    """安装确认：把名称、作者、尤其是权限列成人话。"""
    name = str(raw.get("name") or raw.get("id") or "未命名模组")
    version = str(raw.get("version") or "0.0.0")
    author = str(raw.get("author") or "未知")
    desc = str(raw.get("description") or "").strip()
    perms = [str(p).strip() for p in (raw.get("permissions") or []) if str(p).strip()]

    lines = [f"模组：{name}　v{version}", f"作者：{author}"]
    if desc:
        lines += ["", desc]
    lines += [""]
    if perms:
        lines.append("它要申请这些能力：")
        for p in perms:
            lines.append(f"　· {p} —— {PERM_TEXT.get(p, '未在规范里登记的权限，来源不明，建议别装')}")
        lines += ["", "这些能力只在你启用这个模组后才用得上，停用即收回。"]
    else:
        lines.append("这个模组不申请任何权限。")

    # 包里自带可执行程序（比如随包发一个 yt-dlp.exe）：安装前就把清单摆出来
    exes = [str(n) for n in (files or []) if str(n).lower().endswith((".exe", ".dll", ".bat", ".cmd"))]
    if exes:
        lines += ["", f"这个包里还带了 {len(exes)} 个可执行文件："]
        for n in exes[:6]:
            lines.append(f"　· {n}")
        if len(exes) > 6:
            lines.append(f"　· …还有 {len(exes) - 6} 个")
        lines.append("它们只在你启用模组、并且用到对应功能（比如下载 / 转码）时才会被运行，不放心就先取消。")

    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle("安装模组")
    box.setIcon(QtWidgets.QMessageBox.Question)
    box.setText(f"确定安装「{name}」吗？")
    box.setInformativeText("\n".join(lines))
    yes = box.addButton("安装", QtWidgets.QMessageBox.AcceptRole)
    box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
    box.setDefaultButton(yes)
    box.exec()
    return box.clickedButton() is yes


# ---------------------------------------------------------------------------
# 弹窗 / 目录 / 卸载：列表卡片和宫格磁贴共用
# ---------------------------------------------------------------------------
def _mod_detail(parent, rt: ModRuntime) -> None:
    spec = rt.spec
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
    if rt.error:
        lines.append("\n加载错误：\n" + rt.error.strip()[:600])
    QtWidgets.QMessageBox.information(parent, spec.name, "\n".join(lines))


def _mod_open_dir(parent, rt: ModRuntime) -> None:
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(rt.spec.root)))


def _mod_uninstall(parent, rt: ModRuntime) -> None:
    name = rt.spec.name
    ok = QtWidgets.QMessageBox.question(
        parent, "卸载模组", f"把「{name}」从模组目录里删掉？\n\n配置文件会保留在 mods_data 里。"
    )
    if ok != QtWidgets.QMessageBox.Yes:
        return
    page = getattr(parent, "page", None)
    registry = page.registry if page is not None else None
    if registry is None:
        return
    good, msg = registry.uninstall(rt.spec.id)
    page.main.toast(msg, good)
    page.reload()


def _letter_icon(name: str, color: str = "#8a7bd4") -> QtGui.QIcon:
    """宫格里取不到程序图标时，画一个首字母方块。"""
    px = QtGui.QPixmap(64, 64)
    px.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(px)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#1b2230"))
    p.drawRoundedRect(QtCore.QRectF(2, 2, 60, 60), 12, 12)
    p.setPen(QtGui.QColor(color))
    f = p.font()
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(px.rect(), QtCore.Qt.AlignCenter, (name or "?")[:1])
    p.end()
    return QtGui.QIcon(px)


def _tile_icon(rt: ModRuntime) -> QtGui.QIcon:
    """外部程序取它自己的 exe 图标；包类模组用首字母方块。"""
    spec = rt.spec
    if spec.kind == KIND_EXTERNAL:
        try:
            exe = Path(str(getattr(spec, "resolved_external", "") or ""))
            if exe.exists():
                ic = QtWidgets.QFileIconProvider().icon(QtCore.QFileInfo(str(exe)))
                if not ic.isNull():
                    return ic
        except Exception:
            pass
    return _letter_icon(spec.name, "#20ffe0" if spec.kind == KIND_EXTERNAL else "#8a7bd4")


class _Tile(QtWidgets.QFrame):
    """宫格视图的一格：双击启用 / 停用，右键详情、打开文件夹、卸载。"""

    W = 118
    H = 124

    def __init__(self, rt: ModRuntime, page: "ModPage") -> None:
        super().__init__()
        self.rt = rt
        self.page = page
        self.setObjectName("ModTile")
        self.setProperty("off", not rt.running)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        # 宫格磁贴自己兜底一层实色底：主题里的玻璃样式在半透明主窗口上会淡到看不见
        self.setStyleSheet(
            'QFrame#ModTile { background: rgba(20, 26, 36, 0.80);'
            " border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 14px; }"
            'QFrame#ModTile[off="true"] { background: rgba(16, 21, 29, 0.72); }'
            'QFrame#ModTile[hover="true"] { background: rgba(31, 39, 53, 0.88);'
            " border-color: rgba(255, 255, 255, 0.30); }"
        )
        self.setFixedSize(self.W, self.H)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(3)

        self.icon_label = QtWidgets.QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setAlignment(QtCore.Qt.AlignCenter)
        self.icon_label.setPixmap(_tile_icon(self.rt).pixmap(44, 44))
        lay.addWidget(self.icon_label, 0, QtCore.Qt.AlignHCenter)

        self.name_label = QtWidgets.QLabel()
        self.name_label.setAlignment(QtCore.Qt.AlignCenter)
        self.name_label.setFixedHeight(18)
        self.name_label.setText(self._short_name())
        self.name_label.setToolTip(self.rt.spec.name)
        lay.addWidget(self.name_label)

        self.sub_label = QtWidgets.QLabel()
        self.sub_label.setObjectName("Small")
        self.sub_label.setAlignment(QtCore.Qt.AlignCenter)
        self.sub_label.setText(self._sub_text())
        lay.addWidget(self.sub_label)

        lay.addStretch(1)

        self.state_label = QtWidgets.QLabel()
        self.state_label.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.state_label)

        self.badge = QtWidgets.QLabel("内置", self)
        self.badge.setStyleSheet(
            "color:#20ffe0; background:#10302c; border:1px solid #1c5049;"
            "border-radius:5px; padding:1px 4px; font-size:9.5px;"
        )
        self.badge.adjustSize()
        self.badge.setVisible(bool(self.rt.spec.builtin))
        if self.rt.spec.builtin:
            self.badge.move(self.W - self.badge.width() - 7, 7)

    def _short_name(self) -> str:
        name = self.rt.spec.name
        # 一格宽 132，再长就截断，鼠标悬停能看全名
        return name if len(name) <= 8 else name[:7] + "…"

    def _sub_text(self) -> str:
        text = f"v{self.rt.spec.version}"
        if self.rt.spec.permissions:
            text += f" · 权限 {len(self.rt.spec.permissions)}"
        return text

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.setProperty("off", not self.rt.running)
        self.style().unpolish(self)
        self.style().polish(self)
        self.sub_label.setText(self._sub_text())
        if self.rt.error:
            self.state_label.setText("加载失败")
            self.state_label.setStyleSheet("color:#ff7b7b; font-size:11px;")
        elif self.rt.running:
            self.state_label.setText("已启用")
            self.state_label.setStyleSheet("color:#20ffe0; font-size:11px;")
        else:
            self.state_label.setText("已停用")
            self.state_label.setStyleSheet("color:#7b8494; font-size:11px;")

    def enterEvent(self, event) -> None:
        self.setProperty("hover", "true")
        self.style().unpolish(self)
        self.style().polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hover", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.toggle()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def toggle(self) -> None:
        spec = self.rt.spec
        if self.rt.running:
            self.page.registry.disable(spec.id)
        else:
            if not self.page.registry.enable(spec.id):
                self.page.main.toast(f"{spec.name} 启用失败，看 logs\\mods.log", False)
        self.refresh()
        self.page.refresh_count()

    def _on_menu(self, pos) -> None:
        m = QtWidgets.QMenu(self)
        m.addAction("启用" if not self.rt.running else "停用", self.toggle)
        m.addSeparator()
        # 界面的 builder 只在模组启用时活着：停用后 _CTX 里的东西都收掉了，
        # 这时候再点「打开界面」只会得到一个空壳，干脆不列出来。
        pages = self.page.pages_for(self.rt.spec.id) if (hasattr(self.page, "pages_for") and self.rt.running) else []
        for key, _builder in pages:
            m.addAction(f"打开界面：{key}", lambda k=key: self.page.open_page(self.rt.spec.id, k))
        if pages:
            m.addSeparator()
        m.addAction("详情…", lambda: _mod_detail(self, self.rt))
        m.addAction("打开所在文件夹", lambda: _mod_open_dir(self, self.rt))
        if not self.rt.spec.builtin:
            m.addSeparator()
            m.addAction("卸载", lambda: _mod_uninstall(self, self.rt))
        m.exec(self.mapToGlobal(pos))


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
        pages = self.page.pages_for(self.rt.spec.id) if (hasattr(self.page, "pages_for") and self.rt.running) else []
        if pages:
            for key, _builder in pages:
                m.addAction(f"打开界面：{key}", lambda k=key: self.page.open_page(self.rt.spec.id, k))
            m.addSeparator()
        m.addAction("详情…", self._detail)
        m.addAction("打开所在文件夹", self._open_dir)
        if not self.rt.spec.builtin:
            m.addSeparator()
            act = m.addAction("卸载", self._uninstall)
            act.setEnabled(True)
        m.exec(self.mapToGlobal(QtCore.QPoint(self.width() - 120, self.height())))

    def _detail(self) -> None:
        _mod_detail(self, self.rt)

    def _open_dir(self) -> None:
        _mod_open_dir(self, self.rt)

    def _uninstall(self) -> None:
        _mod_uninstall(self, self.rt)


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
            "模组是打包好的 .sjmod 文件，拖这一个文件就能装。\n"
            "别把模组文件夹（manifest.json / main.py / assets）整个拖进来，那不是安装物。\n"
            "模组只能在这个软件里跑，和工具页那种「直接启动一个 exe」不一样。"
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

        # 宫格（默认）/ 列表，记在本机配置里，下次打开保持上次选的
        try:
            mode = str(getattr(self.main.cfg, "mod_view_mode", "grid") or "grid").lower()
        except Exception:
            mode = "grid"
        self.view_mode = "grid" if mode == "grid" else "list"

        self.registry = ModRegistry(
            ui_register=self._register_page,
            hotkey_register=self._register_hotkey,
            notify=self._notify,
            app_version=app_version,
        )
        # 模组自己注册的界面页：(模组 id, key) → builder
        self._pages: dict = {}

        self._cards: list[_Card] = []
        self._tiles: list[_Tile] = []
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
        # 视图切换：宫格 / 列表（跟「工具」页那两个小按钮一个样式）
        self.seg_grid = QtWidgets.QToolButton()
        self.seg_grid.setObjectName("Seg")
        self.seg_grid.setText("宫格")
        self.seg_grid.setCheckable(True)
        self.seg_grid.setCursor(QtCore.Qt.PointingHandCursor)
        self.seg_grid.setToolTip("方块图标排列，面板拉宽会自动多排一列；双击启用 / 停用")
        self.seg_grid.clicked.connect(lambda: self.set_view_mode("grid"))
        head.addWidget(self.seg_grid)

        self.seg_list = QtWidgets.QToolButton()
        self.seg_list.setObjectName("Seg")
        self.seg_list.setText("列表")
        self.seg_list.setCheckable(True)
        self.seg_list.setCursor(QtCore.Qt.PointingHandCursor)
        self.seg_list.setToolTip("一行一个，能看清作者、权限和说明")
        self.seg_list.clicked.connect(lambda: self.set_view_mode("list"))
        head.addWidget(self.seg_list)

        head.addStretch(1)

        help_btn = QtWidgets.QPushButton("?")
        help_btn.setObjectName("Ghost")
        help_btn.setFixedSize(30, 30)
        help_btn.setCursor(QtCore.Qt.PointingHandCursor)
        help_btn.setToolTip("怎么装模组：拖的是哪个文件？点开看看")
        help_btn.clicked.connect(self.show_install_help)
        head.addWidget(help_btn)

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
            "分不清拖什么就点右上角「?」。"
        )
        foot.setObjectName("Hint")
        foot.setWordWrap(True)
        col.addWidget(foot)

    # ---------- 装法说明 ----------
    def show_install_help(self) -> None:
        """那个小问号：把「拖哪个文件」讲清楚，免得把模组文件夹整个拖进来。"""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("怎么装模组")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("要拖的是 .sjmod 那个包，不是模组文件夹")
        box.setInformativeText(
            "你在「模组」页看到的 manifest.json / main.py / assets，是模组文件夹里的三样东西，"
            "它们是打包的原料，不是安装物。把文件夹拖进来宿主不认，还会被当成坏包拒掉。\n\n"
            "正确的做法只有一步：\n"
            "1. 打开上一级目录 mods\\，找到 com.xxx.sjmod（2.8MB 上下的单个压缩包文件，"
            "图标通常是压缩包样子）\n"
            "2. 把这一个文件拖到燧镜「模组」页的空白处，或点「+ 安装模组文件」选中它\n"
            "3. 弹出中文权限卡时逐项确认，要下载 / 转码的会多一项「启动外部程序」，然后点「安装」"
        )
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.button(QtWidgets.QMessageBox.Ok).setText("知道了")
        box.exec()

    # ---------- 刷新 ----------
    def reload(self) -> None:
        self.registry.scan()
        # 卸载/重扫之后，把已不在列表里的模组登记的界面页清掉，
        # 免得卡片菜单里留一个点了没反应的「打开界面」。
        alive = {rt.spec.id for rt in self.registry.all()}
        for key in [k for k in self._pages if k[0] not in alive]:
            self._pages.pop(key, None)
        while self.box.count():
            item = self.box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()
        self._tiles.clear()
        self._sync_seg()

        runtimes = self.registry.all()
        if not runtimes:
            self.box.addWidget(_DropZone(self))
        elif self.view_mode == "grid":
            page = FlowPage(self.host)
            flow = FlowLayout(page, margin=0, hspacing=8, vspacing=8)
            page.flow = flow
            for rt in runtimes:
                tile = _Tile(rt, self)
                self._tiles.append(tile)
                flow.addWidget(tile)
            self.box.addWidget(page, 0, QtCore.Qt.AlignTop)
            QtCore.QTimer.singleShot(0, self._fit_grid)
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

    def _fit_grid(self) -> None:
        """宫格内容不满一屏时，别留一块空的可滚动区域。"""
        if self.view_mode != "grid" or not self.box.count():
            return
        page = self.box.itemAt(0).widget()
        if not isinstance(page, FlowPage):
            return
        flow = getattr(page, "flow", None)
        if flow is None:
            return
        h = flow.heightForWidth(max(200, self.host.width() - 8))
        if h > 0:
            page.setFixedHeight(h)

    def set_view_mode(self, mode: str) -> None:
        mode = "grid" if mode == "grid" else "list"
        if mode == self.view_mode:
            self._sync_seg()
            return
        self.view_mode = mode
        try:
            self.main.cfg.mod_view_mode = mode
            self.main.cfg.save()
        except Exception:
            pass
        self.reload()

    def _sync_seg(self) -> None:
        is_grid = self.view_mode == "grid"
        self.seg_grid.setChecked(is_grid)
        self.seg_list.setChecked(not is_grid)

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
        # 先把包里的 manifest 只读捞出来，让用户看清这包要什么权限再决定装不装。
        # 拖拽、选文件、拖放区三个入口都走这里，所以只加这一处就全覆盖了。
        raw, files = _peek_manifest(pkg)
        if raw is not None and not _confirm_install(self, raw, files):
            self.main.toast("已取消安装", False)
            return
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

    # ---------- 模组注册的界面页 / 热键 ----------
    def _register_page(self, spec, key: str, builder) -> None:
        self._pages[(spec.id, key)] = builder

    def pages_for(self, mod_id: str) -> list:
        return [(k, b) for (mid, k), b in self._pages.items() if mid == mod_id]

    def open_page(self, mod_id: str, key: str) -> None:
        """把模组注册的控件塞进一个对话框显示（不占模组页布局）。"""
        builder = self._pages.get((mod_id, key))
        if builder is None:
            return
        try:
            body = builder()
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "模组页面出错", str(exc)[:300])
            return
        if not isinstance(body, QtWidgets.QWidget):
            QtWidgets.QMessageBox.warning(self, "模组页面出错", "builder 没有返回 QWidget")
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(key)
        dlg.resize(560, 420)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(body, 1)
        dlg.exec()

    def _register_hotkey(self, spec, combo: str, fn) -> None:
        hook = getattr(self.main, "register_mod_hotkey", None)
        if hook is None:
            return
        if not hook(spec, combo, fn):
            try:
                self.main.toast(f"{spec.name} 的热键 {combo} 注册不上", False)
            except Exception:
                pass
