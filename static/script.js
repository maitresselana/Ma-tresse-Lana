document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("form");

  if (form) {
    form.addEventListener("submit", () => {
      const button = form.querySelector('button[type="submit"]');

      if (button) {
        button.disabled = true;
        button.textContent = "Réservation en cours...";
      }
    });
  }

  const header = document.querySelector("body > header");
  const reserveButton = header
    ? header.querySelector('a[href="#reservation"]')
    : null;

  if (
    header &&
    reserveButton &&
    !header.querySelector('a[href="/pratiques"]')
  ) {
    const nav = document.createElement("div");
    nav.className = "lana-header-actions";

    const practicesLink = document.createElement("a");
    practicesLink.className = "btn secondary lana-practices-link";
    practicesLink.href = "/pratiques";
    practicesLink.textContent = "Pratiques & Conditions";

    reserveButton.before(nav);
    nav.append(practicesLink, reserveButton);
  }

  const heroButton = document.querySelector(
    ".hero-text-card .btn-gold"
  );

  if (
    heroButton &&
    !document.querySelector(".lana-practices-hero")
  ) {
    const practicesHero = document.createElement("a");
    practicesHero.className = "btn lana-practices-hero";
    practicesHero.href = "/pratiques";
    practicesHero.textContent =
      "Découvrir les pratiques & conditions";

    heroButton.insertAdjacentElement("afterend", practicesHero);
  }

  const style = document.createElement("style");

  style.textContent = `
    .lana-header-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
    }

    .lana-practices-link {
      border-color: rgba(218, 181, 106, .55) !important;
      color: #e7c781 !important;
    }

    .lana-practices-hero {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-top: 12px;
      border: 1px solid rgba(218, 181, 106, .55);
      color: #e7c781;
      background: rgba(10, 10, 12, .42);
    }

    @media (max-width: 680px) {
      body > header {
        align-items: flex-start;
        gap: 12px;
      }

      .lana-header-actions {
        width: 100%;
        justify-content: flex-start;
      }

      .lana-header-actions .btn {
        flex: 1 1 155px;
        text-align: center;
      }

      .lana-practices-hero {
        width: 100%;
      }
    }
  `;

  document.head.appendChild(style);
});
