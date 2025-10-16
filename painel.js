

document.addEventListener('DOMContentLoaded', function() {

const API_BASE_URL = 'http://192.168.2.23:5000';    

      
    function renderizarPodio(ranking) {
        const podioContainer = document.getElementById('podio-diario');
        podioContainer.innerHTML = '';
        if (ranking.length === 0) {
            podioContainer.innerHTML = '<p><i>O pódio de hoje ainda está vazio. Conclua tarefas para aparecer aqui!</i></p>';
            return;
        }
        const medalhas = ['🥇', '🥈', '🥉'];
        ranking.forEach((item, index) => {
            const podioItem = document.createElement('div');
            podioItem.className = `podio-item posicao-${index + 1}`;
            podioItem.innerHTML = `
                <div class="posicao">${medalhas[index]}</div>
                <div class="nome">${item.NomeCompleto}</div>
                <div class="pontos">${item.TotalPontosHoje} pts hoje</div>
            `;
            podioContainer.appendChild(podioItem);
        });
    }

    function renderizarColunas(dados) {
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
    }
    
    function atualizarBarraDeProgresso(progresso) {
        const barraInterna = document.getElementById('progresso-barra-interna');
        const textoLabel = document.getElementById('progresso-texto-label');
        if (progresso && progresso.total > 0) {
            const percentual = (progresso.concluidas / progresso.total) * 100;
            barraInterna.style.width = `${percentual}%`;
            textoLabel.textContent = `Progresso do Dia: ${progresso.concluidas} / ${progresso.total} Tarefas`;
        } else {
            barraInterna.style.width = '0%';
            textoLabel.textContent = 'Nenhuma tarefa para hoje ainda.';
        }
    }

    function agruparTarefasPorFuncionario(listaDeTarefas) {
        const grupos = {};
        for (const tarefa of listaDeTarefas) {
            const nomeFuncionario = tarefa.NomeCompleto;
            if (!grupos[nomeFuncionario]) { grupos[nomeFuncionario] = []; }
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

    function criarCard(tarefa, tipo) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'card';
        let tituloHtml = `<span>${tarefa.Titulo}</span>`;
        let infoExtra = `<p class="card-info">Funcionário: ${tarefa.NomeCompleto}</p>`;
        if (tarefa.DataReferencia) {
            const dataRef = new Date(tarefa.DataReferencia).toLocaleDateString('pt-BR');
            infoExtra += `<p class="card-info-debug">Referente a: ${dataRef}</p>`;
        }
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
        cardDiv.innerHTML = `<div class="card-titulo">${tituloHtml}</div>${infoExtra}<p class="card-pontos">+ ${tarefa.Pontos} pts</p>`;
        return cardDiv;
    }

    function renderizarFeed(eventos) {
        const feedLista = document.getElementById('feed-lista');
        feedLista.innerHTML = '';

        if (eventos.length === 0) {
            feedLista.innerHTML = '<li>Nenhuma atividade recente.</li>';
            return;
        }

        eventos.forEach(evento => {
            const item = document.createElement('li');
            const tempoAtras = new Date(evento.Timestamp).toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'});
            let icone = '';
            let texto = '';

            if (evento.TipoEvento === 'tarefa_concluida') {
                item.className = 'feed-item-tarefa';
                icone = '✅';
                texto = `<b>${evento.TextoPrincipal}</b> concluiu a tarefa <i>"${evento.TextoSecundario}"</i> (+${evento.Pontos} pts)`;
            } else if (evento.TipoEvento === 'conquista') {
                item.className = 'feed-item-conquista';
                icone = '⭐';
                texto = `<b>${evento.TextoPrincipal}</b> desbloqueou a conquista <i>"${evento.TextoSecundario}"</i>! (+${evento.Pontos} pts)`;
            }

            item.innerHTML = `<span class="feed-icone">${icone}</span> <div>${texto} <small style="color: #888;">às ${tempoAtras}</small></div>`;
            feedLista.appendChild(item);
        });
    }

    function renderizarMetaPrincipal(meta) {
        const containerEl = document.getElementById('container-meta-mensal');
        const tituloEl = document.getElementById('meta-titulo');
        const barraEl = document.getElementById('meta-progresso-barra');
        const textoEl = document.getElementById('meta-progresso-texto');
        const atingidoEl = document.getElementById('meta-valor-atingido');
        const totalEl = document.getElementById('meta-valor-total');

        if (meta && meta.valor_meta > 0) {
            containerEl.style.display = 'block'; // <<< NOVA LINHA
            const percentual = (meta.valor_atingido / meta.valor_meta) * 100;
            
            tituloEl.textContent = meta.nome_meta;
            barraEl.style.width = `${Math.min(percentual, 100)}%`; // Não deixa passar de 100%
            textoEl.textContent = `${percentual.toFixed(1)}%`;
            atingidoEl.textContent = `R$ ${meta.valor_atingido.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
            totalEl.textContent = `R$ ${meta.valor_meta.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
        } else {
            tituloEl.textContent = "Nenhuma meta principal ativa no momento.";
            containerEl.style.display = 'none';
            barraEl.style.width = '0%';
            textoEl.textContent = '0%';
            atingidoEl.textContent = 'R$ 0,00';
            totalEl.textContent = 'R$ 0,00';
        }
    }

    async function atualizarPainel() {
        console.log("Iniciando atualização do painel vFinal...");
        try {
            // A linha abaixo é a que você vai ADICIONAR
            const [respostaTarefas, respostaRanking, respostaFeed, respostaMeta, respostaMetaDiaria] = await Promise.all([ // <<< Adicionado 'respostaMetaDiaria'
                fetch(`${API_BASE_URL}/api/painel/tarefas`),
                fetch(`${API_BASE_URL}/api/ranking/diario`), 
                fetch(`${API_BASE_URL}/api/feed`),
                fetch(`${API_BASE_URL}/api/meta_principal_do_dia`),
                fetch(`${API_BASE_URL}/api/meta_diaria_do_dia`) // <<< NOVA LINHA
            ]);

            if (!respostaTarefas.ok || !respostaRanking.ok || !respostaFeed.ok || !respostaMeta.ok || !respostaMetaDiaria.ok) { // <<< Adicionado 'respostaMetaDiaria'
                throw new Error('Falha em uma das chamadas da API');
            }

            const dadosTarefas = await respostaTarefas.json();
            const dadosRanking = await respostaRanking.json();
            const dadosFeed = await respostaFeed.json();
            const dadosMeta = await respostaMeta.json();
            const dadosMetaDiaria = await respostaMetaDiaria.json(); // <<< NOVA LINHA

            renderizarColunas(dadosTarefas);
            atualizarBarraDeProgresso(dadosTarefas.progresso);
            renderizarPodio(dadosRanking);
            renderizarFeed(dadosFeed);
            renderizarMetaPrincipal(dadosMeta);
            renderizarMetaDiaria(dadosMetaDiaria); 

            // ... o resto da função continua igual
        } catch (error) {
            // ...
        }
    }

    function renderizarMetaDiaria(meta) {
        const containerEl = document.getElementById('container-meta-diaria');
        const barraEl = document.getElementById('meta-diaria-progresso-barra');
        const textoEl = document.getElementById('meta-diaria-progresso-texto');
        const atingidoEl = document.getElementById('meta-diaria-valor-atingido');
        const totalEl = document.getElementById('meta-diaria-valor-total');

        if (meta && meta.valor_meta_diaria > 0) {
            containerEl.style.display = 'block'; // Garante que o painel seja visível
            const percentual = (meta.valor_atingido_hoje / meta.valor_meta_diaria) * 100;

            barraEl.style.width = `${Math.min(percentual, 100)}%`;
            textoEl.textContent = `${percentual.toFixed(1)}%`;
            atingidoEl.textContent = `R$ ${meta.valor_atingido_hoje.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
            totalEl.textContent = `R$ ${meta.valor_meta_diaria.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
        } else {
            // Se não houver meta para o dia, esconde o painel
            containerEl.style.display = 'none';
        }
    }


    atualizarPainel();
    setInterval(atualizarPainel, 60000);
});
