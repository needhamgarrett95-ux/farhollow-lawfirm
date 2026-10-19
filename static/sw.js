/* Law Firm Case Management — service worker (offline fallback only).
   NOTE: Service workers require HTTPS (or localhost). On plain HTTP over
   the office LAN, browsers will refuse to install this — the app still
   works normally as a web page; only the offline fallback is unavailable.
   On iOS, "Add to Home Screen" works over HTTP, but offline mode needs HTTPS. */

const CACHE = 'lawfirm-v1';
const OFFLINE_URL = '/offline.html';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.add(OFFLINE_URL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Only handle GET navigations; let API/form POSTs fail naturally when offline.
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request).catch(() => {
      // Network failed — if it was a page navigation, show the offline page.
      if (event.request.mode === 'navigate') {
        return caches.match(OFFLINE_URL);
      }
      return Response.error();
    })
  );
});
