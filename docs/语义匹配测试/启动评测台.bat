@echo off
setlocal
cd /d "%~dp0"

rem 端口可以用第一个参数改：启动评测台.bat 8766
set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"
set "EVAL_APP_PORT=%PORT%"

rem ---- 找 Python ----
set "PY="
if exist "C:\Python314\python.exe" set "PY=C:\Python314\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
  echo.
  echo   [X] 找不到 Python。
  echo       去 python.org 装一个 3.11 以上版本，安装时务必勾选 "Add python.exe to PATH"。
  echo.
  pause
  exit /b 1
)

rem ---- 端口已被占用就别再起一份 ----
netstat -ano | findstr ":%PORT%" | findstr LISTENING >nul
if not errorlevel 1 (
  echo.
  echo   [!] %PORT% 端口已经有人在监听 —— 评测台多半已经在跑了。
  echo       正在打开浏览器。如果打开的不是评测台，换个端口重来：
  echo         启动评测台.bat 8766
  echo.
  start "" "http://127.0.0.1:%PORT%"
  pause
  exit /b 0
)

rem ---- 缺依赖就补（走阿里云源，直连 pypi 会间歇性抓不到索引页） ----
"%PY%" -c "import fastapi, uvicorn, openai" 2>nul
if errorlevel 1 (
  echo.
  echo   首次运行，正在安装 fastapi / uvicorn / openai ...
  "%PY%" -m pip install -q fastapi uvicorn openai -i https://mirrors.aliyun.com/pypi/simple/
  if errorlevel 1 (
    echo.
    echo   [X] 依赖没装上。检查一下网络，或者手动跑：
    echo       "%PY%" -m pip install fastapi uvicorn openai
    echo.
    pause
    exit /b 1
  )
)

echo.
echo   Python : %PY%
echo   地址   : http://127.0.0.1:%PORT%
echo   浏览器会自动打开。要停服务，关掉这个窗口或按 Ctrl+C。
echo.
"%PY%" app.py

echo.
echo   服务已停止。
pause
