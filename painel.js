document.addEventListener('DOMContentLoaded', function() {

    async function atualizarPainel() {
        console.log("Iniciando atualização do painel v3.0...");
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

            dados.para_fazer.forEach(tarefa => colunaParaFazer.appendChild(criarCard(tarefa, 'para_fazer')));
            dados.validacao.forEach(tarefa => colunaValidacao.appendChild(criarCard(tarefa, 'validacao')));
            dados.concluidas.forEach(tarefa => colunaConcluidas.appendChild(criarCard(tarefa, 'concluida')));

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
        
        let tituloHtml = `<h3 class="card-titulo">${tarefa.Titulo}</h3>`;
        let infoExtra = `<p class="card-info">Funcionário: ${tarefa.NomeCompleto}</p>`;

        // Lógica para adicionar a tag [ATRASADA]
        if (tipo === 'para_fazer' && tarefa.Categoria === 'Atrasada') {
            tituloHtml = `
                <h3 class="card-titulo">
                    <span>${tarefa.Titulo}</span>
                    <span class="card-tag-atrasada">ATRASADA</span>
                </h3>`;
        }
        
        // Lógica para adicionar classe ao card concluído
        if (tipo === 'concluida') {
            cardDiv.classList.add('concluida');
            infoExtra += `<p class="card-info">Concluída em: ${new Date(tarefa.DataEnvio).toLocaleTimeString('pt-BR')}</p>`;
        }

        cardDiv.innerHTML = `
            ${tituloHtml}
            ${infoExtra}
            <p class="card-pontos">+ ${tarefa.Pontos} pts</p>
        `;
        return cardDiv;
    }

    atualizarPainel();
    setInterval(atualizarPainel, 60000);

});
