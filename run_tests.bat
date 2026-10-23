@echo off
rem Runs the automated tests (headless, no window appears). Takes a few minutes.
cd /d "%~dp0"
set PYTHONWARNINGS=ignore
for %%T in (test_matrix test_bulk test_meta) do (
    echo === %%T
    python tests\%%T.py
    if errorlevel 1 (
        echo %%T FAILED
        pause
        exit /b 1
    )
)
echo All tests passed.
pause
