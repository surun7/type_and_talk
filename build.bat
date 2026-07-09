@echo off
REM ======================================================
REM Build TNT executable locally with PyInstaller
REM ======================================================
echo ===== Building Type and Talk (TNT) =====
echo.

REM 1. Install dependencies
echo [1/4] Installing Python dependencies...
pip install -e ".[dev]" -q
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: pip install failed
    exit /b 1
)

REM Optional: CPU-only PyTorch
echo.
echo NOTE: If you haven't installed torch yet, run:
echo   pip install torch --index-url https://download.pytorch.org/whl/cpu
echo.

REM 2. Install PyInstaller
echo [2/4] Installing PyInstaller...
pip install pyinstaller -q
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PyInstaller install failed
    exit /b 1
)

REM 3. Run PyInstaller
echo [3/4] Building executable (this may take 2-5 minutes)...
pyinstaller --clean build.spec
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Build failed
    exit /b 1
)

REM 4. Done
echo.
echo [4/4] Done!
echo ============================
echo Output:
echo   GUI:     dist\tnt.exe
echo   CLI:     dist\tnt-cli.exe
echo.
echo Total size: 
dir /s dist\tnt.exe dist\tnt-cli.exe 2>nul | findstr "File(s)"
echo ============================
pause
