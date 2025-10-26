# -*- coding: utf-8 -*-
"""
Módulo de conexão com o banco de dados SQL Server.
"""

import os
import logging
import pyodbc
from dotenv import load_dotenv
from typing import List, Tuple, Optional
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
import datetime

# Configura um logging básico
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

# --- Configurações do Banco de Dados ---
DB_SERVER: str | None = os.getenv("DB_SERVER")
DB_DATABASE: str | None = os.getenv("DB_DATABASE")
DB_USERNAME: str | None = os.getenv("DB_USERNAME")
DB_PASSWORD: str | None = os.getenv("DB_PASSWORD")

if not DB_SERVER or not DB_DATABASE:
    error_msg = "Erro crítico: Variáveis de ambiente DB_SERVER ou DB_DATABASE não definidas."
    logging.error(error_msg)
    raise ValueError(error_msg)

# --- Montagem da String de Conexão ---
connection_string: str
# ... (código existente da string de conexão) ...
if not DB_USERNAME:
    connection_string = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_DATABASE};"
        f"Trusted_Connection=yes;"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes;"
    )
else:
    connection_string = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_DATABASE};"
        f"UID={DB_USERNAME};"
        f"PWD={DB_PASSWORD};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes;"
    )


def get_db_connection() -> Optional[pyodbc.Connection]:
    try:
        return pyodbc.connect(connection_string, autocommit=False) # Mudamos autocommit para False para usar transações explícitas
    except pyodbc.Error as ex:
        logging.error(f"Falha ao conectar ao banco: {ex}")
        return None

def get_categories(tipo: str) -> List[Tuple[int, str]]:
    conn = get_db_connection()
    if not conn: return []

    # --- INÍCIO DA CORREÇÃO ---
    # A lógica antiga falharia se novas categorias de receita fossem adicionadas.
    # Esta nova query filtra pela coluna 'Tipo' no banco de dados,
    # que é a forma correta e robusta de separar os tipos.
    query = "SELECT CategoriaID, Nome FROM dbo.Categorias WHERE Tipo = ? ORDER BY Nome;"
    # --- FIM DA CORREÇÃO ---

    try:
        cursor = conn.cursor()

        # --- INÍCIO DA CORREÇÃO ---
        cursor.execute(query, tipo) # Passamos 'Receita' ou 'Despesa' como parâmetro
        # --- FIM DA CORREÇÃO ---

        result = cursor.fetchall()
        # Removido: conn.commit() 
        return result
    except pyodbc.Error as ex:
        logging.error(f"Erro ao buscar categorias: {ex}")
        conn.rollback() 
        return []
    finally:
        if conn: conn.close()

def ensure_user_exists(user_id: int, user_name: str) -> None:
    conn = get_db_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT UsuarioID FROM dbo.Usuarios WHERE UsuarioID = ?", user_id)
        if cursor.fetchone() is None:
            logging.info(f"Usuário {user_name} ({user_id}) não encontrado. Criando novo registro.")
            cursor.execute("INSERT INTO dbo.Usuarios (UsuarioID, NomeUsuario) VALUES (?, ?)", user_id, user_name)
        conn.commit()
    except pyodbc.Error as ex:
        logging.error(f"Erro ao verificar/criar usuário: {ex}")
        conn.rollback()
    finally:
        if conn: conn.close()

def save_lancamento(user_id: int, categoria_id: int, tipo: str, valor: Decimal, descricao: str | None) -> bool:
    conn = get_db_connection()
    if not conn: return False
    query = "INSERT INTO dbo.Lancamentos (UsuarioID, CategoriaID, Tipo, Valor, Descricao) VALUES (?, ?, ?, ?, ?)"
    try:
        cursor = conn.cursor()
        cursor.execute(query, user_id, categoria_id, tipo, valor, descricao)
        conn.commit()
        return True
    except pyodbc.Error as ex:
        logging.error(f"Erro ao salvar lançamento: {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()

def get_latest_lancamentos(user_id: int, limit: int = 10) -> List[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return []
    query = """
        SELECT TOP (?) l.Tipo, l.Valor, c.Nome AS CategoriaNome, l.Descricao, l.DataLancamento
        FROM dbo.Lancamentos AS l JOIN dbo.Categorias AS c ON l.CategoriaID = c.CategoriaID
        WHERE l.UsuarioID = ? ORDER BY l.DataLancamento DESC
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, limit, user_id)
        result = cursor.fetchall()
        # Removido: conn.commit() 
        return result
    except pyodbc.Error as ex:
        logging.error(f"Erro ao buscar extrato para o usuário {user_id}: {ex}")
        conn.rollback()
        return []
    finally:
        if conn: conn.close()


def get_monthly_summary(user_id: int, ano: int, mes: int) -> dict | None:
    conn = get_db_connection()
    if not conn: return None
    
    summary = {
        "total_receitas": Decimal(0),
        "total_despesas": Decimal(0),
        "metas": []
    }
    
    query_totais = """
        SELECT Tipo, COALESCE(SUM(Valor), 0) AS Total
        FROM dbo.Lancamentos
        WHERE UsuarioID = ? AND YEAR(DataLancamento) = ? AND MONTH(DataLancamento) = ?
        GROUP BY Tipo;
    """
    
    query_metas = """
        SELECT 
            c.Nome AS CategoriaNome, m.ValorMeta, COALESCE(gastos.TotalGasto, 0) AS TotalGasto
        FROM dbo.Metas m
        JOIN dbo.Categorias c ON m.CategoriaID = c.CategoriaID
        LEFT JOIN (
            SELECT CategoriaID, SUM(Valor) AS TotalGasto
            FROM dbo.Lancamentos
            WHERE UsuarioID = ? AND Tipo = 'Despesa' AND YEAR(DataLancamento) = ? AND MONTH(DataLancamento) = ?
            GROUP BY CategoriaID
        ) AS gastos ON m.CategoriaID = gastos.CategoriaID
        WHERE m.UsuarioID = ? AND m.Ano = ? AND m.Mes = ?
        ORDER BY c.Nome;
    """
    
    try:
        cursor = conn.cursor()
        
        # Busca Receitas e Despesas
        cursor.execute(query_totais, user_id, ano, mes)
        for row in cursor.fetchall():
            if row.Tipo == 'Receita':
                summary["total_receitas"] = row.Total
            elif row.Tipo == 'Despesa':
                summary["total_despesas"] = row.Total
                
        # Busca progresso das Metas
        cursor.execute(query_metas, user_id, ano, mes, user_id, ano, mes)
        summary["metas"] = cursor.fetchall()
        
        return summary
        
    except pyodbc.Error as ex:
        logging.error(f"Erro ao gerar resumo mensal para usuário {user_id}: {ex}")
        conn.rollback()
        return None
    finally:
        if conn: conn.close()


def get_weekly_summary(user_id: int, end_date: datetime.date) -> Decimal:
    conn = get_db_connection()
    if not conn: return Decimal(0)
    
    start_date = end_date - datetime.timedelta(days=6)
    
    query = """
        SELECT COALESCE(SUM(Valor), 0) AS TotalSemana
        FROM dbo.Lancamentos
        WHERE UsuarioID = ? AND Tipo = 'Despesa' AND DataLancamento BETWEEN ? AND ?;
    """
    
    try:
        cursor = conn.cursor()
        cursor.execute(query, user_id, start_date, end_date)
        total = cursor.fetchval()
        return total or Decimal(0)
        
    except pyodbc.Error as ex:
        logging.error(f"Erro ao gerar resumo semanal para usuário {user_id}: {ex}")
        conn.rollback()
        return Decimal(0)
    finally:
        if conn: conn.close()

def set_meta(user_id: int, categoria_id: int, valor: Decimal, ano: int, mes: int) -> bool:
    conn = get_db_connection()
    if not conn: return False
    query = """
        MERGE dbo.Metas AS target USING (VALUES (?, ?, ?, ?)) AS source (UsuarioID, CategoriaID, Ano, Mes)
        ON target.UsuarioID = source.UsuarioID AND target.CategoriaID = source.CategoriaID AND target.Ano = source.Ano AND target.Mes = source.Mes
        WHEN MATCHED THEN UPDATE SET ValorMeta = ?
        WHEN NOT MATCHED THEN INSERT (UsuarioID, CategoriaID, ValorMeta, Ano, Mes) VALUES (?, ?, ?, ?, ?);
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, user_id, categoria_id, ano, mes, valor, user_id, categoria_id, valor, ano, mes)
        conn.commit()
        return True
    except pyodbc.Error as ex:
        logging.error(f"Erro ao definir meta para o usuário {user_id}: {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()

def get_meta_progress(user_id: int, categoria_id: int, ano: int, mes: int) -> tuple[Optional[Decimal], Optional[Decimal]]:
    conn = get_db_connection()
    if not conn: return None, None
    query = """
        SELECT
            (SELECT m.ValorMeta FROM dbo.Metas m WHERE m.UsuarioID = ? AND m.CategoriaID = ? AND m.Ano = ? AND m.Mes = ?) AS ValorMeta,
            (SELECT SUM(l.Valor) FROM dbo.Lancamentos l WHERE l.UsuarioID = ? AND l.CategoriaID = ? AND l.Tipo = 'Despesa'
               AND YEAR(l.DataLancamento) = ? AND MONTH(l.DataLancamento) = ?) AS TotalGasto;
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, user_id, categoria_id, ano, mes, user_id, categoria_id, ano, mes)
        resultado = cursor.fetchone()
        # Removido: conn.commit()
        return (resultado.ValorMeta, resultado.TotalGasto or Decimal(0)) if resultado else (None, None)
    finally:
        if conn: conn.close()

def get_ativos() -> List[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return []
    query = "SELECT AtivoID, Simbolo, NomeAmigavel FROM dbo.Ativos ORDER BY NomeAmigavel;"
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        # Removido: conn.commit()
        return result
    finally:
        if conn: conn.close()

def save_alerta(user_id: int, ativo_id: int, indicador: str, condicao: str, valor_alvo: Decimal, timeframe: str | None, recorrente: bool = False) -> bool:
    conn = get_db_connection()
    if not conn: return False
    query = "INSERT INTO dbo.Alertas (UsuarioID, AtivoID, Indicador, Condicao, ValorAlvo, Timeframe, Recorrente) VALUES (?, ?, ?, ?, ?, ?, ?);"
    try:
        cursor = conn.cursor()
        cursor.execute(query, user_id, ativo_id, indicador, condicao, valor_alvo, timeframe, recorrente)
        conn.commit()
        return True
    except pyodbc.Error as ex:
        logging.error(f"Erro ao salvar alerta: {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()

def get_active_alerts(user_id: int) -> List[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return []
    query = """
        SELECT al.Indicador, al.Condicao, al.ValorAlvo, al.Timeframe, at.NomeAmigavel, al.Recorrente
        FROM dbo.Alertas AS al JOIN dbo.Ativos AS at ON al.AtivoID = at.AtivoID
        WHERE al.UsuarioID = ? AND al.Status = 'ativo' ORDER BY at.NomeAmigavel, al.Indicador;
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, user_id)
        result = cursor.fetchall()
        # Removido: conn.commit()
        return result
    finally:
        if conn: conn.close()

def get_all_active_alerts() -> List[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return []
    query = """
        SELECT al.AlertaID, al.UsuarioID, al.Indicador, al.Condicao, al.ValorAlvo, al.Timeframe, at.Simbolo, at.NomeAmigavel, al.Recorrente
        FROM dbo.Alertas AS al JOIN dbo.Ativos AS at ON al.AtivoID = at.AtivoID WHERE al.Status = 'ativo';
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        # Removido: conn.commit()
        return result
    finally:
        if conn: conn.close()

def update_alert_status(alerta_id: int, new_status: str) -> bool:
    conn = get_db_connection()
    if not conn: return False
    query = "UPDATE dbo.Alertas SET Status = ? WHERE AlertaID = ?;"
    try:
        cursor = conn.cursor()
        cursor.execute(query, new_status, alerta_id)
        conn.commit()
        logging.info(f"Status do AlertaID {alerta_id} atualizado para '{new_status}'.")
        return True
    except pyodbc.Error as ex:
        logging.error(f"Erro ao atualizar status do alerta {alerta_id}: {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()

def add_product(nome: str, custo: Decimal, preco_venda: Decimal) -> Tuple[bool, str]:
    conn = get_db_connection()
    if not conn: return False, "Falha ao conectar ao banco."
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT ProdutoID FROM dbo.Produtos WHERE LOWER(Nome) = LOWER(?)", nome)
        if cursor.fetchone():
            return False, f"Produto '{nome}' já cadastrado."
        
        cursor.execute("INSERT INTO dbo.Produtos (Nome, Custo, PrecoVenda) OUTPUT INSERTED.ProdutoID VALUES (?, ?, ?);", nome, custo, preco_venda)
        produto_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO dbo.Estoque (ProdutoID, Quantidade) VALUES (?, 0);", produto_id)
        
        conn.commit() # USAMOS O COMMIT DA CONEXÃO
        
        logging.info(f"Produto '{nome}' (ID: {produto_id}) cadastrado.")
        return True, f"Produto '{nome}' cadastrado!"
    except pyodbc.Error as ex:
        logging.error(f"Erro ao adicionar produto '{nome}': {ex}")
        
        conn.rollback() # USAMOS O ROLLBACK DA CONEXÃO
       
        return False, "Erro ao cadastrar produto."
    finally:
        if conn: conn.close()

def get_all_products() -> List[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return []
    query = "SELECT ProdutoID, Nome FROM dbo.Produtos WHERE Status = 'ativo' ORDER BY Nome;"
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        # Removido: conn.commit()
        return result
    finally:
        if conn: conn.close()

def add_stock(produto_id: int, quantidade: int) -> bool:
    conn = get_db_connection()
    if not conn: return False
    query = "UPDATE dbo.Estoque SET Quantidade = Quantidade + ? WHERE ProdutoID = ?;"
    try:
        cursor = conn.cursor()
        cursor.execute(query, quantidade, produto_id)
        conn.commit()
        logging.info(f"Adicionado {quantidade} unidades ao estoque do ProdutoID {produto_id}.")
        return True
    except pyodbc.Error as ex:
        logging.error(f"Erro ao adicionar estoque para ProdutoID {produto_id}: {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()

def get_stock_status() -> List[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return []
    query = "SELECT p.Nome, e.Quantidade FROM dbo.Estoque e JOIN dbo.Produtos p ON e.ProdutoID = p.ProdutoID WHERE p.Status = 'ativo' ORDER BY p.Nome;"
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        # Removido: conn.commit()
        return result
    finally:
        if conn: conn.close()
        
def get_product_details(produto_id: int) -> Optional[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return None
    query = "SELECT p.Nome, p.Custo, p.PrecoVenda, COALESCE(e.Quantidade, 0) AS QuantidadeEstoque FROM dbo.Produtos p LEFT JOIN dbo.Estoque e ON p.ProdutoID = e.ProdutoID WHERE p.ProdutoID = ? AND p.Status = 'ativo';"
    try:
        cursor = conn.cursor()
        cursor.execute(query, produto_id)
        result = cursor.fetchone()
        # Removido: conn.commit()
        return result
    except pyodbc.Error as ex:
        logging.error(f"Erro ao buscar detalhes do ProdutoID {produto_id}: {ex}")
        conn.rollback()
        return None
    finally:
        if conn: conn.close()

# --- Funções de Clientes (Novas) ---

def add_cliente(nome: str, telefone: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
    conn = get_db_connection()
    if not conn: return False, "Falha na conexão.", None
    query = "INSERT INTO dbo.Clientes (Nome, Telefone) OUTPUT INSERTED.ClienteID VALUES (?, ?);"
    try:
        cursor = conn.cursor()
        cursor.execute(query, nome, telefone)
        cliente_id = cursor.fetchone()[0]
        conn.commit()
        logging.info(f"Cliente '{nome}' (ID: {cliente_id}) adicionado.")
        return True, f"Cliente '{nome}' adicionado com sucesso!", cliente_id
    except pyodbc.Error as ex:
        logging.error(f"Erro ao adicionar cliente '{nome}': {ex}")
        conn.rollback()
        return False, "Erro ao adicionar cliente.", None
    finally:
        if conn: conn.close()

def find_cliente(search_term: str) -> List[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return []
    query = "SELECT ClienteID, Nome, Telefone FROM dbo.Clientes WHERE Nome LIKE ? OR Telefone LIKE ? ORDER BY Nome;"
    term = f"%{search_term}%"
    try:
        cursor = conn.cursor()
        cursor.execute(query, term, term)
        result = cursor.fetchall()
        # Removido: conn.commit()
        return result
    finally:
        if conn: conn.close()

def register_sale(user_id: int, items: List[dict], num_installments: int = 1, sale_date: Optional[datetime.date] = None, cliente_id: Optional[int] = None) -> Tuple[bool, str, Optional[int]]:
    conn = get_db_connection()
    if not conn: return False, "Falha na conexão.", None
    cursor = conn.cursor()
    sale_date = sale_date or datetime.date.today()
    try:

        # --- INÍCIO DA CORREÇÃO ---
        # 1. Agrega as quantidades por produto_id
        produtos_agregados: dict[int, dict] = defaultdict(lambda: {'quantidade': 0, 'nome': '', 'ids_carrinho': []})

        for idx, item in enumerate(items):
            pid = item['produto_id']
            produtos_agregados[pid]['quantidade'] += item['quantidade']
            # Armazena o nome do item (presumindo que o nome é o mesmo para o mesmo produto_id)
            if 'nome' in item:
                produtos_agregados[pid]['nome'] = item['nome'] 
            produtos_agregados[pid]['ids_carrinho'].append(idx) # Guarda os índices originais (não usado aqui, mas boa prática)

        # 2. Verifica o estoque com base nos totais agregados
        for produto_id, dados_agregados in produtos_agregados.items():
            quantidade_total = dados_agregados['quantidade']

            cursor.execute("SELECT Quantidade FROM dbo.Estoque WHERE ProdutoID = ?", produto_id)
            stock = cursor.fetchval() or 0

            if stock < quantidade_total:
                conn.rollback() # USAMOS O ROLLBACK DA CONEXÃO

                # Pega o nome do produto (se não tivermos, busca no DB)
                nome_produto = dados_agregados.get('nome')
                if not nome_produto:
                     cursor.execute("SELECT Nome FROM dbo.Produtos WHERE ProdutoID = ?", produto_id)
                     nome_produto = cursor.fetchval() or f"ProdutoID {produto_id}"

                return False, f"Estoque insuficiente para '{nome_produto}'. Pedido total: {quantidade_total} un. Disponível: {stock} un.", None
        # --- FIM DA CORREÇÃO ---

        # 3. O resto da lógica de inserção permanece a mesma, pois ela itera
        #    a lista original 'items', que é o comportamento correto.

        valor_total = sum(Decimal(str(item['preco_unitario'])) * item['quantidade'] for item in items) 
        custo_total = sum(Decimal(str(item['custo_unitario'])) * item['quantidade'] for item in items) 

        query_venda = "INSERT INTO dbo.Vendas (UsuarioID, DataVenda, ValorTotal, CustoTotal, ClienteID) OUTPUT INSERTED.VendaID VALUES (?, ?, ?, ?, ?);"
        cursor.execute(query_venda, user_id, sale_date, valor_total, custo_total, cliente_id)
        venda_id = cursor.fetchone()[0]

        query_item = "INSERT INTO dbo.ItensVenda (VendaID, ProdutoID, Quantidade, PrecoUnitario, CustoUnitario) VALUES (?, ?, ?, ?, ?);"
        for item in items: # Insere os itens originais (não agregados)
            cursor.execute(query_item, venda_id, item['produto_id'], item['quantidade'], item['preco_unitario'], item['custo_unitario'])

        query_stock = "UPDATE dbo.Estoque SET Quantidade = Quantidade - ? WHERE ProdutoID = ?;"
        for item in items: # Abate o estoque (agora sabemos que é seguro)
            cursor.execute(query_stock, item['quantidade'], item['produto_id'])

        # --- INÍCIO DA CORREÇÃO (Lógica de Pagamento) ---

        if num_installments == 1:
            # 1. É "Pago (A Vista)". Registra no Caixa imediatamente.
            desc_caixa = f"Recebimento Venda à Vista #{venda_id}"
            query_caixa = "INSERT INTO dbo.Caixa (Descricao, Valor, TipoMovimento, VendaID) VALUES (?, ?, 'entrada', ?);"
            cursor.execute(query_caixa, desc_caixa, valor_total, venda_id)

            # 2. Cria a 'ContaAReceber' já PAGA, para fins de histórico.
            query_parcela_paga = """
                INSERT INTO dbo.ContasAReceber (VendaID, ClienteID, NumeroParcela, ValorParcela, DataVencimento, Status, DataPagamento) 
                VALUES (?, ?, 1, ?, ?, 'pago', ?);
            """
            cursor.execute(query_parcela_paga, venda_id, cliente_id, valor_total, sale_date, sale_date)

            msg_log = f"Venda {venda_id} (R$ {valor_total}) registrada à vista e baixada no caixa."
            msg_retorno = f"Venda registrada! Total: R$ {valor_total:.2f} (À Vista)"

        else:
            # 3. É parcelado. Mantém a lógica antiga de criar parcelas 'pendentes'.
            valor_parcela = (valor_total / Decimal(num_installments)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            valor_ultima_parcela = valor_total - (valor_parcela * (num_installments - 1))
            query_parcela_pendente = "INSERT INTO dbo.ContasAReceber (VendaID, ClienteID, NumeroParcela, ValorParcela, DataVencimento) VALUES (?, ?, ?, ?, ?);"

            for i in range(1, num_installments + 1):
                # O vencimento da primeira parcela é em 30 dias (i=1 -> 30 dias)
                vencimento = sale_date + datetime.timedelta(days=30 * i)
                valor = valor_ultima_parcela if i == num_installments else valor_parcela
                cursor.execute(query_parcela_pendente, venda_id, cliente_id, i, valor, vencimento)

            msg_log = f"Venda {venda_id} registrada com {num_installments} parcela(s)."
            msg_retorno = f"Venda registrada! Total: R$ {valor_total:.2f} ({num_installments}x R$ {valor_parcela:.2f})"

        # --- FIM DA CORREÇÃO ---

        conn.commit() # USAMOS O COMMIT DA CONEXÃO

        logging.info(msg_log)
        return True, msg_retorno, venda_id
    except pyodbc.Error as ex:
        logging.error(f"Erro ao registrar venda: {ex}")

        conn.rollback() # USAMOS O ROLLBACK DA CONEXÃO
        return False, "Erro ao registrar venda no banco.", None
    finally:
        if conn: conn.close()

def get_contas_pendentes(cliente_id: Optional[int] = None) -> List[pyodbc.Row]:
    conn = get_db_connection()
    if not conn: return []
    query = """
        SELECT cr.ContaID, cr.VendaID, cr.NumeroParcela, cr.ValorParcela, cr.DataVencimento, c.Nome AS NomeCliente
        FROM dbo.ContasAReceber cr LEFT JOIN dbo.Clientes c ON cr.ClienteID = c.ClienteID
        WHERE cr.Status = 'pendente'
    """
    params = []
    if cliente_id:
        query += " AND cr.ClienteID = ?"
        params.append(cliente_id)
    query += " ORDER BY cr.DataVencimento;"
    try:
        cursor = conn.cursor()
        cursor.execute(query, params if params else []) 
        result = cursor.fetchall()
        # Removido: conn.commit()
        return result
    finally:
        if conn: conn.close()

def get_contas_pendentes_total() -> Decimal:
    conn = get_db_connection()
    if not conn: return Decimal(0)
    query = "SELECT COALESCE(SUM(ValorParcela), 0) FROM dbo.ContasAReceber WHERE Status = 'pendente';"
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        total = cursor.fetchval()
        return total or Decimal(0)
    except pyodbc.Error as ex:
        logging.error(f"Erro ao calcular total de contas a receber: {ex}")
        conn.rollback()
        return Decimal(0)
    finally:
        if conn: conn.close()

def add_conta_pagar(descricao_base: str, valor_total: Decimal, data_primeiro_vencimento: datetime.date, num_parcelas: int = 1) -> bool:
    conn = get_db_connection()
    if not conn: return False
    cursor = conn.cursor()
    
    query = "INSERT INTO dbo.ContasAPagar (Descricao, Valor, DataVencimento) VALUES (?, ?, ?);"
    
    try:
        if num_parcelas <= 0:
            num_parcelas = 1
            
        # Calcula o valor de cada parcela, garantindo que o total feche
        valor_parcela = (valor_total / Decimal(num_parcelas)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        valor_ultima_parcela = valor_total - (valor_parcela * (num_parcelas - 1))
        
        for i in range(1, num_parcelas + 1):
            valor = valor_ultima_parcela if i == num_parcelas else valor_parcela
            # Calcula o vencimento (Parcela 1 vence na data exata, Parcela 2 em 30 dias, etc.)
            vencimento = data_primeiro_vencimento + datetime.timedelta(days=30 * (i-1)) 
            
            descricao = f"{descricao_base} [{i}/{num_parcelas}]" if num_parcelas > 1 else descricao_base
            
            cursor.execute(query, descricao, valor, vencimento)
            
        conn.commit()
        logging.info(f"Conta a pagar '{descricao_base}' (R$ {valor_total}) adicionada em {num_parcelas} parcela(s).")
        return True
        
    except pyodbc.Error as ex:
        logging.error(f"Erro ao adicionar conta a pagar parcelada: {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()
        
def mark_conta_pagar_paga(conta_pagar_id: int, payment_date: Optional[datetime.date] = None) -> bool:
    conn = get_db_connection()
    if not conn: return False
    payment_date = payment_date or datetime.date.today()
    cursor = conn.cursor()
    try:
        # 1. Verifica se a conta existe e está pendente
        cursor.execute("SELECT Descricao, Valor FROM dbo.ContasAPagar WHERE ContaPagarID = ? AND Status = 'pendente';", conta_pagar_id)
        conta_info = cursor.fetchone()

        if not conta_info:
            logging.warning(f"Conta a pagar ID {conta_pagar_id} não encontrada ou já paga.")
            conn.rollback() # Usar o rollback da conexão principal
            return False

        descricao_conta, valor_pago = conta_info

        # 2. Atualiza o status da conta (Transação A)
        cursor.execute("UPDATE dbo.ContasAPagar SET Status = 'pago', DataPagamento = ? WHERE ContaPagarID = ?;", payment_date, conta_pagar_id)

        # 3. Gera a descrição para o caixa
        desc_caixa = f"Pagamento: {descricao_conta} (ContaPagarID #{conta_pagar_id})"

        # 4. Registra a SAÍDA no caixa USANDO O MESMO CURSOR E TRANSAÇÃO
        #    (Lógica anteriormente em add_retirada/add_caixa_movement)
        if valor_pago > 0:
            query_caixa = "INSERT INTO dbo.Caixa (Descricao, Valor, TipoMovimento) VALUES (?, ?, 'saida');"
            cursor.execute(query_caixa, desc_caixa, valor_pago)
        else:
             # Se o valor for 0, não precisamos registrar no caixa, mas o pagamento da conta (status) é válido.
             pass

        # 5. Comita as DUAS operações (UPDATE e INSERT) juntas
        conn.commit()
        logging.info(f"Conta a pagar {conta_pagar_id} marcada como paga e registrada no caixa.")
        return True

    except pyodbc.Error as ex:
        logging.error(f"Erro ao marcar conta a pagar {conta_pagar_id} como paga: {ex}")
        conn.rollback() # Desfaz TUDO (UPDATE e INSERT) se algo der errado
        return False
    finally:
        if conn: conn.close()

# --- Função de Fluxo de Caixa (Nova - Etapa 3) ---

def get_fluxo_caixa_projetado(dias_frente: int = 30) -> dict:
    conn = get_db_connection()
    if not conn: 
        return {'saldo_atual': Decimal(0), 'projecao': [], 'erros': 'Falha na conexão.'}

    # 1. Define o período da projeção
    data_hoje = datetime.date.today()
    data_limite = data_hoje + datetime.timedelta(days=dias_frente)
    
    # 2. Busca o saldo atual
    saldo_atual = get_caixa_balance()
    
    # 3. Esta query SQL combina todas as entradas e saídas futuras em uma única "agenda"
    #    e agrupa os valores por dia.
    query_projecao = """
        WITH Futuro AS (
            SELECT 
                DataVencimento AS Data,
                ValorParcela AS Valor,
                'entrada' AS Tipo
            FROM dbo.ContasAReceber
            WHERE Status = 'pendente' AND DataVencimento BETWEEN ? AND ?
            
            UNION ALL
            
            SELECT 
                DataVencimento AS Data,
                Valor AS Valor,
                'saida' AS Tipo
            FROM dbo.ContasAPagar
            WHERE Status = 'pendente' AND DataVencimento BETWEEN ? AND ?
        ),
        EventosDiarios AS (
            SELECT 
                Data,
                SUM(CASE WHEN Tipo = 'entrada' THEN Valor ELSE 0 END) AS Entradas,
                SUM(CASE WHEN Tipo = 'saida' THEN Valor ELSE 0 END) AS Saidas
            FROM Futuro
            GROUP BY Data
        )
        SELECT * FROM EventosDiarios ORDER BY Data;
    """
    
    resultado = {'saldo_atual': saldo_atual, 'projecao': []}
    
    try:
        cursor = conn.cursor()
        cursor.execute(query_projecao, data_hoje, data_limite, data_hoje, data_limite)
        eventos_futuros = cursor.fetchall()
        
        saldo_projetado = saldo_atual
        
        # 4. Processa os eventos dia a dia e calcula o saldo corrente
        for evento in eventos_futuros:
            saldo_projetado = saldo_projetado + evento.Entradas - evento.Saidas
            resultado['projecao'].append({
                'data': evento.Data,
                'entradas': evento.Entradas,
                'saidas': evento.Saidas,
                'saldo_projetado': saldo_projetado
            })
            
        return resultado
        
    except pyodbc.Error as ex:
        logging.error(f"Erro ao gerar projeção de fluxo de caixa: {ex}")
        conn.rollback()
        return {'saldo_atual': saldo_atual, 'projecao': [], 'erros': str(ex)}
    finally:
        if conn: conn.close()

# --- Funções de Cancelamento (Novas - Etapa 3.1) ---

def cancelar_conta_pagar_pendente(conta_pagar_id: int) -> bool:
    conn = get_db_connection()
    if not conn: return False
    cursor = conn.cursor()
    
    query_check = "SELECT Status FROM dbo.ContasAPagar WHERE ContaPagarID = ?;"
    query_update = "UPDATE dbo.ContasAPagar SET Status = 'cancelado' WHERE ContaPagarID = ?;"
    
    try:
        cursor.execute(query_check, conta_pagar_id)
        resultado = cursor.fetchone()
        
        if not resultado:
            logging.warning(f"Tentativa de cancelar ContaPagarID {conta_pagar_id} falhou: ID não encontrado.")
            conn.rollback()
            return False
        
        if resultado.Status != 'pendente':
            logging.warning(f"Tentativa de cancelar ContaPagarID {conta_pagar_id} falhou: Status é '{resultado.Status}', não 'pendente'.")
            conn.rollback()
            return False
            
        cursor.execute(query_update, conta_pagar_id)
        conn.commit()
        logging.info(f"ContaPagarID {conta_pagar_id} cancelada com sucesso.")
        return True
        
    except pyodbc.Error as ex:
        logging.error(f"Erro ao cancelar ContaPagarID {conta_pagar_id}: {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()

def cancelar_conta_receber_pendente(conta_receber_id: int) -> bool:
    conn = get_db_connection()
    if not conn: return False
    cursor = conn.cursor()
    
    query_check = "SELECT Status FROM dbo.ContasAReceber WHERE ContaID = ?;"
    query_update = "UPDATE dbo.ContasAReceber SET Status = 'cancelado' WHERE ContaID = ?;"
    
    try:
        cursor.execute(query_check, conta_receber_id)
        resultado = cursor.fetchone()
        
        if not resultado:
            logging.warning(f"Tentativa de cancelar ContaID {conta_receber_id} (A Receber) falhou: ID não encontrado.")
            conn.rollback()
            return False
        
        if resultado.Status != 'pendente':
            logging.warning(f"Tentativa de cancelar ContaID {conta_receber_id} (A Receber) falhou: Status é '{resultado.Status}', não 'pendente'.")
            conn.rollback()
            return False
            
        cursor.execute(query_update, conta_receber_id)
        conn.commit()
        logging.info(f"ContaID {conta_receber_id} (A Receber) cancelada com sucesso.")
        return True
        
    except pyodbc.Error as ex:
        logging.error(f"Erro ao cancelar ContaID {conta_receber_id} (A Receber): {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()

# --- Fim das Funções de Cancelamento ---

def mark_conta_paga(conta_id: int, payment_date: Optional[datetime.date] = None) -> bool:
    conn = get_db_connection()
    if not conn: return False
    payment_date = payment_date or datetime.date.today()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT VendaID, ValorParcela FROM dbo.ContasAReceber WHERE ContaID = ? AND Status = 'pendente';", conta_id)
        conta_info = cursor.fetchone()
        if not conta_info:
            logging.warning(f"Conta {conta_id} não encontrada ou já paga.")
            
            conn.rollback() # USAMOS O ROLLBACK DA CONEXÃO
            
            return False
        
        venda_id, valor_parcela = conta_info
        cursor.execute("UPDATE dbo.ContasAReceber SET Status = 'pago', DataPagamento = ? WHERE ContaID = ?;", payment_date, conta_id)
        desc_caixa = f"Recebimento Parcela (Venda #{venda_id}, Conta #{conta_id})"
        cursor.execute("INSERT INTO dbo.Caixa (Descricao, Valor, TipoMovimento, VendaID, ContaReceberID) VALUES (?, ?, 'entrada', ?, ?);", desc_caixa, valor_parcela, venda_id, conta_id)
        
        conn.commit() # USAMOS O COMMIT DA CONEXÃO
        
        logging.info(f"Conta a receber {conta_id} marcada como paga.")
        return True
    except pyodbc.Error as ex:
        logging.error(f"Erro ao marcar conta {conta_id} como paga: {ex}")
        
        conn.rollback() # USAMOS O ROLLBACK DA CONEXÃO
        
        return False
    finally:
        if conn: conn.close()

def add_caixa_movement(descricao: str, valor: Decimal, tipo: str, venda_id: Optional[int] = None, conta_receber_id: Optional[int] = None) -> bool:
    conn = get_db_connection()
    if not conn: return False
    query = "INSERT INTO dbo.Caixa (Descricao, Valor, TipoMovimento, VendaID, ContaReceberID) VALUES (?, ?, ?, ?, ?);"
    try:
        cursor = conn.cursor()
        cursor.execute(query, descricao, valor, tipo, venda_id, conta_receber_id)
        conn.commit()
        logging.info(f"Movimento de caixa: {tipo} de R$ {valor} - {descricao}")
        return True
    except pyodbc.Error as ex:
        logging.error(f"Erro ao registrar movimento no caixa: {ex}")
        conn.rollback()
        return False
    finally:
        if conn: conn.close()

def get_caixa_balance() -> Decimal:
    conn = get_db_connection()
    if not conn: return Decimal(0)
    query = "SELECT SUM(CASE WHEN TipoMovimento = 'entrada' THEN Valor ELSE -Valor END) FROM dbo.Caixa;"
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        saldo = cursor.fetchval()
        # Removido: conn.commit()
        return saldo or Decimal(0)
    finally:
        if conn: conn.close()

def get_sales_report(ano: int, mes: int) -> dict:
    conn = get_db_connection()
    if not conn: return {"faturamento": Decimal(0), "cmv": Decimal(0), "lucro_bruto": Decimal(0)}
    query = "SELECT COALESCE(SUM(ValorTotal), 0) AS Faturamento, COALESCE(SUM(CustoTotal), 0) AS CMV FROM dbo.Vendas WHERE YEAR(DataVenda) = ? AND MONTH(DataVenda) = ?;"
    try:
        cursor = conn.cursor()
        cursor.execute(query, ano, mes)
        data = cursor.fetchone()
        # Removido: conn.commit()
        fat = data.Faturamento if data else Decimal(0)
        cmv = data.CMV if data else Decimal(0)
        return {"faturamento": fat, "cmv": cmv, "lucro_bruto": fat - cmv}
    except pyodbc.Error as ex:
        logging.error(f"Erro ao gerar relatório vendas {mes}/{ano}: {ex}")
        conn.rollback()
        return {"faturamento": Decimal(0), "cmv": Decimal(0), "lucro_bruto": Decimal(0)}
    finally:
        if conn: conn.close()

def set_saldo_inicial(valor: Decimal) -> bool:
    conn = get_db_connection()
    if not conn: return False
    cursor = conn.cursor()
    try:
        
        logging.warning("Apagando histórico do caixa para definir saldo inicial.")
        cursor.execute("DELETE FROM dbo.Caixa;")
        cursor.execute("INSERT INTO dbo.Caixa (Descricao, Valor, TipoMovimento) VALUES (?, ?, 'entrada');", "Saldo Inicial", valor)
        
        conn.commit() # USAMOS O COMMIT DA CONEXÃO
        
        logging.info(f"Saldo inicial do caixa definido para R$ {valor}.")
        return True
    except pyodbc.Error as ex:
        logging.error(f"Erro ao definir saldo inicial: {ex}")
        
        conn.rollback() # USAMOS O ROLLBACK DA CONEXÃO
        
        return False
    finally:
        if conn: conn.close()

def add_retirada(valor: Decimal, descricao: str = "Retirada de Lucro/Pró-labore") -> bool:
    if valor <= 0: return False
    return add_caixa_movement(descricao, valor, 'saida')

if __name__ == "__main__":
    pass
