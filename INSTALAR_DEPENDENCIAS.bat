@echo off
chcp 65001 >nul
title Instalador de Dependencias - Dashboard de Promocoes
echo.
echo ==================================================
echo   INSTALADOR DE DEPENDENCIAS
echo   Dashboard de Promocoes
echo ==================================================
echo.
echo Este script ira verificar e instalar todas as dependencias
echo necessarias para executar o Dashboard de Promocoes.
echo.

REM Verificar se Python está instalado
echo [1/5] Verificando Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ERRO: Python nao encontrado!
    echo.
    echo SOLUCAO:
    echo 1. Acesse: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    echo 2. Baixe a versao mais recente do Python
    echo 3. Durante a instalacao, MARQUE a opcao "Add Python to PATH"
    echo 4. Reinicie o computador apos a instalacao
    echo 5. Execute este script novamente
    echo.
    echo Pressione qualquer tecla para abrir o site do Python...
    pause >nul
    start https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    exit /b 1
)

echo ✅ Python encontrado
python --version

REM Verificar se pip está disponível
echo.
echo [2/5] Verificando pip...
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ pip nao encontrado! Tentando instalar...
    python -m ensurepip --upgrade
    if %errorlevel% neq 0 (
        echo ❌ ERRO: Nao foi possivel instalar o pip automaticamente
        echo.
        echo SOLUCAO:
        echo 1. Reinstale o Python com a opcao "Add Python to PATH"
        echo 2. Ou execute: python -m ensurepip --upgrade
        pause
        exit /b 1
    )
    echo ✅ pip instalado com sucesso
) else (
    echo ✅ pip encontrado
)

REM Atualizar pip
echo.
echo [3/5] Atualizando pip...
python -m pip install --upgrade pip --quiet
echo ✅ pip atualizado

REM Verificar se requirements.txt existe
echo.
echo [4/5] Verificando arquivo de dependencias...
if not exist "requirements.txt" (
    echo ⚠️  Arquivo requirements.txt nao encontrado!
    echo Criando arquivo de dependencias...
    (
        echo streamlit==1.31.0
        echo requests==2.31.0
        echo pandas==2.2.0
        echo openpyxl==3.1.2
    ) > requirements.txt
    echo ✅ Arquivo requirements.txt criado
) else (
    echo ✅ Arquivo requirements.txt encontrado
)

REM Instalar dependências
echo.
echo [5/5] Instalando dependencias...
echo.
echo Instalando bibliotecas necessarias...
echo (Isso pode levar alguns minutos na primeira execucao)
echo.

pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo ⚠️  AVISO: Algumas dependencias podem nao ter sido instaladas corretamente
    echo Tentando instalar dependencias individuais...
    echo.
    pip install streamlit==1.31.0
    pip install requests==2.31.0
    pip install pandas==2.2.0
    pip install openpyxl==3.1.2
)

echo.
echo ==================================================
echo   INSTALACAO CONCLUIDA COM SUCESSO!
echo ==================================================
echo.
echo ✅ Todas as dependencias foram instaladas
echo.
echo Agora voce pode executar:
echo - EXECUTAR_NORMAL.bat (Dashboard normal)
echo - EXECUTAR_HIERARQUICO.bat (Dashboard hierarquico)
echo.
echo Pressione qualquer tecla para sair...
pause >nul
