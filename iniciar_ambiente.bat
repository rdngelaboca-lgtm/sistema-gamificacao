@echo off
REM Esta linha desativa a exibição dos próprios comandos, deixando o terminal mais limpo.

REM Define um título útil para a janela do terminal que será aberta.
title Gamificacao DEV (Python 3.12 - C:\dev)

REM O comando mais importante! Ele muda o diretório para a pasta onde o .bat está.
REM %~dp0 é uma variável especial que significa "o Drive e o Path (caminho) deste script".
REM Isso garante que o script funcione não importa onde a pasta do projeto esteja.
cd /d "%~dp0"

REM Inicia uma NOVA janela de terminal, executa o comando de ativação e a mantém aberta.
REM /K (Keep) diz ao terminal para executar o comando e depois permanecer aberto para usarmos.
start "Gamificacao DEV" cmd /K "venv_gamificacao\Scripts\activate.bat"