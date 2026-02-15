// Variável para guardar os dados na memória do navegador
let dadosOcupacaoCache = [];

// Configura o ouvinte do Dropdown assim que o JS carregar
const filtroSetorEl = document.getElementById('filtro-setor-grafico');
if (filtroSetorEl) {
    filtroSetorEl.addEventListener('change', function() {
        console.log("Mudança de setor detectada:", this.value);
        // Chama a função sem passar novos dados, forçando o uso do cache
        renderizarGraficoOcupacao(null);
    });
}

function renderizarGraficoOcupacao(novosDados) {
    const container = document.getElementById('grafico-barras-container');
    const selectFiltro = document.getElementById('filtro-setor-grafico');

    if (!container) return;

    // --- LÓGICA DE CACHE ---
    // 1. Se a API mandou dados novos, atualizamos o cache
    if (novosDados && novosDados.length > 0) {
        dadosOcupacaoCache = novosDados;
    }

    // 2. Se não temos dados nem novos e nem no cache, paramos
    if (!dadosOcupacaoCache || dadosOcupacaoCache.length === 0) {
        container.innerHTML = '<p style="width:100%; text-align:center; color: #666;">Aguardando dados da escala...</p>';
        return;
    }

    // 3. Usamos sempre os dados do Cache para desenhar/redesenhar
    const dadosParaProcessar = dadosOcupacaoCache;
    // -----------------------

    container.innerHTML = '';

    // Pega o setor selecionado no momento
    const setorSelecionado = selectFiltro ? selectFiltro.value : "Geral (Todos)";

    // Processa os dados hora a hora (07:00 as 23:00)
    const horasEixo = [7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23];
    const dadosGrafico = [];

    const paraMinutos = (strHora) => {
        if (!strHora) return null;
        const [h, m] = strHora.split(':').map(Number);
        return h * 60 + m;
    };

    horasEixo.forEach(hora => {
        const momentoAnalise = hora * 60; 
        let qtdPessoas = 0;

        dadosParaProcessar.forEach(item => {
            // --- FILTRO: A mágica acontece aqui ---
            if (setorSelecionado !== "Geral (Todos)" && item.setor !== setorSelecionado) {
                return; // Pula este funcionário se não for do setor escolhido
            }

            const ent = paraMinutos(item.entrada);
            const sai = paraMinutos(item.saida);
            const intIni = paraMinutos(item.int_ini);
            const intFim = paraMinutos(item.int_fim);

            if (ent === null || sai === null) return;

            let noTurno = false;
            if (ent <= sai) {
                if (ent <= momentoAnalise && momentoAnalise < sai) noTurno = true;
            } else { 
                if (momentoAnalise >= ent || momentoAnalise < sai) noTurno = true;
            }

            if (noTurno) {
                let noIntervalo = false;
                if (intIni !== null && intFim !== null) {
                    if (intIni <= intFim) {
                        if (intIni <= momentoAnalise && momentoAnalise < intFim) noIntervalo = true;
                    } else { 
                        if (momentoAnalise >= intIni || momentoAnalise < intFim) noIntervalo = true;
                    }
                }
                if (!noIntervalo) qtdPessoas++;
            }
        });

        dadosGrafico.push({ hora: `${hora}:00`, qtd: qtdPessoas });
    });

    // Renderiza as barras
    const maxPessoas = Math.max(...dadosGrafico.map(d => d.qtd), 5); 

    dadosGrafico.forEach(d => {
        const wrapper = document.createElement('div');
        wrapper.className = 'barra-wrapper';

        const alturaPercentual = (d.qtd / maxPessoas) * 100;

        let corBarra = '#33b5e5'; // Azul padrão para setores
        if (setorSelecionado === "Geral (Todos)") {
            if (d.qtd < 3) corBarra = '#d9534f'; // Vermelho alerta
            else corBarra = '#5cb85c'; // Verde ok
        }

        wrapper.innerHTML = `
            <div class="barra-visual" style="height: ${alturaPercentual}%; background-color: ${corBarra};">
                <span class="barra-valor">${d.qtd > 0 ? d.qtd : ''}</span>
            </div>
            <span class="barra-hora">${d.hora}</span>
        `;
        container.appendChild(wrapper);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    let metaDiariaAnimacaoExibida = false; // Flag para controlar a animação
    // CORREÇÃO: Usa string vazia para forçar o uso da mesma origem (IP/Porta) do navegador
    const API_BASE_URL = '';

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

            // [CORREÇÃO] Lógica para tratar Lucro vs Prejuízo
            let larguraBarra = 0;

            // Remove classes de estado anteriores para evitar conflitos
            progressoBarra.classList.remove('meta-lucro-batida', 'meta-prejuizo');

            if (item.percentual < 0) {
                // Se for prejuízo, fixa um tamanho visual mínimo para mostrar que existe algo, mas pinta de vermelho
                larguraBarra = Math.min(Math.abs(item.percentual) * 2, 100); // *2 para dar ênfase visual ao prejuízo
                progressoBarra.classList.add('meta-prejuizo'); 
            } else {
                // Lucro positivo
                larguraBarra = Math.max(1, Math.min((item.percentual / MAX_BARRA_PERCENTUAL) * 100, 100));
                if (item.percentual >= META_LUCRO) {
                    progressoBarra.classList.add('meta-lucro-batida');
                }
            }
            progressoBarra.style.width = `${larguraBarra}%`;
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

        // --- LÓGICA DE HORÁRIO E ALERTA (GRUPOS) ---
        if (tipo === 'para_fazer') {
            
            // [DEBUG] Imprime no console o que está chegando do banco de dados para diagnóstico
            // Pressione F12 -> Console para ver esses logs
            if (tarefa.HorarioDisparo !== undefined) {
                // console.log(`Tarefa: "${tarefa.Titulo}" | HorarioDisparo: [${tarefa.HorarioDisparo}]`);
            }

            // Verifica se a tarefa tem um horário de disparo definido e não é vazio
            if (tarefa.HorarioDisparo && tarefa.HorarioDisparo.trim() !== '') {
                // Formata para mostrar apenas HH:MM
                const horaFormatada = tarefa.HorarioDisparo.substring(0, 5);
                
                // Adiciona o horário visualmente no card
                infoExtra += `<span class="card-hora-grupo">🕒 Disparado às ${horaFormatada}</span>`;

                // --- CÁLCULO DE ATRASO ---
                try {
                    // Cria datas para comparação
                    const agora = new Date();
                    const dataDisparo = new Date();
                    
                    // Divide a string "18:00:00" em partes
                    const partes = tarefa.HorarioDisparo.split(':');
                    if (partes.length >= 2) {
                        dataDisparo.setHours(parseInt(partes[0]), parseInt(partes[1]), 0, 0);

                        // Correção para virada do dia (Ex: Tarefa 23:00, Agora 00:10)
                        // Se o horário de disparo for maior que agora, assumimos que foi ontem
                        if (dataDisparo > agora) {
                            dataDisparo.setDate(dataDisparo.getDate() - 1);
                        }

                        // Calcula diferença em minutos
                        const diferencaMs = agora - dataDisparo;
                        const diferencaMinutos = diferencaMs / 1000 / 60;

                        // Se passou de 30 minutos, ativa o alerta
                        if (diferencaMinutos > 30) {
                            cardDiv.classList.add('alerta-atraso');
                            tituloHtml = `<span>⚠️</span> ${tituloHtml}`; // Adiciona ícone de alerta no título
                        }
                    }
                } catch (e) {
                    console.error("Erro ao calcular data do alerta:", e);
                }
            } else if (tarefa.DataReferencia) {
                // Fallback para tarefas individuais: mostra apenas a data simples
                const dataRef = new Date(tarefa.DataReferencia);
                const dataRefFormatada = dataRef.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                infoExtra = `<p class="card-info">Data: ${dataRefFormatada}</p>`;
            }
            
            // Tag de Atrasada (para tarefas individuais antigas)
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

        const infoFuncionario = tarefa.NomeCompleto ? `<p class="card-info">Responsável: ${tarefa.NomeCompleto}</p>` : '';

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

    // [CORREÇÃO] Verifica se valor_meta_diaria > 0 para evitar divisão por zero
        if (meta && meta.valor_meta_diaria > 0) {
            containerEl.style.display = 'flex';
            // Garante cálculo seguro: se meta for 0 (por erro de dado), percentual é 0
            const percentual = meta.valor_meta_diaria > 0 
                ? (meta.valor_atingido_hoje / meta.valor_meta_diaria) * 100 
                : 0;

            barraEl.style.width = `${Math.min(percentual, 100)}%`;            textoEl.textContent = `${percentual.toFixed(1)}%`;
            
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
        item.className = 'feed-item-instagram'; // Nova classe para estilização
        const tempoAtras = formatarHora(evento.Timestamp);
        
        // Cabeçalho: Ícone + Texto
        const icone = evento.TipoEvento === 'tarefa_concluida' ? '✅' : '⭐'; 
        const texto = `<b>${evento.TextoPrincipal}</b> ${evento.TipoEvento === 'tarefa_concluida' ? 'concluiu' : 'desbloqueou'} <i>"${evento.TextoSecundario}"</i> <span class="feed-pontos">(+${evento.Pontos} pts)</span>`;
        
        let htmlImagem = '';
        
        // Se houver caminho de foto e for tarefa, monta a imagem
        if (evento.CaminhoFoto && evento.TipoEvento === 'tarefa_concluida') {
            // Extrai apenas o nome do arquivo do caminho completo (compatível com barras Windows/Linux)
            const nomeArquivo = evento.CaminhoFoto.split(/[\\/]/).pop();
            // Monta a URL apontando para a nova rota da API
            const urlImagem = `${API_BASE_URL}/imagens/entregas/${nomeArquivo}`;
            
            htmlImagem = `
                <div class="feed-imagem-wrapper">
                    <img src="${urlImagem}" alt="Evidência" class="feed-foto" onerror="this.style.display='none'">
                </div>
            `;
        }

        // Montagem do HTML Final do Card
        item.innerHTML = `
            <div class="feed-header">
                <span class="feed-icone">${icone}</span> 
                <div class="feed-texto">${texto}</div>
            </div>
            ${htmlImagem}
            <div class="feed-footer">
                <small>🕒 ${tempoAtras}</small>
            </div>
        `;
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
    const containerPai = document.getElementById('container-do-mapa');
    
    if (!container || !containerPai) return;
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/escala/hoje`);
        if (!response.ok) return;
        
        const posicoes = await response.json();
        
        // --- CÁLCULO DA ÁREA REAL DA IMAGEM ---
        // Dimensões originais da imagem (Baseado no seu Desktop App)
        const imgOriginalW = 1180;
        const imgOriginalH = 600;
        const ratioOriginal = imgOriginalW / imgOriginalH;

        // Dimensões do container na tela
        const rect = containerPai.getBoundingClientRect();
        const containerW = rect.width;
        const containerH = rect.height;
        const containerRatio = containerW / containerH;

        let renderW, renderH, offsetX, offsetY;

        // Lógica do 'background-size: contain'
        if (containerRatio > ratioOriginal) {
            // Container é mais largo que a imagem -> Altura limita
            renderH = containerH;
            renderW = containerH * ratioOriginal;
            offsetX = (containerW - renderW) / 2; // Centralizado horizontalmente
            offsetY = 0; // Topo
        } else {
            // Container é mais alto que a imagem -> Largura limita
            renderW = containerW;
            renderH = containerW / ratioOriginal;
            offsetX = 0;
            offsetY = 0; // Topo (definido no CSS como 'center top')
            // Se fosse 'center center', o offsetY seria (containerH - renderH) / 2
        }

        container.innerHTML = ''; 
        
        posicoes.forEach(pos => {
            const el = document.createElement('div');
            el.className = 'marcador-mapa';
            
            let posX, posY;

            // Lógica Híbrida (Percentual vs Pixel)
            if (pos.x <= 2 && pos.y <= 2) {
                // Percentual (0.0 a 1.0)
                posX = offsetX + (pos.x * renderW);
                posY = offsetY + (pos.y * renderH);
            } else {
                // Legado (Pixels fixos baseados em 1180x600)
                const pctX = pos.x / 1180;
                const pctY = pos.y / 600;
                posX = offsetX + (pctX * renderW);
                posY = offsetY + (pctY * renderH);
            }

            el.style.left = `${posX}px`; 
            el.style.top = `${posY}px`;
            el.style.backgroundColor = pos.cor;
            
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


function renderizarGraficoOcupacao(dadosBrutos) {
    // Atualiza o cache global
    dadosOcupacaoCache = dadosBrutos;

    const container = document.getElementById('grafico-barras-container');
    const selectFiltro = document.getElementById('filtro-setor-grafico');

    if (!container) return;
    container.innerHTML = '';

    if (!dadosBrutos || dadosBrutos.length === 0) {
        container.innerHTML = '<p style="width:100%; text-align:center;">Sem dados de escala.</p>';
        return;
    }

    // 1. Pega o setor selecionado
    const setorSelecionado = selectFiltro ? selectFiltro.value : "Geral (Todos)";

    // 2. Processa os dados hora a hora (07:00 as 23:00)
    const horasEixo = [7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23];
    const dadosGrafico = [];

    // Função auxiliar para converter "HH:MM" em minutos desde 00:00
    const paraMinutos = (strHora) => {
        if (!strHora) return null;
        const [h, m] = strHora.split(':').map(Number);
        return h * 60 + m;
    };

    horasEixo.forEach(hora => {
        const momentoAnalise = hora * 60; // Minutos (ex: 08:00 = 480)
        let qtdPessoas = 0;

        dadosBrutos.forEach(item => {
            // Filtro de Setor
            if (setorSelecionado !== "Geral (Todos)" && item.setor !== setorSelecionado) {
                return;
            }

            const ent = paraMinutos(item.entrada);
            const sai = paraMinutos(item.saida);
            const intIni = paraMinutos(item.int_ini);
            const intFim = paraMinutos(item.int_fim);

            if (ent === null || sai === null) return;

            // Lógica de Turno
            let noTurno = false;
            if (ent <= sai) {
                if (ent <= momentoAnalise && momentoAnalise < sai) noTurno = true;
            } else { // Turno vira a noite
                if (momentoAnalise >= ent || momentoAnalise < sai) noTurno = true;
            }

            if (noTurno) {
                // Lógica de Intervalo (Desconto)
                let noIntervalo = false;
                if (intIni !== null && intFim !== null) {
                    if (intIni <= intFim) {
                        if (intIni <= momentoAnalise && momentoAnalise < intFim) noIntervalo = true;
                    } else { // Intervalo vira noite
                        if (momentoAnalise >= intIni || momentoAnalise < intFim) noIntervalo = true;
                    }
                }

                if (!noIntervalo) {
                    qtdPessoas++;
                }
            }
        });

        dadosGrafico.push({ hora: `${hora}:00`, qtd: qtdPessoas });
    });

    // 3. Renderiza as barras (Lógica Visual)
    const maxPessoas = Math.max(...dadosGrafico.map(d => d.qtd), 5); // Escala mínima de 5

    dadosGrafico.forEach(d => {
        const wrapper = document.createElement('div');
        wrapper.className = 'barra-wrapper';

        const alturaPercentual = (d.qtd / maxPessoas) * 100;

        // Cores: Se tem filtro específico = Azul. Se Geral: Vermelho (poucos) / Verde (ok)
        let corBarra = '#33b5e5'; // Azul
        if (setorSelecionado === "Geral (Todos)") {
            if (d.qtd < 3) corBarra = '#d9534f'; // Vermelho
            else corBarra = '#5cb85c'; // Verde
        }

        wrapper.innerHTML = `
            <div class="barra-visual" style="height: ${alturaPercentual}%; background-color: ${corBarra};">
                <span class="barra-valor">${d.qtd > 0 ? d.qtd : ''}</span>
            </div>
            <span class="barra-hora">${d.hora}</span>
        `;
        container.appendChild(wrapper);
    });
}
    
// === NOVA FUNCIONALIDADE: CRONOGRAMA DE PAUSAS ===

function timeToMinutes(timeStr) {
    if (!timeStr) return -1;
    const [h, m] = timeStr.split(':').map(Number);
    return h * 60 + m;
}

async function atualizarCronogramaPausas() {
    const container = document.getElementById('lista-pausas-content');
    const relogio = document.getElementById('relogio-tempo-real');

    if (!container) return; 

    try {
        // 1. Relógio Visual
        const agora = new Date();
        const horaStr = agora.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
        if (relogio) relogio.textContent = horaStr;

        const minutosAgora = timeToMinutes(horaStr);

        // 2. Busca dados
        const response = await fetch(`${API_BASE_URL}/api/escala/tabela`);
        if (!response.ok) return;
        const dadosAgrupados = await response.json();

        container.innerHTML = '';

        // 3. Ordem de Setores
        const ordem = ['Cozinha', 'Buffet', 'Caixa', 'Atendimento', 'Salão', 'Frente Loja', 'Varanda', 'Limpeza', 'Camara Fria'];

        const setores = Object.keys(dadosAgrupados).sort((a, b) => {
            const idxA = ordem.indexOf(a);
            const idxB = ordem.indexOf(b);
            return (idxA === -1 ? 99 : idxA) - (idxB === -1 ? 99 : idxB);
        });

        if (setores.length === 0) {
            container.innerHTML = '<p style="text-align:center; padding:20px; color:#888;">Sem escala hoje.</p>';
            return;
        }

        // 4. Renderização
        setores.forEach(setor => {
            const funcs = dadosAgrupados[setor];
            if (!funcs || funcs.length === 0) return;

            const bloco = document.createElement('div');
            bloco.className = 'setor-bloco';

            const titulo = document.createElement('div');
            titulo.className = 'setor-titulo';
            titulo.textContent = setor;
            bloco.appendChild(titulo);

            funcs.forEach(f => {
                const card = document.createElement('div');
                card.className = 'pausa-card';

                let statusClass = 'status-futuro';
                let icone = '';
                let textoHorario = 'Sem intervalo';

                if (f.int_ini && f.int_fim) {
                    textoHorario = `${f.int_ini} - ${f.int_fim}`;
                    const mIni = timeToMinutes(f.int_ini);
                    const mFim = timeToMinutes(f.int_fim);

                    if (minutosAgora >= mFim) {
                        statusClass = 'status-concluido';
                        icone = '🏁';
                    } else if (minutosAgora >= mIni && minutosAgora < mFim) {
                        statusClass = 'status-em-pausa';
                        icone = '☕';
                    } else {
                        icone = '⏳'; // Futuro
                    }
                }

                card.classList.add(statusClass);

                card.innerHTML = `
                    <div class="pausa-info">
                        <span class="pausa-nome">${f.nome}</span>
                        <span class="pausa-horario">${textoHorario}</span>
                    </div>
                    <div class="pausa-status-icon">${icone}</div>
                `;
                bloco.appendChild(card);
            });

            container.appendChild(bloco);
        });

    } catch (error) {
        console.error("Erro cronograma:", error);
    }
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
         atualizarCronogramaPausas(); // Atualiza a lista lateral

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

// Função atualizada para trocar de abas e carregar a agenda
function abrirAba(nomeAba) {
    // 1. Esconde TODAS as abas (procura pela classe .tab-content)
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.style.display = 'none';
    });
    
    // 2. Remove a classe 'active' de todos os botões
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // 3. Mostra a aba clicada
    const abaAlvo = document.getElementById('tab-' + nomeAba);
    if (abaAlvo) {
        abaAlvo.style.display = 'block';
    }
    
    // 4. Marca o botão clicado como ativo
    if (event && event.currentTarget) {
        event.currentTarget.classList.add('active');
    }

    // 5. Se for a aba da Agenda, inicializa o calendário
    if (nomeAba === 'agenda') {
        // Pequeno delay para garantir que a div está visível antes de desenhar
        setTimeout(inicializarCalendario, 100);
    }
}

// =========================================================
// === MÓDULO DE AGENDA E CALENDÁRIO (FULLCALENDAR) ========
// =========================================================

let calendarInstance = null;

function inicializarCalendario() {
    const calendarEl = document.getElementById('calendar');
    if (!calendarEl) return;

    if (calendarInstance) {
        calendarInstance.refetchEvents();
        calendarInstance.render();
        return;
    }

    calendarInstance = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        locale: 'pt-br',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,listWeek'
        },
        buttonText: { today: 'Hoje', month: 'Mês', week: 'Semana', list: 'Lista' },
        height: 'auto',
        navLinks: true,
        editable: false,
        
        // BUSCAR EVENTOS DA API
        events: function(info, successCallback, failureCallback) {
            fetch('http://192.168.18.44:5000/api/agendamentos')
                .then(response => response.json())
                .then(data => {
                    const eventosFormatados = data.map(ag => {
                        const [dataPt, horaPt] = ag.data_evento.split(' ');
                        const [dia, mes, ano] = dataPt.split('/');
                        const dataIso = `${ano}-${mes}-${dia}T${horaPt}:00`;

                        let cor = '#3788d8';
                        if(ag.tipo_evento.includes('Festa')) cor = '#e83e8c';
                        if(ag.tipo_evento.includes('Carrinho')) cor = '#fd7e14';
                        if(ag.tipo_evento.includes('Torta')) cor = '#20c997';
                        
                        return {
                            id: ag.agendamento_id,
                            title: `${horaPt} - ${ag.nome_cliente}`,
                            start: dataIso,
                            backgroundColor: cor,
                            borderColor: cor,
                            // Dados extras para o formulário de edição
                            extendedProps: {
                                nome_cliente: ag.nome_cliente,
                                tipo: ag.tipo_evento,
                                telefone: ag.telefone_cliente,
                                cpf: ag.cpf_cliente,
                                status_pag: ag.status_pagamento,
                                obs: ag.observacoes || "",
                                funcionario_id: ag.funcionario_id || 2, // Default Gestor
                                data_pura: `${ano}-${mes}-${dia}`,
                                hora_pura: horaPt
                            }
                        };
                    });
                    successCallback(eventosFormatados);
                })
                .catch(error => {
                    console.error('Erro ao buscar agenda:', error);
                    failureCallback(error);
                });
        },

        // CLIQUE NO EVENTO -> ABRE EDIÇÃO
        eventClick: function(info) {
            abrirModalEdicao(info.event);
        }
    });

    calendarInstance.render();
}

// --- FUNÇÕES DO MODAL ---

function abrirModalAgendamento() {
    // Configura para MODO CRIAÇÃO
    document.getElementById('modal-agendamento').style.display = 'flex';
    document.getElementById('modal-titulo').innerText = "📅 Novo Agendamento";
    document.getElementById('form-agendamento').reset();
    document.getElementById('ag-id').value = ""; // Limpa ID
    
    // Mostra botões de Novo, esconde de Edição
    document.getElementById('btn-container-novo').style.display = 'block';
    document.getElementById('btn-container-editar').style.display = 'none';

    // Padrões
    document.getElementById('ag-data').value = new Date().toISOString().split('T')[0];
    document.getElementById('ag-hora').value = "14:00";
}

function abrirModalEdicao(evento) {
    // Configura para MODO EDIÇÃO
    document.getElementById('modal-agendamento').style.display = 'flex';
    document.getElementById('modal-titulo').innerText = "✏️ Editar / Excluir Agendamento";
    
    // Mostra botões de Edição, esconde de Novo
    document.getElementById('btn-container-novo').style.display = 'none';
    document.getElementById('btn-container-editar').style.display = 'flex';

    // Preenche os campos com os dados do evento clicado
    const props = evento.extendedProps;
    document.getElementById('ag-id').value = evento.id;
    document.getElementById('ag-cliente').value = props.nome_cliente; // Pega nome puro
    document.getElementById('ag-funcionario').value = props.funcionario_id;
    document.getElementById('ag-telefone').value = props.telefone;
    document.getElementById('ag-cpf').value = props.cpf;
    document.getElementById('ag-tipo').value = props.tipo;
    document.getElementById('ag-pagamento').value = props.status_pag;
    document.getElementById('ag-obs').value = props.obs;
    document.getElementById('ag-data').value = props.data_pura;
    document.getElementById('ag-hora').value = props.hora_pura;
}

function fecharModalAgendamento() {
    document.getElementById('modal-agendamento').style.display = 'none';
}

function processarFormulario(event) {
    event.preventDefault();
    // Esta função é chamada apenas pelo botão de SALVAR NOVO
    // O botão de salvar edição chama atualizarAgendamento diretamente
    salvarNovoAgendamento();
}

// 1. CRIAR NOVO
async function salvarNovoAgendamento() {
    const payload = coletarDadosFormulario();
    try {
        const response = await fetch('http://192.168.18.44:5000/agendamentos/novo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok) {
            alert("✅ " + result.mensagem);
            fecharModalAgendamento();
            calendarInstance.refetchEvents();
        } else {
            alert("❌ Erro: " + result.mensagem);
        }
    } catch (error) { console.error(error); alert("Erro de conexão."); }
}

// 2. ATUALIZAR EXISTENTE (PUT)
async function atualizarAgendamento() {
    const id = document.getElementById('ag-id').value;
    if(!id) return;

    if(!confirm("Deseja salvar as alterações neste agendamento?")) return;

    const payload = coletarDadosFormulario();
    // A rota de atualização espera o ID na URL
    try {
        const response = await fetch(`http://192.168.18.44:5000/agendamentos/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok) {
            alert("✅ Agendamento atualizado!");
            fecharModalAgendamento();
            calendarInstance.refetchEvents();
        } else {
            alert("❌ Erro: " + result.mensagem);
        }
    } catch (error) { console.error(error); alert("Erro de conexão."); }
}

// 3. EXCLUIR (DELETE)
async function excluirAgendamento() {
    const id = document.getElementById('ag-id').value;
    if(!id) return;

    if(!confirm("⚠️ Tem certeza que deseja EXCLUIR este agendamento?\nEssa ação não pode ser desfeita.")) return;

    try {
        const response = await fetch(`http://192.168.18.44:5000/agendamentos/${id}`, {
            method: 'DELETE'
        });
        
        if (response.status === 204) {
            alert("🗑️ Agendamento excluído.");
            fecharModalAgendamento();
            calendarInstance.refetchEvents();
        } else {
            alert("❌ Erro ao excluir.");
        }
    } catch (error) { console.error(error); alert("Erro de conexão."); }
}

// 4. ABRIR WHATSAPP
function abrirWhatsAppCliente() {
    const tel = document.getElementById('ag-telefone').value;
    const telLimpo = tel.replace(/\D/g, '');
    if(telLimpo) window.open(`https://wa.me/55${telLimpo}`, '_blank');
    else alert("Telefone inválido.");
}

// Helper para pegar dados do form
function coletarDadosFormulario() {
    const dataInput = document.getElementById('ag-data').value;
    const horaInput = document.getElementById('ag-hora').value;
    
    return {
        funcionario_id: document.getElementById('ag-funcionario').value,
        nome_cliente: document.getElementById('ag-cliente').value,
        telefone_cliente: document.getElementById('ag-telefone').value,
        cpf_cliente: document.getElementById('ag-cpf').value,
        tipo_evento: document.getElementById('ag-tipo').value,
        status_pagamento: document.getElementById('ag-pagamento').value,
        data_evento: `${dataInput} ${horaInput}`,
        observacoes: document.getElementById('ag-obs').value
    };
}

window.onclick = function(event) {
    const modal = document.getElementById('modal-agendamento');
    if (event.target == modal) fecharModalAgendamento();
}
