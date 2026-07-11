@echo off
title Eat_stat - 校园卡消费统计
cd /d "%~dp0"

echo ============================================
echo    清华校园卡消费统计程序  Eat_stat
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
    goto :run
)
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    goto :run
)

echo [错误] 未检测到 Python。
echo 请先安装 Python 3.8 及以上版本:
echo     https://www.python.org/downloads/
echo 安装时务必勾选 "Add Python to PATH"。
echo.
pause
exit /b 1

:run
echo 正在检查 / 安装依赖(首次较慢,请稍候)...
"%PY%" -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败,请检查网络后重试。
    pause
    exit /b 1
)
echo.
echo 依赖就绪,启动中... 浏览器将自动打开 http://127.0.0.1:5000
echo (若未自动打开,请手动访问该地址)
echo 关闭此窗口即可停止程序。
echo.
"%PY%" app.py
pause
