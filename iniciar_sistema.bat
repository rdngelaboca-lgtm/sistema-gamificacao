@echo off
TITLE Sistema de Gamificacao - Lancador Principal

ECHO.
ECHO  ================================================
ECHO      INICIANDO SISTEMA DE GAMIFICACAO
ECHO  ================================================
ECHO.
ECHO [1/4] Ativando o ambiente virtual Python...
CALL venv_gamificacao\Scripts\activate.bat

ECHO [2/4] Iniciando os componentes do sistema...
ECHO       - Interface do Gestor (main.py)
ECHO       - Modulo de Comunicados (comunicados_main.py)
ECHO.

start "Interface do Gestor" cmd /k python main.py
start "Gestão de Pessoas" cmd /k python gestao_pessoas_main.py

ECHO [3/4] Todos os componentes foram iniciados em janelas separadas.
ECHO [4/4] Esta janela pode ser fechada.