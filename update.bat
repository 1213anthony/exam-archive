@echo off
setlocal
cd /d "%~dp0"

echo ===== exam-archive update (incremental) =====
echo.

python crawl.py
if errorlevel 1 (
    echo.
    echo [ERROR] crawl.py failed. Check the messages above.
    pause
    exit /b 1
)

echo.
echo ---- git ----
git add data.js
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "update data.js"
    git push
    echo.
    echo ===== done: pushed to the site =====
) else (
    echo Nothing changed - nothing to deploy.
)

pause
