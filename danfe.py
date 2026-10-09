# -*- coding: utf-8 -*-
"""
[DANFE] O DANFE (PDF) de uma nota de compra, montado a partir do XML que o sistema já guardou.

O robô baixa da SEFAZ o XML completo de cada nota emitida para a loja e guarda na pasta
NFE_PASTA_XML (padrão 'notas_xml_sefaz'; depois de entrar no estoque, na subpasta 'importadas').
Daqui sai o DANFE do mesmo jeito que o papel que vem com a mercadoria: para conferir a entrega,
imprimir ou mandar pelo WhatsApp. Usado pelo Gestão de Estoque, pelo app de compras e pelo
aviso de nota nova.

Precisa da biblioteca (uma vez, com o ambiente do sistema ativo):
    pip install brazilfiscalreport

O PDF fica guardado em <pasta dos XML>/danfe/<chave>.pdf e só é refeito se o XML mudar.
"""
import logging
import os
import re
import xml.etree.ElementTree as ET

import config

logger = logging.getLogger(__name__)

PASTA_DO_PROGRAMA = os.path.dirname(os.path.abspath(__file__))
NS = '{http://www.portalfiscal.inf.br/nfe}'


class ErroDanfe(Exception):
    """Mensagem pronta para mostrar na tela."""


def _so_digitos(texto):
    return re.sub(r'\D', '', str(texto or ''))


def pasta_xml():
    """A mesma pasta do nfe_distribuicao (sem importar as bibliotecas da SEFAZ)."""
    pasta = getattr(config, 'NFE_PASTA_XML', None) or 'notas_xml_sefaz'
    return pasta if os.path.isabs(pasta) else os.path.join(PASTA_DO_PROGRAMA, pasta)


def localizar_xml(chave):
    """Caminho do XML da nota (pasta da SEFAZ ou 'importadas') ou None."""
    chave = _so_digitos(chave)
    if len(chave) != 44:
        return None
    for sub in ('', 'importadas'):
        caminho = os.path.join(pasta_xml(), sub, f"{chave}.xml")
        if os.path.exists(caminho):
            return caminho
    return None


def dados_do_xml(texto_xml):
    """{'chave', 'numero', 'emitente', 'valor'} do XML (para o nome do arquivo e a legenda)."""
    try:
        raiz = ET.fromstring(texto_xml.encode('utf-8') if isinstance(texto_xml, str) else texto_xml)
    except ET.ParseError as e:
        raise ErroDanfe(f"O arquivo da nota não é um XML válido ({e}).")
    inf = raiz.find(f'.//{NS}infNFe')
    if inf is None:
        raise ErroDanfe("Este arquivo não é o XML completo da nota (é só o resumo que a SEFAZ manda antes). "
                        "O DANFE sai quando o XML completo chegar.")

    def texto(caminho):
        el = inf.find(caminho)
        return (el.text or '').strip() if el is not None and el.text else ''
    return {'chave': _so_digitos(inf.get('Id')), 'numero': texto(f'{NS}ide/{NS}nNF'),
            'emitente': texto(f'{NS}emit/{NS}xFant') or texto(f'{NS}emit/{NS}xNome'),
            'valor': texto(f'{NS}total/{NS}ICMSTot/{NS}vNF')}


def nome_arquivo(dados):
    """'DANFE NF 12345 - Distribuidora Exemplo.pdf' (sem caracteres que o Windows recusa)."""
    emit = re.sub(r'[\\/:*?"<>|]+', ' ', dados.get('emitente') or '').strip()[:40]
    return f"DANFE NF {dados.get('numero') or dados.get('chave', '')[-9:]}" + (f" - {emit}" if emit else "") + ".pdf"


def gerar(chave=None, caminho_xml=None):
    """
    Monta (ou reaproveita) o DANFE. Pela chave (procura o XML guardado) ou por um XML qualquer.
    Devolve (caminho_do_pdf, dados_do_xml). Levanta ErroDanfe com a explicação.
    """
    if caminho_xml is None:
        chave = _so_digitos(chave)
        if len(chave) != 44:
            raise ErroDanfe("Esta nota está sem a chave de acesso no sistema (foi lançada à mão ou com um XML "
                            "antigo): não tenho o XML para montar o DANFE.")
        caminho_xml = localizar_xml(chave)
        if not caminho_xml:
            raise ErroDanfe("O XML desta nota não está no servidor. Só as notas baixadas da SEFAZ pelo robô têm o "
                            "XML guardado (se ela foi importada de outra pasta, o DANFE sai pelo site da SEFAZ).")
    try:
        with open(caminho_xml, 'r', encoding='utf-8') as f:
            texto_xml = f.read()
    except UnicodeDecodeError:
        with open(caminho_xml, 'r', encoding='latin-1') as f:
            texto_xml = f.read()
    except OSError as e:
        raise ErroDanfe(f"Não consegui abrir o XML da nota ({e}).")
    dados = dados_do_xml(texto_xml)
    pasta = os.path.join(pasta_xml(), 'danfe')
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f"{dados['chave'] or os.path.splitext(os.path.basename(caminho_xml))[0]}.pdf")
    if os.path.exists(destino) and os.path.getmtime(destino) >= os.path.getmtime(caminho_xml):
        return destino, dados
    try:
        from brazilfiscalreport.danfe import Danfe
    except ImportError:
        raise ErroDanfe("Falta instalar o gerador de DANFE no servidor: com o ambiente do sistema ativo, "
                        "rode  pip install brazilfiscalreport")
    temporario = destino + '.tmp'
    try:
        Danfe(xml=texto_xml).output(temporario)
        os.replace(temporario, destino)                  # troca de uma vez (nunca fica um PDF pela metade)
    except Exception as e:
        logger.error(f"DANFE: falha ao montar o PDF de {caminho_xml}: {e}", exc_info=True)
        try:
            os.remove(temporario)
        except OSError:
            pass
        raise ErroDanfe("Não consegui montar o DANFE desta nota: o XML veio incompleto ou num formato diferente "
                        "(o detalhe ficou no log). O DANFE dela sai pelo site da SEFAZ, com a chave de acesso.")
    logger.info(f"DANFE gerado: {destino}")
    return destino, dados
