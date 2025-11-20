document.addEventListener('DOMContentLoaded', function() {
    let metaDiariaAnimacaoExibida = false; // Flag para controlar a animação
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

    // ===== FUNÇÃO SIMPLIFICADA PARA RENDERIZAR HISTÓRICO DE LUCRO (SÓ BARRAS) =====
    function renderizarHistoricoLucro(historico) {
        const container = document.getElementById('historico-lucro-barras');
        if (!container) return;
        container.innerHTML = ''; // Limpa o conteúdo anterior

        if (!historico || historico.length === 0 || historico.every(item => item.percentual === 0.0 && item.mes.toLowerCase().includes('erro') || item.mes === 'N/A')) {
            // Mantém a mensagem de indisponível, mas sem necessidade de ocupar muito espaço
            container.innerHTML = '<p style="text-align: center; color: #888; font-size: 0.9em;"><i>Histórico indisponível.</i></p>';
            return;
        }

        const META_LUCRO = 18.0; // Meta de 18%
        const MAX_BARRA_PERCENTUAL = 25; // Teto visual

        historico.forEach(item => {
             if (item.mes === 'N/A' || item.mes.toLowerCase().includes('erro')) {
                return; // Pula meses N/A ou Erro
            }

            const mesItemDiv = document.createElement('div');
            mesItemDiv.className = 'mes-lucro-item';

            // 1. Label do Mês
            const mesLabel = document.createElement('span');
            mesLabel.className = 'mes-lucro-label';
            mesLabel.textContent = item.mes;
            mesItemDiv.appendChild(mesLabel);

            // 2. Container da Barra de Progresso
            const progressoContainer = document.createElement('div');
            progressoContainer.className = 'progresso-lucro-container';

            const progressoBarra = document.createElement('div');
            progressoBarra.className = 'progresso-lucro-barra';

            // Calcula a largura da barra
            let larguraBarra = 0;
            if (item.percentual > 0) {
                larguraBarra = Math.max(1, Math.min((item.percentual / MAX_BARRA_PERCENTUAL) * 100, 100));
            }
            progressoBarra.style.width = `${larguraBarra}%`;

            // Adiciona classe se a meta foi batida para mudar a cor
            if (item.percentual >= META_LUCRO) {
                progressoBarra.classList.add('meta-lucro-batida');
            }

            progressoContainer.appendChild(progressoBarra);
            mesItemDiv.appendChild(progressoContainer);

            // 3. REMOVIDO: Ícone de Olho e Div de Detalhes

            container.appendChild(mesItemDiv);
        });
    }

    function renderizarColunas(dados) {
    // --- CORREÇÃO APLICADA AQUI ---
    // Removemos 'coluna-concluidas' deste objeto, pois ela não existe mais no HTML.
    // A coluna "ATIVIDADE RECENTE" é preenchida pela função renderizarFeed().
    const colunas = {
        'coluna-para-fazer': dados.para_fazer,
        'coluna-validacao': dados.validacao
        // 'coluna-concluidas': dados.concluidas // <-- REMOVIDO
    };
    // ---------------------------------

    for (const idColuna in colunas) {
        const elementoColuna = document.getElementById(idColuna);

        // Adicionamos uma verificação de segurança (embora o erro fosse 'coluna-concluidas')
        if (elementoColuna) {
            elementoColuna.innerHTML = '';
            const tarefasAgrupadas = agruparTarefasPorFuncionario(colunas[idColuna]);
            renderizarGrupos(tarefasAgrupadas, elementoColuna, idColuna.split('-')[1]);
        } else {
            // Isso não deve acontecer agora que removemos 'coluna-concluidas'
            console.error(`Elemento da coluna não encontrado: #${idColuna}`);
        }
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
        
        // Não buscamos mais os elementos de valor (atingido/total) para escrita

        if (meta && meta.valor_meta > 0) {
            containerEl.style.display = 'flex';
            const percentual = (meta.valor_atingido / meta.valor_meta) * 100;
            tituloEl.textContent = meta.nome_meta;
            barraEl.style.width = `${Math.min(percentual, 100)}%`;
            textoEl.textContent = `${percentual.toFixed(1)}%`;
            
            // REMOVIDO: Escrita dos valores monetários
        } else {
            containerEl.style.display = 'none';
        }
    }

    function renderizarMetaDiaria(meta) {
        const containerEl = document.getElementById('container-meta-diaria');
        if (!containerEl) return;
        
        const barraEl = document.getElementById('meta-diaria-progresso-barra');
        const textoEl = document.getElementById('meta-diaria-progresso-texto');
        
        // Não buscamos mais os elementos de valor para escrita

        if (meta && meta.valor_meta_diaria > 0) {
            containerEl.style.display = 'flex';
            const percentual = (meta.valor_atingido_hoje / meta.valor_meta_diaria) * 100;
            
            barraEl.style.width = `${Math.min(percentual, 100)}%`;
            textoEl.textContent = `${percentual.toFixed(1)}%`;
            
            // REMOVIDO: Escrita dos valores monetários e toggle
            
            // --- Lógica de Animação (Mantida) ---
            const valorAtingido = meta.valor_atingido_hoje || 0;
            const valorMeta = meta.valor_meta_diaria || 0;

            if (valorMeta > 0 && valorAtingido >= valorMeta && !metaDiariaAnimacaoExibida) {
                console.log("Meta diária ATINGIDA! Disparando animação...");
                dispararFogos();
                metaDiariaAnimacaoExibida = true;
            }
        } else {
            containerEl.style.display = 'none';
        }
    }

function renderizarFeed(eventos) {
    // REQ 3: Alvo da renderização atualizado para a lista dentro do Kanban
    const feedLista = document.getElementById('feed-lista-kanban'); 
    feedLista.innerHTML = '';
    if (!eventos || eventos.length === 0) {
         feedLista.innerHTML = '<li style="color: #888; font-size: 0.9em;"><i>Nenhuma atividade recente.</i></li>';
        return;
    }
    eventos.forEach(evento => {
        const item = document.createElement('li');
        const tempoAtras = formatarHora(evento.Timestamp);
        // Ícone atualizado para economizar espaço
        const icone = evento.TipoEvento === 'tarefa_concluida' ? '✅' : '⭐'; 
        const texto = `<b>${evento.TextoPrincipal}</b> ${evento.TipoEvento === 'tarefa_concluida' ? 'concluiu' : 'desbloqueou'} <i>"${evento.TextoSecundario}"</i> (+${evento.Pontos} pts)`;

        // Texto formatado para o feed
        item.innerHTML = `<span class="feed-icone">${icone}</span> <div>${texto} <small style="color: #888;">às ${tempoAtras}</small></div>`;
        feedLista.appendChild(item);
    });
}

// REQ 4: Nova função para renderizar o feed de resgates
function renderizarResgatesRecentes(resgates) {
    const resgatesLista = document.getElementById('resgates-lista');
    resgatesLista.innerHTML = '';
    if (!resgates || resgates.length === 0) {
        resgatesLista.innerHTML = '<li style="color: #888; text-align: center;"><i>Nenhum resgate recente.</i></li>';
        return;
    }
    resgates.forEach(resgate => {
        const item = document.createElement('li');
        const tempoAtras = formatarHora(resgate.Timestamp);
        const icone = '🎁'; // Ícone de presente para resgate
        const texto = `<b>${resgate.TextoPrincipal}</b> resgatou <i>"${resgate.TextoSecundario}"</i> (${resgate.Pontos} pts)`;

        item.innerHTML = `<span class="feed-icone">${icone}</span> <div>${texto} <small style="color: #888;">às ${tempoAtras}</small></div>`;
        resgatesLista.appendChild(item);
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
        // Usamos Math.round() para garantir o arredondamento correto (ex: 1.69 -> 2)
        textoLabel.textContent = `${concluidas} de ${total} tarefas concluídas (${Math.round(percentual)}%)`; // Atualiza o texto
    } else {
        // Se não houver dados de progresso, mostra um estado padrão
        if (barraInterna) barraInterna.style.width = '0%';
        if (textoLabel) textoLabel.textContent = 'Calculando...';
        // Você pode querer logar um aviso aqui se os dados de progresso estiverem faltando
        // console.warn("Dados de progresso ausentes ou inválidos:", progresso);
    }
}

async function atualizarMapaLoja() {
        const container = document.getElementById('marcadores-mapa');
        // Se o container não existir (estiver na aba errada ou carregando), para aqui.
        if (!container) return;
        
        try {
            // Faz a chamada para a API
            const response = await fetch(`${API_BASE_URL}/api/escala/hoje`);
            if (!response.ok) return;
            
            const posicoes = await response.json();
            
            container.innerHTML = ''; // Limpa marcadores antigos para não duplicar
            
            posicoes.forEach(pos => {
                const el = document.createElement('div');
                el.className = 'marcador-mapa';
                // Usa as coordenadas que vieram do banco
                el.style.left = `${pos.x}px`; 
                el.style.top = `${pos.y}px`;
                el.style.backgroundColor = pos.cor; // Verde (ocupado) ou Vermelho (vazio)
                
                // Cria o balãozinho com as informações
                el.innerHTML = `
                    <div class="info-box">
                        <strong>${pos.nome_posicao}</strong><br>
                        ${pos.ocupante}<br>
                        <small>${pos.detalhes}</small>
                    </div>
                `;
                
                container.appendChild(el);
            });
        } catch (error) {
            console.error("Erro ao atualizar mapa:", error);
        }
    }


function renderizarGraficoOcupacao(dados) {
        const container = document.getElementById('grafico-barras-container');
        if (!container) return;
        container.innerHTML = '';

        if (!dados || dados.length === 0) {
            container.innerHTML = '<p style="width:100%; text-align:center;">Sem dados de escala.</p>';
            return;
        }

        // Encontra o valor máximo para calcular a altura proporcional (regra de 3)
        // Se o máximo for muito baixo (ex: 2 pessoas), definimos um mínimo de 5 para o gráfico não ficar gigante
        const maxPessoas = Math.max(...dados.map(d => d.qtd), 5); 

        dados.forEach(d => {
            const wrapper = document.createElement('div');
            wrapper.className = 'barra-wrapper';

            const alturaPercentual = (d.qtd / maxPessoas) * 100;

            // Define cor baseada na quantidade (opcional)
            // Ex: Pouca gente (<=2) vermelho, Normal azul
            let corBarra = '#33b5e5'; // Azul padrão
            if (d.qtd > 0 && d.qtd <= 2) corBarra = '#ffbb33'; // Amarelo alerta

            wrapper.innerHTML = `
                <div class="barra-visual" style="height: ${alturaPercentual}%; background-color: ${corBarra};">
                    <span class="barra-valor">${d.qtd > 0 ? d.qtd : ''}</span>
                </div>
                <span class="barra-hora">${d.hora}</span>
            `;

            container.appendChild(wrapper);
        });
    }

    
async function atualizarPainel() {
    // Reseta a flag da animação se o dia mudou (usando localStorage)
    const hoje = new Date().toDateString();
    if (localStorage.getItem('ultimoDiaAnimacaoMetaDiaria') !== hoje) {
        metaDiariaAnimacaoExibida = false;
        localStorage.setItem('ultimoDiaAnimacaoMetaDiaria', hoje);
        console.log("Novo dia detectado, flag de animação da meta diária resetada.");
    }
    const statusElement = document.getElementById('ultima-atualizacao');
    try {
        statusElement.textContent = 'Atualizando dados...';
        statusElement.style.color = '#888';


        // --- INICIO DA CORRECAO ---
        // Lista de URLs que vamos buscar
        const endpoints = [
            `${API_BASE_URL}/api/painel/tarefas`,           // Indice 0
            `${API_BASE_URL}/api/ranking/diario`,           // Indice 1
            `${API_BASE_URL}/api/feed`,                     // Indice 2
            `${API_BASE_URL}/api/meta_principal_do_dia`,    // Indice 3
            `${API_BASE_URL}/api/meta_diaria_do_dia`,       // Indice 4
            `${API_BASE_URL}/api/agendamentos/proximos`,    // Indice 5
            `${API_BASE_URL}/api/historico_lucro`,          // Indice 6
            `${API_BASE_URL}/api/resgates/recentes`,         // Indice 7
            `${API_BASE_URL}/api/escala/ocupacao`           // Indice 8 (NOVO)
        ];

        // Promise.allSettled: Tenta buscar todos. Se um falhar, ele NÃO trava os outros.
        // Cada resultado terá status 'fulfilled' (sucesso) ou 'rejected' (erro).
        const resultados = await Promise.allSettled(
            endpoints.map(url => fetch(url).then(r => r.ok ? r.json() : null))
        );

        // Agora extraímos os dados. Se deu erro ou veio null, colocamos um valor vazio padrão
        // para que o painel continue funcionando com as partes que deram certo.
        
        const dadosTarefas = resultados[0].status === 'fulfilled' && resultados[0].value 
            ? resultados[0].value 
            : { para_fazer: [], validacao: [], progresso: {} };

        const dadosRanking = resultados[1].status === 'fulfilled' && resultados[1].value 
            ? resultados[1].value 
            : [];

        const dadosFeed = resultados[2].status === 'fulfilled' && resultados[2].value 
            ? resultados[2].value 
            : [];

        const dadosMeta = resultados[3].status === 'fulfilled' && resultados[3].value 
            ? resultados[3].value 
            : null;

        const dadosMetaDiaria = resultados[4].status === 'fulfilled' && resultados[4].value 
            ? resultados[4].value 
            : null;

        const dadosAgendamentos = resultados[5].status === 'fulfilled' && resultados[5].value 
            ? resultados[5].value 
            : [];

        const dadosHistoricoLucro = resultados[6].status === 'fulfilled' && resultados[6].value 
            ? resultados[6].value 
            : [];

        const dadosResgates = resultados[7].status === 'fulfilled' && resultados[7].value 
            ? resultados[7].value 
            : [];

        const dadosOcupacao = resultados[8].status === 'fulfilled' && resultados[8].value ? resultados[8].value : [];
        // --- FIM DA CORRECAO ---


        renderizarColunas(dadosTarefas);
        renderizarProgressoGeral(dadosTarefas.progresso);
        renderizarPodio(dadosRanking);
        renderizarFeed(dadosFeed);
        renderizarMetaPrincipal(dadosMeta);
        renderizarMetaDiaria(dadosMetaDiaria);
        renderizarProximosAgendamentos(dadosAgendamentos);
        renderizarHistoricoLucro(dadosHistoricoLucro);
        renderizarResgatesRecentes(dadosResgates); 

         atualizarMapaLoja();
         renderizarGraficoOcupacao(dadosOcupacao);

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

    // =========================================================================
    // == INÍCIO DOS EVENT LISTENERS E FUNÇÕES AUXILIARES (DENTRO DO DOM) ======
    // =========================================================================

    // REQ 1: Event Listener atualizado para o ícone (👁️) da Meta do Dia
    const toggleValoresButton = document.getElementById('toggle-valores-dia');
    const metaValoresContainer = document.getElementById('meta-diaria-valores');

    if (toggleValoresButton && metaValoresContainer) {
        toggleValoresButton.addEventListener('click', () => {
            // Adiciona ou remove a classe 'oculto' do container dos valores
            metaValoresContainer.classList.toggle('oculto');

            // Muda o ícone (🙈 para oculto, 👁️ para visível)
            toggleValoresButton.textContent = metaValoresContainer.classList.contains('oculto') ? '🙈' : '👁️';
        });
    } else {
        console.error("Erro: Elemento do botão de toggle ou container dos valores da meta diária não encontrado.");
    }
    // ===== FIM DO EVENT LISTENER ATUALIZADO =====


    // --- INÍCIO: Função para disparar a animação de fogos ---
    // (Esta função é chamada por renderizarMetaDiaria, então ela precisa
    // estar acessível no escopo do DOMContentLoaded onde as outras funções estão)
    function dispararFogos() {
        // Usa a biblioteca canvas-confetti
        // Configuração para simular fogos (cores, formas, etc.)
        const duration = 5 * 1000; // Duração da animação (5 segundos)
        const animationEnd = Date.now() + duration;
        const defaults = { startVelocity: 30, spread: 360, ticks: 60, zIndex: 9999 };

        function randomInRange(min, max) {
            return Math.random() * (max - min) + min;
        }

        const interval = setInterval(function() {
            const timeLeft = animationEnd - Date.now();

            if (timeLeft <= 0) {
                return clearInterval(interval);
            }

            const particleCount = 50 * (timeLeft / duration);
            // Dispara da esquerda e da direita
            confetti(Object.assign({}, defaults, { particleCount, origin: { x: randomInRange(0.1, 0.3), y: Math.random() - 0.2 }, shapes: ['star'], colors: ['#FFD700', '#FF4500', '#FFFFFF', '#00FF00', '#0000FF'] }));
            confetti(Object.assign({}, defaults, { particleCount, origin: { x: randomInRange(0.7, 0.9), y: Math.random() - 0.2 }, shapes: ['star'], colors: ['#FFD700', '#FF4500', '#FFFFFF', '#00FF00', '#0000FF'] }));
        }, 250);
    }
    // --- FIM: Função para disparar a animação ---

    // =========================================================================
    // == FIM DOS EVENT LISTENERS E FUNÇÕES AUXILIARES =========================
    // =========================================================================

}); // <<<<<< Fim do addEventListener('DOMContentLoaded', ...)

// (A função "dispararFogos" que estava aqui foi movida para dentro do DOMContentLoaded)

