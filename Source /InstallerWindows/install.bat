@echo off
setlocal EnableDelayedExpansion
title VRChat OSC Banner — Installer
color 0A

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║         VRChat OSC Banner  Installer             ║
echo  ║               by adam77461                       ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: ── Set paths ──
set "INSTALL_DIR=%LOCALAPPDATA%\VRChatOSCBanner"
set "APP_DIR=%INSTALL_DIR%\app"
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "PYTHON_INSTALLER=%INSTALL_DIR%\python_setup.exe"
set "MAIN_URL=https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/Source%%20/main.py"

where curl >nul 2>&1
if errorlevel 1 ( echo  [!] curl not found. Requires Windows 10 1803+. & pause & exit /b 1 )

echo  [1/5] Creating install directory...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%APP_DIR%"     mkdir "%APP_DIR%"
echo        %INSTALL_DIR%
echo.

:: ════════════════════════════════════════════
::  [2/5] Find a valid Python 3.10+
:: ════════════════════════════════════════════
echo  [2/5] Checking for Python 3.10+...
set "PYTHON_EXE="

:: Check well-known install paths first
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
) do (
    if exist %%p (
        if not defined PYTHON_EXE (
            call :check_version %%~p
        )
    )
)

:: Also scan PATH
if not defined PYTHON_EXE (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if not defined PYTHON_EXE call :check_version "%%i"
    )
)
if not defined PYTHON_EXE (
    for /f "delims=" %%i in ('where python3 2^>nul') do (
        if not defined PYTHON_EXE call :check_version "%%i"
    )
)

if defined PYTHON_EXE (
    echo        Using Python: %PYTHON_EXE%
    goto :install_deps
)

:: ── No valid Python found — install full Python 3.11 ──
echo        No Python 3.10+ found. Downloading full Python 3.11...
echo        (Includes tkinter and all standard modules)
echo.
curl -L --progress-bar "%PYTHON_URL%" -o "%PYTHON_INSTALLER%"
if errorlevel 1 ( echo  [!] Download failed. & pause & exit /b 1 )

echo        Installing Python 3.11...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_pip=1
if errorlevel 1 ( echo  [!] Python installation failed. & del "%PYTHON_INSTALLER%" 2>nul & pause & exit /b 1 )
del "%PYTHON_INSTALLER%"

:: Refresh PATH from registry
for /f "skip=2 tokens=3*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "PATH=%%a %%b;%PATH%"

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" (
    for /f "delims=" %%i in ('where python 2^>nul') do set "PYTHON_EXE=%%i"
)
echo        Python installed: %PYTHON_EXE%
echo.

:install_deps
:: ════════════════════════════════════════════
::  [3/5] Install packages
:: ════════════════════════════════════════════
echo  [3/5] Installing dependencies...
echo.
"%PYTHON_EXE%" -m pip install --upgrade pip --quiet
"%PYTHON_EXE%" -m pip install customtkinter python-osc
if errorlevel 1 ( echo  [!] pip install failed. & pause & exit /b 1 )

:: Verify all imports work
echo.
echo        Verifying imports...
"%PYTHON_EXE%" -c "import tkinter; import customtkinter; import pythonosc; print('        tkinter         OK'); print('        customtkinter   OK'); print('        python-osc      OK')"
if errorlevel 1 (
    echo.
    echo  [!] Import check failed. See error above.
    pause & exit /b 1
)
echo.

:: ════════════════════════════════════════════
::  [4/5] Download main.py
:: ════════════════════════════════════════════
echo  [4/5] Downloading VRChat OSC Banner...
curl -L --progress-bar "%MAIN_URL%" -o "%APP_DIR%\main.py"
if errorlevel 1 (
    echo  [!] GitHub download failed. Trying local fallback...
    set "BAT_DIR=%~dp0"
    if exist "%BAT_DIR%main.py" (
        copy "%BAT_DIR%main.py" "%APP_DIR%\main.py" >nul
        echo        Copied from local folder.
    ) else (
        echo  [!] main.py not found.
        pause & exit /b 1
    )
)
echo        main.py OK
echo.

:: ════════════════════════════════════════════
::  [5/5] Launcher + shortcuts
:: ════════════════════════════════════════════
echo  [5/5] Creating launcher and shortcuts...

set "LAUNCHER=%INSTALL_DIR%\Launch VRChat OSC Banner.bat"
(
echo @echo off
echo title VRChat OSC Banner
echo cd /d "%APP_DIR%"
echo "%PYTHON_EXE%" "%APP_DIR%\main.py"
echo if errorlevel 1 ^(
echo     echo.
echo     echo  [ERROR] App crashed. See error above.
echo     pause
echo ^)
) > "%LAUNCHER%"

set "SHORTCUT=%USERPROFILE%\Desktop\VRChat OSC Banner.lnk"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%LAUNCHER%'; $s.WorkingDirectory = '%APP_DIR%'; $s.Description = 'VRChat OSC Banner by adam77461'; $s.Save()"

set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\VRChat OSC Banner.lnk"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%START_MENU%'); $s.TargetPath = '%LAUNCHER%'; $s.WorkingDirectory = '%APP_DIR%'; $s.Description = 'VRChat OSC Banner by adam77461'; $s.Save()"

set "UNINSTALLER=%INSTALL_DIR%\Uninstall.bat"
(
echo @echo off
echo title Uninstall VRChat OSC Banner
echo echo Removing VRChat OSC Banner...
echo rd /s /q "%INSTALL_DIR%"
echo del "%SHORTCUT%" 2^>nul
echo del "%START_MENU%" 2^>nul
echo echo Done.
echo pause
) > "%UNINSTALLER%"

echo        Desktop shortcut created
echo        Start Menu entry created
echo.

echo  ╔══════════════════════════════════════════════════╗
echo  ║  Installation complete!                          ║
echo  ║                                                  ║
echo  ║  ✓ Desktop shortcut created                      ║
echo  ║  ✓ Start Menu entry created                      ║
echo  ║                                                  ║
echo  ║  Launch from Desktop or search Start Menu for    ║
echo  ║  "VRChat OSC Banner"                             ║
echo  ╚══════════════════════════════════════════════════╝
echo.

set /p LAUNCH="  Launch now? (Y/N): "
if /i "%LAUNCH%"=="Y" call "%LAUNCHER%"

echo.
echo  To uninstall: %UNINSTALLER%
echo.
pause
endlocal
goto :eof

:: ════════════════════════════════════════════
::  Subroutine: check if a python.exe is 3.10+
::  Sets PYTHON_EXE if valid, skips if not
:: ════════════════════════════════════════════
:check_version
set "_candidate=%~1"
if not exist "%_candidate%" goto :eof

:: Skip the Windows Store stub — it lives in WindowsApps and just opens the Store
echo "%_candidate%" | findstr /i "WindowsApps" >nul 2>&1
if not errorlevel 1 (
    echo        Skipping — Windows Store stub ^(not a real Python^)
    goto :eof
)

:: Also detect Store stub by checking if it exits with code 9009 (store redirect)
"%_candidate%" --version >nul 2>&1
if errorlevel 9009 (
    echo        Skipping — Windows Store stub ^(returned 9009^)
    goto :eof
)

:: Get version string
set "_ver="
for /f "tokens=2 delims= " %%v in ('"%_candidate%" --version 2^>^&1') do (
    set "_ver=%%v"
)

:: If version is empty, it's probably the Store stub silently failing
if not defined _ver (
    echo        Skipping — could not get version ^(likely Store stub^)
    goto :eof
)

:: Extract major and minor
for /f "tokens=1,2 delims=." %%a in ("!_ver!") do (
    set "_major=%%a"
    set "_minor=%%b"
)

echo        Found Python !_ver! at %_candidate%

if !_major! LSS 3 (
    echo        Skipping — too old ^(need 3.10+^)
    goto :eof
)
if !_major! EQU 3 if !_minor! LSS 10 (
    echo        Skipping — too old ^(need 3.10+^)
    goto :eof
)

:: Passed all checks
set "PYTHON_EXE=%_candidate%"
goto :eof
