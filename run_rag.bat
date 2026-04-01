@echo off

echo Activating environment...
call D:\Download\Anaconda\Scripts\activate.bat rag_env

echo Starting backend...
start cmd /k "cd backend && python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"


echo Starting frontend...
start cmd /k "cd frontend && npm run dev"

timeout /t 3

start http://localhost:5173