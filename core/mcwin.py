# -*- coding: utf-8 -*-
"""MC 全能指令控制台：快捷指令 / NBT 生成器 / 区域填充 / 发送记录。

四块共用一个底部「指令条」：任何一块拼出来的指令都先落在这里给你看一眼，
你点「发送」它才去按 Ctrl+V + 回车。危险指令先弹窗问一句。

红线（和 core/input_send.py 一致）：只生成文本、只模拟键鼠。不注入进程、
不读写游戏内存、不做反作弊对抗。单人世界或朋友房间用，稳。
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from core import input_send as ins
from core import mccmd

BG = "#0b1117"
CARD = "rgba(255,255,255,.05)"
EDGE = "rgba(255,255,255,.10)"
MAIN = "#20ffe0"
MONO = "Consolas,'Cascadia Mono','JetBrains Mono',monospace"

BTN_PRIMARY = (
    "QPushButton{padding:0 16px;border:none;border-radius:9px;font-size:12.5px;"
    "font-weight:600;background:rgba(32,255,224,.30);color:#04231d;}"
    "QPushButton:hover{background:rgba(60,255,230,.46);}"
    "QPushButton:disabled{background:rgba(32,255,224,.12);color:#4b6b66;}"
)
BTN_GHOST = (
    "QPushButton{padding:0 14px;border:1px solid rgba(255,255,255,.16);"
    "border-radius:9px;font-size:12px;background:transparent;color:#d5e3ee;}"
    "QPushButton:hover{background:rgba(255,255,255,.10);}"
)
BTN_SOFT = (
    "QPushButton{padding:0 12px;border:1px solid rgba(120,255,228,.36);"
    "border-radius:9px;font-size:12px;background:rgba(32,255,224,.10);color:#bffff4;}"
    "QPushButton:hover{background:rgba(32,255,224,.20);}"
)
BTN_WARN = (
    "QPushButton{padding:0 12px;border:1px solid rgba(255,140,120,.42);"
    "border-radius:9px;font-size:12px;background:rgba(255,120,100,.10);color:#ffd6cd;}"
    "QPushButton:hover{background:rgba(255,120,100,.22);}"
)
INPUT_CSS = (
    "QLineEdit,QSpinBox,QComboBox{background:rgba(255,255,255,.06);"
    "border:1px solid rgba(255,255,255,.12);border-radius:9px;padding:4px 9px;"
    "font-size:12px;color:#dff0f7;}"
    "QLineEdit:focus,QSpinBox:focus,QComboBox:focus{border-color:rgba(32,255,224,.55);}"
    "QComboBox QAbstractItemView{background:#0e1720;color:#dff0f7;"
    "selection-background-color:rgba(32,255,224,.28);border:1px solid rgba(255,255,255,.12);}"
)
LIST_CSS = (
    "QListWidget,QPlainTextEdit,QTreeWidget{background:rgba(255,255,255,.04);"
    "border:1px solid rgba(255,255,255,.10);border-radius:10px;"
    "font-size:12px;color:#cfdde9;padding:4px;}"
    "QListWidget::item{padding:3px 6px;border-radius:6px;}"
    "QListWidget::item:selected{background:rgba(32,255,224,.22);color:#eafffb;}"
)
TAB_CSS = (
    "QTabWidget::pane{border:none;}"
    "QTabBar::tab{background:transparent;color:#8fa3b6;padding:7px 16px;margin-right:6px;"
    "border:1px solid transparent;border-radius:9px;font-size:12.5px;}"
    "QTabBar::tab:selected{background:rgba(32,255,224,.14);color:#c8fff6;"
    "border:1px solid rgba(32,255,224,.34);}"
    "QTabBar::tab:hover{color:#dbe7f2;}"
)


def _caption(text: str) -> QtWidgets.QLabel:
    lab = QtWidgets.QLabel(text)
    lab.setStyleSheet("color:#93a6ba;font-size:11.5px;")
    return lab


def _card() -> QtWidgets.QFrame:
    frame = QtWidgets.QFrame()
    frame.setStyleSheet(f"QFrame{{background:{CARD};border:1px solid {EDGE};border-radius:12px;}}")
    return frame


class MCWindow(QtWidgets.QWidget):
    """主窗口点「MC 指令台」时弹出来的独立窗口。"""

    def __init__(self, cfg=None) -> None:
        super().__init__(None)
        self.setWindowTitle("MC 全能指令控制台 · 燧镜")
        self.setMinimumSize(920, 660)
        self.resize(1020, 740)
        self.setStyleSheet(f"QWidget{{background:{BG};color:#dbe7f2;}}QLabel{{background:transparent;}}")
        self.cfg = cfg

        # 本次会话的发送记录（不落盘：里面都是聊天/指令内容，没必要留在磁盘上）
        self._hist: List[Tuple[str, str, bool, str]] = []
        self._enchosen: Dict[str, int] = {}
        self._suppress = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        root.addLayout(self._build_top())

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setStyleSheet(TAB_CSS)
        self.tabs.addTab(self._build_quick(), "快捷指令")
        self.tabs.addTab(self._build_give(), "NBT 生成器")
        self.tabs.addTab(self._build_fill(), "区域填充")
        self.tabs.addTab(self._build_hist(), "发送记录")
        root.addWidget(self.tabs, 1)

        root.addLayout(self._build_bar())

        hint = QtWidgets.QLabel(
            "只做指令拼接 + 键鼠模拟：软件帮你按 Ctrl+V 和回车，和自己手按没区别。"
            "不读游戏内存、不注入、不碰反作弊。服务器上有反作弊插件时，人工输入同样可能被判定为频繁指令。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7d8fa3;font-size:11px;")
        root.addWidget(hint)

        self._refresh_game()

    # ---------------------------------------------------------------- 顶部
    def _build_top(self) -> QtWidgets.QHBoxLayout:
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)

        cap = QtWidgets.QLabel("Minecraft")
        cap.setStyleSheet("font-size:12.5px;font-weight:700;color:#eaf6ff;")
        top.addWidget(cap)

        self.game_lbl = QtWidgets.QLabel("检测中…")
        self.game_lbl.setStyleSheet(
            "font-size:11.5px;color:#ffd166;background:rgba(255,209,102,.10);"
            "border:1px solid rgba(255,209,102,.30);border-radius:8px;padding:3px 10px;"
        )
        top.addWidget(self.game_lbl)

        self.btn_find = QtWidgets.QPushButton("重新检测")
        self.btn_find.setCursor(Qt.PointingHandCursor)
        self.btn_find.setFixedHeight(26)
        self.btn_find.setStyleSheet(BTN_GHOST)
        self.btn_find.clicked.connect(self._refresh_game)
        top.addWidget(self.btn_find)

        top.addStretch(1)
        return top

    def _refresh_game(self) -> None:
        hwnd = ins.find_game_window()
        if hwnd:
            proc = ins.process_name(hwnd) or "游戏"
            title = ins.window_title(hwnd).strip()
            text = f"已找到 · {proc}"
            if title:
                text += f" · {title[:32]}"
            self.game_lbl.setText(text)
            self.game_lbl.setStyleSheet(
                "font-size:11.5px;color:#8dffd8;background:rgba(32,255,224,.10);"
                "border:1px solid rgba(32,255,224,.32);border-radius:8px;padding:3px 10px;"
            )
        else:
            self.game_lbl.setText("没找到 Minecraft 窗口（先把游戏开起来）")
            self.game_lbl.setStyleSheet(
                "font-size:11.5px;color:#ffb3a6;background:rgba(255,120,100,.10);"
                "border:1px solid rgba(255,120,100,.34);border-radius:8px;padding:3px 10px;"
            )

    # ---------------------------------------------------------------- 底部指令条
    def _build_bar(self) -> QtWidgets.QVBoxLayout:
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(6)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_caption("即将发送"))
        self.cmd_edit = QtWidgets.QLineEdit()
        self.cmd_edit.setPlaceholderText("点上面的快捷指令，或在这里直接敲 /指令")
        self.cmd_edit.setStyleSheet(INPUT_CSS + "QLineEdit{font-family:%s;font-size:12.5px;padding:6px 10px;}" % MONO)
        self.cmd_edit.returnPressed.connect(self._send_bar)
        row.addWidget(self.cmd_edit, 1)

        self.btn_copy = QtWidgets.QPushButton("复制")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.setFixedHeight(30)
        self.btn_copy.setStyleSheet(BTN_GHOST)
        self.btn_copy.clicked.connect(self._copy_bar)
        row.addWidget(self.btn_copy)

        self.btn_send = QtWidgets.QPushButton("发送")
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.setFixedHeight(30)
        self.btn_send.setStyleSheet(BTN_PRIMARY)
        self.btn_send.setMinimumWidth(88)
        self.btn_send.clicked.connect(self._send_bar)
        row.addWidget(self.btn_send)
        box.addLayout(row)

        opt = QtWidgets.QHBoxLayout()
        opt.setSpacing(10)
        opt.addWidget(_caption("输入方式"))
        self.method_box = QtWidgets.QComboBox()
        self.method_box.addItems(["剪贴板粘贴（推荐）", "逐字输入（慢，兼容稳）"])
        self.method_box.setFixedWidth(150)
        self.method_box.setStyleSheet(INPUT_CSS)
        opt.addWidget(self.method_box)

        self.chk_delay = QtWidgets.QCheckBox("延迟 3 秒（留时间自己切窗口）")
        self.chk_delay.setStyleSheet("font-size:11.5px;color:#9fb2c6;")
        opt.addWidget(self.chk_delay)

        self.chk_enter = QtWidgets.QCheckBox("发完按回车")
        self.chk_enter.setChecked(True)
        self.chk_enter.setStyleSheet("font-size:11.5px;color:#9fb2c6;")
        opt.addWidget(self.chk_enter)
        opt.addStretch(1)

        self.tip_lbl = QtWidgets.QLabel("")
        self.tip_lbl.setStyleSheet("color:#8fa8bd;font-size:11.5px;")
        opt.addWidget(self.tip_lbl)
        box.addLayout(opt)
        return box

    # ---------------------------------------------------------------- 1 快捷指令
    def _build_quick(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        world = [q for q in mccmd.QUICK if q.get("group") == "world"]
        clean = [q for q in mccmd.QUICK if q.get("group") == "clean"]
        lay.addWidget(self._quick_col("世界 · 自己", world, 4), 0)
        lay.addWidget(self._quick_col("清理 · 慎用", clean, 4), 0)
        lay.addStretch(1)
        return page

    def _quick_col(self, title: str, items, cols: int = 3) -> QtWidgets.QWidget:
        card = _card()
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)

        head = QtWidgets.QLabel(title)
        head.setStyleSheet("font-size:12.5px;font-weight:700;color:#dff6ff;")
        v.addWidget(head)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(7)
        for i, q in enumerate(items):
            btn = QtWidgets.QPushButton(str(q["label"]))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setToolTip(str(q["cmd"]))
            btn.setStyleSheet(BTN_WARN if q.get("danger") else BTN_SOFT)
            cmd = str(q["cmd"])
            btn.clicked.connect(lambda _=False, c=cmd: self._quick(c))
            grid.addWidget(btn, i // cols, i % cols)
        v.addLayout(grid)
        v.addStretch(1)

        note = QtWidgets.QLabel("点一下就把指令填进底部指令条并发送（红的会先问一句）")
        note.setWordWrap(True)
        note.setStyleSheet("color:#7d8fa3;font-size:11px;")
        v.addWidget(note)
        return card

    def _quick(self, cmd: str) -> None:
        self.cmd_edit.setText(cmd)
        self._dispatch(cmd)

    # ---------------------------------------------------------------- 2 NBT 生成器
    def _build_give(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        outer = QtWidgets.QHBoxLayout(page)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)

        left = _card()
        form = QtWidgets.QVBoxLayout(left)
        form.setContentsMargins(12, 10, 12, 10)
        form.setSpacing(8)
        t = QtWidgets.QLabel("物品与名字")
        t.setStyleSheet("font-size:12.5px;font-weight:700;color:#dff6ff;")
        form.addWidget(t)

        syn = QtWidgets.QHBoxLayout()
        syn.setSpacing(7)
        syn.addWidget(_caption("指令语法"))
        self.syntax_box = QtWidgets.QComboBox()
        self.syntax_box.addItems(["1.20.5+（组件）", "1.20.4 及以下（旧 NBT）"])
        self.syntax_box.setStyleSheet(INPUT_CSS)
        self.syntax_box.currentIndexChanged.connect(lambda *_: self._refresh_give())
        syn.addWidget(self.syntax_box, 1)
        form.addLayout(syn)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(7)

        grid.addWidget(_caption("物品"), 0, 0)
        self.item_box = QtWidgets.QComboBox()
        self.item_box.setEditable(True)
        for label, iid in mccmd.ITEMS:
            self.item_box.addItem(f"{label} · {iid.split(':')[-1]}", iid)
        self.item_box.setStyleSheet(INPUT_CSS)
        self.item_box.currentIndexChanged.connect(lambda *_: self._refresh_give())
        self.item_box.lineEdit().editingFinished.connect(self._refresh_give)
        grid.addWidget(self.item_box, 0, 1, 1, 2)

        grid.addWidget(_caption("给谁"), 1, 0)
        self.target_box = QtWidgets.QComboBox()
        self.target_box.setEditable(True)
        self.target_box.addItems(["@s", "@p", "@a", "@r", "@e"])
        self.target_box.setStyleSheet(INPUT_CSS)
        self.target_box.currentIndexChanged.connect(lambda *_: self._refresh_give())
        grid.addWidget(self.target_box, 1, 1, 1, 2)

        grid.addWidget(_caption("数量"), 2, 0)
        self.count_box = QtWidgets.QSpinBox()
        self.count_box.setRange(1, 640)
        self.count_box.setValue(1)
        self.count_box.setStyleSheet(INPUT_CSS)
        self.count_box.valueChanged.connect(lambda *_: self._refresh_give())
        grid.addWidget(self.count_box, 2, 1, 1, 2)

        grid.addWidget(_caption("自定义名字"), 3, 0)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("留空就没有名字，例：屠龙刀")
        self.name_edit.setStyleSheet(INPUT_CSS)
        self.name_edit.textChanged.connect(lambda *_: self._refresh_give())
        grid.addWidget(self.name_edit, 3, 1, 1, 2)
        form.addLayout(grid)

        self.give_hint = QtWidgets.QLabel("")
        self.give_hint.setWordWrap(True)
        self.give_hint.setStyleSheet("color:#7d8fa3;font-size:11px;")
        form.addWidget(self.give_hint)
        form.addStretch(1)
        left.setFixedWidth(380)
        outer.addWidget(left, 0)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(8)

        ench = _card()
        ev = QtWidgets.QVBoxLayout(ench)
        ev.setContentsMargins(12, 10, 12, 10)
        ev.setSpacing(7)
        et = QtWidgets.QLabel("附魔")
        et.setStyleSheet("font-size:12.5px;font-weight:700;color:#dff6ff;")
        ev.addWidget(et)

        self.ench_list = QtWidgets.QListWidget()
        self.ench_list.setStyleSheet(LIST_CSS)
        self.ench_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        for label, eid, mx in mccmd.ENCHANTS:
            it = QtWidgets.QListWidgetItem(f"{label} · {eid.split(':')[-1]}（≤{mx}）")
            it.setData(Qt.UserRole, (eid, mx))
            self.ench_list.addItem(it)
        ev.addWidget(self.ench_list, 1)

        erow = QtWidgets.QHBoxLayout()
        erow.setSpacing(7)
        erow.addWidget(_caption("等级"))
        self.lvl_box = QtWidgets.QSpinBox()
        self.lvl_box.setRange(1, 255)
        self.lvl_box.setValue(5)
        self.lvl_box.setFixedWidth(72)
        self.lvl_box.setStyleSheet(INPUT_CSS)
        erow.addWidget(self.lvl_box)

        b_add = QtWidgets.QPushButton("加入已有")
        b_add.setCursor(Qt.PointingHandCursor)
        b_add.setFixedHeight(28)
        b_add.setStyleSheet(BTN_SOFT)
        b_add.clicked.connect(self._add_ench)
        erow.addWidget(b_add)

        b_del = QtWidgets.QPushButton("移除选中")
        b_del.setCursor(Qt.PointingHandCursor)
        b_del.setFixedHeight(28)
        b_del.setStyleSheet(BTN_GHOST)
        b_del.clicked.connect(self._del_ench)
        erow.addWidget(b_del)
        erow.addStretch(1)
        ev.addLayout(erow)

        self.chosen_lbl = QtWidgets.QLabel("还没选附魔")
        self.chosen_lbl.setWordWrap(True)
        self.chosen_lbl.setStyleSheet("color:#9fe9dc;font-size:11.5px;")
        ev.addWidget(self.chosen_lbl)
        right.addWidget(ench, 0)

        prev = _card()
        pv = QtWidgets.QVBoxLayout(prev)
        pv.setContentsMargins(12, 10, 12, 10)
        pv.setSpacing(6)
        pt = QtWidgets.QLabel("实时预览")
        pt.setStyleSheet("font-size:12.5px;font-weight:700;color:#dff6ff;")
        pv.addWidget(pt)
        self.give_view = QtWidgets.QPlainTextEdit()
        self.give_view.setReadOnly(True)
        self.give_view.setFixedHeight(80)
        self.give_view.setStyleSheet(LIST_CSS + f"QPlainTextEdit{{font-family:{MONO};font-size:12px;}}")
        pv.addWidget(self.give_view)

        prow = QtWidgets.QHBoxLayout()
        prow.setSpacing(7)
        prow.addStretch(1)
        b_cp = QtWidgets.QPushButton("复制")
        b_cp.setCursor(Qt.PointingHandCursor)
        b_cp.setFixedHeight(28)
        b_cp.setStyleSheet(BTN_GHOST)
        b_cp.clicked.connect(lambda: self._copy_text(self.give_view.toPlainText()))
        prow.addWidget(b_cp)
        b_sd = QtWidgets.QPushButton("发送")
        b_sd.setCursor(Qt.PointingHandCursor)
        b_sd.setFixedHeight(28)
        b_sd.setStyleSheet(BTN_PRIMARY)
        b_sd.clicked.connect(lambda: self._send_from(self.give_view.toPlainText()))
        prow.addWidget(b_sd)
        pv.addLayout(prow)
        right.addWidget(prev, 1)
        outer.addLayout(right, 1)

        self._refresh_give()
        return page

    def _modern(self) -> bool:
        return self.syntax_box.currentIndex() == 0

    def _item_id(self) -> str:
        data = self.item_box.currentData()
        text = self.item_box.currentText().strip()
        if data and "·" in text:
            return str(data)
        if text:
            return text if ":" in text else f"minecraft:{text}"
        return str(data or "minecraft:diamond_sword")

    def _give_text(self) -> str:
        return mccmd.give_command(
            target=self.target_box.currentText().strip() or "@s",
            item_id=self._item_id(),
            count=self.count_box.value(),
            custom_name=self.name_edit.text(),
            enchants=list(self._enchosen.items()),
            modern=self._modern(),
        )

    def _refresh_give(self) -> None:
        if self._suppress:
            return
        cmd = self._give_text()
        self.give_view.setPlainText(cmd)
        self.give_hint.setText(
            "当前语法：" + ("1.20.5+ 组件（custom_name / enchantments）"
                            if self._modern() else "旧版 NBT（display.Name / Enchantments）")
        )

    def _add_ench(self) -> None:
        picked = self.ench_list.selectedItems()
        if not picked:
            self.tip_lbl.setText("先在列表里点一个附魔")
            return
        for it in picked:
            eid, mx = it.data(Qt.UserRole)
            self._enchosen[eid] = max(1, min(int(mx), self.lvl_box.value()))
        self._sync_chosen()

    def _del_ench(self) -> None:
        picked = self.ench_list.selectedItems()
        if not picked:
            # 没选列表就清空所有
            self._enchosen.clear()
            self._sync_chosen()
            return
        for it in picked:
            eid, _mx = it.data(Qt.UserRole)
            self._enchosen.pop(eid, None)
        self._sync_chosen()

    def _sync_chosen(self) -> None:
        names = {eid: label for label, eid, _mx in mccmd.ENCHANTS}
        if self._enchosen:
            parts = [f"{names.get(eid, eid)} Lv{lvl}" for eid, lvl in self._enchosen.items()]
            self.chosen_lbl.setText("已加：" + " · ".join(parts))
        else:
            self.chosen_lbl.setText("还没选附魔")
        self._refresh_give()

    # ---------------------------------------------------------------- 3 区域填充
    def _build_fill(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        card = _card()
        form = QtWidgets.QVBoxLayout(card)
        form.setContentsMargins(12, 10, 12, 10)
        form.setSpacing(9)

        t = QtWidgets.QLabel("从哪到哪，填什么")
        t.setStyleSheet("font-size:12.5px;font-weight:700;color:#dff6ff;")
        form.addWidget(t)

        def _row(label: str, widgets) -> QtWidgets.QHBoxLayout:
            h = QtWidgets.QHBoxLayout()
            h.setSpacing(7)
            cap = _caption(label)
            cap.setFixedWidth(104)
            h.addWidget(cap)
            for wd in widgets:
                h.addWidget(wd)
            h.addStretch(1)
            return h

        self.p1_edits = [self._coord_edit(v) for v in ("0", "60", "0")]
        form.addLayout(_row("起点 x / y / z", self.p1_edits))

        self.p2_edits = [self._coord_edit(v) for v in ("10", "70", "10")]
        form.addLayout(_row("终点 x / y / z", self.p2_edits))

        self.block_box = QtWidgets.QComboBox()
        self.block_box.setEditable(True)
        for label, bid in mccmd.BLOCKS:
            self.block_box.addItem(f"{label} · {bid.split(':')[-1]}", bid)
        self.block_box.setCurrentIndex(1)
        self.block_box.setFixedWidth(250)
        self.block_box.setStyleSheet(INPUT_CSS)
        self.block_box.currentIndexChanged.connect(lambda *_: self._refresh_fill())
        self.block_box.lineEdit().editingFinished.connect(self._refresh_fill)
        form.addLayout(_row("目标方块", [self.block_box]))

        self.old_box = QtWidgets.QComboBox()
        self.old_box.setEditable(True)
        self.old_box.addItem("（留空 = 整块都填）", "")
        for label, bid in mccmd.BLOCKS:
            self.old_box.addItem(f"{label} · {bid.split(':')[-1]}", bid)
        self.old_box.setFixedWidth(250)
        self.old_box.setStyleSheet(INPUT_CSS)
        self.old_box.currentIndexChanged.connect(lambda *_: self._refresh_fill())
        self.old_box.lineEdit().editingFinished.connect(self._refresh_fill)
        form.addLayout(_row("被替换的方块", [self.old_box]))

        self.mode_box = QtWidgets.QComboBox()
        self.mode_box.addItems(["/fill 直接填（原版指令）", "//replace 替换（WorldEdit）"])
        self.mode_box.setFixedWidth(250)
        self.mode_box.setStyleSheet(INPUT_CSS)
        self.mode_box.currentIndexChanged.connect(lambda *_: self._refresh_fill())
        form.addLayout(_row("方式", [self.mode_box]))

        self.vol_lbl = QtWidgets.QLabel("")
        self.vol_lbl.setWordWrap(True)
        self.vol_lbl.setStyleSheet("color:#9fe9dc;font-size:11.5px;")
        form.addWidget(self.vol_lbl)
        v.addWidget(card)

        prev = _card()
        pv = QtWidgets.QVBoxLayout(prev)
        pv.setContentsMargins(12, 10, 12, 10)
        pv.setSpacing(6)
        pt = QtWidgets.QLabel("预览")
        pt.setStyleSheet("font-size:12.5px;font-weight:700;color:#dff6ff;")
        pv.addWidget(pt)
        self.fill_view = QtWidgets.QPlainTextEdit()
        self.fill_view.setReadOnly(True)
        self.fill_view.setFixedHeight(64)
        self.fill_view.setStyleSheet(LIST_CSS + f"QPlainTextEdit{{font-family:{MONO};font-size:12px;}}")
        pv.addWidget(self.fill_view)

        prow = QtWidgets.QHBoxLayout()
        prow.addStretch(1)
        b_cp = QtWidgets.QPushButton("复制")
        b_cp.setCursor(Qt.PointingHandCursor)
        b_cp.setFixedHeight(28)
        b_cp.setStyleSheet(BTN_GHOST)
        b_cp.clicked.connect(lambda: self._copy_text(self.fill_view.toPlainText()))
        prow.addWidget(b_cp)
        b_sd = QtWidgets.QPushButton("发送")
        b_sd.setCursor(Qt.PointingHandCursor)
        b_sd.setFixedHeight(28)
        b_sd.setStyleSheet(BTN_PRIMARY)
        b_sd.clicked.connect(lambda: self._send_from(self.fill_view.toPlainText()))
        prow.addWidget(b_sd)
        pv.addLayout(prow)
        v.addWidget(prev, 0)

        note = QtWidgets.QLabel(
            "小技巧：游戏里按 F3 看坐标；WorldEdit 那档得先拿木斧左右各点一下选好区域，"
            "坐标框对 //replace 不起作用。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7d8fa3;font-size:11px;")
        v.addWidget(note)
        v.addStretch(1)

        self._refresh_fill()
        return page

    def _coord_edit(self, default: str) -> QtWidgets.QLineEdit:
        e = QtWidgets.QLineEdit(default)
        e.setFixedWidth(84)
        e.setAlignment(Qt.AlignCenter)
        e.setStyleSheet(INPUT_CSS + f"QLineEdit{{font-family:{MONO};}}")
        e.textChanged.connect(lambda *_: self._refresh_fill())
        return e

    def _fill_mode(self) -> str:
        return "replace" if self.mode_box.currentIndex() == 1 else "fill"

    def _block_id(self) -> str:
        data = self.block_box.currentData()
        text = self.block_box.currentText().strip()
        if data and "·" in text:
            return str(data)
        if text:
            return text if ":" in text else f"minecraft:{text}"
        return str(data or "minecraft:stone")

    def _old_id(self) -> str:
        data = self.old_box.currentData()
        text = self.old_box.currentText().strip()
        if data == "" or "留空" in text:
            return ""
        if data and "·" in text:
            return str(data)
        if text:
            return text if ":" in text else f"minecraft:{text}"
        return ""

    def _fill_text(self) -> Tuple[str, str, bool]:
        p1 = mccmd.parse_box(self.p1_edits[0].text() + " " + self.p1_edits[1].text() + " " + self.p1_edits[2].text())
        p2 = mccmd.parse_box(self.p2_edits[0].text() + " " + self.p2_edits[1].text() + " " + self.p2_edits[2].text())
        if not p1 or not p2:
            return "", "坐标得是整数（例：0 64 0），每一格都要填", False
        mode = self._fill_mode()
        cmd = mccmd.fill_command(p1, p2, self._block_id(), self._old_id(), mode=mode)
        vol = mccmd.box_volume(p1, p2)
        ok, advice = mccmd.fill_advice(vol, mode)
        return cmd, advice, ok

    def _refresh_fill(self) -> None:
        if self._suppress:
            return
        cmd, advice, ok = self._fill_text()
        self.fill_view.setPlainText(cmd)
        if cmd:
            color = "#9fe9dc" if ok else "#ffb3a6"
            self.vol_lbl.setStyleSheet(f"color:{color};font-size:11.5px;")
            prefix = "体积参考 · " if self._fill_mode() == "replace" else "体积 "
            self.vol_lbl.setText(prefix + advice)
        else:
            self.vol_lbl.setStyleSheet("color:#ffb3a6;font-size:11.5px;")
            self.vol_lbl.setText(advice)

    def _send_from(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.cmd_edit.setText(text)
        self._dispatch(text)

    # ---------------------------------------------------------------- 4 发送记录
    def _build_hist(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        self.hist_view = QtWidgets.QPlainTextEdit()
        self.hist_view.setReadOnly(True)
        self.hist_view.setStyleSheet(LIST_CSS + f"QPlainTextEdit{{font-family:{MONO};font-size:11.5px;}}")
        v.addWidget(self.hist_view, 1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        b_cp = QtWidgets.QPushButton("复制全部")
        b_cp.setCursor(Qt.PointingHandCursor)
        b_cp.setFixedHeight(28)
        b_cp.setStyleSheet(BTN_GHOST)
        b_cp.clicked.connect(lambda: self._copy_text(self.hist_view.toPlainText()))
        row.addWidget(b_cp)
        b_cl = QtWidgets.QPushButton("清空记录")
        b_cl.setCursor(Qt.PointingHandCursor)
        b_cl.setFixedHeight(28)
        b_cl.setStyleSheet(BTN_GHOST)
        b_cl.clicked.connect(self._clear_hist)
        row.addWidget(b_cl)
        b_ex = QtWidgets.QPushButton("导出 txt")
        b_ex.setCursor(Qt.PointingHandCursor)
        b_ex.setFixedHeight(28)
        b_ex.setStyleSheet(BTN_SOFT)
        b_ex.clicked.connect(self._export_hist)
        row.addWidget(b_ex)
        v.addLayout(row)

        self._render_hist()
        return page

    def _render_hist(self) -> None:
        if not self._hist:
            self.hist_view.setPlainText("还没有发送记录。发出去的每条都会记在这里（只在本次运行里，不落盘）。")
            return
        lines = []
        for stamp, cmd, ok, msg in self._hist:
            lines.append(f"{stamp}  {'✓' if ok else '✗'}  {cmd}")
            if not ok:
                lines.append(f"         └ {msg}")
        self.hist_view.setPlainText("\n".join(lines))

    def _clear_hist(self) -> None:
        self._hist.clear()
        self._render_hist()

    def _export_hist(self) -> None:
        if not self._hist:
            self.tip_lbl.setText("没有记录可导出")
            return
        text = self.hist_view.toPlainText()
        path, _sel = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出发送记录", "mc_commands.txt", "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            self.tip_lbl.setText("已导出：" + path.split("\\")[-1])
        except OSError as exc:
            self.tip_lbl.setText("导出失败：" + str(exc))

    # ---------------------------------------------------------------- 发送链路
    def _method(self) -> str:
        return "type" if self.method_box.currentIndex() == 1 else "paste"

    def _copy_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self.tip_lbl.setText("没东西可复制")
            return
        cb = QtWidgets.QApplication.clipboard()
        if cb is not None:
            cb.setText(text)
        self.tip_lbl.setText("已复制到剪贴板")

    def _copy_bar(self) -> None:
        self._copy_text(self.cmd_edit.text())

    def _send_bar(self) -> None:
        self._dispatch(self.cmd_edit.text())

    def _dispatch(self, cmd: str) -> bool:
        cmd = (cmd or "").strip()
        if not cmd:
            self.tip_lbl.setText("指令是空的")
            return False
        if cmd.startswith("//"):
            self.tip_lbl.setText("WorldEdit 的 // 指令要在游戏里装 WE 插件/模组才有效")
        danger, why = mccmd.is_dangerous(cmd)
        if danger:
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("确认发送")
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setText("这条会改动世界")
            box.setInformativeText(f"{cmd}\n\n{why}")
            yes = box.addButton("照样发", QtWidgets.QMessageBox.AcceptRole)
            box.addButton("算了", QtWidgets.QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                self.tip_lbl.setText("已取消")
                return False

        if self.chk_delay.isChecked():
            self.tip_lbl.setText("3 秒后发送…现在切到游戏窗口")
            QtCore.QTimer.singleShot(3000, lambda: self._do_send(cmd, activate=False))
            return True
        return self._do_send(cmd, activate=True)

    def _do_send(self, cmd: str, activate: bool) -> bool:
        ok, msg = ins.send_command(cmd, method=self._method(),
                                   enter=self.chk_enter.isChecked(),
                                   activate_window=activate)
        stamp = time.strftime("%H:%M:%S")
        self._hist.insert(0, (stamp, cmd, ok, msg))
        del self._hist[80:]
        self._render_hist()
        if ok:
            self.tip_lbl.setStyleSheet("color:#8dffd8;font-size:11.5px;")
        else:
            self.tip_lbl.setStyleSheet("color:#ffb3a6;font-size:11.5px;")
        self.tip_lbl.setText(msg)
        return ok

    # ---------------------------------------------------------------- 窗口
    def show_window(self) -> None:
        self._refresh_game()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()
