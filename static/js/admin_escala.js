// Configuração Global
let funcionariosDisponiveis = [];
let escalaDoDia = [];

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Verificar Login
    const auth = await fetch('/api/auth/check').then(r => r.json());
    if (!auth.logado) { window.location.href = '/login'; return; }
    document.getElementById('user-name').textContent = auth.nome;

    // 2. Definir Data de Hoje se estiver vazio
    const inputData = document.getElementById('data-escala');
    if (!inputData.value) {
        const hoje = new Date().toISOString().split('T')[0];
        inputData.value = hoje;
    }
    
    // Listener para mudança de data
    inputData.addEventListener('change', () => inicializar());

    // 3. Carregar Tudo
    inicializar();
});

async function inicializar() {
    // Limpa UI antes de carregar
    document.getElementById('lista-disponiveis').innerHTML = '<div class="loading">Carregando...</div>';
    document.getElementById('board-grid').innerHTML = '<div class="loading">Carregando mapa...</div>';
    
    // Carrega em paralelo para ser mais rápido
    await Promise.all([carregarEscala(), carregarFuncionariosSidebar()]);
    
    // Renderiza após ter os dados
    renderizarBoard();
    renderizarSidebar(funcionariosDisponiveis);
}

function mudarDia(dias) {
    const input = document.getElementById('data-escala');
    const data = new Date(input.value);
    data.setDate(data.getDate() + dias);
    input.value = data.toISOString().split('T')[0];
    inicializar();
}

// --- CARREGAMENTO DE DADOS ---

async function carregarFuncionariosSidebar() {
    try {
        const res = await fetch('/api/admin/funcionarios/disponiveis');
        if (res.ok) {
            funcionariosDisponiveis = await res.json();
        } else {
            console.error("Erro ao buscar funcionários");
            funcionariosDisponiveis = [];
        }
    } catch (e) {
        console.error(e);
        funcionariosDisponiveis = [];
    }
}

async function carregarEscala() {
    const data = document.getElementById('data-escala').value;
    try {
        const res = await fetch(`/api/admin/escala/${data}`);
        if (res.ok) {
            escalaDoDia = await res.json();
        } else {
            console.error("Erro ao buscar escala");
            escalaDoDia = [];
        }
    } catch (e) {
        console.error(e);
        escalaDoDia = [];
    }
}

// --- RENDERIZAÇÃO ---

function renderizarSidebar(lista) {
    const container = document.getElementById('lista-disponiveis');
    container.innerHTML = '';

    // Filtra quem JÁ está na escala para não duplicar (verificação por ID)
    const idsNaEscala = escalaDoDia.map(e => e.funcionario_id);
    const listaFiltrada = lista.filter(f => !idsNaEscala.includes(f.id));

    if (listaFiltrada.length === 0) {
        container.innerHTML = '<div style="padding:10px; color:#777; text-align:center">Todos escalados ou lista vazia.</div>';
    }

    listaFiltrada.forEach(func => {
        const card = document.createElement('div');
        card.className = 'func-card';
        card.setAttribute('data-id', func.id);
        card.setAttribute('data-nome', func.nome); 
        card.innerHTML = `
            <div class="func-info">
                <span class="func-name">${func.nome}</span>
                <span class="func-role">${func.cargo || 'Funcionario'}</span>
            </div>
            <span class="material-icons" style="color:#ccc">drag_indicator</span>
        `;
        container.appendChild(card);
    });

    // Torna a sidebar uma zona de "arrastar"
    new Sortable(container, {
        group: { name: 'shared', pull: 'clone', put: false }, 
        sort: false,
        animation: 150,
        onEnd: function (evt) {
            if (!evt.to.classList.contains('sector-list')) {
                evt.item.remove(); 
            }
        }
    });
}

function renderizarBoard() {
    const grid = document.getElementById('board-grid');
    grid.innerHTML = '';

    // Lista fixa de setores para garantir que apareçam mesmo vazios
    const setores = ["Gerência", "Caixa", "Balcão", "Cozinha", "Salão", "Estoque", "Limpeza", "Folga"];

    setores.forEach(setor => {
        const col = document.createElement('div');
        col.className = 'sector-column';
        
        // Cabeçalho do Setor
        col.innerHTML = `<div class="sector-header"><span>${setor}</span> <small>0 pessoas</small></div>`;
        
        // Lista de Cards do Setor
        const list = document.createElement('div');
        list.className = 'sector-list';
        list.setAttribute('data-setor', setor);

        // Preenche com quem já está na escala neste setor (comparação de string segura)
        const pessoasNoSetor = escalaDoDia.filter(e => 
            (e.setor && e.setor.toLowerCase() === setor.toLowerCase())
        );
        
        pessoasNoSetor.forEach(p => {
            const card = criarCardEscala(p);
            list.appendChild(card);
        });

        col.querySelector('small').textContent = `${pessoasNoSetor.length} pessoas`;
        col.appendChild(list);
        grid.appendChild(col);

        // Configura Drag & Drop deste setor
        new Sortable(list, {
            group: 'shared',
            animation: 150,
            onAdd: async function (evt) {
                // ALGUÉM NOVO ENTROU NO SETOR (Vindo da Sidebar)
                const item = evt.item;
                const funcId = item.getAttribute('data-id');
                const setorDestino = this.el.getAttribute('data-setor');
                
                // 1. Remove o clone visual para evitar duplicação visual antes do reload
                item.remove(); 

                // 2. Salva no Banco e Recarrega
                await adicionarNaEscala(funcId, setorDestino);
                await inicializar(); // Recarrega tudo para ficar sincronizado
            }
        });
    });
}

function criarCardEscala(dados) {
    const card = document.createElement('div');
    card.className = 'func-card';
    card.setAttribute('data-escala-id', dados.escala_id);
    card.style.backgroundColor = "#e3f2fd"; // Cor levemente diferente para indicar que já está escalado
    
    // Adiciona evento de clique para editar
    card.onclick = () => abrirModalEdicao(dados.escala_id);
    
    let horarioTexto = "08:00 - 17:00"; // Padrão visual
    if (dados.entrada && dados.saida) {
        horarioTexto = `${dados.entrada} - ${dados.saida}`;
    }

    card.innerHTML = `
        <div class="func-info">
            <span class="func-name">${dados.nome}</span>
            <span class="func-time">🕒 ${horarioTexto}</span>
        </div>
        <span class="material-icons" style="font-size:16px; cursor:pointer">edit</span>
    `;
    return card;
}

// --- LÓGICA DE API ---

async function adicionarNaEscala(funcId, setor) {
    const data = document.getElementById('data-escala').value;
    try {
        const res = await fetch('/api/admin/escala/adicionar', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ funcionario_id: funcId, data: data, setor: setor })
        });
        if (!res.ok) alert("Erro ao adicionar. Verifique se já não existe duplicidade.");
    } catch (e) {
        console.error(e);
        alert("Erro de conexão.");
    }
}

// --- MODAL E EDIÇÃO ---

let idEmEdicao = null;

function abrirModalEdicao(escalaId) {
    idEmEdicao = escalaId;
    // Encontra os dados atuais na memória
    const item = escalaDoDia.find(e => e.escala_id == escalaId);
    if (!item) return;

    document.getElementById('modal-nome-func').textContent = item.nome;
    document.getElementById('modal-escala-id').value = item.escala_id;
    
    // Preenche campos (trata null como string vazia)
    document.getElementById('modal-entrada').value = item.entrada || '08:00';
    document.getElementById('modal-saida').value = item.saida || '17:00';
    document.getElementById('modal-int-ini').value = item.int_ini || '';
    document.getElementById('modal-int-fim').value = item.int_fim || '';

    document.getElementById('modal-editar').style.display = 'flex';
}

function fecharModal() {
    document.getElementById('modal-editar').style.display = 'none';
}

async function salvarHorario() {
    const dados = {
        escala_id: idEmEdicao,
        entrada: document.getElementById('modal-entrada').value,
        saida: document.getElementById('modal-saida').value,
        int_ini: document.getElementById('modal-int-ini').value,
        int_fim: document.getElementById('modal-int-fim').value
    };

    try {
        const res = await fetch('/api/admin/escala/atualizar', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(dados)
        });

        if (res.ok) {
            fecharModal();
            inicializar(); // Atualiza a tela
        } else {
            alert("Erro ao salvar horário!");
        }
    } catch(e) {
        alert("Erro de conexão.");
    }
}

async function removerDaEscala() {
    if(!confirm("Tem certeza que deseja remover este funcionário da escala de hoje?")) return;

    try {
        const res = await fetch(`/api/admin/escala/remover/${idEmEdicao}`, { method: 'DELETE' });
        
        if (res.ok) {
            fecharModal();
            inicializar(); // Atualiza tudo (sidebar volta a ter o func)
        } else {
            alert("Erro ao remover!");
        }
    } catch(e) {
        alert("Erro de conexão.");
    }
}

async function logout() {
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.href = '/login';
}

// Fecha modal se clicar fora
window.onclick = function(event) {
    const modal = document.getElementById('modal-editar');
    if (event.target == modal) {
        fecharModal();
    }
}
