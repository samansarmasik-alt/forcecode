@echo off
setlocal
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 "%~dp0forgecode.py" %*
  exit /b %errorlevel%
)
where python >nul 2>nul
if %errorlevel% equ 0 (
  python "%~dp0forgecode.py" %*
  exit /b %errorlevel%
)
echo ForgeCode icin Python 3.10 veya yenisi gerekiyor.
echo https://www.python.org/downloads/
exit /b 1
