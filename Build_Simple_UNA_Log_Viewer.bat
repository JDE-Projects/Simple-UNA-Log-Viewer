@echo off
echo =====================================================
echo  Simple UNA Log Viewer - Build Script
echo =====================================================
echo.
echo Installing build + runtime dependencies...
pip install pyinstaller pywebview PyQt6 PyQt6-WebEngine
echo.
echo Building executable...
pyinstaller --onefile --windowed --name "Simple UNA Log Viewer" ^
  --icon "simple_una_log_viewer.ico" ^
  --splash "simple_una_log_viewer-splash.png" ^
  --add-data "simple_una_log_viewer-UI.html;." ^
  --add-data "simple_una_log_viewer.png;." ^
  --add-data "fonts;fonts" ^
  --collect-all PyQt6 ^
  --collect-all qtpy ^
  simple_una_log_viewer.py
echo.
echo =====================================================
echo  Done. Your .exe is in:  dist\Simple UNA Log Viewer.exe
echo =====================================================
echo.
pause
