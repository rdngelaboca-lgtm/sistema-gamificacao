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

def excluir_arquivo_seguro(filepath):
    """
    Exclui um arquivo do disco e retorna True/False.
    """
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"--> [UTILS] Arquivo excluído com sucesso: {filepath}")
            return True
        else:
            print(f"--> [UTILS] Aviso: Tentativa de excluir arquivo que não existe: {filepath}")
            return True # Consideramos sucesso se o arquivo já não estiver lá
    except Exception as e:
        print(f"ERRO CRÍTICO ao excluir arquivo {filepath}: {e}")
        return False
