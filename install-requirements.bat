@echo off
REM ===== 1) 가상환경 활성화 (반드시 call 사용) =====
call "C:\kiwoomautotrade\venv\Scripts\activate.bat"

REM ===== 2) 파이썬 아키텍처 확인 =====
python -c "import platform; print(platform.architecture())"

REM ===== 3) requirements.txt 설치 =====
REM requirements.txt가 이 배치파일(.bat)과 같은 폴더에 있다고 가정
python -m pip install -r "%~dp0requirements.txt"

REM ===== 4) 결과 확인용 일시정지 (원하면 삭제 가능) =====
pause
