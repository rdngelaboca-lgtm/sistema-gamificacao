document.addEventListener('DOMContentLoaded', function() {
    const API_BASE_URL = 'http://192.168.2.23:5000';

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

    // ===== NOVA FUNÇÃO PARA RENDERIZAR OS AGENDAMENTOS =====
    function renderizarProximosAgendamentos(agendamentos) {
        const container = document.getElementById('lista-proximos-agendamentos');
        container.innerHTML = '';
        
        if (!agendamentos || agendamentos.length === 0) {
            container.innerHTML = '<p style="text-align: center; color: #888;"><i>Nenhum agendamento futuro.</i></p>';
            return;
        }

        const hoje = new Date();
        hoje.setHours(0, 0, 0, 0); // Normaliza para o início do dia
        
        // 1. Mapeia, Converte a data de 'dd/mm/yyyy HH:MM' para um objeto Date
        const proximos = agendamentos
            .map(ag => {
                try {
                    const [dataParte, horaParte] = ag.data_evento.split(' ');
                    const [dia, mes, ano] = dataParte.split('/');
                    ag.dataObj = new Date(`${ano}-${mes}-${dia}T${horaParte}`);
                    return ag;
                } catch (e) {
                    console.error("Erro ao parsear data do agendamento:", ag.data_evento);
                    return null; // Ignora agendamentos com data inválida
                }
            })
            .filter(ag => ag && ag.dataObj >= hoje) // 2. Filtra (pega só de hoje em diante)
            .slice(0, 5); // 3. Pega apenas os 5 primeiros

        if (proximos.length === 0) {
            container.innerHTML = '<p style="text-align: center; color: #888;"><i>Nenhum agendamento futuro.</i></p>';
            return;
        }

        // 4. Renderiza os itens na tela
        proximos.forEach(ag => {
            const itemDiv = document.createElement('div');
            itemDiv.className = 'agendamento-item';
            
            const dataFormatada = ag.dataObj.toLocaleDateString('pt-BR', {
                weekday: 'short', day: '2-digit', month: '2-digit'
            });
            const horaFormatada = ag.dataObj.toLocaleTimeString('pt-BR', {
                hour: '2-digit', minute: '2-digit'
            });

            itemDiv.innerHTML = `
                <strong>${ag.tipo_evento}</strong>
                <small>${ag.nome_cliente}</small>
                <small style="font-weight: bold; color: #0056b3;">${dataFormatada} às ${horaFormatada}</small>
            `;
            container.appendChild(itemDiv);
        });
    }
    
    async function atualizarPainel() {
        try {
            // Adicionamos 'resAgendamentos' ao Promise.all
            const [resTarefas, resRanking, resFeed, resMeta, resMetaDiaria, resAgendamentos] = await Promise.all([
                fetch(`${API_BASE_URL}/api/painel/tarefas`),
                fetch(`${API_BASE_URL}/api/ranking/diario`),
                fetch(`${API_BASE_URL}/api/feed`),
                fetch(`${API_BASE_URL}/api/meta_principal_do_dia`),
                fetch(`${API_BASE_URL}/api/meta_diaria_do_dia`),
                fetch(`${API_BASE_URL}/api/agendamentos`) 
            ]);

            if (!resTarefas.ok) throw new Error(`Erro na API de tarefas: ${resTarefas.statusText}`);

            // Extraímos os dados da nova chamada
            const dadosTarefas = await resTarefas.json();
            const dadosRanking = resRanking.ok ? await resRanking.json() : [];
            const dadosFeed = resFeed.ok ? await resFeed.json() : [];
            const dadosMeta = resMeta.ok ? await resMeta.json() : {};
            const dadosMetaDiaria = resMetaDiaria.ok ? await resMetaDiaria.json() : {};
            const dadosAgendamentos = resAgendamentos.ok ? await resAgendamentos.json() : []; // <-- NOVOS DADOS

            // Chamamos as funções de renderização
            renderizarColunas(dadosTarefas);
            renderizarProgressoGeral(dadosTarefas.progresso);
            renderizarPodio(dadosRanking);
            renderizarFeed(dadosFeed);
            renderizarMetaPrincipal(dadosMeta);
            renderizarMetaDiaria(dadosMetaDiaria);
            renderizarProximosAgendamentos(dadosAgendamentos); // <-- NOVA CHAMADA DE RENDERIZAÇÃO

            document.getElementById('ultima-atualizacao').textContent = `Última atualização: ${new Date().toLocaleTimeString('pt-BR')}`;

        } catch (error) {
            console.error("Falha ao atualizar o painel:", error);
            document.getElementById('ultima-atualizacao').textContent = `Erro ao atualizar. Tentando novamente...`;
        }
    }

    // Adicione esta nova função ao seu painel.js

    function renderizarProgressoGeral(progresso) {
        const barraEl = document.getElementById('progresso-barra-interna');
        const textoEl = document.getElementById('progresso-texto-label');

        if (progresso && progresso.total > 0) {
            const percentual = (progresso.concluidas / progresso.total) * 100;
            barraEl.style.width = `${percentual}%`;
            textoEl.textContent = `Progresso do Dia: ${progresso.concluidas} / ${progresso.total} tarefas`;
        } else {
            barraEl.style.width = '0%';
            textoEl.textContent = 'Nenhuma tarefa para hoje';
        }
    }

    atualizarPainel();
    setInterval(atualizarPainel, 60000); // Atualiza a cada 60 segundos
});
