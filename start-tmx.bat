@echo off
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

cd /d C:\Users\Pjitpila\TM-X\Backend-server
start "" cmd /c "..\.venv\Scripts\python.exe -u main_split.py >> C:\Users\Pjitpila\TM-X\logs\backend.log 2>&1"
start "" cmd /c "..\.venv\Scripts\python.exe -u Data-receiver.py >> C:\Users\Pjitpila\TM-X\logs\receiver.log 2>&1"
start "" cmd /c "..\.venv\Scripts\python.exe -u server_image.py >> C:\Users\Pjitpila\TM-X\logs\image.log 2>&1"

cd /d C:\Users\Pjitpila\TM-X\Backend-pc_station
start "" cmd /c "..\.venv\Scripts\python.exe -u Pi.py >> C:\Users\Pjitpila\TM-X\logs\pi.log 2>&1"