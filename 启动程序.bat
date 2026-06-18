@echo off
chcp 65001 >nul
title QFXM 启动器

echo ========================================
echo   QFXM — Telegram 多账号群控系统
echo ========================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或以上版本
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b
)

:: 检查 .env 文件
if not exist ".env" (
    echo [提示] 未找到 .env 配置文件，正在从模板创建...
    copy .env.example .env >nul
    echo.
    echo [重要] 请用记事本打开 .env 文件，填入你的 API_ID 和 API_HASH
    echo        获取地址: https://my.telegram.org
    echo.
    notepad .env
    echo 填写完毕后请重新运行本程序。
    pause
    exit /b
)

:: 检查依赖是否安装
python -c "import pyrogram" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装依赖，首次运行需要等待几分钟...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络或使用代理
        pause
        exit /b
    )
    echo [成功] 依赖安装完毕
    echo.
)

echo [启动] 正在启动 QFXM...
python main.py

if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出，请查看 logs\qfxm.log 获取详细信息
    pause
)
