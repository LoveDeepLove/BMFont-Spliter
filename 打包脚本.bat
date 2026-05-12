@echo off
chcp 65001 >nul
echo ==========================================
echo     BMFont 拆分工具 - 自动打包脚本
echo ==========================================
echo.

set /p version=请输入版本号 (例如 1.0.0): 

if "%version%"=="" (
    echo 错误：版本号不能为空！
    pause
    exit /b 1
)

echo.
echo 正在使用版本号 v%version% 进行打包...
echo.

pyinstaller --noconfirm --clean --onefile --windowed -n "BMFont拆分工具v%version%" main.py

if %errorlevel% neq 0 (
    echo.
    echo 打包失败！请检查是否已安装 pyinstaller。
    echo 建议在 PyCharm Terminal 中执行：pip install pyinstaller
    pause
    exit /b 1
)

echo.
echo ==========================================
echo 打包成功！
echo 可执行文件：dist\BMFont拆分工具v%version%.exe
echo ==========================================
echo.
pause
