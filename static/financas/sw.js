// sw.js - "service worker" do app de finanças.
// Só serve para o navegador deixar "instalar" o app na tela inicial e abrir a tela
// mais rápido. Os dados (lançamentos, cupons) vêm SEMPRE do servidor.
// Ao mudar o app (financas_app.html), aumente o número da versão abaixo.
const VERSAO = 'financas-v1';
const ARQUIVOS = ['/financas/', '/financas/manifest.webmanifest', '/financas/arquivos/icone-192.png', '/financas/arquivos/icone-512.png'];

self.addEventListener('install', evento => {
  evento.waitUntil(caches.open(VERSAO).then(c => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', evento => {
  evento.waitUntil(caches.keys()
    .then(nomes => Promise.all(nomes.filter(n => n.startsWith('financas-') && n !== VERSAO).map(n => caches.delete(n))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', evento => {
  const req = evento.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  // internet primeiro (versão mais nova); sem internet, a cópia guardada
  evento.respondWith(
    fetch(req).then(resp => {
      if (resp.ok) {
        const copia = resp.clone();
        caches.open(VERSAO).then(c => c.put(req.mode === 'navigate' ? '/financas/' : req, copia));
      }
      return resp;
    }).catch(() => caches.match(req.mode === 'navigate' ? '/financas/' : req)
      .then(r => r || new Response('Sem internet.', {status: 503, headers: {'Content-Type': 'text/plain; charset=utf-8'}})))
  );
});
