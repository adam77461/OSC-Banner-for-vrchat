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

:: ── Set install directory ──
set "INSTALL_DIR=%LOCALAPPDATA%\VRChatOSCBanner"
set "PYTHON_DIR=%INSTALL_DIR%\python"
set "APP_DIR=%INSTALL_DIR%\app"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PIP_EXE=%PYTHON_DIR%\Scripts\pip.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "MAIN_URL=https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/Source%%20/main.py"

:: ── Check for required tools ──
where curl >nul 2>&1
if errorlevel 1 (
    echo  [!] curl not found. Please install it or use Windows 10 1803+
    pause & exit /b 1
)
where powershell >nul 2>&1
if errorlevel 1 (
    echo  [!] PowerShell not found.
    pause & exit /b 1
)

echo  [1/6] Creating install directory...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"
if not exist "%APP_DIR%" mkdir "%APP_DIR%"
echo        %INSTALL_DIR%
echo.

:: ── Download embedded Python ──
echo  [2/6] Downloading Python 3.11 (embedded)...
set "PY_ZIP=%INSTALL_DIR%\python.zip"
curl -L --progress-bar "%PYTHON_URL%" -o "%PY_ZIP%"
if errorlevel 1 (
    echo  [!] Failed to download Python. Check your internet connection.
    pause & exit /b 1
)

echo  Extracting Python...
powershell -Command "Expand-Archive -Force '%PY_ZIP%' '%PYTHON_DIR%'"
del "%PY_ZIP%"
echo        Done.
echo.

:: ── Enable pip in embedded Python ──
echo  [3/6] Configuring Python...

:: Find and fix the ._pth file — uncomment 'import site'
for %%f in ("%PYTHON_DIR%\python*._pth") do (
    echo        Patching: %%f
    powershell -Command "(Get-Content '%%f') -replace '#import site','import site' | Set-Content '%%f'"
    echo        Verifying patch...
    powershell -Command "if ((Get-Content '%%f') -match 'import site') { Write-Host '        import site OK' } else { Write-Host '        WARNING: patch may have failed' }"
)

:: Also manually append Scripts to PATH so pip works
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PATH%"

set "GET_PIP=%INSTALL_DIR%\get-pip.py"
curl -L --progress-bar "%GET_PIP_URL%" -o "%GET_PIP%"
"%PYTHON_EXE%" "%GET_PIP%"
if errorlevel 1 (
    echo  [!] pip installation failed.
    pause & exit /b 1
)
del "%GET_PIP%"
echo        pip installed.
echo.

:: ── Install dependencies ──
echo  [4/6] Installing dependencies...
echo        This may take a minute...
echo.
"%PIP_EXE%" install customtkinter python-osc
if errorlevel 1 (
    echo  [!] Failed to install dependencies.
    pause & exit /b 1
)
echo        customtkinter   OK
echo        python-osc      OK
echo.

:: ── Verify imports work ──
echo        Verifying installation...
"%PYTHON_EXE%" -c "import customtkinter; import pythonosc; print('        imports OK')"
if errorlevel 1 (
    echo.
    echo  [!] Import verification failed.
    echo      The packages installed but Python cannot find them.
    echo      This is a known embedded Python issue.
    echo      Trying fix...
    echo.
    :: Force add site-packages to python path via .pth
    for %%f in ("%PYTHON_DIR%\python*._pth") do (
        echo %PYTHON_DIR%\Lib\site-packages>> "%%f"
        echo        Added site-packages path to %%f
    )
    :: Retry
    "%PYTHON_EXE%" -c "import customtkinter; import pythonosc; print('        imports OK after fix')"
    if errorlevel 1 (
        echo  [!] Still failing. Installation cannot continue.
        echo      Please report this issue on GitHub.
        pause & exit /b 1
    )
)
echo.

:: ── Download app files ──
echo  [5/6] Downloading VRChat OSC Banner...
curl -L --progress-bar "%MAIN_URL%" -o "%APP_DIR%\main.py"
if errorlevel 1 (
    echo.
    echo  [!] Could not download main.py from GitHub.
    echo      Trying local fallback...
    goto :copy_local
)
goto :create_launcher

:copy_local
set "BAT_DIR=%~dp0"
if exist "%BAT_DIR%main.py" (
    copy "%BAT_DIR%main.py" "%APP_DIR%\main.py" >nul
    echo        Copied main.py from local folder.
) else (
    echo  [!] main.py not found. Place main.py next to this installer.
    pause & exit /b 1
)

:create_launcher
echo.

:: ── Create launcher that stays open on error ──
echo  [6/6] Creating launcher and shortcuts...

set "LAUNCHER=%INSTALL_DIR%\Launch VRChat OSC Banner.bat"
(
echo @echo off
echo title VRChat OSC Banner
echo cd /d "%APP_DIR%"
echo echo Starting VRChat OSC Banner...
echo echo.
echo "%PYTHON_EXE%" "%APP_DIR%\main.py"
echo if errorlevel 1 ^(
echo     echo.
echo     echo  [ERROR] App crashed. See error above.
echo     pause
echo ^)
) > "%LAUNCHER%"

:: Desktop shortcut
set "SHORTCUT=%USERPROFILE%\Desktop\VRChat OSC Banner.lnk"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%LAUNCHER%'; $s.WorkingDirectory = '%APP_DIR%'; $s.Description = 'VRChat OSC Banner by adam77461'; $s.Save()"

:: Start Menu shortcut
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\VRChat OSC Banner.lnk"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%START_MENU%'); $s.TargetPath = '%LAUNCHER%'; $s.WorkingDirectory = '%APP_DIR%'; $s.Description = 'VRChat OSC Banner by adam77461'; $s.Save()"

echo        Desktop shortcut created
echo        Start Menu entry created
echo.

:: ── Create uninstaller ──
set "UNINSTALLER=%INSTALL_DIR%\Uninstall.bat"
(
echo @echo off
echo title Uninstall VRChat OSC Banner
echo echo Removing VRChat OSC Banner...
echo rd /s /q "%INSTALL_DIR%"
echo del "%SHORTCUT%" 2^>nul
echo del "%START_MENU%" 2^>nul
echo echo Done. VRChat OSC Banner has been removed.
echo pause
) > "%UNINSTALLER%"

:: ── Done ──
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║  Installation complete!                          ║
echo  ║                                                  ║
echo  ║  ✓ Desktop shortcut created                      ║
echo  ║  ✓ Start Menu entry created                      ║
echo  ║                                                  ║
echo  ║  Launch from your Desktop or search              ║
echo  ║  "VRChat OSC Banner" in Start Menu               ║
echo  ╚══════════════════════════════════════════════════╝
echo.

set /p LAUNCH="  Launch VRChat OSC Banner now? (Y/N): "
if /i "%LAUNCH%"=="Y" (
    call "%LAUNCHER%"
)

echo.
echo  To uninstall, run: %UNINSTALLER%
echo.
pause
endlocal
