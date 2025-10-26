document.addEventListener('DOMContentLoaded', function() {
    const API_BASE_URL = 'http://192.168.18.17:5000';

    function formatarHora(dataString) {
        if (!dataString) return '';
        return new Date(dataString).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    }

    function renderizarPodio(ranking) {
        const podioContainer = document.getElementById('podio-diario');
        podioContainer.innerHTML = '';
        if (!ranking || ranking.length === 0) {
            podioContainer.innerHTML = '<p style="align-self: center; color: #888;"><i>O pódio de hoje ainda está vazio.</i></p>';
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
        const colunas = {
            'coluna-para-fazer': dados.para_fazer,
            'coluna-validacao': dados.validacao,
            'coluna-concluidas': dados.concluidas
        };
        for (const idColuna in colunas) {
            const elementoColuna = document.getElementById(idColuna);
            elementoColuna.innerHTML = '';
            const tarefasAgrupadas = agruparTarefasPorFuncionario(colunas[idColuna]);
            renderizarGrupos(tarefasAgrupadas, elementoColuna, idColuna.split('-')[1]);
        }
    }

    function agruparTarefasPorFuncionario(listaDeTarefas) {
        if (!listaDeTarefas) return {};
        return listaDeTarefas.reduce((grupos, tarefa) => {
            const nome = tarefa.NomeCompleto;
            if (!grupos[nome]) grupos[nome] = [];
            grupos[nome].push(tarefa);
            return grupos;
        }, {});
    }

    function renderizarGrupos(grupos, elementoColuna, tipo) {
        Object.keys(grupos).sort().forEach(nomeFuncionario => {
            const grupoDiv = document.createElement('div');
            grupoDiv.className = 'grupo-funcionario';
            const tituloGrupo = document.createElement('h3');
            tituloGrupo.className = 'grupo-titulo';
            tituloGrupo.textContent = nomeFuncionario;
            grupoDiv.appendChild(tituloGrupo);
            grupos[nomeFuncionario].forEach(tarefa => grupoDiv.appendChild(criarCard(tarefa, tipo)));
            elementoColuna.appendChild(grupoDiv);
        });
    }

    function criarCard(tarefa, tipo) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'card';
        let tituloHtml = `<span>${tarefa.Titulo}</span>`;
        let infoExtra = '';

        if (tipo === 'para_fazer') {
            // Formata a data de referência que vem da API
            const dataRef = new Date(tarefa.DataReferencia);
            const dataRefFormatada = dataRef.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });

            // Adiciona a data no card
            infoExtra = `<p class="card-info">Referente a: ${dataRefFormatada}</p>`; 

            // Adiciona a tag "ATRASADA" se for o caso
            if (tarefa.Categoria === 'Atrasada') {
                tituloHtml += `<span class="card-tag-atrasada">ATRASADA</span>`;
            }

        } else if (tipo === 'validacao') {
            tituloHtml = `<span>⏳</span> ${tituloHtml}`;
            infoExtra = `<p class="card-info">Enviada às: ${formatarHora(tarefa.DataEnvio)}</p>`;

        } else if (tipo === 'concluidas') {
            cardDiv.classList.add('conclida');
            tituloHtml = `<span>✅</span> ${tituloHtml}`;
            infoExtra = `<p class="card-info">Concluída em: ${formatarHora(tarefa.DataEnvio)}</p>`;
        }

        // A linha abaixo foi ajustada para não mostrar "Funcionário: undefined"
        const infoFuncionario = tarefa.NomeCompleto ? `<p class="card-info">Funcionário: ${tarefa.NomeCompleto}</p>` : '';

        cardDiv.innerHTML = `<div class="card-titulo">${tituloHtml}</div>${infoFuncionario}${infoExtra}<p class="card-pontos">+ ${tarefa.Pontos || tarefa.PontosGanhos} pts</p>`;
        return cardDiv;
    }

    function renderizarMetaPrincipal(meta) {
        const containerEl = document.getElementById('container-meta-mensal');
        if (!containerEl) return;
        const tituloEl = document.getElementById('meta-titulo');
        const barraEl = document.getElementById('meta-progresso-barra');
        const textoEl = document.getElementById('meta-progresso-texto');
        const atingidoEl = document.getElementById('meta-valor-atingido');
        const totalEl = document.getElementById('meta-valor-total');

        if (meta && meta.valor_meta > 0) {
            containerEl.style.display = 'flex';
            const percentual = (meta.valor_atingido / meta.valor_meta) * 100;
            tituloEl.textContent = meta.nome_meta;
            barraEl.style.width = `${Math.min(percentual, 100)}%`;
            textoEl.textContent = `${percentual.toFixed(1)}%`;
            atingidoEl.textContent = `R$ ${meta.valor_atingido.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
            totalEl.textContent = `R$ ${meta.valor_meta.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
        } else {
            containerEl.style.display = 'none';
        }
    }

    function renderizarMetaDiaria(meta) {
        const containerEl = document.getElementById('container-meta-diaria');
        if (!containerEl) return;
        const barraEl = document.getElementById('meta-diaria-progresso-barra');
        const textoEl = document.getElementById('meta-diaria-progresso-texto');
        const atingidoEl = document.getElementById('meta-diaria-valor-atingido');
        const totalEl = document.getElementById('meta-diaria-valor-total');

        if (meta && meta.valor_meta_diaria > 0) {
            containerEl.style.display = 'flex';
            const percentual = (meta.valor_atingido_hoje / meta.valor_meta_diaria) * 100;
            barraEl.style.width = `${Math.min(percentual, 100)}%`;
            textoEl.textContent = `${percentual.toFixed(1)}%`;
            atingidoEl.textContent = `R$ ${meta.valor_atingido_hoje.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
            totalEl.textContent = `R$ ${meta.valor_meta_diaria.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
        } else {
            containerEl.style.display = 'none';
        }
    }
    
    function renderizarFeed(eventos) {
        const feedLista = document.getElementById('feed-lista');
        feedLista.innerHTML = '';
        if (!eventos || eventos.length === 0) return;
        eventos.forEach(evento => {
            const item = document.createElement('li');
            const tempoAtras = formatarHora(evento.Timestamp);
            const icone = evento.TipoEvento === 'tarefa_concluida' ? '✅' : '⭐';
            const texto = `<b>${evento.TextoPrincipal}</b> ${evento.TipoEvento === 'tarefa_concluida' ? 'concluiu' : 'desbloqueou'} <i>"${evento.TextoSecundario}"</i> (+${evento.Pontos} pts)`;
            item.innerHTML = `<span class="feed-icone">${icone}</span> <div>${texto} <small style="color: #888;">às ${tempoAtras}</small></div>`;
            feedLista.appendChild(item);
        });
    }

// Em painel.js

function renderizarProximosAgendamentos(agendamentos) {
    const container = document.getElementById('lista-proximos-agendamentos');
    container.innerHTML = ''; // Limpa antes

    if (!agendamentos || agendamentos.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: #888;"><i>Nenhum agendamento futuro confirmado.</i></p>';
        return;
    }

    // A API já envia apenas os próximos 5 confirmados e formatados.
    agendamentos.forEach(ag => {
        const itemDiv = document.createElement('div');
        itemDiv.className = 'agendamento-item';

        // A API envia data_evento como 'dd/mm/yyyy HH:MM'
        const [dataParte, horaParte] = ag.data_evento.split(' ');
        const dataHoraFormatada = `${dataParte} às ${horaParte}`;

        // Cria o link do WhatsApp (se houver telefone)
        let telefoneHtml = '';
        if (ag.telefone_cliente) {
            const numeros = ag.telefone_cliente.replace(/\D/g, '');
            let linkWpp = `https://wa.me/55${numeros}`; // Assume 55 como padrão
            telefoneHtml = `<small>📞 <a href="${linkWpp}" target="_blank">${ag.telefone_cliente}</a></small>`;
        }


        itemDiv.innerHTML = `
            <strong>${ag.nome_cliente}</strong>
            <small>${ag.tipo_evento}</small>
            ${telefoneHtml}  <small style="font-weight: bold; color: #0056b3;">${dataHoraFormatada}</small>
        `;
        container.appendChild(itemDiv);
    });
}

function renderizarProgressoGeral(progresso) {
    const barraInterna = document.getElementById('progresso-barra-interna');
    const textoLabel = document.getElementById('progresso-texto-label');

    if (barraInterna && textoLabel && progresso && typeof progresso.total !== 'undefined' && progresso.total >= 0) {
        const concluidas = progresso.concluidas || 0;
        const total = progresso.total;
        const percentual = total > 0 ? (concluidas / total) * 100 : 0;

        barraInterna.style.width = `${Math.min(percentual, 100)}%`; // Define a largura da barra
        textoLabel.textContent = `${concluidas} de ${total} tarefas concluídas (${percentual.toFixed(0)}%)`; // Atualiza o texto
    } else {
        // Se não houver dados de progresso, mostra um estado padrão
        if (barraInterna) barraInterna.style.width = '0%';
        if (textoLabel) textoLabel.textContent = 'Calculando...';
        // Você pode querer logar um aviso aqui se os dados de progresso estiverem faltando
        // console.warn("Dados de progresso ausentes ou inválidos:", progresso);
    }
}
    
async function atualizarPainel() {
        const statusElement = document.getElementById('ultima-atualizacao');
        try {
            statusElement.textContent = 'Atualizando dados...';
            statusElement.style.color = '#888';

            const [resTarefas, resRanking, resFeed, resMeta, resMetaDiaria, resProximosAgendamentos] = await Promise.all([
            fetch(`${API_BASE_URL}/api/painel/tarefas`),
            fetch(`${API_BASE_URL}/api/ranking/diario`),
            fetch(`${API_BASE_URL}/api/feed`),
            fetch(`${API_BASE_URL}/api/meta_principal_do_dia`),
            fetch(`${API_BASE_URL}/api/meta_diaria_do_dia`),
            fetch(`${API_BASE_URL}/api/agendamentos/proximos`)
            ]);

            if (!resTarefas.ok || !resRanking.ok || !resFeed.ok || !resMeta.ok || !resMetaDiaria.ok || !resProximosAgendamentos.ok) {
             // Log mais detalhado do erro
             const errorDetails = await Promise.all([
                 resTarefas.ok ? null : resTarefas.text(),
                 resRanking.ok ? null : resRanking.text(),
                 resFeed.ok ? null : resFeed.text(),
                 resMeta.ok ? null : resMeta.text(),
                 resMetaDiaria.ok ? null : resMetaDiaria.text(),
                 resProximosAgendamentos.ok ? null : resProximosAgendamentos.text()
             ]);
             console.error("Pelo menos uma resposta da API falhou:", errorDetails.filter(d => d));
             throw new Error(`Erro na API. Status: Tarefas=${resTarefas.status}, Ranking=${resRanking.status}, Feed=${resFeed.status}, MetaP=${resMeta.status}, MetaD=${resMetaDiaria.status}, Agend=${resProximosAgendamentos.status}`);
             }

            const dadosTarefas = await resTarefas.json();
            const dadosRanking = await resRanking.json(); // Não precisa mais verificar .ok aqui
            const dadosFeed = await resFeed.json();
            const dadosMeta = await resMeta.json();
            const dadosMetaDiaria = await resMetaDiaria.json();
            // <<< ALTERAÇÃO AQUI: A API já retorna os dados prontos >>>
            const dadosAgendamentos = await resProximosAgendamentos.json();

            renderizarColunas(dadosTarefas);
            renderizarProgressoGeral(dadosTarefas.progresso);
            renderizarPodio(dadosRanking);
            renderizarFeed(dadosFeed);
            renderizarMetaPrincipal(dadosMeta);
            renderizarMetaDiaria(dadosMetaDiaria);
            // <<< ALTERAÇÃO AQUI: Passa os dados diretamente para a função de renderização >>>
            renderizarProximosAgendamentos(dadosAgendamentos);

            statusElement.textContent = `Última atualização: ${new Date().toLocaleTimeString('pt-BR')}`;
            statusElement.style.color = 'inherit'; // Volta para a cor padrão

    } catch (error) {
        console.error("Falha ao atualizar o painel:", error);
        statusElement.textContent = `Erro ao atualizar (${new Date().toLocaleTimeString('pt-BR')}). Verifique a conexão com a API.`;
        statusElement.style.color = 'red';
    }
}

    // ===== Chamada inicial e agendamento da atualização =====
    atualizarPainel(); // Chama a função uma vez ao carregar a página
    setInterval(atualizarPainel, 60000); // Agenda para atualizar a cada 60 segundos (1 minuto)

}); // <<<<<< Fim do addEventListener('DOMContentLoaded', ...)
