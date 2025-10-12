# file_utils.py
# Este módulo conterá funções úteis para manipulação de arquivos.

import os
import subprocess
import platform

def abrir_arquivo(filepath):
    """
    Abre um arquivo com o aplicativo padrão do sistema operacional.
    Funciona em Windows, MacOS e Linux.
    """
    try:
        if platform.system() == 'Darwin':       # macOS
            subprocess.call(('open', filepath))
        elif platform.system() == 'Windows':    # Windows
            os.startfile(filepath)
        else:                                   # linux variants
            subprocess.call(('xdg-open', filepath))
        print(f"--> [UTILS] Tentando abrir o arquivo: {filepath}")
    except Exception as e:
        print(f"ERRO ao tentar abrir o arquivo {filepath}: {e}")
