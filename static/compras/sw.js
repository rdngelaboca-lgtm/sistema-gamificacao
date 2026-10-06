// sw.js - "service worker" do app de compras.
// Guarda uma cópia do app no celular para ele ABRIR mesmo sem internet.
// Os dados (contagens, listas) não passam por aqui: o próprio app guarda e envia depois.
// Ao mudar o app (compras_app.html), aumente o número da versão abaixo.
const VERSAO = 'gb-compras-v23';
const ARQUIVOS = ['/compras/', '/compras/manifest.webmanifest', '/compras/arquivos/icone-192.png', '/compras/arquivos/icone-512.png'];

self.addEventListener('install', evento => {
  evento.waitUntil(caches.open(VERSAO).then(c => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', evento => {
  evento.waitUntil(caches.keys()
    .then(nomes => Promise.all(nomes.filter(n => n !== VERSAO).map(n => caches.delete(n))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', evento => {
  const req = evento.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  // Páginas e arquivos do app: tenta a internet primeiro (versão mais nova);
  // sem internet, usa a cópia guardada.
  evento.respondWith(
    fetch(req).then(resp => {
      if (resp.ok) {
        const copia = resp.clone();
        caches.open(VERSAO).then(c => c.put(req.mode === 'navigate' ? '/compras/' : req, copia));
      }
      return resp;
    }).catch(() => caches.match(req.mode === 'navigate' ? '/compras/' : req)
      .then(r => r || new Response('Sem internet e o app ainda não foi guardado neste celular.',
                                    {status: 503, headers: {'Content-Type': 'text/plain; charset=utf-8'}})))
  );
});
