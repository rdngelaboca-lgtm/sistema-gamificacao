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
ECHO       - Bot do Telegram (telegram_bot.py)
ECHO       - Agendador de Tarefas (agendador.py)
ECHO.

start "Interface do Gestor" cmd /k python main.py
start "Modulo de Comunicados" cmd /k python comunicados_main.py
start "Bot do Telegram" cmd /k python telegram_bot.py
start "Agendador de Tarefas" cmd /k python agendador.py

ECHO [3/4] Todos os componentes foram iniciados em janelas separadas.
ECHO [4/4] Esta janela pode ser fechada.