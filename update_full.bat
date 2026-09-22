@echo off
setlocal
cd /d "%~dp0"

echo ===== 기출문제 아카이브 업데이트 (전체 다시 훑기) =====
echo 삭제/이동/이름바꾸기까지 반영하고 싶을 때 가끔 이걸로 실행하세요.
echo 파일이 많아서 몇 분 걸릴 수 있습니다.
echo.

python crawl.py --full
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
    git commit -m "data.js 전체 업데이트 (%date% %time%)"
    git push
    echo.
    echo ===== 완료: 사이트에 반영됐습니다 =====
) else (
    echo 바뀐 내용이 없습니다. 배포할 게 없어요.
)

pause
