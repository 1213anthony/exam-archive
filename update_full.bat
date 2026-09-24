@echo off
setlocal
cd /d "%~dp0"

echo ===== exam-archive update (FULL re-crawl) =====
echo Use this once in a while to catch deletes/moves/renames.
echo This can take a few minutes.
echo.

python crawl.py --full
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
    git commit -m "update data.js (full re-crawl)"
    git push
    if errorlevel 1 (
        echo Remote has newer commits - merging and retrying...
        git pull --rebase -X theirs
        git push
    )
    echo.
    echo ===== done: pushed to the site =====
) else (
    echo Nothing changed - nothing to deploy.
)

pause
