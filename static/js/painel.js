// =============================================================================
// painel.js  -  Painel da TV (templates/painel.html)
// Versão DEPURADA: procure por [DEPURAÇÃO] para ver cada correção.
// =============================================================================

// =============================================================================
// == [DEPURAÇÃO] FUNÇÕES AUXILIARES (usadas no arquivo todo) ==================
// =============================================================================

/**
 * [DEPURAÇÃO] Protege o painel contra textos com < > & " '.
 * Antes, nomes de clientes, títulos de tarefas e observações eram colocados direto
 * no HTML: um nome como "Ana <b>" quebrava o layout, e um texto malicioso podia
 * rodar comandos no navegador da TV.
 */
function esc(valor) {
    return String(valor === null || valor === undefined ? '' : valor)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/**
 * [DEPURAÇÃO] Lê "HH:MM" direto do texto que veio do servidor.
 * O Flask envia datas assim: "Wed, 24 Sep 2026 14:30:00 GMT". O horário é o da
 * LOJA, mas vem marcado como GMT (horário de Londres). O "new Date()" antigo
 * convertia para o fuso local e o painel mostrava 3 ou 4 HORAS A MENOS
 * (14:30 virava 10:30 em Cuiabá). Agora pegamos a hora exatamente como veio.
 */
function extrairHora(valor) {
    if (!valor) return '';
    const m = String(valor).match(/(\d{1,2}):(\d{2})/);
    return m ? `${m[1].padStart(2, '0')}:${m[2]}` : '';
}

/** [DEPURAÇÃO] Mesma ideia para datas: devolve "dd/mm" sem mudar o dia por causa do fuso. */
function extrairDiaMes(valor) {
    if (!valor) return '';
    const s = String(valor);
    let m = s.match(/(\d{4})-(\d{2})-(\d{2})/);                 // 2025-01-31
    if (m) return `${m[3]}/${m[2]}`;
    m = s.match(/(\d{1,2})\/(\d{1,2})\/\d{4}/);                  // 31/01/2025
    if (m) return `${m[1].padStart(2, '0')}/${m[2].padStart(2, '0')}`;
    const meses = { Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
                    Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12' };
    m = s.match(/(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}/); // Fri, 31 Jan 2025
    if (m) return `${m[1].padStart(2, '0')}/${meses[m[2]]}`;
    return '';
}

/** "HH:MM" -> minutos desde 00:00 (ou null se inválido). */
function paraMinutos(strHora) {
    const hm = extrairHora(strHora);
    if (!hm) return null;
    const [h, m] = hm.split(':').map(Number);
    return h * 60 + m;
}

/** Número que pode vir como texto/vazio -> número (0 se inválido). */
function num(valor) {
    const n = Number(valor);
    return Number.isFinite(n) ? n : 0;
}

/**
 * [DEPURAÇÃO] Link do WhatsApp. Antes sempre colocava "55" na frente:
 * um número já salvo como 5544999998888 virava 555544999998888 (link quebrado).
 */
function linkWhatsApp(telefone) {
    let numeros = String(telefone || '').replace(/\D/g, '');
    if (!numeros) return '';
    if (!(numeros.startsWith('55') && numeros.length >= 12)) numeros = '55' + numeros;
    return `https://wa.me/${numeros}`;
}

/** Data de HOJE no formato AAAA-MM-DD, no fuso do computador (não em UTC). */
function hojeLocalISO() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Aceita só cores simples (#ff0000 ou "red") vindas do servidor. */
function corSegura(cor, padrao) {
    return /^#[0-9a-f]{3,8}$|^[a-z]{3,20}$/i.test(String(cor || '')) ? cor : padrao;
}

/** localStorage pode estar bloqueado (modo anônimo): nunca deixa isso travar o painel. */
function lerLocal(chave) {
    try { return localStorage.getItem(chave); } catch (e) { return null; }
}
function gravarLocal(chave, valor) {
    try { localStorage.setItem(chave, valor); } catch (e) { /* ignora */ }
}


// =============================================================================
// == GRÁFICO DE OCUPAÇÃO (Aba Mapa) ===========================================
// =============================================================================
// Variável para guardar os dados na memória do navegador
let dadosOcupacaoCache = [];

// [DEPURAÇÃO] Esta função existia DUAS VEZES no arquivo (uma aqui e outra dentro do
// DOMContentLoaded), com comportamentos diferentes. Ficou só uma.
function renderizarGraficoOcupacao(novosDados) {
    const container = document.getElementById('grafico-barras-container');
    const selectFiltro = document.getElementById('filtro-setor-grafico');
    if (!container) return;

    // Dados novos da API (lista, mesmo vazia) substituem o cache.
    // null = a API falhou -> mantém o último gráfico bom.
    if (Array.isArray(novosDados)) {
        dadosOcupacaoCache = novosDados;
        adicionarSetoresNoFiltro(novosDados, selectFiltro);
    }

    if (!dadosOcupacaoCache || dadosOcupacaoCache.length === 0) {
        container.innerHTML = '<p style="width:100%; text-align:center; color: #666;">Sem dados de escala para hoje.</p>';
        return;
    }

    container.innerHTML = '';
    const setorSelecionado = selectFiltro ? selectFiltro.value : "Geral (Todos)";

    // Processa os dados hora a hora (07:00 às 23:00)
    const horasEixo = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23];
    const dadosGrafico = [];

    horasEixo.forEach(hora => {
        const momentoAnalise = hora * 60;
        let qtdPessoas = 0;

        dadosOcupacaoCache.forEach(item => {
            if (setorSelecionado !== "Geral (Todos)" && item.setor !== setorSelecionado) return;

            const ent = paraMinutos(item.entrada);
            const sai = paraMinutos(item.saida);
            const intIni = paraMinutos(item.int_ini);
            const intFim = paraMinutos(item.int_fim);
            if (ent === null || sai === null) return;

            let noTurno = false;
            if (ent <= sai) {
                noTurno = ent <= momentoAnalise && momentoAnalise < sai;
            } else { // turno que vira a noite
                noTurno = momentoAnalise >= ent || momentoAnalise < sai;
            }
            if (!noTurno) return;

            let noIntervalo = false;
            if (intIni !== null && intFim !== null) {
                if (intIni <= intFim) {
                    noIntervalo = intIni <= momentoAnalise && momentoAnalise < intFim;
                } else {
                    noIntervalo = momentoAnalise >= intIni || momentoAnalise < intFim;
                }
            }
            if (!noIntervalo) qtdPessoas++;
        });

        dadosGrafico.push({ hora: `${hora}:00`, qtd: qtdPessoas });
    });

    const maxPessoas = Math.max(...dadosGrafico.map(d => d.qtd), 5); // escala mínima de 5

    dadosGrafico.forEach(d => {
        const wrapper = document.createElement('div');
        wrapper.className = 'barra-wrapper';
        const alturaPercentual = (d.qtd / maxPessoas) * 100;

        let corBarra = '#33b5e5'; // Azul para setores
        if (setorSelecionado === "Geral (Todos)") {
            corBarra = d.qtd < 3 ? '#d9534f' : '#5cb85c'; // Vermelho alerta / Verde ok
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

/** [DEPURAÇÃO] Setores que aparecem na escala mas não estavam no filtro (ex: "Atendimento"). */
function adicionarSetoresNoFiltro(dados, selectFiltro) {
    if (!selectFiltro) return;
    const existentes = new Set(Array.from(selectFiltro.options).map(o => o.value));
    dados.forEach(item => {
        const setor = item && item.setor;
        if (setor && !existentes.has(setor)) {
            selectFiltro.add(new Option(setor, setor));
            existentes.add(setor);
        }
    });
}

// Configura o ouvinte do filtro de setor
const filtroSetorEl = document.getElementById('filtro-setor-grafico');
if (filtroSetorEl) {
    filtroSetorEl.addEventListener('change', function () {
        renderizarGraficoOcupacao(null); // redesenha usando o cache
    });
}


// =============================================================================
// == PAINEL PRINCIPAL =========================================================
// =============================================================================
document.addEventListener('DOMContentLoaded', function () {
    // Mesmo endereço (IP/porta) que está na barra do navegador
    const API_BASE_URL = '';
    let atualizando = false; // [DEPURAÇÃO] evita duas atualizações ao mesmo tempo

    function formatarHora(dataString) {
        return extrairHora(dataString);  // [DEPURAÇÃO] ver explicação em extrairHora()
    }

    function renderizarPodio(ranking) {
        const podioContainer = document.getElementById('podio-diario');
        if (!podioContainer) return;
        podioContainer.innerHTML = '';
        if (!Array.isArray(ranking) || ranking.length === 0) {
            podioContainer.innerHTML = '<p style="align-self: center; color: #888;"><i>O pódio de hoje ainda está vazio.</i></p>';
            return;
        }
        const medalhas = ['🥇', '🥈', '🥉'];
        // [DEPURAÇÃO] do 4º lugar em diante aparecia "undefined" no lugar da medalha
        ranking.slice(0, 3).forEach((item, index) => {
            const podioItem = document.createElement('div');
            podioItem.className = `podio-item posicao-${index + 1}`;
            podioItem.innerHTML = `
                <div class="posicao">${medalhas[index] || (index + 1) + 'º'}</div>
                <div class="nome">${esc(item.NomeCompleto)}</div>
                <div class="pontos">${num(item.TotalPontosHoje)} pts hoje</div>
            `;
            podioContainer.appendChild(podioItem);
        });
    }

    function renderizarHistoricoLucro(historico) {
        const container = document.getElementById('historico-lucro-barras');
        if (!container) return;
        container.innerHTML = '';

        // [DEPURAÇÃO] um mês sem nome (null) quebrava esta verificação
        const validos = Array.isArray(historico)
            ? historico.filter(item => item && item.mes && item.mes !== 'N/A' && !String(item.mes).toLowerCase().includes('erro'))
            : [];
        if (validos.length === 0) {
            container.innerHTML = '<p style="text-align: center; color: #888; font-size: 0.9em;"><i>Histórico indisponível.</i></p>';
            return;
        }

        const META_LUCRO = 18.0;          // Meta de 18%
        const MAX_BARRA_PERCENTUAL = 25;  // Teto visual

        validos.forEach(item => {
            const percentual = num(item.percentual);
            const mesItemDiv = document.createElement('div');
            mesItemDiv.className = 'mes-lucro-item';

            const mesLabel = document.createElement('span');
            mesLabel.className = 'mes-lucro-label';
            mesLabel.textContent = item.mes;
            mesItemDiv.appendChild(mesLabel);

            const progressoContainer = document.createElement('div');
            progressoContainer.className = 'progresso-lucro-container';
            const progressoBarra = document.createElement('div');
            progressoBarra.className = 'progresso-lucro-barra';

            let larguraBarra;
            if (percentual < 0) {
                larguraBarra = Math.min(Math.abs(percentual) * 2, 100);
                progressoBarra.classList.add('meta-prejuizo');
            } else {
                larguraBarra = Math.max(1, Math.min((percentual / MAX_BARRA_PERCENTUAL) * 100, 100));
                if (percentual >= META_LUCRO) progressoBarra.classList.add('meta-lucro-batida');
            }
            progressoBarra.style.width = `${larguraBarra}%`;
            progressoBarra.title = `${percentual.toFixed(1)}%`;
            progressoContainer.appendChild(progressoBarra);
            mesItemDiv.appendChild(progressoContainer);
            container.appendChild(mesItemDiv);
        });
    }

    function renderizarColunas(dados) {
        const colunas = {
            'coluna-para-fazer': dados.para_fazer,
            'coluna-validacao': dados.validacao
        };
        for (const idColuna in colunas) {
            const elementoColuna = document.getElementById(idColuna);
            if (!elementoColuna) continue;
            elementoColuna.innerHTML = '';
            const tarefasAgrupadas = agruparTarefasPorFuncionario(colunas[idColuna]);
            // [DEPURAÇÃO] BUG: o código antigo usava idColuna.split('-')[1], que dá 'para'
            // (e não 'para_fazer'). Resultado: o horário "Disparado às" e o alerta ⚠️ de
            // tarefa ATRASADA (mais de 30 min) NUNCA apareciam no painel.
            // 'coluna-para-fazer' -> 'para_fazer' ; 'coluna-validacao' -> 'validacao'
            renderizarGrupos(tarefasAgrupadas, elementoColuna, idColuna.replace('coluna-', '').replace('-', '_'));
        }
    }

    function agruparTarefasPorFuncionario(listaDeTarefas) {
        if (!Array.isArray(listaDeTarefas)) return {};
        return listaDeTarefas.reduce((grupos, tarefa) => {
            const nome = tarefa.NomeCompleto || 'Sem responsável';
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
        let tituloHtml = `<span>${esc(tarefa.Titulo)}</span>`;
        let infoExtra = '';

        if (tipo === 'para_fazer') {
            const horaDisparo = extrairHora(tarefa.HorarioDisparo);
            if (horaDisparo) {
                infoExtra += `<span class="card-hora-grupo">🕒 Disparado às ${horaDisparo}</span>`;

                // --- CÁLCULO DE ATRASO ---
                const agora = new Date();
                const dataDisparo = new Date();
                const [h, m] = horaDisparo.split(':').map(Number);
                dataDisparo.setHours(h, m, 0, 0);
                // Tarefa de 23:00 vista às 00:10 -> foi disparada ontem
                if (dataDisparo > agora) dataDisparo.setDate(dataDisparo.getDate() - 1);
                const diferencaMinutos = (agora - dataDisparo) / 60000;
                if (diferencaMinutos > 30) {
                    cardDiv.classList.add('alerta-atraso');
                    tituloHtml = `<span>⚠️</span> ${tituloHtml}`;
                }
            } else if (tarefa.DataReferencia) {
                // [DEPURAÇÃO] new Date() mostrava o DIA ANTERIOR (efeito do fuso GMT)
                const dataRef = extrairDiaMes(tarefa.DataReferencia);
                if (dataRef) infoExtra = `<p class="card-info">Data: ${dataRef}</p>`;
            }
            if (tarefa.Categoria === 'Atrasada') {
                tituloHtml += `<span class="card-tag-atrasada">ATRASADA</span>`;
            }
        } else if (tipo === 'validacao') {
            tituloHtml = `<span>⏳</span> ${tituloHtml}`;
            infoExtra = `<p class="card-info">Enviada às: ${formatarHora(tarefa.DataEnvio) || '--:--'}</p>`;
        }

        const infoFuncionario = tarefa.NomeCompleto ? `<p class="card-info">Responsável: ${esc(tarefa.NomeCompleto)}</p>` : '';
        // [DEPURAÇÃO] tarefa de 0 ponto mostrava "+ undefined pts"
        const pontos = num(tarefa.Pontos !== undefined && tarefa.Pontos !== null ? tarefa.Pontos : tarefa.PontosGanhos);
        cardDiv.innerHTML = `<div class="card-titulo">${tituloHtml}</div>${infoFuncionario}${infoExtra}<p class="card-pontos">+ ${pontos} pts</p>`;
        return cardDiv;
    }

    function renderizarMetaPrincipal(meta) {
        const containerEl = document.getElementById('container-meta-mensal');
        if (!containerEl) return;
        const tituloEl = document.getElementById('meta-titulo');
        const barraEl = document.getElementById('meta-progresso-barra');
        const textoEl = document.getElementById('meta-progresso-texto');

        if (meta && num(meta.valor_meta) > 0) {
            containerEl.style.display = 'flex';
            // [DEPURAÇÃO] valor atingido vazio dava "NaN%"
            const percentual = (num(meta.valor_atingido) / num(meta.valor_meta)) * 100;
            tituloEl.textContent = meta.nome_meta || 'Meta';
            barraEl.style.width = `${Math.min(percentual, 100)}%`;
            textoEl.textContent = `${percentual.toFixed(1)}%`;
        } else {
            containerEl.style.display = 'none';
        }
    }

    function renderizarMetaDiaria(meta) {
        const containerEl = document.getElementById('container-meta-diaria');
        if (!containerEl) return;
        const barraEl = document.getElementById('meta-diaria-progresso-barra');
        const textoEl = document.getElementById('meta-diaria-progresso-texto');

        const valorMeta = meta ? num(meta.valor_meta_diaria) : 0;
        const valorAtingido = meta ? num(meta.valor_atingido_hoje) : 0;

        if (valorMeta > 0) {
            containerEl.style.display = 'flex';
            const percentual = (valorAtingido / valorMeta) * 100;
            barraEl.style.width = `${Math.min(percentual, 100)}%`;
            textoEl.textContent = `${percentual.toFixed(1)}%`;

            // [DEPURAÇÃO] Antes os fogos disparavam de novo A CADA vez que a página era
            // recarregada (ex: TV reiniciada). Agora ficam registrados para o dia.
            const hoje = new Date().toDateString();
            if (valorAtingido >= valorMeta && lerLocal('metaDiariaFogosDia') !== hoje) {
                gravarLocal('metaDiariaFogosDia', hoje);
                dispararFogos();
            }
        } else {
            containerEl.style.display = 'none';
        }
    }

    function renderizarFeed(eventos) {
        const feedLista = document.getElementById('feed-lista-kanban');
        if (!feedLista) return;
        feedLista.innerHTML = '';
        if (!Array.isArray(eventos) || eventos.length === 0) {
            feedLista.innerHTML = '<li style="color: #888; font-size: 0.9em;"><i>Nenhuma atividade recente.</i></li>';
            return;
        }
        eventos.forEach(evento => {
            const item = document.createElement('li');
            item.className = 'feed-item-instagram';
            const ehTarefa = evento.TipoEvento === 'tarefa_concluida';
            const icone = ehTarefa ? '✅' : '⭐';
            const texto = `<b>${esc(evento.TextoPrincipal)}</b> ${ehTarefa ? 'concluiu' : 'desbloqueou'} <i>"${esc(evento.TextoSecundario)}"</i> <span class="feed-pontos">(+${num(evento.Pontos)} pts)</span>`;

            let htmlImagem = '';
            if (evento.CaminhoFoto && ehTarefa) {
                // Só o nome do arquivo (serve para caminhos Windows e Linux)
                const nomeArquivo = String(evento.CaminhoFoto).split(/[\\/]/).pop();
                // [DEPURAÇÃO] encodeURIComponent: nomes com espaço ou # não abriam a foto
                const urlImagem = `${API_BASE_URL}/imagens/entregas/${encodeURIComponent(nomeArquivo)}`;
                htmlImagem = `
                    <div class="feed-imagem-wrapper">
                        <img src="${esc(urlImagem)}" alt="Evidência" class="feed-foto" loading="lazy" onerror="this.style.display='none'">
                    </div>`;
            }

            item.innerHTML = `
                <div class="feed-header">
                    <span class="feed-icone">${icone}</span>
                    <div class="feed-texto">${texto}</div>
                </div>
                ${htmlImagem}
                <div class="feed-footer">
                    <small>🕒 ${formatarHora(evento.Timestamp) || '--:--'}</small>
                </div>
            `;
            feedLista.appendChild(item);
        });
    }

    function renderizarResgatesRecentes(resgates) {
        const resgatesLista = document.getElementById('resgates-lista');
        if (!resgatesLista) return;
        resgatesLista.innerHTML = '';
        if (!Array.isArray(resgates) || resgates.length === 0) {
            resgatesLista.innerHTML = '<li style="color: #888; text-align: center;"><i>Nenhum resgate recente.</i></li>';
            return;
        }
        resgates.forEach(resgate => {
            const item = document.createElement('li');
            const texto = `<b>${esc(resgate.TextoPrincipal)}</b> resgatou <i>"${esc(resgate.TextoSecundario)}"</i> (${num(resgate.Pontos)} pts)`;
            item.innerHTML = `<span class="feed-icone">🎁</span> <div>${texto} <small style="color: #888;">às ${formatarHora(resgate.Timestamp) || '--:--'}</small></div>`;
            resgatesLista.appendChild(item);
        });
    }

    function renderizarProximosAgendamentos(agendamentos) {
        const container = document.getElementById('lista-proximos-agendamentos');
        if (!container) return;
        container.innerHTML = '';

        if (!Array.isArray(agendamentos) || agendamentos.length === 0) {
            container.innerHTML = '<p style="text-align: center; color: #888;"><i>Nenhum agendamento futuro confirmado.</i></p>';
            return;
        }

        agendamentos.forEach(ag => {
            const itemDiv = document.createElement('div');
            itemDiv.className = 'agendamento-item';

            // A API envia data_evento como 'dd/mm/yyyy HH:MM'
            // [DEPURAÇÃO] um agendamento com a data faltando derrubava o painel INTEIRO
            const [dataParte, horaParte] = String(ag.data_evento || '').split(' ');
            const dataHoraFormatada = dataParte ? `${esc(dataParte)} às ${esc(horaParte || '--:--')}` : 'Data a definir';

            let telefoneHtml = '';
            const link = linkWhatsApp(ag.telefone_cliente);
            if (link) {
                telefoneHtml = `<small>📞 <a href="${link}" target="_blank" rel="noopener">${esc(ag.telefone_cliente)}</a></small>`;
            }

            itemDiv.innerHTML = `
                <strong>${esc(ag.nome_cliente)}</strong>
                <small>${esc(ag.tipo_evento)}</small>
                ${telefoneHtml} <small style="font-weight: bold; color: #0056b3;">${dataHoraFormatada}</small>
            `;
            container.appendChild(itemDiv);
        });
    }

    function renderizarProgressoGeral(progresso) {
        const barraInterna = document.getElementById('progresso-barra-interna');
        const textoLabel = document.getElementById('progresso-texto-label');
        if (!barraInterna || !textoLabel) return;

        if (progresso && progresso.total !== undefined && num(progresso.total) >= 0) {
            const concluidas = num(progresso.concluidas);
            const total = num(progresso.total);
            const percentual = total > 0 ? (concluidas / total) * 100 : 0;
            barraInterna.style.width = `${Math.min(percentual, 100)}%`;
            textoLabel.textContent = `${concluidas} de ${total} tarefas concluídas (${Math.round(percentual)}%)`;
        } else {
            barraInterna.style.width = '0%';
            textoLabel.textContent = 'Calculando...';
        }
    }

    async function atualizarMapaLoja() {
        const container = document.getElementById('marcadores-mapa');
        const containerPai = document.getElementById('container-do-mapa');
        if (!container || !containerPai) return;

        // [DEPURAÇÃO] Com a aba do mapa escondida o tamanho do mapa é 0 e TODOS os
        // marcadores iam parar no canto superior esquerdo (até a próxima atualização,
        // 1 minuto depois). Agora só desenha quando o mapa está visível; ao abrir a aba
        // o desenho é refeito na hora (ver abrirAba).
        const rect = containerPai.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        try {
            const response = await fetch(`${API_BASE_URL}/api/escala/hoje`);
            if (!response.ok) return;
            const posicoes = await response.json();
            if (!Array.isArray(posicoes)) return;

            // Dimensões originais da imagem (as mesmas do programa da escala)
            const imgOriginalW = 1180;
            const imgOriginalH = 600;
            const ratioOriginal = imgOriginalW / imgOriginalH;

            const containerW = rect.width;
            const containerH = rect.height;
            let renderW, renderH, offsetX, offsetY;

            // Mesma lógica do 'background-size: contain' (imagem no topo)
            if (containerW / containerH > ratioOriginal) {
                renderH = containerH;
                renderW = containerH * ratioOriginal;
                offsetX = (containerW - renderW) / 2;
                offsetY = 0;
            } else {
                renderW = containerW;
                renderH = containerW / ratioOriginal;
                offsetX = 0;
                offsetY = 0;
            }

            container.innerHTML = '';
            posicoes.forEach(pos => {
                const x = Number(pos.x), y = Number(pos.y);
                // [DEPURAÇÃO] posição sem coordenadas (vazia) ia parar no canto (0,0)
                if (pos.x === null || pos.y === null || !Number.isFinite(x) || !Number.isFinite(y)) return;

                let posX, posY;
                if (x <= 2 && y <= 2) {          // coordenadas em percentual (0.0 a 1.0)
                    posX = offsetX + x * renderW;
                    posY = offsetY + y * renderH;
                } else {                          // coordenadas antigas em pixels (1180x600)
                    posX = offsetX + (x / imgOriginalW) * renderW;
                    posY = offsetY + (y / imgOriginalH) * renderH;
                }

                const el = document.createElement('div');
                el.className = 'marcador-mapa';
                el.style.left = `${posX}px`;
                el.style.top = `${posY}px`;
                el.style.backgroundColor = corSegura(pos.cor, '#999999');
                el.innerHTML = `
                    <div class="info-box">
                        <strong>${esc(pos.nome_posicao)}</strong><br>
                        ${esc(pos.ocupante)}<br>
                        <small>${esc(pos.detalhes)}</small>
                    </div>
                `;
                container.appendChild(el);
            });
        } catch (error) {
            console.error("Erro ao atualizar mapa:", error);
        }
    }

    // === CRONOGRAMA DE PAUSAS ===
    function atualizarRelogio() {
        const relogio = document.getElementById('relogio-tempo-real');
        const horaStr = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
        if (relogio) relogio.textContent = horaStr;
        return horaStr;
    }

    async function atualizarCronogramaPausas() {
        const container = document.getElementById('lista-pausas-content');
        if (!container) return;

        try {
            const minutosAgora = paraMinutos(atualizarRelogio());

            const response = await fetch(`${API_BASE_URL}/api/escala/tabela`);
            if (!response.ok) return;
            const dadosAgrupados = await response.json();
            if (!dadosAgrupados || typeof dadosAgrupados !== 'object') return;

            container.innerHTML = '';
            const ordem = ['Cozinha', 'Buffet', 'Caixa', 'Atendimento', 'Salão', 'Frente Loja', 'Varanda', 'Limpeza', 'Camara Fria'];
            const setores = Object.keys(dadosAgrupados).sort((a, b) => {
                const idxA = ordem.indexOf(a), idxB = ordem.indexOf(b);
                return (idxA === -1 ? 99 : idxA) - (idxB === -1 ? 99 : idxB);
            });

            if (setores.length === 0) {
                container.innerHTML = '<p style="text-align:center; padding:20px; color:#888;">Sem escala hoje.</p>';
                return;
            }

            setores.forEach(setor => {
                const funcs = dadosAgrupados[setor];
                if (!Array.isArray(funcs) || funcs.length === 0) return;

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
                    const mIni = paraMinutos(f.int_ini);
                    const mFim = paraMinutos(f.int_fim);

                    // [DEPURAÇÃO] a API manda "--:--" quando não há intervalo; antes isso
                    // aparecia como "--:-- - --:--" e era tratado como horário válido
                    if (mIni !== null && mFim !== null) {
                        textoHorario = `${extrairHora(f.int_ini)} - ${extrairHora(f.int_fim)}`;
                        const cruzaMeiaNoite = mIni > mFim;
                        const emPausa = cruzaMeiaNoite
                            ? (minutosAgora >= mIni || minutosAgora < mFim)
                            : (minutosAgora >= mIni && minutosAgora < mFim);
                        if (emPausa) {
                            statusClass = 'status-em-pausa';
                            icone = '☕';
                        } else if (!cruzaMeiaNoite && minutosAgora >= mFim) {
                            statusClass = 'status-concluido';
                            icone = '🏁';
                        } else {
                            icone = '⏳';
                        }
                    }

                    card.classList.add(statusClass);
                    card.innerHTML = `
                        <div class="pausa-info">
                            <span class="pausa-nome">${esc(f.nome)}</span>
                            <span class="pausa-horario">${esc(textoHorario)}</span>
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

    async function buscarJson(url) {
        const r = await fetch(url);
        if (!r.ok) return null;
        return r.json();
    }

    async function atualizarPainel() {
        if (atualizando) return; // a anterior ainda não terminou (servidor lento)
        atualizando = true;
        const statusElement = document.getElementById('ultima-atualizacao');
        try {
            if (statusElement) {
                statusElement.textContent = 'Atualizando dados...';
                statusElement.style.color = '#888';
            }

            const endpoints = [
                `${API_BASE_URL}/api/painel/tarefas`,           // 0
                `${API_BASE_URL}/api/ranking/diario`,           // 1
                `${API_BASE_URL}/api/feed`,                     // 2
                `${API_BASE_URL}/api/meta_principal_do_dia`,    // 3
                `${API_BASE_URL}/api/meta_diaria_do_dia`,       // 4
                `${API_BASE_URL}/api/agendamentos/proximos`,    // 5
                `${API_BASE_URL}/api/historico_lucro`,          // 6
                `${API_BASE_URL}/api/resgates/recentes`,        // 7
                `${API_BASE_URL}/api/escala/ocupacao`           // 8
            ];

            // allSettled: se um endereço falhar, os outros continuam funcionando
            const resultados = await Promise.allSettled(endpoints.map(buscarJson));
            const valor = (i, padrao) =>
                (resultados[i].status === 'fulfilled' && resultados[i].value) ? resultados[i].value : padrao;

            const falhas = resultados.filter(r => r.status === 'rejected' || !r.value).length;

            const dadosTarefas = valor(0, { para_fazer: [], validacao: [], progresso: {} });

            // [DEPURAÇÃO] cada parte é desenhada separadamente: antes, um erro em UMA
            // delas (ex: agendamento sem data) interrompia todas as seguintes.
            const partes = [
                () => renderizarColunas(dadosTarefas),
                () => renderizarProgressoGeral(dadosTarefas.progresso),
                () => renderizarPodio(valor(1, [])),
                () => renderizarFeed(valor(2, [])),
                () => renderizarMetaPrincipal(valor(3, null)),
                () => renderizarMetaDiaria(valor(4, null)),
                () => renderizarProximosAgendamentos(valor(5, [])),
                () => renderizarHistoricoLucro(valor(6, [])),
                () => renderizarResgatesRecentes(valor(7, [])),
                () => renderizarGraficoOcupacao(valor(8, null)),
            ];
            let errosDesenho = 0;
            partes.forEach(desenhar => {
                try { desenhar(); } catch (e) { errosDesenho++; console.error("Erro ao desenhar parte do painel:", e); }
            });

            atualizarMapaLoja();
            atualizarCronogramaPausas();

            if (statusElement) {
                const hora = new Date().toLocaleTimeString('pt-BR');
                if (falhas === endpoints.length) {
                    statusElement.textContent = `Sem conexão com o servidor (${hora}). Tentando de novo em 1 minuto...`;
                    statusElement.style.color = 'red';
                } else if (falhas > 0 || errosDesenho > 0) {
                    statusElement.textContent = `Última atualização: ${hora} (algumas informações não carregaram)`;
                    statusElement.style.color = '#b36b00';
                } else {
                    statusElement.textContent = `Última atualização: ${hora}`;
                    statusElement.style.color = 'inherit';
                }
            }
        } catch (error) {
            console.error("Falha ao atualizar o painel:", error);
            if (statusElement) {
                statusElement.textContent = `Erro ao atualizar (${new Date().toLocaleTimeString('pt-BR')}). Verifique a conexão com a API.`;
                statusElement.style.color = 'red';
            }
        } finally {
            atualizando = false;
        }
    }

    function dispararFogos() {
        // [DEPURAÇÃO] sem internet a biblioteca não carrega: antes isso gerava um erro
        // a cada 0,25 segundo por 5 segundos. Agora simplesmente não mostra os fogos.
        if (typeof confetti !== 'function') {
            console.warn("Biblioteca de fogos (confetti) não carregou - sem animação.");
            return;
        }
        const duration = 5 * 1000;
        const animationEnd = Date.now() + duration;
        const defaults = { startVelocity: 30, spread: 360, ticks: 60, zIndex: 9999 };
        const randomInRange = (min, max) => Math.random() * (max - min) + min;

        const interval = setInterval(function () {
            const timeLeft = animationEnd - Date.now();
            if (timeLeft <= 0) return clearInterval(interval);
            const particleCount = 50 * (timeLeft / duration);
            const cores = ['#FFD700', '#FF4500', '#FFFFFF', '#00FF00', '#0000FF'];
            confetti(Object.assign({}, defaults, { particleCount, origin: { x: randomInRange(0.1, 0.3), y: Math.random() - 0.2 }, shapes: ['star'], colors: cores }));
            confetti(Object.assign({}, defaults, { particleCount, origin: { x: randomInRange(0.7, 0.9), y: Math.random() - 0.2 }, shapes: ['star'], colors: cores }));
        }, 250);
    }

    // [DEPURAÇÃO] Deixa estas funções acessíveis para a troca de abas e para a agenda
    window.atualizarPainel = atualizarPainel;
    window.atualizarMapaLoja = atualizarMapaLoja;

    // Redesenha o mapa quando a janela muda de tamanho (ex: TV girada / F11)
    let temporizadorResize = null;
    window.addEventListener('resize', () => {
        clearTimeout(temporizadorResize);
        temporizadorResize = setTimeout(atualizarMapaLoja, 300);
    });

    // ===== Chamada inicial e agendamento das atualizações =====
    atualizarPainel();
    setInterval(atualizarPainel, 60000);   // dados: a cada 1 minuto
    setInterval(atualizarRelogio, 15000);  // [DEPURAÇÃO] relógio ficava até 1 min atrasado

}); // <<<<<< Fim do DOMContentLoaded


// =============================================================================
// == TROCA DE ABAS ============================================================
// =============================================================================
function abrirAba(nomeAba, botao) {
    document.querySelectorAll('.tab-content').forEach(tab => { tab.style.display = 'none'; });
    document.querySelectorAll('.tab-btn').forEach(btn => { btn.classList.remove('active'); });

    const abaAlvo = document.getElementById('tab-' + nomeAba);
    if (abaAlvo) abaAlvo.style.display = 'block';

    // [DEPURAÇÃO] Antes usava a variável global "event" (não existe em todo navegador).
    // Agora o próprio botão é enviado pelo HTML: abrirAba('mapa', this)
    const botaoAtivo = botao
        || document.querySelector(`.tab-btn[onclick*="'${nomeAba}'"]`);
    if (botaoAtivo) botaoAtivo.classList.add('active');

    if (nomeAba === 'mapa' && typeof window.atualizarMapaLoja === 'function') {
        // O mapa precisa estar visível para calcular as posições
        setTimeout(window.atualizarMapaLoja, 50);
    }
    if (nomeAba === 'agenda') {
        setTimeout(inicializarCalendario, 100);
    }
}


// =============================================================================
// == MÓDULO DE AGENDA E CALENDÁRIO (FULLCALENDAR) =============================
// =============================================================================
let calendarInstance = null;

/**
 * [DEPURAÇÃO] Lê a resposta do servidor sem quebrar.
 * Antes, se o servidor respondesse com uma página de erro (HTML) em vez de JSON,
 * aparecia "Erro de conexão." mesmo o servidor estando no ar.
 */
async function lerResposta(response) {
    const texto = await response.text();
    try { return texto ? JSON.parse(texto) : {}; } catch (e) { return { mensagem: `Resposta inesperada do servidor (código ${response.status}).` }; }
}

/** Recarrega o calendário e a lista "Próximos Agendamentos" da aba Operacional. */
function recarregarAgendas() {
    if (calendarInstance) calendarInstance.refetchEvents();
    if (typeof window.atualizarPainel === 'function') window.atualizarPainel();
}

/** Garante que o <select> tenha a opção (ex: funcionário ou tipo de evento que não estava na lista). */
function garantirOpcao(select, valor, texto) {
    if (valor === null || valor === undefined || valor === '') return;
    const v = String(valor);
    if (!Array.from(select.options).some(o => o.value === v)) {
        select.add(new Option(texto || v, v));
    }
    select.value = v;
}

function inicializarCalendario() {
    const calendarEl = document.getElementById('calendar');
    if (!calendarEl) return;

    // [DEPURAÇÃO] Sem internet a biblioteca FullCalendar não carrega e a aba dava erro em branco
    if (typeof FullCalendar === 'undefined') {
        calendarEl.innerHTML = '<p style="text-align:center; color:#c00; padding:40px;">' +
            'Não foi possível carregar o calendário (sem acesso à internet?).<br>' +
            'Verifique a conexão e aperte F5.</p>';
        return;
    }

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

        events: function (info, successCallback, failureCallback) {
            fetch('/api/agendamentos')
                .then(response => {
                    if (!response.ok) throw new Error(`Servidor respondeu ${response.status}`);
                    return response.json();
                })
                .then(data => {
                    if (!Array.isArray(data)) throw new Error('Resposta inválida do servidor');
                    const eventosFormatados = [];
                    data.forEach(ag => {
                        // [DEPURAÇÃO] Agendamento sem data virava um evento com data inválida,
                        // e um sem "tipo" (vazio) quebrava o calendário INTEIRO (.includes em null)
                        const [dataPt, horaPt] = String(ag.data_evento || '').split(' ');
                        const partes = (dataPt || '').split('/');
                        if (partes.length !== 3 || !horaPt) return;
                        const [dia, mes, ano] = partes;
                        const tipo = ag.tipo_evento || '';
                        const cancelado = String(ag.status_agendamento || '').toLowerCase().startsWith('cancel');

                        let cor = '#3788d8';
                        if (tipo.includes('Festa')) cor = '#e83e8c';
                        if (tipo.includes('Carrinho')) cor = '#fd7e14';
                        if (tipo.includes('Torta')) cor = '#20c997';
                        if (cancelado) cor = '#9e9e9e'; // [DEPURAÇÃO] cancelados apareciam iguais aos confirmados

                        eventosFormatados.push({
                            id: ag.agendamento_id,
                            title: `${cancelado ? '(Cancelado) ' : ''}${horaPt} - ${ag.nome_cliente || ''}`,
                            start: `${ano}-${mes}-${dia}T${horaPt}:00`,
                            backgroundColor: cor,
                            borderColor: cor,
                            extendedProps: {
                                nome_cliente: ag.nome_cliente || '',
                                tipo: tipo,
                                telefone: ag.telefone_cliente || '',
                                cpf: ag.cpf_cliente || '',
                                status_pag: ag.status_pagamento || 'Pendente',
                                obs: ag.observacoes || '',
                                funcionario_id: ag.funcionario_id,  // a lista não traz; buscamos ao abrir
                                nome_funcionario: ag.nome_funcionario || '',
                                data_pura: `${ano}-${mes}-${dia}`,
                                hora_pura: horaPt
                            }
                        });
                    });
                    successCallback(eventosFormatados);
                })
                .catch(error => {
                    console.error('Erro ao buscar agenda:', error);
                    failureCallback(error);
                });
        },

        eventClick: function (info) {
            abrirModalEdicao(info.event);
        }
    });

    calendarInstance.render();
}

// --- FUNÇÕES DO MODAL ---

function abrirModalAgendamento() {
    document.getElementById('modal-agendamento').style.display = 'flex';
    document.getElementById('modal-titulo').innerText = "📅 Novo Agendamento";
    document.getElementById('form-agendamento').reset();
    document.getElementById('ag-id').value = "";

    document.getElementById('btn-container-novo').style.display = 'block';
    document.getElementById('btn-container-editar').style.display = 'none';

    // [DEPURAÇÃO] toISOString() usa o horário de Londres (UTC): depois das 20h em
    // Cuiabá (21h em Brasília) a data sugerida já era a de AMANHÃ.
    document.getElementById('ag-data').value = hojeLocalISO();
    document.getElementById('ag-hora').value = "14:00";
    document.getElementById('ag-cliente').focus();
}

async function abrirModalEdicao(evento) {
    document.getElementById('modal-agendamento').style.display = 'flex';
    document.getElementById('modal-titulo').innerText = "✏️ Editar / Excluir Agendamento";
    document.getElementById('btn-container-novo').style.display = 'none';
    document.getElementById('btn-container-editar').style.display = 'flex';

    const props = evento.extendedProps;
    document.getElementById('ag-id').value = evento.id;
    document.getElementById('ag-cliente').value = props.nome_cliente;
    document.getElementById('ag-telefone').value = props.telefone;
    document.getElementById('ag-cpf').value = props.cpf;
    // [DEPURAÇÃO] Se o tipo/pagamento não estivesse na lista, o campo ficava EM BRANCO
    garantirOpcao(document.getElementById('ag-tipo'), props.tipo);
    garantirOpcao(document.getElementById('ag-pagamento'), props.status_pag);
    document.getElementById('ag-obs').value = props.obs;
    document.getElementById('ag-data').value = props.data_pura;
    document.getElementById('ag-hora').value = props.hora_pura;

    // [DEPURAÇÃO] A lista de agendamentos (/api/agendamentos) NÃO informa quem agendou.
    // Antes o campo sempre voltava para "Gestor" e, ao salvar, o responsável era TROCADO.
    // Agora buscamos o agendamento completo para saber o funcionário certo.
    const selectFunc = document.getElementById('ag-funcionario');
    let funcionarioId = props.funcionario_id;
    try {
        const r = await fetch(`/agendamentos/${encodeURIComponent(evento.id)}`);
        if (r.ok) {
            const detalhe = await r.json();
            if (detalhe && detalhe.funcionario_id) funcionarioId = detalhe.funcionario_id;
        }
    } catch (e) {
        console.warn("Não foi possível buscar o responsável do agendamento:", e);
    }
    if (funcionarioId) {
        garantirOpcao(selectFunc, funcionarioId, props.nome_funcionario || `Funcionário ${funcionarioId}`);
    }
}

function fecharModalAgendamento() {
    document.getElementById('modal-agendamento').style.display = 'none';
}

/** Liga/desliga os botões do formulário (evita clique duplo = agendamento duplicado). */
function travarBotoes(travar) {
    ['btn-salvar-novo', 'btn-salvar-edicao', 'btn-excluir'].forEach(id => {
        const b = document.getElementById(id);
        if (b) b.disabled = travar;
    });
}

/** [DEPURAÇÃO] Confere o telefone: DDD + número (10 ou 11 dígitos; aceita 55 na frente). */
function telefoneValido() {
    const campo = document.getElementById('ag-telefone');
    let numeros = campo.value.replace(/\D/g, '');
    if (numeros.startsWith('55') && numeros.length >= 12) numeros = numeros.slice(2);
    const ok = numeros.length === 10 || numeros.length === 11;
    campo.setCustomValidity(ok ? '' : 'Digite o DDD + número (ex: 44999998888).');
    return ok;
}

function processarFormulario(event) {
    event.preventDefault();
    if (!telefoneValido()) {
        document.getElementById('form-agendamento').reportValidity();
        return;
    }
    salvarNovoAgendamento();
}

// 1. CRIAR NOVO
async function salvarNovoAgendamento() {
    const payload = coletarDadosFormulario();
    travarBotoes(true);
    try {
        const response = await fetch('/agendamentos/novo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await lerResposta(response);
        if (response.ok) {
            alert("✅ " + (result.mensagem || "Agendamento criado!"));
            fecharModalAgendamento();
            recarregarAgendas();
        } else {
            alert("❌ Erro: " + (result.mensagem || `código ${response.status}`));
        }
    } catch (error) {
        console.error(error);
        alert("Erro de conexão com o servidor.");
    } finally {
        travarBotoes(false);
    }
}

// 2. ATUALIZAR EXISTENTE (PUT)
async function atualizarAgendamento() {
    const id = document.getElementById('ag-id').value;
    if (!id) return;

    // [DEPURAÇÃO] o botão de edição não passava pela validação do formulário
    const form = document.getElementById('form-agendamento');
    telefoneValido();
    if (!form.reportValidity()) return;

    if (!confirm("Deseja salvar as alterações neste agendamento?")) return;

    const payload = coletarDadosFormulario();
    travarBotoes(true);
    try {
        const response = await fetch(`/agendamentos/${encodeURIComponent(id)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await lerResposta(response);
        if (response.ok) {
            alert("✅ Agendamento atualizado!");
            fecharModalAgendamento();
            recarregarAgendas();
        } else {
            alert("❌ Erro: " + (result.mensagem || `código ${response.status}`));
        }
    } catch (error) {
        console.error(error);
        alert("Erro de conexão com o servidor.");
    } finally {
        travarBotoes(false);
    }
}

// 3. EXCLUIR (DELETE)
async function excluirAgendamento() {
    const id = document.getElementById('ag-id').value;
    if (!id) return;

    if (!confirm("⚠️ Tem certeza que deseja EXCLUIR este agendamento?\nEssa ação não pode ser desfeita.")) return;

    travarBotoes(true);
    try {
        const response = await fetch(`/agendamentos/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (response.ok) {   // 204 (sem conteúdo) ou 200
            alert("🗑️ Agendamento excluído.");
            fecharModalAgendamento();
            recarregarAgendas();
        } else {
            const result = await lerResposta(response);
            alert("❌ Erro ao excluir: " + (result.mensagem || `código ${response.status}`));
        }
    } catch (error) {
        console.error(error);
        alert("Erro de conexão com o servidor.");
    } finally {
        travarBotoes(false);
    }
}

// 4. ABRIR WHATSAPP
function abrirWhatsAppCliente() {
    const link = linkWhatsApp(document.getElementById('ag-telefone').value);
    if (link) window.open(link, '_blank', 'noopener');
    else alert("Telefone inválido.");
}

// Helper para pegar dados do form
function coletarDadosFormulario() {
    const dataInput = document.getElementById('ag-data').value;
    const horaInput = document.getElementById('ag-hora').value;
    return {
        funcionario_id: document.getElementById('ag-funcionario').value,
        nome_cliente: document.getElementById('ag-cliente').value.trim(),
        telefone_cliente: document.getElementById('ag-telefone').value.trim(),
        cpf_cliente: document.getElementById('ag-cpf').value.trim(),
        tipo_evento: document.getElementById('ag-tipo').value,
        status_pagamento: document.getElementById('ag-pagamento').value,
        data_evento: `${dataInput} ${horaInput}`,
        observacoes: document.getElementById('ag-obs').value.trim()
    };
}

// Fecha a janela clicando fora dela...
window.addEventListener('click', function (event) {
    const modal = document.getElementById('modal-agendamento');
    if (event.target === modal) fecharModalAgendamento();
});
// ...ou apertando Esc  [DEPURAÇÃO] novo
document.addEventListener('keydown', function (event) {
    const modal = document.getElementById('modal-agendamento');
    if (event.key === 'Escape' && modal && modal.style.display !== 'none') fecharModalAgendamento();
});
// O telefone é conferido de novo enquanto a pessoa digita
document.addEventListener('input', function (event) {
    if (event.target && event.target.id === 'ag-telefone') telefoneValido();
});
