@echo off
cd /d "%~dp0"

echo ==========================================
echo   强制恢复原生分辨率
echo ==========================================
echo.

if exist "App\游戏助手.exe" (
    "App\游戏助手.exe" --restore
    echo 已恢复原生分辨率。
) else (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" launcher.py --restore
    ) else (
        echo [错误] 找不到 App\游戏助手.exe
    )
)

echo.
timeout 4
