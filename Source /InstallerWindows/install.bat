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

:: ── Check curl ──
where curl >nul 2>&1
if errorlevel 1 (
    echo  [!] curl not found. Requires Windows 10 1803 or later.
    pause & exit /b 1
)

echo  [1/5] Creating install directory...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%APP_DIR%"     mkdir "%APP_DIR%"
echo        %INSTALL_DIR%
echo.

:: ── Check if Python 3 already installed ──
echo  [2/5] Checking for Python...
set "PYTHON_EXE="

:: Check common install locations
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python311\python.exe"
    "C:\Python312\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist %%p (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%~p"
    )
)

:: Also try PATH
if not defined PYTHON_EXE (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%i in ('where python 2^>nul') do (
            if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
        )
    )
)

if defined PYTHON_EXE (
    echo        Found Python at: %PYTHON_EXE%
    "%PYTHON_EXE%" --version
    goto :install_deps
)

:: ── Install full Python ──
echo        Python not found. Downloading full Python 3.11...
echo        (This includes tkinter and all standard modules)
echo.
curl -L --progress-bar "%PYTHON_URL%" -o "%PYTHON_INSTALLER%"
if errorlevel 1 (
    echo  [!] Failed to download Python installer.
    pause & exit /b 1
)

echo        Installing Python 3.11 (user install, no admin needed)...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_pip=1
if errorlevel 1 (
    echo  [!] Python installation failed.
    del "%PYTHON_INSTALLER%" 2>nul
    pause & exit /b 1
)
del "%PYTHON_INSTALLER%"

:: Reload PATH so python is findable
set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" (
    :: Try refreshing PATH from registry
    for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USERPATH=%%b"
    set "PATH=%USERPATH%;%PATH%"
    for /f "delims=" %%i in ('where python 2^>nul') do set "PYTHON_EXE=%%i"
)

echo        Python installed: %PYTHON_EXE%
echo.

:install_deps
echo  [3/5] Installing dependencies...
echo        customtkinter, python-osc...
echo.

"%PYTHON_EXE%" -m pip install --upgrade pip --quiet
"%PYTHON_EXE%" -m pip install customtkinter python-osc
if errorlevel 1 (
    echo  [!] Failed to install packages.
    pause & exit /b 1
)

:: Verify
"%PYTHON_EXE%" -c "import tkinter; import customtkinter; import pythonosc; print('        All imports OK')"
if errorlevel 1 (
    echo  [!] Import check failed — see error above.
    pause & exit /b 1
)
echo.

:: ── Download main.py ──
echo  [4/5] Downloading VRChat OSC Banner...
curl -L --progress-bar "%MAIN_URL%" -o "%APP_DIR%\main.py"
if errorlevel 1 (
    echo  [!] Download from GitHub failed. Trying local fallback...
    set "BAT_DIR=%~dp0"
    if exist "%BAT_DIR%main.py" (
        copy "%BAT_DIR%main.py" "%APP_DIR%\main.py" >nul
        echo        Copied main.py from local folder.
    ) else (
        echo  [!] main.py not found.
        pause & exit /b 1
    )
)
echo        main.py downloaded.
echo.

:: ── Save Python path for launcher ──
echo %PYTHON_EXE%> "%INSTALL_DIR%\python_path.txt"

:: ── Create launcher ──
echo  [5/5] Creating launcher and shortcuts...

set "LAUNCHER=%INSTALL_DIR%\Launch VRChat OSC Banner.bat"
(
echo @echo off
echo title VRChat OSC Banner
echo cd /d "%APP_DIR%"
echo echo Starting VRChat OSC Banner...
echo "%PYTHON_EXE%" "%APP_DIR%\main.py"
echo if errorlevel 1 ^(
echo     echo.
echo     echo  [ERROR] App exited with an error. See above.
echo     pause
echo ^)
) > "%LAUNCHER%"

:: Desktop shortcut
set "SHORTCUT=%USERPROFILE%\Desktop\VRChat OSC Banner.lnk"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%LAUNCHER%'; $s.WorkingDirectory = '%APP_DIR%'; $s.Description = 'VRChat OSC Banner by adam77461'; $s.Save()"

:: Start Menu shortcut
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\VRChat OSC Banner.lnk"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%START_MENU%'); $s.TargetPath = '%LAUNCHER%'; $s.WorkingDirectory = '%APP_DIR%'; $s.Description = 'VRChat OSC Banner by adam77461'; $s.Save()"

:: Uninstaller
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

:: ── Done ──
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
