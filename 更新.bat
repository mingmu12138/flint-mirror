@echo off
chcp 936 >nul
cd /d "%~dp0"
title 燧镜 一键更新

echo ==========================================
echo   燧镜 一键更新：打包 - 分发版 - 安装包
echo ==========================================
echo.

set "PY="
if exist ".venv313\Scripts\python.exe" set "PY=.venv313\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
)
if not defined PY (
    echo [错误] 找不到可用的 Python 环境，先装好依赖再试。
    pause
    exit /b 1
)
echo 用的解释器：%PY%
echo.

if not exist "assets\icon.ico" (
    echo [错误] 缺少 assets\icon.ico，打出来的 exe 没有图标。
    pause
    exit /b 1
)

echo [0/3] 同步版本号，只看 version.txt...
"%PY%" sync_version.py
if errorlevel 1 (
    echo.
    echo [失败] 版本号同步没通过，看一眼 version.txt。
    pause
    exit /b 1
)
echo [0/3] 完成。
echo.

echo [1/3] 打主程序，约 4-6 分钟...
"%PY%" -X utf8 -m PyInstaller --noconfirm --clean 燧镜.spec
if not exist "dist\燧镜\燧镜.exe" (
    echo.
    echo [失败] 没打出 dist\燧镜\燧镜.exe，往上翻日志找原因。
    pause
    exit /b 1
)
echo [1/3] 完成。
echo.

echo [2/3] 生成分发版（目录 + zip）...
"%PY%" -X utf8 build_dist.py
if not exist "分发版\燧镜\燧镜.exe" (
    echo [失败] 分发版没生成，看 build_dist.py 的输出。
    pause
    exit /b 1
)
echo [2/3] 完成。
echo.

echo [3/3] 生成安装包，约 2-4 分钟...
"%PY%" -X utf8 build_installer.py
dir /b "燧镜_v*_安装包.exe" >nul 2>&1
if errorlevel 1 (
    echo [失败] 安装包没生成，看 installer.nsi 的输出。
    pause
    exit /b 1
)
echo [3/3] 安装包完成。
echo.

for %%F in ("燧镜_v*_安装包.exe") do echo 安装包：%%~fF  %%~zF 字节
echo 分发版：%cd%\分发版\燧镜
echo.
echo 全部完成。
echo.
explorer .
pause
