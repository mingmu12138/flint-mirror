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

# 扩展包（.sjmod）的依赖一律不进安装包：宿主只提供接口，包体积不为某一个模组让步。
# 「平台视频」那类要下视频的模组，yt-dlp / ffmpeg 都由模组自己解决（它现在会先找
# 系统 PATH，找不到就提示用户把 ffmpeg.exe 放进自己的数据目录）。
# QtMultimediaWidgets 本来就在 PySide6 的收集里，不用单独声明。


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
