@echo off
chcp 65001 >nul
echo ====================================
echo  Dashboard de Promocoes
echo ====================================
echo.
echo Iniciando aplicacao...
echo URL: http://localhost:8501
echo Para parar: Ctrl+C
echo.
python -m streamlit run app_promocoes.py
pause
