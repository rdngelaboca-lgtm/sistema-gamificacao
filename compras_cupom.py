# ==============================================================================
# compras_cupom.py - LER O QR CODE DO CUPOM FISCAL (NFC-e) NO APP DE COMPRAS
# ------------------------------------------------------------------------------
# O QR Code do cupom do mercado é um endereço da SEFAZ. Este arquivo:
#   1) tira desse endereço a CHAVE DE ACESSO (44 números: CNPJ do mercado, número
#      e série do cupom já estão dentro dela);
#   2) abre a página da SEFAZ (só endereços .gov.br) e lê os itens, as quantidades,
#      os preços, o desconto e o total;
#   3) reconhece cada item pelos vínculos que o Gestão de Estoque já tem
#      (mesmo jeito da importação do XML: descrição, código do produto);
#   4) o gestor confere, vincula o que faltar e LANÇA NO ESTOQUE: vira uma nota de
#      entrada igual às do XML (Consultas, Valor do Estoque e Sugestão enxergam).
#
# Se a SEFAZ mudar a página e o sistema não entender um cupom, a página baixada é
# guardada em logs/cupons/ para conferência (nada é lançado sem o gestor ver).
# ==============================================================================

import html as html_lib
import logging
import os
import re
import base64
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse, urljoin, unquote

import database
from database import _dec
import compras_database as cd
from compras_database import ErroCompras, _iso, _num, _como_datahora

logger = logging.getLogger(__name__)

TEMPO_LIMITE_SEFAZ = 25            # segundos esperando a página da SEFAZ
PASTA_DIAGNOSTICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'cupons')
NAVEGADOR = ('Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) '
             'Chrome/124.0 Mobile Safari/537.36')

ST_PENDENTE = 'pendente'          # lido: falta conferir/vincular e lançar
ST_IMPORTADO = 'importado'        # virou nota de entrada no estoque
ST_ERRO = 'erro'                  # não deu para ler a página da SEFAZ (dá para tentar de novo)
ST_JA_LANCADO = 'ja_lancado'      # esta nota já estava no estoque (ex.: XML importado antes)

ACAO_VINCULAR = 'vincular'
ACAO_IGNORAR = 'ignorar'

_tabelas_ok = False


# ==============================================================================
# == 1) Chave de acesso =========================================================
# ==============================================================================

def _dv_chave(chave43):
    """Dígito verificador da chave de acesso (módulo 11, pesos 2 a 9)."""
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(chave43)))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def extrair_chave(texto):
    """
    Acha a chave de 44 números no texto do QR Code (o endereço da SEFAZ) e confere o
    dígito verificador. Devolve (chave, endereco_ou_None).
    """
    texto = unquote(str(texto or '')).strip()
    if not texto:
        raise ErroCompras("QR Code vazio.")
    candidatos = re.findall(r'(?<!\d)(\d{44})(?!\d)', re.sub(r'(?<=\d)[ .](?=\d)', '', texto))
    for chave in candidatos:
        if _dv_chave(chave[:43]) == int(chave[43]):
            endereco = texto if re.match(r'https?://', texto, re.I) else None
            return chave, endereco
    if candidatos:
        raise ErroCompras("A chave do cupom não confere (dígito verificador). Tente ler o QR Code de novo.")
    raise ErroCompras("Este QR Code não é de um cupom fiscal (NFC-e).")


def dados_da_chave(chave):
    """O que já vem DENTRO da chave: estado, ano/mês, CNPJ do emitente, modelo, série e número."""
    return {'uf': chave[0:2], 'ano_mes': f"20{chave[2:4]}-{chave[4:6]}", 'cnpj': chave[6:20],
            'modelo': chave[20:22], 'serie': str(int(chave[22:25])), 'numero': str(int(chave[25:34]))}


def endereco_seguro(url):
    """Só deixa o servidor abrir páginas de SEFAZ (.gov.br). Protege o computador da loja."""
    try:
        p = urlparse(url)
    except ValueError:
        raise ErroCompras("Endereço do QR Code inválido.")
    host = (p.hostname or '').lower()
    if p.scheme not in ('http', 'https') or not (host.endswith('.gov.br')):
        raise ErroCompras("O QR Code não aponta para um site da SEFAZ (.gov.br).")
    if p.port not in (None, 80, 443):
        raise ErroCompras("Endereço do QR Code com porta estranha: recusado.")
    return url


# ==============================================================================
# == 2) Baixar e entender a página da SEFAZ ====================================
# ==============================================================================

def _decodificar(bruto, codificacao=None):
    for cod in ('utf-8', codificacao or 'latin-1', 'latin-1'):
        try:
            return bruto.decode(cod)
        except (UnicodeDecodeError, LookupError):
            continue
    return bruto.decode('utf-8', errors='replace')


def _baixar_com_requests(url):
    """Jeito normal (biblioteca requests). Devolve o texto da página."""
    import requests
    sessao = requests.Session()
    sessao.headers.update({'User-Agent': NAVEGADOR, 'Accept': 'text/html,application/xhtml+xml',
                           'Accept-Language': 'pt-BR,pt;q=0.9'})
    atual = endereco_seguro(url)
    for _ in range(6):
        try:
            try:
                r = sessao.get(atual, timeout=TEMPO_LIMITE_SEFAZ, allow_redirects=False)
            except requests.exceptions.SSLError:
                # Alguns sites do governo usam certificado que o Python não reconhece.
                # A página é pública e só lemos dados dela: segue sem conferir o certificado.
                logger.warning(f"Certificado da SEFAZ não reconhecido ({urlparse(atual).hostname}); lendo assim mesmo.")
                r = sessao.get(atual, timeout=TEMPO_LIMITE_SEFAZ, allow_redirects=False, verify=False)
        except requests.exceptions.Timeout:
            raise ErroCompras("A SEFAZ demorou demais para responder. Tente de novo em alguns minutos.")
        except requests.exceptions.ConnectionError as e:
            # [MT] a SEFAZ-MT derruba a conexão https de programas que não abrem a conexão como um navegador
            logger.warning(f"A SEFAZ derrubou a conexão ({urlparse(atual).hostname}): {e}")
            raise _ConexaoDerrubada(atual)
        except requests.exceptions.RequestException as e:
            logger.warning(f"Falha ao abrir a página da SEFAZ: {e}")
            raise ErroCompras("Não consegui abrir o site da SEFAZ. O computador da loja está com internet?")
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get('Location'):
            atual = endereco_seguro(urljoin(atual, r.headers['Location']))
            continue
        if r.status_code != 200:
            raise ErroCompras(f"O site da SEFAZ respondeu com erro {r.status_code}. Tente de novo mais tarde.")
        return _decodificar(r.content, r.encoding)
    raise ErroCompras("O site da SEFAZ redirecionou vezes demais.")


class _ConexaoDerrubada(Exception):
    """A SEFAZ fechou a conexão sem responder (guarda o endereço em que parou)."""
    def __init__(self, url):
        super().__init__(url)
        self.url = url


def _baixar_imitando_chrome(url):
    """
    Plano B: abre a página com a biblioteca curl_cffi, que faz a conexão segura IGUAL ao
    Google Chrome. Alguns sites do governo derrubam qualquer outro programa.
    Instalar no servidor:  pip install curl_cffi
    """
    try:
        from curl_cffi import requests as creq
    except ImportError:
        raise ErroCompras("A SEFAZ recusou a conexão do computador da loja. Falta instalar o leitor que "
                          "imita o navegador: pip install curl_cffi  (depois reinicie o serviço).")
    atual = endereco_seguro(url.replace('|', '%7C'))
    for _ in range(6):
        try:
            r = creq.get(atual, impersonate='chrome', timeout=TEMPO_LIMITE_SEFAZ, allow_redirects=False,
                         headers={'Accept-Language': 'pt-BR,pt;q=0.9'})
        except Exception as e:
            logger.warning(f"Plano B (imitando o Chrome) também falhou em {atual}: {e}")
            raise ErroCompras("A SEFAZ recusou a conexão do computador da loja. Tente de novo mais tarde; "
                              "se continuar, avise o gestor.")
        local = r.headers.get('Location')
        if r.status_code in (301, 302, 303, 307, 308) and local:
            atual = endereco_seguro(urljoin(atual, local))
            continue
        if r.status_code != 200:
            raise ErroCompras(f"O site da SEFAZ respondeu com erro {r.status_code}. Tente de novo mais tarde.")
        return _decodificar(r.content, r.encoding)
    raise ErroCompras("O site da SEFAZ redirecionou vezes demais.")


def baixar_pagina(url):
    """Abre a página do cupom na SEFAZ. Segue no máximo 5 redirecionamentos, todos .gov.br."""
    try:
        return _baixar_com_requests(url)
    except _ConexaoDerrubada as e:
        logger.info("Tentando de novo imitando o Google Chrome (curl_cffi)...")
        return _baixar_imitando_chrome(e.url)


def _texto(fragmento):
    """Tira as marcações HTML e deixa só o texto limpo."""
    t = re.sub(r'<br\s*/?>', ' ', fragmento or '', flags=re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    return re.sub(r'\s+', ' ', html_lib.unescape(t)).strip()


def numero_br(texto):
    """'1.234,56' -> Decimal('1234.56');  '0,79' -> 0.79;  '2.5' -> 2.5."""
    t = str(texto or '').strip().replace('R$', '').replace(' ', '')
    if not t:
        return None
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    elif t.count('.') > 1:
        t = t.replace('.', '')
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _valor_rotulo(html, rotulo):
    """Valor que vem depois de um rótulo, ex.: 'Valor a pagar R$:' -> 275,94."""
    m = re.search(re.escape(rotulo) + r'\s*:?\s*</label>\s*<span[^>]*>\s*([\d.,]+)', html, re.I)
    if m:
        return numero_br(m.group(1))
    m = re.search(re.escape(rotulo) + r'\s*:?\s*([\d.,]+)', _texto(html), re.I)
    return numero_br(m.group(1)) if m else None


def _itens_layout_nacional(html):
    """Layout nacional da consulta da NFC-e (tabela 'tabResult', usado pela maioria dos estados)."""
    itens = []
    blocos = re.split(r'<tr[^>]*id\s*=\s*["\']Item', html, flags=re.I)[1:]
    for bloco in blocos:
        bloco = bloco.split('</tr>')[0]
        desc = re.search(r'class="txtTit\d?"[^>]*>(.*?)</span>', bloco, re.S | re.I)
        cod = re.search(r'C[óo]digo:\s*([^)<]*)\)?', _texto(bloco), re.I)
        qtd = re.search(r'Qtde\.?:\s*</strong>\s*([\d.,]+)', bloco, re.I)
        un = re.search(r'UN:\s*</strong>\s*([^<]+)', bloco, re.I)
        vun = re.search(r'Vl\.?\s*Unit\.?:\s*</strong>\s*([\d.,]+)', bloco, re.I)
        vtot = re.search(r'class="valor"[^>]*>\s*([\d.,]+)', bloco, re.I)
        # [MT] a SEFAZ-MT põe espaços especiais (&nbsp;) e marcações diferentes entre o rótulo e o
        # número: se a busca no HTML falhar, procura no TEXTO limpo do item
        texto_item = _texto(bloco)
        if not qtd:
            qtd = re.search(r'Qtde\.?:?\s*([\d.,]+)', texto_item, re.I)
        if not un:
            un = re.search(r'\bUN:\s*([A-Za-z]{1,6})', texto_item)
        if not vun:
            vun = re.search(r'Vl\.?\s*Unit\.?:?\s*([\d.,]+)', texto_item, re.I)
        if not (desc and qtd and vtot):
            continue
        q, total = numero_br(qtd.group(1)), numero_br(vtot.group(1))
        unit = numero_br(vun.group(1)) if vun else None
        if unit is None and q and total is not None:
            unit = (total / q).quantize(Decimal('0.0001'))     # sem o preço unitário: total ÷ quantidade
        itens.append({'descricao': _texto(desc.group(1)), 'codigo': (cod.group(1).strip() if cod else ''),
                      'qtd': q, 'unidade': (_texto(un.group(1)) if un else 'UN').upper()[:10],
                      'valor_unit': unit, 'valor_total': total})
    return itens


def _itens_por_texto(html):
    """Plano B: lê os itens pelo TEXTO da página (quando o estado usa outro desenho de tela)."""
    texto = _texto(html)
    padrao = re.compile(
        r'(?P<desc>[^()]{3,120}?)\s*\(\s*C[óo]digo:\s*(?P<cod>[^)]*)\)\s*Qtde\.?:\s*(?P<qtd>[\d.,]+)\s*'
        r'UN:\s*(?P<un>[A-Za-z0-9]{1,6})\s*Vl\.?\s*Unit\.?:\s*(?P<vun>[\d.,]+)\s*Vl\.?\s*Total\s*(?P<vtot>[\d.,]+)', re.I)
    itens = []
    for m in padrao.finditer(texto):
        # a descrição do 1º item pode vir grudada no cabeçalho (endereço do mercado): fica só o fim
        desc = re.split(r'[,:]', m.group('desc'))[-1].strip()[-80:]
        itens.append({'descricao': desc, 'codigo': m.group('cod').strip(), 'qtd': numero_br(m.group('qtd')),
                      'unidade': m.group('un').upper(), 'valor_unit': numero_br(m.group('vun')),
                      'valor_total': numero_br(m.group('vtot'))})
    return itens


def interpretar_pagina(html):
    """
    Lê a página do cupom e devolve emitente, itens, totais e data.
    Levanta ErroCompras se não achar itens.
    """
    texto = _texto(html)
    baixo = texto.lower()
    if 'cancelad' in baixo and ('nfc-e cancelada' in baixo or 'nota cancelada' in baixo or 'situação: cancelad' in baixo):
        raise ErroCompras("A SEFAZ informa que este cupom foi CANCELADO. Não dá para lançar.")
    itens = _itens_layout_nacional(html) or _itens_por_texto(html)
    if not itens:
        if re.search(r'n[ãa]o (foi )?encontrad|inexistente|n[ãa]o consta', baixo):
            raise ErroCompras("A SEFAZ ainda não encontrou este cupom. Cupons emitidos sem internet podem levar "
                              "até 24 horas para aparecer: tente de novo mais tarde.")
        if 'captcha' in baixo:
            raise ErroCompras("O site da SEFAZ pediu verificação 'não sou robô'. Não dá para ler automaticamente.")
        raise ErroCompras("Não consegui entender a página da SEFAZ deste cupom.")
    for i, it in enumerate(itens, start=1):
        it['seq'] = i
        if it['qtd'] is None or it['qtd'] <= 0 or it['valor_total'] is None:
            raise ErroCompras(f"Item {i} do cupom com quantidade ou valor que não consegui ler.")
    nome = re.search(r'class="txtTopo"[^>]*>(.*?)</div>', html, re.S | re.I)
    cnpj = re.search(r'CNPJ:?\s*([\d./-]{14,18})', texto)
    emissao = re.search(r'Emiss[ãa]o:\s*(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?', texto)
    data_emissao = None
    if emissao:
        d, m, a, hh, mm, ss = emissao.groups()
        try:
            data_emissao = datetime(int(a), int(m), int(d), int(hh or 0), int(mm or 0), int(ss or 0))
        except ValueError:
            data_emissao = None
    chave_pagina = re.search(r'class="chave"[^>]*>([\d\s]+)<', html, re.I)
    soma = sum((i['valor_total'] for i in itens), Decimal('0'))
    valor_total = _valor_rotulo(html, 'Valor total R$') or soma
    descontos = _valor_rotulo(html, 'Descontos R$') or Decimal('0')
    valor_pagar = _valor_rotulo(html, 'Valor a pagar R$') or (valor_total - descontos)
    return {
        'emitente_nome': _texto(nome.group(1))[:150] if nome else '',
        'emitente_cnpj': re.sub(r'\D', '', cnpj.group(1)) if cnpj else '',
        'data_emissao': data_emissao,
        'chave_pagina': re.sub(r'\D', '', chave_pagina.group(1)) if chave_pagina else '',
        'itens': itens, 'soma_itens': soma, 'valor_total': valor_total,
        'descontos': descontos, 'valor_pagar': valor_pagar,
    }


def guardar_para_diagnostico(chave, html):
    """Guarda a página que não foi entendida (para ajustar o leitor depois)."""
    try:
        os.makedirs(PASTA_DIAGNOSTICO, exist_ok=True)
        caminho = os.path.join(PASTA_DIAGNOSTICO, f"{chave}.html")
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(html or '')
        return caminho
    except OSError as e:
        logger.error(f"Não consegui guardar a página do cupom para diagnóstico: {e}")
        return None


# ==============================================================================
# == 3) Ler o QR Code de uma FOTO (para celulares que não leem sozinhos) ========
# ==============================================================================

def ler_qr_da_foto(dados_imagem):
    """
    Recebe a foto (bytes ou 'data:image/jpeg;base64,...') e devolve o texto do QR Code.
    Usa o OpenCV (pip install opencv-python-headless). Tenta várias versões da imagem
    (tamanhos e contraste), porque cupom térmico costuma sair claro ou amassado.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise ErroCompras("O computador da loja não tem o leitor de QR instalado. "
                          "Rode: pip install opencv-python-headless  (ou cole o link do QR Code).")
    if isinstance(dados_imagem, str):
        if ',' in dados_imagem[:100]:
            dados_imagem = dados_imagem.split(',', 1)[1]
        try:
            dados_imagem = base64.b64decode(dados_imagem, validate=False)
        except (ValueError, TypeError):
            raise ErroCompras("Foto inválida.")
    if not dados_imagem or len(dados_imagem) > 12 * 1024 * 1024:
        raise ErroCompras("Foto vazia ou grande demais.")
    img = cv2.imdecode(np.frombuffer(dados_imagem, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ErroCompras("Não consegui abrir a foto. Tire outra.")
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    detectores = [cv2.QRCodeDetector()]
    if hasattr(cv2, 'QRCodeDetectorAruco'):
        detectores.append(cv2.QRCodeDetectorAruco())
    versoes = []
    alt, larg = cinza.shape[:2]
    for escala in (1.0, 0.5, 1.5, 2.0):
        if escala != 1.0 and max(alt, larg) * escala > 4000:
            continue
        base = cinza if escala == 1.0 else cv2.resize(cinza, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC)
        versoes.append(base)
        versoes.append(cv2.adaptiveThreshold(base, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 10))
    for v in versoes:
        for det in detectores:
            try:
                texto, pontos, _ = det.detectAndDecode(v)
            except cv2.error:
                continue
            if texto:
                return texto
    raise ErroCompras("Não achei o QR Code na foto. Chegue mais perto, com boa luz, e deixe o QR inteiro e reto na foto.")


# ==============================================================================
# == 4) Tabelas e registro do cupom ============================================
# ==============================================================================

def garantir_tabelas():
    global _tabelas_ok
    if _tabelas_ok:
        return
    cd.garantir_tabelas()
    conn = database.get_db_connection()
    if not conn:
        raise ErroCompras("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraCupons')
            CREATE TABLE CompraCupons (
                CupomID INT IDENTITY(1,1) PRIMARY KEY,
                Chave VARCHAR(44) NOT NULL UNIQUE,
                Url NVARCHAR(600) NULL,
                ListaCodigo VARCHAR(40) NULL,
                CNPJ VARCHAR(14) NULL,
                Emitente NVARCHAR(150) NULL,
                Numero VARCHAR(12) NULL,
                Serie VARCHAR(5) NULL,
                DataEmissao DATETIME NULL,
                ValorTotal DECIMAL(18, 2) NULL,
                Descontos DECIMAL(18, 2) NULL,
                ValorPagar DECIMAL(18, 2) NULL,
                Status VARCHAR(20) NOT NULL,
                Erro NVARCHAR(400) NULL,
                LidoPorID INT NULL,
                LidoPor NVARCHAR(150) NULL,
                LidoEm DATETIME NULL,
                LancadoPor NVARCHAR(150) NULL,
                LancadoEm DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompraCupomItens')
            CREATE TABLE CompraCupomItens (
                CupomID INT NOT NULL,
                Seq INT NOT NULL,
                Codigo NVARCHAR(60) NULL,
                Descricao NVARCHAR(255) NOT NULL,
                Qtd DECIMAL(18, 4) NOT NULL,
                Unidade VARCHAR(10) NULL,
                ValorUnit DECIMAL(18, 4) NULL,
                ValorTotal DECIMAL(18, 2) NOT NULL,
                Acao VARCHAR(20) NULL,
                ProdutoID INT NULL,
                Fator DECIMAL(18, 4) NULL,
                PRIMARY KEY (CupomID, Seq)
            )
        """)
        conn.commit()
        _tabelas_ok = True
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao criar tabelas de cupons: {e}", exc_info=True)
        raise ErroCompras("Não foi possível preparar o banco para os cupons (veja o log).")
    finally:
        conn.close()


def _conectar():
    garantir_tabelas()
    conn = database.get_db_connection()
    if not conn:
        raise ErroCompras("Sem conexão com o banco de dados.")
    return conn


def _id_cupom_por_chave(chave):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT CupomID FROM CompraCupons WHERE Chave = ?", (chave,))
        r = cur.fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def _nota_ja_lancada(cnpj, numero, serie=None, chave=None):
    """A mesma nota já está no estoque? (ex.: XML importado no Gestão de Estoque)
    Série e chave evitam confundir cupons de caixas diferentes com o mesmo número."""
    fornecedor_id = database.buscar_fornecedor_por_cnpj(cnpj)
    if not fornecedor_id:
        return False
    return bool(database.buscar_nota_importada(numero, fornecedor_id, serie, chave))


def registrar_cupom(texto_qr, usuario, lista_codigo=None, html=None):
    """
    Guarda o cupom lido e (se der) os itens da página da SEFAZ.
    Ler o mesmo QR duas vezes não duplica: devolve o cupom já guardado
    (se ele estava com erro, tenta ler a página de novo).
    'html' é só para testes (pula o download).
    """
    chave, url = extrair_chave(texto_qr)
    info = dados_da_chave(chave)
    if info['modelo'] not in ('65', '55'):
        raise ErroCompras("Este QR Code não é de nota fiscal.")
    if not url:
        raise ErroCompras("Só a chave não basta: a SEFAZ pede o QR Code completo. Leia o QR Code do cupom.")
    endereco_seguro(url)
    existente = _id_cupom_por_chave(chave)
    if existente:
        cupom = obter_cupom(existente)
        if cupom['status'] == ST_ERRO:
            return tentar_de_novo(existente, html=html)
        cupom['ja_existia'] = True
        return cupom

    status, erro, pagina = ST_PENDENTE, None, None
    if _nota_ja_lancada(info['cnpj'], info['numero'], info['serie'], chave):
        status, erro = ST_JA_LANCADO, "Esta nota já está no estoque (provavelmente o XML foi importado)."
    else:
        try:
            pagina_html = html if html is not None else baixar_pagina(url)
            try:
                pagina = interpretar_pagina(pagina_html)
            except ErroCompras:
                guardar_para_diagnostico(chave, pagina_html)
                raise
            if pagina['chave_pagina'] and pagina['chave_pagina'] != chave:
                raise ErroCompras("A página da SEFAZ mostrou outro cupom. Tente ler de novo.")
        except ErroCompras as e:
            status, erro = ST_ERRO, str(e)

    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO CompraCupons (Chave, Url, ListaCodigo, CNPJ, Emitente, Numero, Serie, DataEmissao,
                                                 ValorTotal, Descontos, ValorPagar, Status, Erro, LidoPorID, LidoPor, LidoEm)
                       OUTPUT INSERTED.CupomID VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (chave, url[:600], (lista_codigo or None), info['cnpj'],
                     (pagina['emitente_nome'] if pagina else None), info['numero'], info['serie'],
                     pagina['data_emissao'] if pagina else None,
                     pagina['valor_total'] if pagina else None, pagina['descontos'] if pagina else None,
                     pagina['valor_pagar'] if pagina else None, status, (erro or '')[:400] or None,
                     usuario.get('id'), usuario.get('nome'), datetime.now()))
        cupom_id = int(cur.fetchone()[0])
        if pagina:
            _gravar_itens(cur, cupom_id, pagina['itens'])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info(f"Cupom {chave} lido por {usuario.get('nome')}: {status} {erro or ''}")
    return obter_cupom(cupom_id)


def _gravar_itens(cur, cupom_id, itens):
    cur.execute("DELETE FROM CompraCupomItens WHERE CupomID = ?", (cupom_id,))
    for it in itens:
        cur.execute("""INSERT INTO CompraCupomItens (CupomID, Seq, Codigo, Descricao, Qtd, Unidade, ValorUnit, ValorTotal)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cupom_id, it['seq'], (it['codigo'] or '')[:60], it['descricao'][:255], it['qtd'],
                     it['unidade'], it['valor_unit'], it['valor_total']))


def tentar_de_novo(cupom_id, html=None):
    """Lê a página da SEFAZ outra vez (para cupom com erro: SEFAZ fora do ar, cupom ainda não transmitido)."""
    cupom = obter_cupom(cupom_id)
    if cupom['status'] != ST_ERRO:
        return cupom
    try:
        pagina_html = html if html is not None else baixar_pagina(cupom['url'])
        try:
            pagina = interpretar_pagina(pagina_html)
        except ErroCompras:
            guardar_para_diagnostico(cupom['chave'], pagina_html)
            raise
        status, erro = ST_PENDENTE, None
    except ErroCompras as e:
        pagina, status, erro = None, ST_ERRO, str(e)
    conn = _conectar()
    try:
        cur = conn.cursor()
        if pagina:
            cur.execute("""UPDATE CompraCupons SET Emitente = ?, DataEmissao = ?, ValorTotal = ?, Descontos = ?, ValorPagar = ?,
                           Status = ?, Erro = NULL WHERE CupomID = ?""",
                        (pagina['emitente_nome'], pagina['data_emissao'], pagina['valor_total'], pagina['descontos'],
                         pagina['valor_pagar'], status, cupom_id))
            _gravar_itens(cur, cupom_id, pagina['itens'])
        else:
            cur.execute("UPDATE CompraCupons SET Erro = ? WHERE CupomID = ?", ((erro or '')[:400], cupom_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obter_cupom(cupom_id)


# ==============================================================================
# == 5) Conferir, vincular e lançar ============================================
# ==============================================================================

def _ean_do_codigo(codigo):
    """Muitos mercados usam o código de barras (EAN) como código do produto no cupom."""
    d = re.sub(r'\D', '', str(codigo or ''))
    return d if len(d) in (8, 12, 13, 14) and d.strip('0') else None


def _reconhecer(fornecedor_id, it):
    """Mesmo reconhecimento da importação do XML (descrição, código, EAN)."""
    if not fornecedor_id:
        return None
    return database.buscar_vinculo_inteligente(fornecedor_id, it['descricao'], cprod=it['codigo'],
                                               ean=_ean_do_codigo(it['codigo']))


def obter_cupom(cupom_id):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT CupomID, Chave, Url, ListaCodigo, CNPJ, Emitente, Numero, Serie, DataEmissao, ValorTotal,
                              Descontos, ValorPagar, Status, Erro, LidoPorID, LidoPor, LidoEm, LancadoPor, LancadoEm
                       FROM CompraCupons WHERE CupomID = ?""", (int(cupom_id),))
        r = cur.fetchone()
        if not r:
            raise ErroCompras("Cupom não encontrado.")
        cur.execute("""SELECT Seq, Codigo, Descricao, Qtd, Unidade, ValorUnit, ValorTotal, Acao, ProdutoID, Fator
                       FROM CompraCupomItens WHERE CupomID = ? ORDER BY Seq""", (int(cupom_id),))
        linhas = cur.fetchall()
        pids = {l[8] for l in linhas if l[8]}
        nomes = {}
        if pids:
            cur.execute(f"SELECT ProdutoID, NomeProduto, UnidadeMedida FROM ProdutosEstoque WHERE ProdutoID IN ({','.join('?' * len(pids))})",
                        list(pids))
            nomes = {p[0]: (p[1], (p[2] or 'UN').strip() or 'UN') for p in cur.fetchall()}
    finally:
        conn.close()
    cupom = {'id': r[0], 'chave': r[1], 'url': r[2], 'lista_codigo': r[3], 'cnpj': r[4], 'emitente': r[5] or '',
             'numero': r[6], 'serie': r[7], 'data_emissao': _iso(_como_datahora(r[8])), 'valor_total': _num(r[9], 2),
             'descontos': _num(r[10], 2), 'valor_pagar': _num(r[11], 2), 'status': r[12], 'erro': r[13],
             'lido_por_id': r[14], 'lido_por': r[15], 'lido_em': _iso(_como_datahora(r[16])),
             'lancado_por': r[17], 'lancado_em': _iso(_como_datahora(r[18]))}
    fornecedor_id = database.buscar_fornecedor_por_cnpj(cupom['cnpj']) if cupom['cnpj'] else None
    cupom['fornecedor_cadastrado'] = bool(fornecedor_id)
    pendentes = 0
    itens = []
    for seq, codigo, desc, qtd, un, vun, vtot, acao, pid, fator in linhas:
        if vun is None and qtd and _dec(qtd) > 0:
            vun = _dec(vtot) / _dec(qtd)                       # cupom lido antes da correção do MT
        it = {'seq': seq, 'codigo': codigo or '', 'descricao': desc, 'qtd': _num(qtd), 'unidade': un or '',
              'valor_unit': _num(vun, 4), 'valor_total': _num(vtot, 2), 'acao': acao or ''}
        if acao == ACAO_IGNORAR:
            it['situacao'] = 'ignorado'
        elif acao == ACAO_VINCULAR and pid:
            nome, unp = nomes.get(pid, (f'Produto {pid} (apagado?)', 'UN'))
            it.update({'situacao': 'vinculado', 'produto_id': pid, 'produto': nome, 'unidade_produto': unp,
                       'fator': _num(fator or 1)})
        else:
            v = _reconhecer(fornecedor_id, {'descricao': desc, 'codigo': codigo}) if cupom['status'] == ST_PENDENTE else None
            if v and v.get('ProdutoID'):
                pid2 = v['ProdutoID']
                if pid2 not in nomes:
                    nomes.update(_nomes_produtos([pid2]))
                nome, unp = nomes.get(pid2, (f'Produto {pid2}', 'UN'))
                it.update({'situacao': 'reconhecido', 'produto_id': pid2, 'produto': nome, 'unidade_produto': unp,
                           'fator': _num(v['Fator'] or 1), 'vinculo_id': v['ProdutoFornecedorID']})
            else:
                it['situacao'] = 'pendente'
                pendentes += 1
        if it.get('fator') and it.get('qtd'):
            it['qtd_estoque'] = _num(Decimal(str(it['qtd'])) * Decimal(str(it['fator'])))
        itens.append(it)
    cupom['itens'] = itens
    cupom['pendentes'] = pendentes if cupom['status'] == ST_PENDENTE else 0
    cupom['pode_lancar'] = cupom['status'] == ST_PENDENTE and pendentes == 0 and bool(itens)
    return cupom


def _nomes_produtos(pids):
    conn = database.get_db_connection()
    if not conn or not pids:
        return {}
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT ProdutoID, NomeProduto, UnidadeMedida FROM ProdutosEstoque WHERE ProdutoID IN ({','.join('?' * len(pids))})",
                    list(pids))
        return {p[0]: (p[1], (p[2] or 'UN').strip() or 'UN') for p in cur.fetchall()}
    finally:
        conn.close()


def listar_cupons(dias=60):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT C.CupomID, C.Emitente, C.CNPJ, C.Numero, C.DataEmissao, C.ValorPagar, C.Status, C.LidoPor, C.LidoEm,
                              (SELECT COUNT(*) FROM CompraCupomItens I WHERE I.CupomID = C.CupomID), C.Erro
                       FROM CompraCupons C""")
        limite = datetime.now().timestamp() - dias * 86400
        cupons = []
        for r in cur.fetchall():
            lido = _como_datahora(r[8])
            if r[6] in (ST_IMPORTADO, ST_JA_LANCADO) and lido and lido.timestamp() < limite:
                continue
            cupons.append({'id': r[0], 'emitente': r[1] or f"CNPJ {r[2]}", 'numero': r[3],
                           'data_emissao': _iso(_como_datahora(r[4])), 'valor_pagar': _num(r[5], 2), 'status': r[6],
                           'lido_por': r[7], 'lido_em': _iso(lido), 'qtd_itens': int(r[9] or 0), 'erro': r[10]})
        ordem = {ST_PENDENTE: 0, ST_ERRO: 1, ST_IMPORTADO: 2, ST_JA_LANCADO: 3}
        cupons.sort(key=lambda c: (ordem.get(c['status'], 9), '' if not c['lido_em'] else c['lido_em']), reverse=False)
        abertos = [c for c in cupons if c['status'] in (ST_PENDENTE, ST_ERRO)]
        fechados = sorted([c for c in cupons if c['status'] not in (ST_PENDENTE, ST_ERRO)], key=lambda c: c['lido_em'] or '', reverse=True)
        return abertos + fechados[:30]
    finally:
        conn.close()


def resolver_item(cupom_id, seq, acao, usuario, produto_id=None, fator=None):
    """
    O gestor decide um item do cupom:
      acao 'vincular': é o produto 'produto_id'; 1 unidade do cupom = 'fator' unidades do estoque;
      acao 'ignorar' : não é do estoque (ex.: café da equipe, sacola);
      acao ''        : desfaz a decisão.
    """
    if not usuario.get('gestor'):
        raise ErroCompras("Só o gestor vincula itens do cupom.")
    cupom = obter_cupom(cupom_id)
    if cupom['status'] != ST_PENDENTE:
        raise ErroCompras("Este cupom não está mais aberto para conferência.")
    if not any(i['seq'] == int(seq) for i in cupom['itens']):
        raise ErroCompras("Item do cupom não encontrado.")
    valores = (None, None, None)
    if acao == ACAO_VINCULAR:
        try:
            produto_id = int(produto_id)
            f = Decimal(str(fator).replace(',', '.')) if fator not in (None, '') else Decimal('1')
        except (TypeError, ValueError, InvalidOperation):
            raise ErroCompras("Produto ou quantidade por embalagem inválidos.")
        if not f.is_finite() or f <= 0 or f > 100000:
            raise ErroCompras("Quantidade por embalagem precisa ser maior que zero.")
        if not _nomes_produtos([produto_id]):
            raise ErroCompras("Produto não encontrado no estoque.")
        valores = (ACAO_VINCULAR, produto_id, f)
    elif acao == ACAO_IGNORAR:
        valores = (ACAO_IGNORAR, None, None)
    elif acao not in ('', None):
        raise ErroCompras("Ação inválida.")
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE CompraCupomItens SET Acao = ?, ProdutoID = ?, Fator = ? WHERE CupomID = ? AND Seq = ?",
                    valores + (int(cupom_id), int(seq)))
        conn.commit()
    finally:
        conn.close()
    return obter_cupom(cupom_id)


def lancar_cupom(cupom_id, usuario):
    """
    Transforma o cupom numa NOTA DE ENTRADA, igual à importação do XML:
      - cadastra o mercado como fornecedor (se ainda não existir);
      - cria os vínculos novos (descrição/código do cupom -> produto do estoque, com o Qtd/Cx);
      - custo de cada item = valor do item - parte do desconto, dividido pela quantidade em unidades do estoque;
      - itens "não é do estoque" ficam fora (valor fora do estoque da nota).
    """
    if not usuario.get('gestor'):
        raise ErroCompras("Só o gestor lança cupons no estoque.")
    cupom = obter_cupom(cupom_id)
    if cupom['status'] != ST_PENDENTE:
        raise ErroCompras("Este cupom não está aberto para lançar.")
    if cupom['pendentes']:
        raise ErroCompras(f"Ainda há {cupom['pendentes']} item(ns) sem produto. Vincule ou marque 'não é do estoque'.")
    if _nota_ja_lancada(cupom['cnpj'], cupom['numero'], cupom.get('serie'), cupom.get('chave')):
        _mudar_status(cupom_id, ST_JA_LANCADO, usuario, "Esta nota já estava no estoque.")
        raise ErroCompras("Esta nota já está no estoque (o XML dela foi importado). Nada foi lançado de novo.")

    fornecedor_id = database.buscar_fornecedor_por_cnpj(cupom['cnpj'])
    if not fornecedor_id:
        database.criar_fornecedor(cupom['cnpj'], (cupom['emitente'] or f"Fornecedor {cupom['cnpj']}")[:150])
        fornecedor_id = database.buscar_fornecedor_por_cnpj(cupom['cnpj'])
        if not fornecedor_id:
            raise ErroCompras("Não consegui cadastrar o mercado como fornecedor (veja o log).")

    itens = cupom['itens']
    soma = sum((Decimal(str(i['valor_total'])) for i in itens), Decimal('0'))
    desconto = Decimal(str(cupom['descontos'] or 0))
    if soma > 0 and cupom['valor_pagar'] is not None:
        # usa a diferença real entre a soma dos itens e o valor pago (pega desconto e acréscimo);
        # se a diferença for absurda (página lida errado), fica só com o desconto informado
        diferenca = soma - Decimal(str(cupom['valor_pagar']))
        if abs(diferenca) <= soma / 2:
            desconto = diferenca
    itens_nota, fora = [], Decimal('0')
    for i in itens:
        total_item = Decimal(str(i['valor_total']))
        liquido = total_item - (desconto * total_item / soma if soma > 0 else Decimal('0'))
        if i['situacao'] == 'ignorado':
            fora += liquido
            continue
        fator = Decimal(str(i['fator'] or 1))
        vinculo_id = i.get('vinculo_id')
        if i['situacao'] == 'vinculado' or not vinculo_id:
            v = database.buscar_vinculo_inteligente(fornecedor_id, i['descricao'], cprod=i['codigo'], ean=_ean_do_codigo(i['codigo']))
            if v and v['ProdutoID'] == i['produto_id'] and _dec(v['Fator'] or 1) == fator:
                vinculo_id = v['ProdutoFornecedorID']
            else:
                vinculo_id = database.criar_vinculo_produto_fornecedor(
                    i['produto_id'], fornecedor_id, i['descricao'][:255], (i['codigo'] or None),
                    _ean_do_codigo(i['codigo']) or '', '', fator)
                if not vinculo_id:
                    raise ErroCompras(f"Não consegui criar o vínculo de '{i['descricao']}' (veja o log).")
        qtd_estoque = Decimal(str(i['qtd'])) * fator
        itens_nota.append({'ProdutoFornecedorID': int(vinculo_id), 'Quantidade': qtd_estoque,
                           'PrecoCustoUnitario': (liquido / qtd_estoque) if qtd_estoque > 0 else Decimal('0'),
                           'FatorUsado': fator})
    if not itens_nota:
        raise ErroCompras("Nenhum item do cupom é do estoque: nada para lançar. (Se quiser, apague o cupom.)")
    data = _como_datahora(cupom['data_emissao'])
    cabecalho = {'NumeroNF': cupom['numero'], 'FornecedorID': fornecedor_id,
                 'DataEmissao': (data.date() if data else date.today()),
                 'ValorTotalNF': Decimal(str(cupom['valor_pagar'] if cupom['valor_pagar'] is not None else soma)),
                 'ValorForaDoEstoque': fora.quantize(Decimal('0.01')),
                 'Serie': cupom.get('serie'), 'ChaveAcesso': cupom.get('chave')}
    ok, msg = database.salvar_nota_fiscal_completa(cabecalho, itens_nota)
    if not ok:
        raise ErroCompras(msg)
    _mudar_status(cupom_id, ST_IMPORTADO, usuario)
    logger.info(f"Cupom {cupom['chave']} lançado no estoque por {usuario.get('nome')}: {len(itens_nota)} itens.")
    return obter_cupom(cupom_id)


def _mudar_status(cupom_id, status, usuario, erro=None):
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE CompraCupons SET Status = ?, Erro = ?, LancadoPor = ?, LancadoEm = ? WHERE CupomID = ?",
                    (status, erro, usuario.get('nome'), datetime.now(), int(cupom_id)))
        conn.commit()
    finally:
        conn.close()


def apagar_cupom(cupom_id, usuario):
    """Apaga um cupom lido por engano (só se ainda não foi lançado)."""
    cupom = obter_cupom(cupom_id)
    if not usuario.get('gestor') and cupom['lido_por_id'] != usuario.get('id'):
        raise ErroCompras("Só o gestor ou quem leu o cupom pode apagar.")
    if cupom['status'] == ST_IMPORTADO:
        raise ErroCompras("Cupom já lançado no estoque: para desfazer, exclua a nota no Gestão de Estoque.")
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM CompraCupomItens WHERE CupomID = ?", (int(cupom_id),))
        cur.execute("DELETE FROM CompraCupons WHERE CupomID = ?", (int(cupom_id),))
        conn.commit()
    finally:
        conn.close()
    return {'ok': True}


# ==============================================================================
# == 6) Produto que ainda NÃO existe no estoque =================================
# ==============================================================================

def listar_categorias():
    """Categorias do catálogo do Gestão de Estoque (para o produto novo)."""
    try:
        categorias = database.listar_categorias_produto() or []
    except Exception as e:
        logger.warning(f"Não consegui listar as categorias: {e}")
        categorias = []
    return sorted(set(categorias) | {'Geral'}, key=lambda c: cd.database_normalizar(c))


def criar_produto_do_cupom(cupom_id, seq, usuario, nome, unidade, categoria='Geral', estoque_minimo=0, fator=1):
    """
    Cadastra no catálogo do estoque um produto que veio no cupom e ainda não existia
    (ex.: tomate) e já deixa o item do cupom vinculado a ele.
    É o mesmo cadastro do Catálogo do Gestão de Estoque: lá ele aparece igual aos outros.
    """
    if not usuario.get('gestor'):
        raise ErroCompras("Só o gestor cadastra produtos.")
    nome = re.sub(r'\s+', ' ', str(nome or '')).strip()
    unidade = re.sub(r'[^A-Za-z]', '', str(unidade or '')).upper()[:10]
    categoria = (str(categoria or '').strip() or 'Geral')[:100]
    if len(nome) < 3:
        raise ErroCompras("Digite o nome do produto (pelo menos 3 letras).")
    if len(nome) > 100:
        raise ErroCompras("Nome muito comprido (máximo 100 letras).")
    if not unidade:
        raise ErroCompras("Escolha a unidade (UN, KG, L...).")
    try:
        minimo = Decimal(str(estoque_minimo or 0).replace(',', '.'))
    except InvalidOperation:
        raise ErroCompras("Estoque mínimo inválido.")
    if not minimo.is_finite() or minimo < 0:
        raise ErroCompras("Estoque mínimo inválido.")
    cupom = obter_cupom(cupom_id)
    if cupom['status'] != ST_PENDENTE:
        raise ErroCompras("Este cupom não está mais aberto para conferência.")
    if not any(i['seq'] == int(seq) for i in cupom['itens']):
        raise ErroCompras("Item do cupom não encontrado.")
    # não deixa criar o mesmo produto duas vezes (ignora maiúsculas e acentos)
    alvo = cd.database_normalizar(nome)
    for p in cd.buscar_produtos(nome, limite=500):
        if cd.database_normalizar(p['nome']) == alvo:
            raise ErroCompras(f"Já existe o produto '{p['nome']}' no estoque. Use a busca para escolher ele.")
    produto_id = database.criar_produto_estoque(nome, unidade, minimo, categoria)
    if not produto_id:
        raise ErroCompras("Não consegui cadastrar o produto (veja o log).")
    logger.info(f"Produto '{nome}' ({unidade}) cadastrado pelo app de compras por {usuario.get('nome')}.")
    return resolver_item(cupom_id, seq, ACAO_VINCULAR, usuario, produto_id=int(produto_id), fator=fator)


# ==============================================================================
# == 7) Código de barras por FOTO (quando o celular não lê ao vivo) ============
# ==============================================================================
# A leitura ao vivo pela câmera só existe no Chrome do Android e só no endereço
# https. No Wi-Fi da loja (http) ou no iPhone, o app tira uma FOTO do código de
# barras e manda para cá; o OpenCV do computador da loja lê o código.

def ler_codigo_barras_da_foto(dados_imagem):
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise ErroCompras("O computador da loja não tem o leitor instalado. Rode: pip install opencv-python-headless")
    if not hasattr(cv2, 'barcode'):
        raise ErroCompras("O OpenCV do computador da loja é antigo. Rode: pip install --upgrade opencv-python-headless")
    if isinstance(dados_imagem, str):
        if ',' in dados_imagem[:100]:
            dados_imagem = dados_imagem.split(',', 1)[1]
        try:
            dados_imagem = base64.b64decode(dados_imagem, validate=False)
        except (ValueError, TypeError):
            raise ErroCompras("Foto inválida.")
    if not dados_imagem or len(dados_imagem) > 12 * 1024 * 1024:
        raise ErroCompras("Foto vazia ou grande demais.")
    img = cv2.imdecode(np.frombuffer(dados_imagem, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ErroCompras("Não consegui abrir a foto. Tire outra.")
    det = cv2.barcode.BarcodeDetector()
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    alt, larg = cinza.shape[:2]
    tentativas = [img, cinza]
    for escala in (0.5, 1.5):
        if max(alt, larg) * escala <= 4000:
            tentativas.append(cv2.resize(cinza, None, fx=escala, fy=escala,
                                         interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC))
    tentativas.append(cv2.rotate(cinza, cv2.ROTATE_90_CLOCKWISE))       # foto tirada "em pé"
    for t in tentativas:
        try:
            resultado = det.detectAndDecodeWithType(t)
        except cv2.error:
            continue
        textos = resultado[1] if len(resultado) >= 2 else ()
        for texto in textos or ():
            digitos = re.sub(r'\D', '', texto or '')
            if 8 <= len(digitos) <= 14:
                return digitos
    raise ErroCompras("Não achei o código de barras na foto. Chegue perto, com luz, com as barras retas e inteiras na foto.")
