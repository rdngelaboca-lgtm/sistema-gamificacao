document.addEventListener('DOMContentLoaded', function() {

    async function atualizarPainel() {
        console.log("Iniciando atualização do painel v4.1 (Com Agrupamento e Debug)...");
        try {
            const response = await fetch('http://192.168.2.23:5000/api/painel/tarefas');
            if (!response.ok) throw new Error(`Erro na API: ${response.statusText}`);
            const dados = await response.json();

            const colunaParaFazer = document.getElementById('coluna-para-fazer');
            const colunaValidacao = document.getElementById('coluna-validacao');
            const colunaConcluidas = document.getElementById('coluna-concluidas');

            colunaParaFazer.innerHTML = '';
            colunaValidacao.innerHTML = '';
            colunaConcluidas.innerHTML = '';

            const tarefasAgrupadasParaFazer = agruparTarefasPorFuncionario(dados.para_fazer);
            const tarefasAgrupadasConcluidas = agruparTarefasPorFuncionario(dados.concluidas);

            renderizarGrupos(tarefasAgrupadasParaFazer, colunaParaFazer, 'para_fazer');
            renderizarGrupos(tarefasAgrupadasConcluidas, colunaConcluidas, 'concluida');
            
            dados.validacao.forEach(tarefa => colunaValidacao.appendChild(criarCard(tarefa, 'validacao')));
            
            const timestamp = new Date().toLocaleTimeString('pt-BR');
            document.getElementById('ultima-atualizacao').textContent = `Última atualização: ${timestamp}`;

        } catch (error) {
            console.error("Falha ao atualizar o painel:", error);
            document.getElementById('ultima-atualizacao').textContent = "Erro ao carregar dados.";
        }
    }

    function agruparTarefasPorFuncionario(listaDeTarefas) {
        const grupos = {};
        for (const tarefa of listaDeTarefas) {
            const nomeFuncionario = tarefa.NomeCompleto;
            if (!grupos[nomeFuncionario]) {
                grupos[nomeFuncionario] = [];
            }
            grupos[nomeFuncionario].push(tarefa);
        }
        return grupos;
    }

    function renderizarGrupos(grupos, elementoColuna, tipo) {
        const nomesOrdenados = Object.keys(grupos).sort();

        for (const nomeFuncionario of nomesOrdenados) {
            const grupoDiv = document.createElement('div');
            grupoDiv.className = 'grupo-funcionario';
            
            const tituloGrupo = document.createElement('h3');
            tituloGrupo.className = 'grupo-titulo';
            tituloGrupo.textContent = nomeFuncionario;
            grupoDiv.appendChild(tituloGrupo);
            
            for (const tarefa of grupos[nomeFuncionario]) {
                const card = criarCard(tarefa, tipo);
                grupoDiv.appendChild(card);
            }
            elementoColuna.appendChild(grupoDiv);
        }
    }

    // FUNÇÃO criarCard COM A DATA DE REFERÊNCIA DE VOLTA
    function criarCard(tarefa, tipo) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'card';
        
        let tituloHtml = `<span>${tarefa.Titulo}</span>`;
        let infoExtra = `<p class="card-info">Funcionário: ${tarefa.NomeCompleto}</p>`;
        
        // ===== LINHAS QUE ESTAVAM FALTANDO =====
        if (tarefa.DataReferencia) {
            const dataRef = new Date(tarefa.DataReferencia).toLocaleDateString('pt-BR');
            infoExtra += `<p class="card-info-debug">Referente a: ${dataRef}</p>`;
        }
        // =========================================

        if (tipo === 'para_fazer' && tarefa.Categoria === 'Atrasada') {
            tituloHtml += `<span class="card-tag-atrasada">ATRASADA</span>`;
        }
        
        if (tipo === 'validacao') {
            tituloHtml = `<span>⏳</span>` + tituloHtml;
        } else if (tipo === 'concluida') {
            cardDiv.classList.add('concluida');
            infoExtra += `<p class="card-info">Concluída em: ${new Date(tarefa.DataEnvio).toLocaleTimeString('pt-BR')}</p>`;
            tituloHtml = `<span>🏆</span>` + tituloHtml;
        }

        cardDiv.innerHTML = `
            <div class="card-titulo">${tituloHtml}</div>
            ${infoExtra}
            <p class="card-pontos">+ ${tarefa.Pontos} pts</p>
        `;
        return cardDiv;
    }

    atualizarPainel();
    setInterval(atualizarPainel, 60000);
});
