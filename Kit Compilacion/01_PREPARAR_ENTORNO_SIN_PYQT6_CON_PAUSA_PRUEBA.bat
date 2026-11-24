@echo off
setlocal
cd /d "%~dp0"
title Kalaka's Soft - Preparar entorno SIN PyQt6

echo.
echo ===========================================
echo   KALAKA'S SOFT - ENTORNO SIN PYQT6
echo ===========================================
echo.

if not exist "requirements-compilacion.txt" (
    echo ERROR: Falta requirements-compilacion.txt en esta carpeta.
    goto error
)

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv ".venv"
    ) else (
        python -m venv ".venv"
    )
    if errorlevel 1 goto error
)

echo.
echo Actualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error

echo.
echo Instalando dependencias de compilacion...
".venv\Scripts\python.exe" -m pip install -r "requirements-compilacion.txt" openpyxl
if errorlevel 1 goto error

echo.
echo Comprobando dependencias (SIN PyQt6)...
".venv\Scripts\python.exe" -c "import PyInstaller, PIL, truststore, openpyxl; print('Entorno OK: PyInstaller, Pillow, truststore, openpyxl')"
if errorlevel 1 goto error

echo.
echo LISTO. Entorno preparado para compilar sin PyQt6.
echo NOTA: Si ya existia PyQt6 en el entorno, este BAT no lo desinstala.
pause
exit /b 0

:error
echo.
echo ERROR: No se pudo preparar el entorno.
echo Revisar el mensaje anterior, Python, dependencias y conexion a Internet.
pause
exit /b 1
