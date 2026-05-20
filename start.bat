@echo off
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting Trading News Dashboard...
echo Open http://localhost:8000 in your browser
echo.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
