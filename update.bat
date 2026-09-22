@echo off
setlocal
cd /d "%~dp0"

echo ===== 기출문제 아카이브 업데이트 (증분) =====
echo.

python crawl.py
if errorlevel 1 (
    echo.
    echo [오류] 크롤링이 실패했습니다. 위 메시지를 확인하세요.
    pause
    exit /b 1
)

echo.
echo ---- 깃에 반영 ----
git add data.js
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "data.js 업데이트 (%date% %time%)"
    git push
    echo.
    echo ===== 완료: 사이트에 반영됐습니다 =====
) else (
    echo 바뀐 내용이 없습니다. 배포할 게 없어요.
)

pause
