@echo off
chcp 65001 >nul

REM ===== 0) 이 배치파일이 있는 폴더로 이동 =====
cd /d "%~dp0"

REM ===== 1) 가상환경 활성화 (반드시 call 사용) =====
call "%cd%\venv\Scripts\activate.bat"

REM ===== 2) 파이썬 아키텍처 및 실행 파일 경로 확인 =====
python -c "import platform, sys; print(platform.architecture(), sys.executable)"

REM ===== 3) 현재 패키지 정보를 requirements.txt에 기록 =====
echo [INFO] requirements.txt에 패키지 정보를 기록합니다...
python -m pip freeze > "%~dp0requirements.txt"

REM ===== 4) 결과 확인용 일시정지 =====
pause
