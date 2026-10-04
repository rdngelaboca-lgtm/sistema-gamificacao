# ==============================================================================
# diagnosticar_cupom.py - DESCOBRIR POR QUE O CUPOM (QR CODE) NÃO FOI LIDO
# ------------------------------------------------------------------------------
# Não grava NADA no banco. Só abre a página da SEFAZ, guarda uma cópia e mostra
# o que o sistema conseguiu (ou não) entender.
#
# Como usar (no computador da loja, com o ambiente virtual ativado):
#     python diagnosticar_cupom.py
# e cole o LINK do QR Code (o mesmo que você colaria no app)
# ou só a CHAVE DE ACESSO (os 44 números impressos no cupom).
#
# As páginas baixadas ficam em logs/cupons/diag_....html
# ==============================================================================
import re
import sys
import os
from urllib.parse import urlparse, urljoin

try:
    import requests
except ImportError:
    print("\n[ERRO] Falta a biblioteca 'requests'. Rode:  pip install requests")
    sys.exit(1)

try:
    import compras_cupom as cc
except Exception as erro:
    print(f"\n[ERRO] Não consegui carregar o compras_cupom.py: {erro}")
    sys.exit(1)

# Endereço da consulta pública da NFC-e de cada estado (código do estado = 2 primeiros números da chave)
CONSULTA_POR_UF = {
    '51': 'https://www.sefaz.mt.gov.br/nfce/consultanfce',
}


def linha(t=''):
    print(t, flush=True)


def baixar_mostrando(url, sessao, metodo='GET', dados=None):
    """Baixa a página mostrando cada passo (redirecionamentos, código de resposta, tamanho)."""
    atual = url
    for passo in range(1, 7):
        host = (urlparse(atual).hostname or '').lower()
        if not host.endswith('.gov.br'):
            linha(f"  [PARA] O site mandou para fora do governo: {atual}")
            return None, atual
        try:
            try:
                r = sessao.request(metodo, atual, data=dados, timeout=cc.TEMPO_LIMITE_SEFAZ, allow_redirects=False)
            except requests.exceptions.SSLError as e:
                linha(f"  [AVISO] Certificado não reconhecido ({e.__class__.__name__}); tentando sem conferir.")
                r = sessao.request(metodo, atual, data=dados, timeout=cc.TEMPO_LIMITE_SEFAZ,
                                   allow_redirects=False, verify=False)
        except requests.exceptions.RequestException as e:
            linha(f"  [ERRO] Não consegui abrir {atual}")
            linha(f"         {e.__class__.__name__}: {e}")
            return None, atual
        linha(f"  passo {passo}: {r.status_code}  {r.headers.get('Content-Type', '?')}  "
              f"{len(r.content)} bytes  {r.url}")
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get('Location'):
            atual = urljoin(atual, r.headers['Location'])
            linha(f"          -> redireciona para {atual}")
            metodo, dados = 'GET', None
            continue
        bruto = r.content
        for cod in ('utf-8', r.encoding or 'latin-1', 'latin-1'):
            try:
                return bruto.decode(cod), atual
            except (UnicodeDecodeError, LookupError):
                continue
        return bruto.decode('utf-8', errors='replace'), atual
    linha("  [ERRO] Redirecionou vezes demais.")
    return None, atual


def guardar(nome, html):
    os.makedirs(cc.PASTA_DIAGNOSTICO, exist_ok=True)
    caminho = os.path.join(cc.PASTA_DIAGNOSTICO, nome)
    with open(caminho, 'w', encoding='utf-8') as f:
        f.write(html or '')
    return caminho


def raio_x(html):
    """Mostra o 'esqueleto' da página: título, formulários, campos, captcha, scripts."""
    baixo = html.lower()
    titulo = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I)
    linha(f"  Título da página: {cc._texto(titulo.group(1)) if titulo else '(sem título)'}")
    linha(f"  Tem a tabela de itens padrão (tabResult)? {'SIM' if 'tabresult' in baixo else 'não'}")
    qtd_linhas = len(re.findall(r'<tr[^>]*id\s*=\s*["\']Item', html, re.I))
    linha(f"  Linhas de item (id=Item...)? {qtd_linhas}")
    for palavra in ('captcha', 'recaptcha', 'hcaptcha', 'turnstile', 'iframe', 'frameset'):
        if palavra in baixo:
            linha(f"  [!] A página contém '{palavra}'")
    linha(f"  Scripts (<script>): {len(re.findall(r'<script', html, re.I))}")
    refresh = re.search(r'http-equiv=["\']?refresh["\']?[^>]*content=["\']([^"\']+)', html, re.I)
    if refresh:
        linha(f"  [!] A página manda recarregar/ir para: {refresh.group(1)}")
    for m in re.finditer(r'<form\b([^>]*)>(.*?)</form>', html, re.S | re.I):
        atributos = m.group(1)
        acao = re.search(r'action\s*=\s*["\']([^"\']*)', atributos, re.I)
        met = re.search(r'method\s*=\s*["\']?(\w+)', atributos, re.I)
        linha(f"  Formulário: método={met.group(1).upper() if met else 'GET'}  envia para={acao.group(1) if acao else '(mesma página)'}")
        for c in re.finditer(r'<(input|select|textarea)\b([^>]*)>', m.group(2), re.I):
            nome = re.search(r'name\s*=\s*["\']([^"\']*)', c.group(2), re.I)
            tipo = re.search(r'type\s*=\s*["\']([^"\']*)', c.group(2), re.I)
            if nome:
                linha(f"     campo: {nome.group(1)}  ({tipo.group(1) if tipo else c.group(1)})")
    texto = cc._texto(html)
    linha("  Começo do texto da página:")
    linha("     " + (texto[:700] or '(página sem texto)'))


def tentar_ler(html):
    """Roda o MESMO leitor que o app usa e mostra o resultado."""
    try:
        p = cc.interpretar_pagina(html)
    except cc.ErroCompras as e:
        linha(f"  RESULTADO: NÃO LEU -> {e}")
        return False
    linha(f"  RESULTADO: LEU OK! Mercado: {p['emitente_nome']}  CNPJ: {p['emitente_cnpj']}  Emissão: {p['data_emissao']}")
    for it in p['itens']:
        linha(f"     {it['seq']:>3}. {it['descricao'][:45]:<45} {it['qtd']} {it['unidade']} x {it['valor_unit']} = {it['valor_total']}")
    linha(f"  Soma dos itens: {p['soma_itens']}  Total: {p['valor_total']}  Descontos: {p['descontos']}  A pagar: {p['valor_pagar']}")
    return True


def diagnosticar(entrada):
    sessao = requests.Session()
    sessao.headers.update({'User-Agent': cc.NAVEGADOR, 'Accept': 'text/html,application/xhtml+xml',
                           'Accept-Language': 'pt-BR,pt;q=0.9'})
    linha("\n1) CHAVE DE ACESSO")
    try:
        chave, url = cc.extrair_chave(entrada)
    except cc.ErroCompras as e:
        linha(f"  [ERRO] {e}")
        linha(f"  Texto recebido ({len(entrada)} letras): {entrada[:200]!r}")
        return
    info = cc.dados_da_chave(chave)
    linha(f"  Chave: {chave}  (dígito verificador OK)")
    linha(f"  Estado {info['uf']} · {info['ano_mes']} · CNPJ {info['cnpj']} · modelo {info['modelo']} · série {info['serie']} · nº {info['numero']}")

    if url:
        linha("\n2) ABRINDO O LINK DO QR CODE (igual o app faz)")
        linha(f"  {url}")
        try:
            cc.endereco_seguro(url)
        except cc.ErroCompras as e:
            linha(f"  [ERRO] {e}")
            return
        html, final = baixar_mostrando(url, sessao)
        if html is None:
            return
        linha(f"  Página guardada em: {guardar(f'diag_{chave}_qr.html', html)}")
        linha("\n3) RAIO-X DA PÁGINA")
        raio_x(html)
        linha("\n4) LEITURA DOS ITENS")
        tentar_ler(html)
        return

    linha("\n2) SÓ A CHAVE: procurando a consulta por chave no site da SEFAZ")
    base = CONSULTA_POR_UF.get(info['uf'])
    if not base:
        linha(f"  Ainda não sei o endereço da consulta do estado {info['uf']}.")
        return
    html, final = baixar_mostrando(base, sessao)
    if html is not None:
        linha(f"  Página guardada em: {guardar(f'diag_{chave}_consulta.html', html)}")
        linha("\n3) RAIO-X DA PÁGINA DE CONSULTA (para descobrir como ela recebe a chave)")
        raio_x(html)
    linha("\n4) TESTANDO JEITOS DE MANDAR SÓ A CHAVE")
    for nome, teste in (('p=chave', f"{base}?p={chave}"), ('chNFe=chave', f"{base}?chNFe={chave}"),
                        ('chave=chave', f"{base}?chave={chave}")):
        linha(f"\n  -- {nome}")
        html, final = baixar_mostrando(teste, sessao)
        if html is None:
            continue
        guardar(f"diag_{chave}_{nome.split('=')[0]}.html", html)
        if tentar_ler(html):
            linha(f"  >>> ESTE FUNCIONA: {nome}")


def main():
    if len(sys.argv) > 1:
        entrada = ' '.join(sys.argv[1:])
    else:
        linha("Cole o LINK do QR Code do cupom (ou só a CHAVE de 44 números) e aperte Enter:")
        entrada = input("> ")
    diagnosticar(entrada.strip())
    linha("\nPronto. Copie TUDO o que apareceu acima e mande para o Claude.")


if __name__ == '__main__':
    main()
