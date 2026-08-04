const CACHE_NAME = "admin-lana-v4";

const APP_SHELL = [
  "/admin",
  "/static/style.css",
  "/static/admin-icon-192.png",
  "/static/admin-icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );

  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );

  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    return;
  }

  if (
    url.pathname.startsWith("/admin") ||
    url.pathname.startsWith("/static/")
  ) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();

          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, copy);
          });

          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});

self.addEventListener("push", (event) => {
  let data = {
    title: "Admin Lana",
    body: "Nouvelle réservation",
    url: "/admin",
    icon: "/static/admin-icon-192.png",
    badge: "/static/admin-icon-192.png",
    badgeCount: 1
  };

  if (event.data) {
    try {
      data = {
        ...data,
        ...event.data.json()
      };
    } catch (error) {
      data.body = event.data.text();
    }
  }

  const tasks = [
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      badge: data.badge,
      data: {
        url: data.url
      },
      tag: "nouvelle-reservation",
      renotify: true
    })
  ];

  if ("setAppBadge" in self.navigator) {
    tasks.push(
      self.navigator.setAppBadge(
        Number(data.badgeCount) || 1
      )
    );
  }

  event.waitUntil(Promise.all(tasks));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const targetUrl =
    event.notification.data?.url || "/admin";

  event.waitUntil(
    clients
      .matchAll({
        type: "window",
        includeUncontrolled: true
      })
      .then((clientList) => {
        for (const client of clientList) {
          if ("focus" in client) {
            client.navigate(targetUrl);
            return client.focus();
          }
        }

        return clients.openWindow(targetUrl);
      })
  );
});

self.addEventListener("message", (event) => {
  if (
    event.data?.type === "SET_BADGE" &&
    "setAppBadge" in self.navigator
  ) {
    self.navigator.setAppBadge(
      Number(event.data.count) || 0
    );
  }

  if (
    event.data?.type === "CLEAR_BADGE" &&
    "clearAppBadge" in self.navigator
  ) {
    self.navigator.clearAppBadge();
  }
});
