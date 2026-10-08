# -*- coding: utf-8 -*-
"""
Configuração ÚNICA do log do programa (logs/gamificacao_sistema.log + tela).

[F-20] Antes cada módulo (o programa e o database.py) apagava os "handlers" do log e abria
OUTRO RotatingFileHandler para o MESMO arquivo. O primeiro ficava esquecido com o arquivo
aberto: no Windows, quando o log chegava a 10 MB, a troca de arquivo (renomear) falhava porque
o arquivo continuava em uso. Agora quem chega depois vê que o arquivo já está configurado
neste processo e não abre outro.
"""
import logging
import logging.handlers
import os
import sys

LOG_FILENAME = 'gamificacao_sistema.log'
LOG_FOLDER = 'logs'
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
LOG_MAX_BYTES = 10 * 1024 * 1024   # 10 MB por arquivo
LOG_BACKUP_COUNT = 5               # arquivos antigos guardados


def caminho_do_log():
    """logs/gamificacao_sistema.log ao lado do programa (ou na própria pasta, se não der para criar 'logs')."""
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_FOLDER)
    if not os.path.isdir(pasta):
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError as e:
            print(f"Erro ao criar pasta de logs '{pasta}': {e}", file=sys.stderr)
            pasta = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(pasta, LOG_FILENAME))


def configurar_log():
    """
    Liga o log do processo UMA vez. Se já existe um handler gravando no mesmo arquivo (de qualquer
    módulo), não faz nada. Senão tira os handlers antigos (FECHANDO cada um) e cria o arquivo
    rotativo + a saída na tela. Devolve o caminho do arquivo de log.
    """
    caminho = caminho_do_log()
    raiz = logging.getLogger('')
    for h in raiz.handlers:
        if os.path.abspath(getattr(h, 'baseFilename', '') or '') == caminho:
            return caminho
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    formato = logging.Formatter(LOG_FORMAT)
    arquivo = logging.handlers.RotatingFileHandler(caminho, maxBytes=LOG_MAX_BYTES,
                                                   backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    arquivo.setLevel(LOG_LEVEL)
    arquivo.setFormatter(formato)
    tela = logging.StreamHandler(sys.stdout)
    tela.setLevel(LOG_LEVEL)
    tela.setFormatter(formato)
    raiz.setLevel(LOG_LEVEL)
    raiz.addHandler(arquivo)
    raiz.addHandler(tela)
    return caminho
