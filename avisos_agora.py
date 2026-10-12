"""
[AVISOS DE AGORA] Cada aviso da gestão montado NA HORA, para ver pelo app (Gestão › 📣 Avisos) sem esperar
o horário do robô. Usa as mesmas contas do robô (agendador.py) e NÃO marca nada como enviado: o grupo
continua recebendo no horário de sempre.

Previsão e sugestão: se a previsão do clima tem mais de 1 hora, busca de novo antes de montar (no máximo
uma busca a cada 15 minutos). As notas da SEFAZ continuam chegando de hora em hora (a SEFAZ bloqueia
quem consulta mais vezes): aqui aparece o que já chegou e está esperando o resumo das 12h/18h.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal

import alertas_estoque
import clima
import database
import folha_faturamento as ff

logger = logging.getLogger(__name__)

ARQUIVO_ESTADO_ROBO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agendador_estado.json')  # só leitura
ORDEM = ['previsao', 'sugestao', 'resultado', 'faturamento', 'lembrete', 'estoque', 'notas', 'precos']
CLIMA_VELHO_MIN = 60          # previsão com mais de 1 hora: busca de novo
CLIMA_INTERVALO_MIN = 15      # no máximo 1 busca a cada 15 minutos (vários celulares abrindo juntos)
MAX_NOTAS = 25

_trava_clima = threading.Lock()
_ultima_busca_clima = {'t': -1e9}


def _estado_robo():
    """O que o robô guardou (fila das notas, último resumo). Arquivo do agendador: aqui só lê."""
    try:
        with open(ARQUIVO_ESTADO_ROBO, 'r', encoding='utf-8') as f:
            dados = json.load(f)
            return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _como_datahora(v):
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return None


def _clima_atualizado_em(hoje):
    """Quando a previsão (hoje em diante) foi atualizada pela última vez."""
    conn = database.get_db_connection()
    if not conn:
        raise ff.ErroFolha("Sem conexão com o banco de dados.")
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(AtualizadoEm) FROM ClimaDiario WHERE Data >= ?", str(hoje))
        r = cur.fetchone()
        return _como_datahora(r[0]) if r else None
    finally:
        conn.close()


def clima_fresco(agora=None, http=None):
    """Previsão com mais de 1 hora: busca agora. Devolve (quando a previsão foi atualizada, erro ou None)."""
    agora = agora or datetime.now()
    clima.garantir_tabela()
    erro = None
    with _trava_clima:
        quando = _clima_atualizado_em(agora.date())
        velha = quando is None or agora - quando > timedelta(minutes=CLIMA_VELHO_MIN)
        if velha and time.monotonic() - _ultima_busca_clima['t'] > CLIMA_INTERVALO_MIN * 60:
            _ultima_busca_clima['t'] = time.monotonic()
            try:
                clima.atualizar(http, agora.date())
                quando = _clima_atualizado_em(agora.date())
            except clima.ErroClima as e:
                erro = str(e)
                logger.warning(f"Avisos de agora: {e}")
    return quando, erro


def _nota_clima(agora):
    quando, erro = clima_fresco(agora)
    if erro:
        return f"⚠️ Não consegui atualizar o clima agora ({erro})" + (f": usando a previsão das {quando:%H:%M}." if quando else ".")
    if quando:
        return f"🌡️ Previsão do clima atualizada {'hoje' if quando.date() == agora.date() else f'em {quando:%d/%m}'} às {quando:%H:%M}."
    return ''


# ------------------------------------------------------------------------------
# Um montador por aviso: devolve (texto, mensagem se não tem nada, observação)
# ------------------------------------------------------------------------------
def _previsao(agora):
    nota = _nota_clima(agora)
    return ff.boletim_previsao(agora), "Ainda sem a previsão do clima (o robô busca de 3 em 3 horas).", nota


def _sugestao(agora):
    nota = _nota_clima(agora)
    hoje = agora.date()
    datas = ff.dias_da_sugestao(hoje) or [hoje + timedelta(days=1)]
    return ff.texto_sugestao(datas, hoje), "Ainda sem a previsão do clima para esse dia.", nota


def _resultado(agora):
    hoje = agora.date()
    datas = ff.resultados_recentes(hoje)
    if not datas:
        return '', "Ainda não tem dia com 🔮 sugestão enviada e faturamento lançado (últimos 7 dias).", ''
    d = datas[-1]
    nota = ("⏳ O dia ainda não fechou: no grupo, o resultado vai depois das 21h."
            if d == hoje and agora.hour < ff.HORA_RESUMO_HOJE else '')
    return ff.texto_resultado([d], hoje), "Sem média dos dias parecidos para comparar.", nota


def _faturamento(agora):
    d = ff.ultimo_dia_lancado(agora.date())
    if not d:
        return '', "Nenhum faturamento lançado nos últimos 60 dias.", ''
    return ff.texto_telegram([d], agora), '', f"Resumo do último dia lançado ({ff.DIAS_SEMANA[d.weekday()]} {d:%d/%m})."


def _lembrete(agora):
    faltam = ff.dias_sem_faturamento(agora.date())
    return ff.texto_lembrete(faltam, agora.date()), "✅ Os faturamentos dos últimos 7 dias estão todos lançados.", ''


def _estoque(agora):
    texto = alertas_estoque.montar_avisos_diarios(agora.date(), agora)
    return (texto, "✅ Nada acabando, abaixo do mínimo ou lista esquecida agora.",
            "Aqui aparece a lista completa; no grupo, às 08:30, vai só o que entrou de novo.")


def _reais(v):
    try:
        return ff._reais(Decimal(str(v)))
    except Exception:
        return '—'


def _notas(agora):
    estado = _estado_robo()
    fila = estado.get('notas_novas_fila') or []
    linhas = []
    if fila:
        linhas.append(f"📥 <b>{len(fila)} nota(s) nova(s) da SEFAZ</b> esperando o próximo resumo")
        linhas += [f"• {alertas_estoque.esc(n.get('emitente') or 'Fornecedor')} · {_reais(n.get('valor'))}" for n in fila[:MAX_NOTAS]]
        if len(fila) > MAX_NOTAS:
            linhas.append(f"<i>… e mais {len(fila) - MAX_NOTAS}</i>")
        try:
            import cadastro_franquia
            novos = cadastro_franquia.produtos_novos_nas_notas([n.get('chave') for n in fila])
            if novos:
                linhas.append(f"🏷️ <b>{novos} produto(s) novo(s)</b> nestas notas: cadastre na aba <b>🏷️ Cadastro Franquia</b>.")
        except Exception as e:
            logger.warning(f"Avisos de agora: produtos novos das notas: {e}")
    try:
        import orcamentos
        textos = [t for _, t in orcamentos.avisos_pendentes(marcar=False)]
    except Exception as e:
        logger.warning(f"Avisos de agora: orçamentos que chegaram: {e}")
        textos = []
    if textos:
        linhas += ([''] if linhas else []) + textos
    turno = estado.get('resumo_notas_turno') or ''
    nota = "A busca na SEFAZ é de hora em hora (mais rápido a SEFAZ bloqueia)."
    if len(turno) >= 16:
        try:
            quando = datetime.fromisoformat(turno[:10])
            nota = (f"Último resumo no grupo: {'hoje' if quando.date() == agora.date() else f'{quando:%d/%m}'} às {turno[-5:]}. "
                    + nota)
        except ValueError:
            pass
    return "\n".join(linhas), "Nenhuma nota nova nem orçamento esperando o próximo resumo (12h/18h).", nota


def _precos(agora):
    texto, _ = alertas_estoque.montar_resumo_precos(desde_data=agora.date() - timedelta(days=7))
    return texto, "Nenhum aumento de preço nas notas dos últimos 7 dias.", "No grupo: toda segunda, com as notas da semana."


MONTADORES = {'previsao': _previsao, 'sugestao': _sugestao, 'resultado': _resultado, 'faturamento': _faturamento,
              'lembrete': _lembrete, 'estoque': _estoque, 'notas': _notas, 'precos': _precos}


def lista():
    """Os avisos que dá para ver agora, na ordem da tela (nome e horário do grupo vêm de TIPOS_AVISO)."""
    tipos = {c: (n, q) for c, n, q, _ in alertas_estoque.TIPOS_AVISO}
    return [{'tipo': t, 'nome': tipos.get(t, (t, ''))[0], 'quando': tipos.get(t, ('', ''))[1]} for t in ORDEM]


def ver(tipo, agora=None):
    """Um aviso montado agora: {'texto' (HTML), 'vazio', 'nota', 'ligado', 'gerado', 'erro'}."""
    if tipo not in MONTADORES:
        raise ValueError("Aviso desconhecido.")
    agora = agora or datetime.now()
    r = {'tipo': tipo, 'texto': '', 'vazio': '', 'nota': '', 'erro': '', 'gerado': f"{agora:%H:%M}",
         'ligado': alertas_estoque.aviso_ligado(tipo)}
    try:
        texto, vazio, nota = MONTADORES[tipo](agora)
        r.update(texto=texto or '', vazio='' if texto else vazio, nota=nota or '')
    except Exception as e:
        logger.error(f"Avisos de agora ({tipo}): {e}", exc_info=True)
        r['erro'] = f"Não consegui montar este aviso agora: {e}"
    return r
