@echo off
chcp 65001 >nul
title Dashboard Promocoes - Layout Hierarquico
echo ==================================================
echo   DASHBOARD DE PROMOCOES - LAYOUT HIERARQUICO
echo ==================================================
echo.

REM Verificar se Python está disponível
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ERRO: Python nao encontrado!
    echo.
    echo SOLUCAO:
    echo 1. Execute: INSTALAR_DEPENDENCIAS.bat
    echo 2. Ou execute: INSTALAR_E_EXECUTAR_HIERARQUICO.bat
    echo.
    pause
    exit /b 1
)

REM Verificar se Streamlit está instalado
python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ERRO: Streamlit nao encontrado!
    echo.
    echo SOLUCAO:
    echo 1. Execute: INSTALAR_DEPENDENCIAS.bat
    echo 2. Ou execute: INSTALAR_E_EXECUTAR_HIERARQUICO.bat
    echo.
    pause
    exit /b 1
)

echo ✅ Verificacoes concluidas com sucesso!
echo.
echo Iniciando aplicacao...
echo URL: http://localhost:8502
echo Para parar: Ctrl+C
echo ==================================================
echo.

python -m streamlit run app_promocoes_hierarquico.py --server.port 8502 --server.headless false

if %errorlevel% neq 0 (
    echo.
    echo ❌ ERRO: Falha ao executar o dashboard!
    echo.
    echo POSSIVEIS SOLUCOES:
    echo 1. Execute: INSTALAR_DEPENDENCIAS.bat
    echo 2. Execute: INSTALAR_E_EXECUTAR_HIERARQUICO.bat
    echo 3. Execute: REINSTALAR_PYTHON_COMPLETO.bat
    echo 4. Verifique se a porta 8502 esta disponivel
    echo.
)

pause
