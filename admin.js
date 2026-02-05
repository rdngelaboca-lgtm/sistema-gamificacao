// URL base da API (se rodar na mesma máquina, basta vazio)
const API_BASE = "/api";

// --- 1. LÓGICA DE LOGIN ---
async function realizarLogin() {
    const senha = document.getElementById('senha-admin').value;
    try {
        const res = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({senha: senha})
        });
        const json = await res.json();
        
        if (json.sucesso) {
            document.getElementById('login-overlay').style.display = 'none';
            document.getElementById('admin-panel').style.display = 'block';
            carregarEscala(); // Carrega os dados assim que logar
        } else {
            document.getElementById('msg-erro').style.display = 'block';
        }
    } catch (e) {
        alert("Erro ao conectar com servidor");
    }
}

async function logout() {
    await fetch(`${API_BASE}/logout`, {method: 'POST'});
    location.reload();
}

// Verifica se já estava logado ao abrir a página
window.onload = async () => {
    // Define data de hoje no input
    document.getElementById('data-selecionada').valueAsDate = new Date();
    
    const res = await fetch(`${API_BASE}/check-auth`);
    const json = await res.json();
    if (json.logado) {
        document.getElementById('login-overlay').style.display = 'none';
        document.getElementById('admin-panel').style.display = 'block';
        carregarEscala();
    }
};

// --- 2. CARREGAMENTO DE DADOS ---
async function carregarEscala() {
    const data = document.getElementById('data-selecionada').value;
    // Por enquanto chamamos 'hoje', mas idealmente passaria a data na URL
    // Ex: /api/escala?data=2023-10-10
    const res = await fetch(`${API_BASE}/escala/hoje`);
    const dados = await res.json();
    
    renderizarMapa(dados);
}

function renderizarMapa(dadosAgrupados) {
    const container = document.getElementById('mapa-container');
    container.innerHTML = ''; // Limpa tudo

    // Itera sobre os setores (Frente, Cozinha, etc)
    for (const [setor, funcionarios] of Object.entries(dadosAgrupados)) {
        funcionarios.forEach(func => {
            criarBoneco(func, container);
        });
    }
}

function criarBoneco(func, container) {
    const el = document.createElement('div');
    el.className = 'avatar-funcionario';
    
    // Posição Inicial (vinda do banco)
    const x = func.posicao_mapa.x || 10;
    const y = func.posicao_mapa.y || 10;
    
    // Importante: Interact.js usa 'transform' para mover, 
    // mas para posicionar inicialmente usamos top/left ou transform também.
    // Vamos usar dataset para guardar a posição atual
    el.style.transform = `translate(${x}px, ${y}px)`;
    el.dataset.x = x;
    el.dataset.y = y;
    el.dataset.id = func.id_escala; // ID para salvar no banco
    
    // Conteúdo HTML do boneco
    el.innerHTML = `
        <span class="avatar-nome">${func.nome.split(' ')[0]}</span>
        <span class="avatar-hora">${func.entrada} - ${func.saida}</span>
    `;

    // Evento de Clique para abrir Modal (mas só se não estiver arrastando)
    el.addEventListener('click', (e) => {
        // Pequeno hack para não abrir modal quando solta o drag
        if (el.getAttribute('data-dragging') === 'true') return;
        abrirModal(func);
    });

    container.appendChild(el);
}

// --- 3. DRAG AND DROP (INTERACT.JS) ---
interact('.avatar-funcionario').draggable({
    inertia: true,
    modifiers: [
        interact.modifiers.restrictRect({
            restriction: 'parent',
            endOnly: true
        })
    ],
    autoScroll: true,
    
    listeners: {
        start (event) {
            event.target.setAttribute('data-dragging', 'true');
        },
        move (event) {
            var target = event.target;
            // Mantém a posição somando o delta do movimento
            var x = (parseFloat(target.dataset.x) || 0) + event.dx;
            var y = (parseFloat(target.dataset.y) || 0) + event.dy;

            // Atualiza visualmente
            target.style.transform = `translate(${x}px, ${y}px)`;

            // Atualiza os atributos de dados
            target.dataset.x = x;
            target.dataset.y = y;
        },
        end (event) {
            setTimeout(() => event.target.setAttribute('data-dragging', 'false'), 100);
            salvarPosicao(event.target);
        }
    }
});

async function salvarPosicao(elemento) {
    const id = elemento.dataset.id;
    const x = elemento.dataset.x;
    const y = elemento.dataset.y;

    // Feedback visual (opacidade muda rapidinho)
    elemento.style.opacity = '0.5';

    try {
        await fetch(`${API_BASE}/escala/atualizar-posicao`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: id, x: x, y: y })
        });
        elemento.style.opacity = '1';
    } catch (e) {
        alert("Erro ao salvar posição!");
        elemento.style.opacity = '1';
    }
}

// --- 4. MODAL E EDIÇÃO ---
function abrirModal(funcObj) {
    const modal = document.getElementById('modal-editar');
    
    // Preenche os campos
    document.getElementById('modal-titulo').innerText = `Editar: ${funcObj.nome}`;
    document.getElementById('edit-id').value = funcObj.id_escala;
    document.getElementById('edit-entrada').value = funcObj.entrada;
    document.getElementById('edit-saida').value = funcObj.saida;
    document.getElementById('edit-int-ini').value = funcObj.int_ini;
    document.getElementById('edit-int-fim').value = funcObj.int_fim;

    modal.style.display = 'flex';
}

function fecharModal() {
    document.getElementById('modal-editar').style.display = 'none';
}

async function salvarAlteracoes() {
    const dados = {
        id: document.getElementById('edit-id').value,
        entrada: document.getElementById('edit-entrada').value,
        saida: document.getElementById('edit-saida').value,
        int_ini: document.getElementById('edit-int-ini').value,
        int_fim: document.getElementById('edit-int-fim').value
    };

    try {
        const res = await fetch(`${API_BASE}/escala/atualizar-horario`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(dados)
        });
        
        const json = await res.json();
        if (json.sucesso) {
            Swal.fire({
                icon: 'success',
                title: 'Salvo!',
                text: 'Horário atualizado com sucesso.',
                timer: 1500,
                showConfirmButton: false
            });
            fecharModal();
            carregarEscala(); // Recarrega para atualizar os textos nos bonecos
        } else {
            Swal.fire('Erro', 'Falha ao salvar: ' + json.erro, 'error');
        }
    } catch (e) {
        Swal.fire('Erro', 'Erro de conexão', 'error');
    }
}

// Fecha modal se clicar fora da caixa branca
window.onclick = function(event) {
    const modal = document.getElementById('modal-editar');
    if (event.target == modal) {
        fecharModal();
    }
}