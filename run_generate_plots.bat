@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Edit this list to choose which countries/regions to regenerate.
set "COUNTRIES=England Australia Germany France Canada Japan"

set "PYTHON_EXE=C:\Users\Zack\AppData\Local\Programs\Python\Python314\python.exe"
set "FINAL_DIR=C:\Users\Zack\Documents\ToR\final"
set "GENERATE_PLOTS=%FINAL_DIR%\publish\generate_plots.py"
set "SOURCE_PLOTS=%FINAL_DIR%\plots\Spike"
set "WEBAPP_PLOTS=%~dp0plots\Spike"

if not exist "%PYTHON_EXE%" (
  echo Python executable not found: "%PYTHON_EXE%"
  exit /b 1
)

if not exist "%GENERATE_PLOTS%" (
  echo generate_plots.py not found: "%GENERATE_PLOTS%"
  exit /b 1
)

if not exist "%WEBAPP_PLOTS%" (
  mkdir "%WEBAPP_PLOTS%"
)

pushd "%FINAL_DIR%" || exit /b 1

for %%C in (%COUNTRIES%) do (
  echo.
  echo ===== Generating plots for %%C =====
  "%PYTHON_EXE%" "%GENERATE_PLOTS%" %%C
  if errorlevel 1 (
    echo generate_plots.py failed for %%C
    popd
    exit /b 1
  )

  if not exist "%SOURCE_PLOTS%\%%C" (
    echo Expected output directory not found: "%SOURCE_PLOTS%\%%C"
    popd
    exit /b 1
  )

  echo Moving "%SOURCE_PLOTS%\%%C" to "%WEBAPP_PLOTS%\%%C"
  if exist "%WEBAPP_PLOTS%\%%C" (
    rmdir /s /q "%WEBAPP_PLOTS%\%%C"
  )
  move "%SOURCE_PLOTS%\%%C" "%WEBAPP_PLOTS%\%%C" >nul
  if errorlevel 1 (
    echo Failed to move plots for %%C into the webapp directory.
    popd
    exit /b 1
  )
)

popd
echo.
echo All requested countries were regenerated and moved into "%WEBAPP_PLOTS%".
