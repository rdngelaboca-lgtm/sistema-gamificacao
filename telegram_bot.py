# Em main.py, adicione esta nova função à classe App

def excluir_apuracao_selecionada(self):
    """Exclui o registro de apuração diária selecionado na lista de detalhes."""
    # 1. Verifica se uma apuração e uma meta principal estão selecionadas
    selecionado_apuracao = self.tree_detalhes_apuracoes.focus()
    selecionado_meta = self.tree_metas_principais.focus()

    if not selecionado_apuracao or not selecionado_meta:
        messagebox.showwarning("Aviso", "Por favor, selecione uma meta na lista de cima e uma apuração na lista de detalhes para excluir.")
        return

    # 2. Pega os dados necessários
    dados_apuracao = self.tree_detalhes_apuracoes.item(selecionado_apuracao, 'values')
    meta_id = self.tree_metas_principais.item(selecionado_meta, 'values')[0]
    data_lancamento_str_br = dados_apuracao[0] # Formato: dd/mm/yyyy

    # 3. Pede confirmação ao usuário
    confirmado = messagebox.askyesno(
        "Confirmar Exclusão",
        f"Tem certeza que deseja excluir permanentemente o lançamento do dia {data_lancamento_str_br}?\n\nEsta ação não pode ser desfeita.",
        icon='warning'
    )

    if confirmado:
        try:
            # 4. Converte a data para o formato do banco (yyyy-mm-dd)
            data_db_format = datetime.strptime(data_lancamento_str_br, '%d/%m/%Y').strftime('%Y-%m-%d')

            # 5. Chama a nova função do banco de dados
            sucesso = database.excluir_apuracao_diaria(meta_id, data_db_format)

            if sucesso:
                messagebox.showinfo("Sucesso", "Lançamento excluído com sucesso!")
                # 6. Atualiza a tela para refletir a exclusão
                self.on_meta_principal_selecionada(None)
            else:
                messagebox.showerror("Erro", "Não foi possível excluir o lançamento do banco de dados.")
        except Exception as e:
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro: {e}")
