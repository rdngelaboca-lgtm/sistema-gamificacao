document.addEventListener('DOMContentLoaded', function() {

    async function atualizarPainel() {
        console.log("Iniciando atualização do painel...");
        try {
            const response = await fetch('http://127.0.0.1:5000/api/painel/tarefas');
            if (!response.ok) {
                throw new Error(`Erro na API: ${response.statusText}`);
            }
            const dados = await response.json();
            console.log("Dados recebidos da API:", dados);

            const colunaAtrasadas = document.getElementById('coluna-atrasadas');
            const colunaHoje = document.getElementById('coluna-hoje');
            const colunaValidacao = document.getElementById('coluna-validacao');

            colunaAtrasadas.innerHTML = '';
            colunaHoje.innerHTML = '';
            colunaValidacao.innerHTML = '';

            dados.atrasadas.forEach(tarefa => {
                const card = criarCard(tarefa, 'atrasada');
                colunaAtrasadas.appendChild(card);
            });

            dados.hoje.forEach(tarefa => {
                const card = criarCard(tarefa, 'hoje');
                colunaHoje.appendChild(card);
            });

            dados.validacao.forEach(tarefa => {
                const card = criarCard(tarefa, 'validacao');
                colunaValidacao.appendChild(card);
            });

            const timestamp = new Date().toLocaleTimeString('pt-BR');
            document.getElementById('ultima-atualizacao').textContent = `Última atualização: ${timestamp}`;

        } catch (error) {
            console.error("Falha ao atualizar o painel:", error);
            document.getElementById('ultima-atualizacao').textContent = "Erro ao carregar dados.";
        }
    }

    function criarCard(tarefa, tipo) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'card';

        let infoExtra = '';
        // CORREÇÃO: Adicionamos uma verificação para o NomeCompleto no tipo 'atrasada'
        if (tipo === 'atrasada') {
            const data = new Date(tarefa.DataAtribuicao).toLocaleDateString('pt-BR');
            infoExtra = `<p class="card-info">Funcionário: ${tarefa.NomeCompleto}</p>
                         <p class="card-info">Atribuída em: ${data}</p>`;
        } else {
            infoExtra = `<p class="card-info">Funcionário: ${tarefa.NomeCompleto}</p>`;
        }

        cardDiv.innerHTML = `
            <h3 class="card-titulo">${tarefa.Titulo}</h3>
            ${infoExtra}
            <p class="card-pontos">+ ${tarefa.Pontos} pts</p>
        `;
        
        return cardDiv;
    }

    atualizarPainel();
    setInterval(atualizarPainel, 60000);

});