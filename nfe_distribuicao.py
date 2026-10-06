# ==============================================================================
# == nfe_distribuicao.py  -  Busca AUTOMÁTICA dos XMLs das notas de compra =====
# ==============================================================================
# Usa o serviço oficial da Receita "Distribuição de DF-e" (Ambiente Nacional): ele
# entrega TODAS as NF-e (modelo 55) emitidas para o CNPJ da loja, com o
# certificado digital A1 da empresa.
#
# Como funciona:
#   1. Pergunta à SEFAZ "o que tem de novo desde a última vez" (número NSU).
#   2. Nota COMPLETA (procNFe)  -> salva o XML na pasta (NFE_PASTA_XML).
#      Só o RESUMO (resNFe)     -> manda a "Ciência da Operação" (evento 210210):
#                                  depois disso a SEFAZ libera o XML completo, que
#                                  chega numa das próximas buscas.
#   3. Sem novidade (137) ou "consumo indevido" (656): espera 1 hora (regra da SEFAZ).
# O Gestão de Estoque lê a pasta (aba 3, botão "Notas da SEFAZ").
#
# config.py (NUNCA mostre esses valores para ninguém):
#   NFE_CERTIFICADO_PFX   = '/home/.../certificado.pfx'   (certificado A1)
#   NFE_CERTIFICADO_SENHA = '...'
#   NFE_CNPJ              = '00000000000000'               (CNPJ da loja, só números)
#   NFE_UF                = '51'                           (MT)
#   NFE_AMBIENTE          = 1                              (1 = produção)
#   NFE_PASTA_XML         = 'notas_xml_sefaz'              (opcional)
#
# Testar à mão:   python nfe_distribuicao.py          (busca agora e mostra o resumo)
# ==============================================================================
import base64
import gzip
import json
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha1

import requests

import config

logger = logging.getLogger(__name__)

PASTA_DO_PROGRAMA = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_ESTADO = os.path.join(PASTA_DO_PROGRAMA, 'nfe_distribuicao_estado.json')
NS_NFE = 'http://www.portalfiscal.inf.br/nfe'
NS_DSIG = 'http://www.w3.org/2000/09/xmldsig#'
NS_SOAP = 'http://www.w3.org/2003/05/soap-envelope'

URLS = {
    1: {'dist': 'https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
        'evento': 'https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx'},
    2: {'dist': 'https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
        'evento': 'https://hom1.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx'},
}
ESPERA_SEM_NOVIDADE = timedelta(hours=1)   # regra da SEFAZ: sem documentos novos, só consultar de novo em 1 h
MAX_LOTES_POR_RODADA = 20                  # cada lote traz até 50 documentos
TIMEOUT = 60
FUSO = timezone(timedelta(hours=-4))       # Cuiabá (MT)

_trava = threading.Lock()


class ErroNFe(Exception):
    """Erro com mensagem para mostrar ao usuário."""


# ------------------------------------------------------------------------------
# Configuração e estado
# ------------------------------------------------------------------------------
def configurado():
    """True se o config.py tem certificado, senha e CNPJ."""
    return all(getattr(config, n, None) for n in ('NFE_CERTIFICADO_PFX', 'NFE_CERTIFICADO_SENHA', 'NFE_CNPJ'))


def pasta_xml():
    pasta = getattr(config, 'NFE_PASTA_XML', None) or 'notas_xml_sefaz'
    pasta = pasta if os.path.isabs(pasta) else os.path.join(PASTA_DO_PROGRAMA, pasta)
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _cnpj():
    cnpj = re.sub(r'\D', '', str(getattr(config, 'NFE_CNPJ', '') or ''))
    if len(cnpj) != 14:
        raise ErroNFe("NFE_CNPJ no config.py precisa ter os 14 números do CNPJ da loja.")
    return cnpj


def _ambiente():
    amb = int(getattr(config, 'NFE_AMBIENTE', 1) or 1)
    return amb if amb in URLS else 1


def ler_estado():
    try:
        with open(ARQUIVO_ESTADO, encoding='utf-8') as f:
            dados = json.load(f)
            return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _salvar_estado(estado):
    tmp = ARQUIVO_ESTADO + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ARQUIVO_ESTADO)


# ------------------------------------------------------------------------------
# Certificado A1 (.pfx)
# ------------------------------------------------------------------------------
def _carregar_certificado():
    """Devolve (chave_privada, certificado, pem_cert_bytes, pem_chave_bytes)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    caminho = os.path.expanduser(str(getattr(config, 'NFE_CERTIFICADO_PFX', '') or '').strip())
    if caminho and not os.path.isabs(caminho):          # caminho sem a pasta: procura ao lado do programa
        caminho = os.path.join(PASTA_DO_PROGRAMA, caminho)
    try:
        with open(caminho, 'rb') as f:
            bruto = f.read()
    except OSError:
        # [SEGURANÇA] não mostra o NOME do arquivo (às vezes o nome do .pfx traz a senha)
        pasta = os.path.dirname(caminho) or PASTA_DO_PROGRAMA
        existe = os.path.isdir(pasta)
        raise ErroNFe("Não achei o arquivo do certificado do NFE_CERTIFICADO_PFX. "
                      + (f"A pasta {pasta} existe, mas o arquivo não está nela com esse nome exato."
                         if existe else f"A pasta {pasta} não existe.")
                      + " Confira o caminho completo no config.py.")
    senha = str(getattr(config, 'NFE_CERTIFICADO_SENHA', '') or '').encode('utf-8')
    try:
        import warnings
        with warnings.catch_warnings():
            # certificados de várias certificadoras vêm em BER (e não DER): funciona, só avisa
            warnings.filterwarnings('ignore', message='PKCS#12 bundle could not be parsed as DER')
            chave, cert, _extras = pkcs12.load_key_and_certificates(bruto, senha)
    except ValueError:
        raise ErroNFe("Não consegui abrir o certificado: a senha (NFE_CERTIFICADO_SENHA) está errada ou o arquivo não é um .pfx.")
    if not chave or not cert:
        raise ErroNFe("O arquivo do certificado não tem a chave privada (precisa ser o A1 .pfx completo).")
    vence = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after.replace(tzinfo=timezone.utc)
    if vence < datetime.now(timezone.utc):
        raise ErroNFe(f"O certificado digital VENCEU em {vence:%d/%m/%Y}. Renove o certificado A1.")
    pem_cert = cert.public_bytes(serialization.Encoding.PEM)
    pem_chave = chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption())
    return chave, cert, pem_cert, pem_chave


def dias_para_vencer_certificado():
    _, cert, _, _ = _carregar_certificado()
    vence = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after.replace(tzinfo=timezone.utc)
    return (vence - datetime.now(timezone.utc)).days


@contextmanager
def _arquivos_certificado(pem_cert, pem_chave):
    """O 'requests' precisa do certificado em arquivos: cria numa pasta temporária só do usuário e apaga no fim."""
    pasta = tempfile.mkdtemp(prefix='nfe_')
    try:
        c, k = os.path.join(pasta, 'c.pem'), os.path.join(pasta, 'k.pem')
        for caminho, dados in ((c, pem_cert), (k, pem_chave)):
            fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(dados)
        yield (c, k)
    finally:
        for nome in os.listdir(pasta):
            try:
                os.remove(os.path.join(pasta, nome))
            except OSError:
                pass
        os.rmdir(pasta)


# ------------------------------------------------------------------------------
# Conversa com a SEFAZ (SOAP 1.2)
# ------------------------------------------------------------------------------
def _soap(url, acao, corpo_xml, arquivos_cert):
    envelope = (f'<?xml version="1.0" encoding="utf-8"?><soap12:Envelope xmlns:soap12="{NS_SOAP}" '
                f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
                f'<soap12:Body>{corpo_xml}</soap12:Body></soap12:Envelope>')
    cabecalho = {'Content-Type': f'application/soap+xml; charset=utf-8; action="{acao}"'}
    verificar = getattr(config, 'NFE_VERIFICAR_SSL', True)
    try:
        resp = requests.post(url, data=envelope.encode('utf-8'), headers=cabecalho, cert=arquivos_cert,
                             timeout=TIMEOUT, verify=verificar)
    except requests.exceptions.SSLError as e:
        if verificar is not True or getattr(config, 'NFE_SSL_ESTRITO', False):
            raise ErroNFe(f"Falha de segurança (SSL) ao falar com a SEFAZ: {e}")
        # Os servidores da Receita usam a cadeia ICP-Brasil, que não vem no Python. A conexão
        # continua autenticada pelo NOSSO certificado; só a conferência do lado da SEFAZ é pulada.
        logger.warning("SEFAZ: certificado do servidor (ICP-Brasil) não reconhecido; repetindo sem conferir.")
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.post(url, data=envelope.encode('utf-8'), headers=cabecalho, cert=arquivos_cert,
                             timeout=TIMEOUT, verify=False)
    except requests.exceptions.RequestException as e:
        raise ErroNFe(f"Sem conexão com a SEFAZ agora ({type(e).__name__}). Tenta de novo mais tarde.")
    if resp.status_code >= 500 and b'Fault' not in resp.content:
        raise ErroNFe(f"A SEFAZ respondeu com erro {resp.status_code}. Tenta de novo mais tarde.")
    if resp.status_code == 403:
        raise ErroNFe("A SEFAZ recusou o certificado (403). Confira se é o certificado A1 do CNPJ da loja.")
    return resp.content


def _filho(no, nome):
    for el in no.iter():
        if isinstance(el.tag, str) and el.tag.split('}')[-1] == nome:
            return el
    return None


def _texto_de(no, nome):
    el = _filho(no, nome)
    return (el.text or '').strip() if el is not None and el.text else ''


def _xml(bruto):
    from lxml import etree
    try:
        return etree.fromstring(bruto, parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    except etree.XMLSyntaxError:
        raise ErroNFe("A SEFAZ devolveu uma resposta que não é XML. Tenta de novo mais tarde.")


def consultar_nsu(ult_nsu, arquivos_cert):
    """Uma consulta 'distNSU'. Devolve (cStat, xMotivo, ultNSU, maxNSU, [(nsu, schema, xml_bytes)])."""
    corpo = (f'<nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"><nfeDadosMsg>'
             f'<distDFeInt xmlns="{NS_NFE}" versao="1.01"><tpAmb>{_ambiente()}</tpAmb>'
             f'<cUFAutor>{str(getattr(config, "NFE_UF", "51"))}</cUFAutor><CNPJ>{_cnpj()}</CNPJ>'
             f'<distNSU><ultNSU>{int(ult_nsu):015d}</ultNSU></distNSU></distDFeInt></nfeDadosMsg></nfeDistDFeInteresse>')
    bruto = _soap(URLS[_ambiente()]['dist'],
                  'http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse', corpo, arquivos_cert)
    return interpretar_retorno_dist(bruto)


def interpretar_retorno_dist(bruto):
    raiz = _xml(bruto)
    ret = _filho(raiz, 'retDistDFeInt')
    if ret is None:
        motivo = _texto_de(raiz, 'Text') or _texto_de(raiz, 'faultstring')
        raise ErroNFe(f"A SEFAZ não respondeu como esperado{': ' + motivo if motivo else ''}.")
    docs = []
    for doc in ret.iter():
        if isinstance(doc.tag, str) and doc.tag.split('}')[-1] == 'docZip':
            try:
                conteudo = gzip.decompress(base64.b64decode(doc.text or ''))
            except (OSError, ValueError) as e:
                logger.error(f"SEFAZ: documento NSU {doc.get('NSU')} não abriu ({e}).")
                continue
            docs.append((int(doc.get('NSU') or 0), doc.get('schema') or '', conteudo))
    return (_texto_de(ret, 'cStat'), _texto_de(ret, 'xMotivo'), int(_texto_de(ret, 'ultNSU') or 0),
            int(_texto_de(ret, 'maxNSU') or 0), docs)


# ------------------------------------------------------------------------------
# Manifestação "Ciência da Operação" (libera o XML completo)
# ------------------------------------------------------------------------------
def _c14n(elemento):
    """
    C14N 1.0 de um elemento. ATENÇÃO: o libxml2 2.14 (que vem no lxml 6) tem um defeito no
    C14N de um PEDAÇO do documento: escreve xmlns="" nos netos, e a SEFAZ recusaria a
    assinatura ("assinatura difere"). Canonizar uma CÓPIA solta do elemento (que leva os
    namespaces em uso) dá o resultado certo.
    """
    from copy import deepcopy
    from lxml import etree
    return etree.tostring(deepcopy(elemento), method='c14n')


def montar_evento_ciencia(chave_nfe, chave_privada, certificado, agora=None):
    """XML do envEvento 210210 já ASSINADO (XMLDSig, RSA-SHA1, C14N), como o manual da NF-e pede."""
    from lxml import etree
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    agora = (agora or datetime.now(FUSO)).replace(microsecond=0)
    id_evento = f"ID210210{chave_nfe}01"
    env = etree.Element(f'{{{NS_NFE}}}envEvento', nsmap={None: NS_NFE}, versao='1.00')
    etree.SubElement(env, f'{{{NS_NFE}}}idLote').text = str(int(agora.timestamp()))[-15:]
    evento = etree.SubElement(env, f'{{{NS_NFE}}}evento', versao='1.00')
    inf = etree.SubElement(evento, f'{{{NS_NFE}}}infEvento', Id=id_evento)
    for nome, valor in (('cOrgao', '91'), ('tpAmb', str(_ambiente())), ('CNPJ', _cnpj()), ('chNFe', chave_nfe),
                        ('dhEvento', agora.isoformat()), ('tpEvento', '210210'), ('nSeqEvento', '1'), ('verEvento', '1.00')):
        etree.SubElement(inf, f'{{{NS_NFE}}}{nome}').text = valor
    det = etree.SubElement(inf, f'{{{NS_NFE}}}detEvento', versao='1.00')
    etree.SubElement(det, f'{{{NS_NFE}}}descEvento').text = 'Ciencia da Operacao'

    # Assinatura "enveloped": o digest é do infEvento canonizado (C14N); a Signature fica ao lado dele
    digest = base64.b64encode(sha1(_c14n(inf)).digest()).decode()
    assin = etree.SubElement(evento, f'{{{NS_DSIG}}}Signature', nsmap={None: NS_DSIG})
    si = etree.SubElement(assin, f'{{{NS_DSIG}}}SignedInfo')
    etree.SubElement(si, f'{{{NS_DSIG}}}CanonicalizationMethod', Algorithm='http://www.w3.org/TR/2001/REC-xml-c14n-20010315')
    etree.SubElement(si, f'{{{NS_DSIG}}}SignatureMethod', Algorithm='http://www.w3.org/2000/09/xmldsig#rsa-sha1')
    ref = etree.SubElement(si, f'{{{NS_DSIG}}}Reference', URI=f'#{id_evento}')
    trs = etree.SubElement(ref, f'{{{NS_DSIG}}}Transforms')
    etree.SubElement(trs, f'{{{NS_DSIG}}}Transform', Algorithm='http://www.w3.org/2000/09/xmldsig#enveloped-signature')
    etree.SubElement(trs, f'{{{NS_DSIG}}}Transform', Algorithm='http://www.w3.org/TR/2001/REC-xml-c14n-20010315')
    etree.SubElement(ref, f'{{{NS_DSIG}}}DigestMethod', Algorithm='http://www.w3.org/2000/09/xmldsig#sha1')
    etree.SubElement(ref, f'{{{NS_DSIG}}}DigestValue').text = digest
    valor_assinatura = chave_privada.sign(_c14n(si), padding.PKCS1v15(), hashes.SHA1())
    etree.SubElement(assin, f'{{{NS_DSIG}}}SignatureValue').text = base64.b64encode(valor_assinatura).decode()
    ki = etree.SubElement(assin, f'{{{NS_DSIG}}}KeyInfo')
    x509 = etree.SubElement(ki, f'{{{NS_DSIG}}}X509Data')
    der = certificado.public_bytes(serialization.Encoding.DER)
    etree.SubElement(x509, f'{{{NS_DSIG}}}X509Certificate').text = base64.b64encode(der).decode()
    return etree.tostring(env, encoding='unicode')


def manifestar_ciencia(chave_nfe, chave_privada, certificado, arquivos_cert):
    """Devolve (ok, mensagem). 135 = registrado; 573 = já tinha sido registrado (também serve)."""
    xml_evento = montar_evento_ciencia(chave_nfe, chave_privada, certificado)
    corpo = (f'<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4">{xml_evento}</nfeDadosMsg>')
    bruto = _soap(URLS[_ambiente()]['evento'],
                  'http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4/nfeRecepcaoEvento', corpo, arquivos_cert)
    raiz = _xml(bruto)
    ret = _filho(raiz, 'retEvento')
    alvo = ret if ret is not None else raiz
    cstat, motivo = _texto_de(alvo, 'cStat'), _texto_de(alvo, 'xMotivo')
    return cstat in ('135', '136', '573'), f"{cstat} {motivo}".strip()


# ------------------------------------------------------------------------------
# Guardar os documentos
# ------------------------------------------------------------------------------
def _ja_temos_xml(chave):
    """O XML desta nota já está na pasta ou na subpasta 'importadas' (nota que já entrou no estoque)."""
    return any(os.path.exists(os.path.join(pasta_xml(), sub, f"{chave}.xml")) for sub in ('', 'importadas'))


def _salvar_xml_completo(conteudo):
    """procNFe -> <pasta>/<chave>.xml. Devolve (chave, emitente, valor, novo?)."""
    raiz = _xml(conteudo)
    inf = _filho(raiz, 'infNFe')
    chave = (inf.get('Id') or '')[3:] if inf is not None else _texto_de(raiz, 'chNFe')
    if not re.fullmatch(r'\d{44}', chave or ''):
        chave = _texto_de(raiz, 'chNFe')
    if not re.fullmatch(r'\d{44}', chave or ''):
        raise ErroNFe("A SEFAZ mandou uma nota sem chave de acesso válida.")
    emit = _filho(raiz, 'emit')
    nome = _texto_de(emit, 'xFant') or _texto_de(emit, 'xNome') if emit is not None else ''
    valor = _texto_de(raiz, 'vNF')
    caminho = os.path.join(pasta_xml(), f"{chave}.xml")
    novo = not _ja_temos_xml(chave)     # [DEPURAÇÃO] nota já lançada (em 'importadas') não volta para a pasta
    if novo:
        with open(caminho, 'wb') as f:
            f.write(conteudo)
    return chave, nome, valor, novo


def _ler_resumo(conteudo):
    """resNFe: chave, emitente, valor, situação (1 = autorizada)."""
    raiz = _xml(conteudo)
    return {'chave': _texto_de(raiz, 'chNFe'), 'emitente': _texto_de(raiz, 'xNome'), 'valor': _texto_de(raiz, 'vNF'),
            'situacao': _texto_de(raiz, 'cSitNFe') or '1', 'emissao': _texto_de(raiz, 'dhEmi')[:10]}


# ------------------------------------------------------------------------------
# A rodada completa
# ------------------------------------------------------------------------------
def buscar_notas(forcar=False, agora=None):
    """
    Busca as novidades na SEFAZ. Devolve um resumo:
      {'novas': [{'chave','emitente','valor'}], 'manifestadas': n, 'aguardando': n,
       'mensagem': texto, 'proxima': 'dd/mm hh:mm' ou None}
    forcar=True ignora a espera de 1 hora (use pouco: a SEFAZ bloqueia quem consulta demais).
    """
    if not configurado():
        raise ErroNFe("Busca automática de XML desligada: falta NFE_CERTIFICADO_PFX, NFE_CERTIFICADO_SENHA e NFE_CNPJ no config.py.")
    if not _trava.acquire(blocking=False):
        raise ErroNFe("Já existe uma busca na SEFAZ em andamento. Espere terminar.")
    trava_arquivo = None
    try:
        # o robô (agendador) e o Gestão de Estoque podem buscar ao mesmo tempo: trava entre programas
        try:
            import fcntl
            trava_arquivo = open(ARQUIVO_ESTADO + '.lock', 'w')
            fcntl.flock(trava_arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass
        except OSError:
            raise ErroNFe("Já existe uma busca na SEFAZ em andamento (pelo robô). Tente em 1 minuto.")
        agora = agora or datetime.now()
        estado = ler_estado()
        resumo = {'novas': [], 'manifestadas': 0, 'aguardando': 0, 'mensagem': '', 'proxima': None}
        prox = estado.get('proxima_consulta')
        if prox and not forcar and datetime.fromisoformat(prox) > agora:
            resumo['proxima'] = datetime.fromisoformat(prox).strftime('%d/%m %H:%M')
            resumo['aguardando'] = len(estado.get('aguardando_xml', {}))
            resumo['mensagem'] = f"A SEFAZ pede 1 hora entre consultas sem novidade. Próxima busca: {resumo['proxima']}."
            return resumo
        chave_priv, cert, pem_cert, pem_chave = _carregar_certificado()
        manifestar = getattr(config, 'NFE_MANIFESTAR_CIENCIA', True)
        aguardando = estado.setdefault('aguardando_xml', {})
        ult = int(estado.get('ult_nsu', 0))
        tentadas_agora = set()          # ciências enviadas nesta rodada (as que falharem, só na próxima)
        with _arquivos_certificado(pem_cert, pem_chave) as arquivos:
            for _ in range(MAX_LOTES_POR_RODADA):
                cstat, motivo, ult_ret, max_nsu, docs = consultar_nsu(ult, arquivos)
                if cstat in ('137', '656'):
                    estado['proxima_consulta'] = (agora + ESPERA_SEM_NOVIDADE).isoformat(timespec='minutes')
                    resumo['mensagem'] = ("Nenhuma nota nova na SEFAZ." if cstat == '137'
                                          else "A SEFAZ pediu para esperar 1 hora (consultas demais).")
                    if cstat == '137' and ult_ret:   # [DEPURAÇÃO] no 656 o NSU não anda (não pula documentos)
                        ult = max(ult, ult_ret)
                    break
                if cstat != '138':
                    raise ErroNFe(f"A SEFAZ respondeu: {cstat} {motivo}")
                for nsu, schema, conteudo in docs:
                    if schema.startswith('procNFe'):
                        try:
                            chave, nome, valor, novo = _salvar_xml_completo(conteudo)
                        except ErroNFe as e:
                            logger.error(f"SEFAZ: documento NSU {nsu} ignorado: {e}")
                            continue
                        aguardando.pop(chave, None)
                        if novo:
                            resumo['novas'].append({'chave': chave, 'emitente': nome, 'valor': valor})
                    elif schema.startswith('resNFe'):
                        r = _ler_resumo(conteudo)
                        if r['situacao'] != '1' or not r['chave'] or _ja_temos_xml(r['chave']):
                            continue            # cancelada/denegada ou já temos o XML
                        if r['chave'] in aguardando:
                            continue
                        aguardando[r['chave']] = {'emitente': r['emitente'], 'valor': r['valor'], 'emissao': r['emissao'],
                                                  'desde': agora.isoformat(timespec='minutes'), 'ciencia': False}
                        tentadas_agora.add(r['chave'])
                        if manifestar and _enviar_ciencia(r['chave'], aguardando[r['chave']], chave_priv, cert, arquivos):
                            resumo['manifestadas'] += 1
                    # eventos (cancelamento, ciência etc.) não precisam de nada
                ult = max(ult, ult_ret)
                estado['ult_nsu'] = ult
                _salvar_estado(estado)
                if ult >= max_nsu:
                    # [SEFAZ] chegou ao fim da fila (ultNSU = maxNSU): a regra manda esperar 1 hora para
                    # consultar de novo. Antes consultava logo em seguida e levava o erro 656 (consumo indevido).
                    estado['proxima_consulta'] = (agora + ESPERA_SEM_NOVIDADE).isoformat(timespec='minutes')
                    break
            # [DEPURAÇÃO] ciência que falhou antes (internet, SEFAZ fora): tenta de novo (até 10 por rodada)
            if manifestar:
                pendentes = [c for c, v in aguardando.items() if not v.get('ciencia', False) and c not in tentadas_agora][:10]
                for ch in pendentes:
                    if _enviar_ciencia(ch, aguardando[ch], chave_priv, cert, arquivos):
                        resumo['manifestadas'] += 1
        # nota que nunca chegou completa em 30 dias: esquece (ex.: emitente cancelou)
        limite = agora - timedelta(days=30)
        for ch in [c for c, v in aguardando.items() if datetime.fromisoformat(v['desde']) < limite]:
            aguardando.pop(ch)
        estado['ult_nsu'] = ult
        estado['ultima_busca'] = agora.isoformat(timespec='minutes')
        _salvar_estado(estado)
        resumo['aguardando'] = len(aguardando)
        resumo['sem_ciencia'] = sum(1 for v in aguardando.values() if not v.get('ciencia', False))
        if not resumo['mensagem']:
            resumo['mensagem'] = "Busca na SEFAZ concluída."
        return resumo
    finally:
        if trava_arquivo:
            trava_arquivo.close()
        _trava.release()


def _enviar_ciencia(chave, registro, chave_priv, cert, arquivos):
    """Manda a Ciência da Operação e anota no registro se foi aceita (erro de rede não derruba a busca)."""
    try:
        ok, msg = manifestar_ciencia(chave, chave_priv, cert, arquivos)
    except ErroNFe as e:
        ok, msg = False, str(e)
    registro['ciencia'] = ok
    if not ok:
        registro['erro_ciencia'] = msg[:200]
        logger.warning(f"SEFAZ: ciência da nota {chave} não registrada: {msg}")
    return ok


def _reais(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except (TypeError, ValueError):
        return "R$ ?"


def texto_resumo(resumo):
    """Texto simples para mostrar na tela ou mandar no Telegram."""
    linhas = [resumo['mensagem']]
    if resumo['novas']:
        linhas.append(f"{len(resumo['novas'])} XML(s) novo(s) baixado(s):")
        for n in resumo['novas'][:20]:
            linhas.append(f"  • {n['emitente'] or 'Fornecedor'} · {_reais(n['valor'])}")
    if resumo['manifestadas']:
        linhas.append(f"{resumo['manifestadas']} nota(s) nova(s) com 'Ciência da Operação' enviada: "
                      "o XML completo chega numa das próximas buscas.")
    if resumo['aguardando']:
        linhas.append(f"{resumo['aguardando']} nota(s) aguardando o XML completo da SEFAZ.")
    if resumo.get('sem_ciencia'):
        linhas.append(f"⚠ {resumo['sem_ciencia']} nota(s) sem a Ciência registrada (a SEFAZ recusou ou estava fora): "
                      "o sistema tenta de novo na próxima busca. Detalhe no log.")
    return "\n".join(linhas)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    try:
        print(f"Certificado vence em {dias_para_vencer_certificado()} dia(s).")
        r = buscar_notas(forcar='forcar' in sys.argv)
        print(texto_resumo(r))
        print(f"XMLs na pasta: {pasta_xml()}")
    except ErroNFe as e:
        print(f"ERRO: {e}")
