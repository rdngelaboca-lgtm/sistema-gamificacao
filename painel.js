document.addEventListener('DOMContentLoaded', function() {

    // FUNÇÃO PRINCIPAL (COM A NOVA LÓGICA DE CHAMADA)
    async function atualizarPainel() {
        console.log("Iniciando atualização do painel v4.0 (Com Agrupamento)...");
        try {
            const response = await fetch('http://192.168.2.23:5000/api/painel/tarefas');
            if (!response.ok) throw new Error(`Erro na API: ${response.statusText}`);
            const dados = await response.json();

            // Pega as colunas do HTML
            const colunaParaFazer = document.getElementById('coluna-para-fazer');
            const colunaValidacao = document.getElementById('coluna-validacao');
            const colunaConcluidas = document.getElementById('coluna-concluidas');

            // Limpa o conteúdo antigo
            colunaParaFazer.innerHTML = '';
            colunaValidacao.innerHTML = '';
            colunaConcluidas.innerHTML = '';

            // ===== A GRANDE MUDANÇA ESTÁ AQUI =====
            // Em vez de criar os cards diretamente, primeiro agrupamos os dados
            const tarefasAgrupadasParaFazer = agruparTarefasPorFuncionario(dados.para_fazer);
            const tarefasAgrupadasConcluidas = agruparTarefasPorFuncionario(dados.concluidas);

            // Agora, renderizamos os grupos nas colunas
            renderizarGrupos(tarefasAgrupadasParaFazer, colunaParaFazer, 'para_fazer');
            renderizarGrupos(tarefasAgrupadasConcluidas, colunaConcluidas, 'concluida');
            
            // A coluna de validação continua com uma lista simples
            dados.validacao.forEach(tarefa => colunaValidacao.appendChild(criarCard(tarefa, 'validacao')));
            
            // Atualiza o timestamp
            const timestamp = new Date().toLocaleTimeString('pt-BR');
            document.getElementById('ultima-atualizacao').textContent = `Última atualização: ${timestamp}`;

        } catch (error) {
            console.error("Falha ao atualizar o painel:", error);
            document.getElementById('ultima-atualizacao').textContent = "Erro ao carregar dados.";
        }
    }

    // NOVA FUNÇÃO: Recebe uma lista de tarefas e agrupa por funcionário
    function agruparTarefasPorFuncionario(listaDeTarefas) {
        const grupos = {};
        // Itera sobre cada tarefa da lista
        for (const tarefa of listaDeTarefas) {
            const nomeFuncionario = tarefa.NomeCompleto;
            // Se ainda não vimos esse funcionário, cria uma nova lista para ele
            if (!grupos[nomeFuncionario]) {
                grupos[nomeFuncionario] = [];
            }
            // Adiciona a tarefa atual à lista do funcionário
            grupos[nomeFuncionario].push(tarefa);
        }
        return grupos; // Retorna o objeto com os grupos
    }

    // NOVA FUNÇÃO: Recebe os grupos e os desenha na coluna
    function renderizarGrupos(grupos, elementoColuna, tipo) {
        // Pega os nomes dos funcionários (as chaves do objeto) e ordena em ordem alfabética
        const nomesOrdenados = Object.keys(grupos).sort();

        // Para cada nome de funcionário...
        for (const nomeFuncionario of nomesOrdenados) {
            // Cria o container do grupo
            const grupoDiv = document.createElement('div');
            grupoDiv.className = 'grupo-funcionario';
            
            // Cria o título com o nome do funcionário
            const tituloGrupo = document.createElement('h3');
            tituloGrupo.className = 'grupo-titulo';
            tituloGrupo.textContent = nomeFuncionario;
            grupoDiv.appendChild(tituloGrupo);
            
            // Para cada tarefa DENTRO do grupo daquele funcionário...
            for (const tarefa of grupos[nomeFuncionario]) {
                // Cria o card e o adiciona ao container do grupo
                const card = criarCard(tarefa, tipo);
                grupoDiv.appendChild(card);
            }
            // Adiciona o grupo inteiro (título + cards) na coluna principal
            elementoColuna.appendChild(grupoDiv);
        }
    }

    // FUNÇÃO criarCard ATUALIZADA COM ÍCONES
    function criarCard(tarefa, tipo) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'card';
        
        let tituloHtml = `<span>${tarefa.Titulo}</span>`;
        let infoExtra = `<p class="card-info">Funcionário: ${tarefa.NomeCompleto}</p>`;

        // Lógica para adicionar a tag [ATRASADA]
        if (tipo === 'para_fazer' && tarefa.Categoria === 'Atrasada') {
            tituloHtml += `<span class="card-tag-atrasada">ATRASADA</span>`;
        }
        
        // Lógica para adicionar ÍCONES
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

    // Inicialização (sem alteração)
    atualizarPainel();
    setInterval(atualizarPainel, 60000);
});
