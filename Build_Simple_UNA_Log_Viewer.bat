@echo off
echo =====================================================
echo  Simple UNA Log Viewer - Build Script
echo =====================================================
echo.
echo Ensuring the LGPL Qt binding is the one bundled...
pip uninstall -y PyQt6 PyQt6-WebEngine PyQt6-Qt6 PyQt6-sip >nul 2>&1
echo.
echo Installing build + runtime dependencies...
pip install pywebview PySide6 pyinstaller
echo.
echo Building executable (onedir, so the bundled Qt stays replaceable)...
set QT_API=pyside6
pyinstaller --onedir --windowed --name "Simple UNA Log Viewer" ^
  --icon "simple_una_log_viewer.ico" ^
  --splash "simple_una_log_viewer-splash.png" ^
  --add-data "simple_una_log_viewer-UI.html;." ^
  --add-data "simple_una_log_viewer.png;." ^
  --add-data "fonts;fonts" ^
  --collect-all PySide6 ^
  --collect-all qtpy ^
  simple_una_log_viewer.py
echo.
echo =====================================================
echo  Done. Your app folder is in:
echo    dist\Simple UNA Log Viewer\
echo  Run:  dist\Simple UNA Log Viewer\Simple UNA Log Viewer.exe
echo =====================================================
echo.
pause
