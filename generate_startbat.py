"""生成 start.bat 的维护工具。

⚠️ 重要：start.bat 必须是 **GBK 编码**，不是 UTF-8。
   Windows cmd 按 GBK（系统 ANSI 代码页）解析 .bat 文件本身，
   若用 UTF-8 保存，其中的中文会被按 GBK 误解，导致命令行解析错误
   （典型现象：python 进了交互式 REPL、app.py 参数丢失）。
   chcp 65001 只改控制台输出页，不影响 cmd 解析 .bat 的编码，救不了。

因此：**不要用文本编辑器/UTF-8 工具直接编辑 start.bat**。
需要改动时，修改下方 content，然后运行 `python generate_startbat.py` 重新生成。
"""
content = r'''@echo off
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
'''

if __name__ == "__main__":
    with open("start.bat", "w", encoding="gbk") as f:
        f.write(content)
    print("已生成 GBK 编码的 start.bat（请勿用编辑器直接修改它，改本文件后重新运行此脚本）")
