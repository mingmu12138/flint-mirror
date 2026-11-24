# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('soundcard')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('comtypes')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# 音乐页的内嵌浏览器登录窗要用 WebEngine，三件套必须收全，
# 少一个装到别人机器上就是白窗或者直接闪退。
for _mod in ('PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
             'PySide6.QtWebChannel'):
    _r = collect_all(_mod)
    datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]

# 内置模组（mods\_builtin）自带的依赖跟着模组目录走：assets\pylibs 由宿主在导入
# main.py 之前挂进 sys.path，不进 _internal。宿主本身只提供接口，不为某个模组改变体积。
# QtMultimediaWidgets 本来就在 PySide6 的收集里，不用单独声明。

# 打包版自身没 import 过 sqlite3，PyInstaller 就不会收 _sqlite3.pyd；
# 内置的「平台视频」用 yt-dlp 读浏览器 cookie 时要它（那边有兜底，但能收就收上）。
hiddenimports += ['sqlite3']

# yt-dlp 是运行时才从模组 pylibs 挂进来的动态代码，静态分析看不见它的 import。
# 它解析页面要用 html.parser（连带 _markupbase、html.entities），自身没 import 过就收不全，
# 表现是模组里报 ModuleNotFoundError: No module named 'html.parser'。
hiddenimports += ['html', 'html.parser', 'html.entities', '_markupbase']


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='燧镜',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['assets/icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='燧镜',
)
