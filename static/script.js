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
    practicesLink.className =
      "btn secondary lana-practices-link";
    practicesLink.href = "/pratiques";
    practicesLink.textContent =
      "Pratiques & Conditions";

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
    practicesHero.className =
      "btn lana-practices-hero";
    practicesHero.href = "/pratiques";
    practicesHero.textContent =
      "Découvrir les pratiques & conditions";

    heroButton.insertAdjacentElement(
      "afterend",
      practicesHero
    );
  }

  async function addHomepageReviews() {
    if (document.querySelector(".lana-home-reviews")) {
      return;
    }

    let reviews = [];

    try {
      const response = await fetch("/api/reviews");

      if (response.ok) {
        reviews = await response.json();
      }
    } catch (error) {
      reviews = [];
    }

    const reservation =
      document.getElementById("reservation");

    if (!reservation) {
      return;
    }

    const section =
      document.createElement("section");

    section.className = "lana-home-reviews";

    const heading =
      document.createElement("div");

    heading.className =
      "lana-home-reviews-head";

    heading.innerHTML = `
      <p>EXPÉRIENCES</p>
      <h2>Avis des clients</h2>
      <span>Seuls les avis validés sont affichés.</span>
    `;

    section.appendChild(heading);

    if (reviews.length) {
      const grid =
        document.createElement("div");

      grid.className =
        "lana-home-reviews-grid";

      reviews.forEach((review) => {
        const card =
          document.createElement("article");

        card.className =
          "lana-home-review-card";

        const stars =
          "★".repeat(review.rating) +
          "☆".repeat(5 - review.rating);

        const verified = review.verified
          ? '<span class="lana-verified">Client vérifié</span>'
          : "";

        const starsElement =
          document.createElement("div");

        starsElement.className =
          "lana-review-stars";

        starsElement.textContent = stars;

        const title =
          document.createElement("h3");

        title.textContent = review.pseudo;

        const badge =
          document.createElement("div");

        badge.innerHTML = verified;

        const comment =
          document.createElement("p");

        comment.textContent = review.comment;

        card.append(
          starsElement,
          title,
          badge,
          comment
        );

        grid.appendChild(card);
      });

      section.appendChild(grid);
    } else {
      const empty =
        document.createElement("div");

      empty.className =
        "lana-home-reviews-empty";

      empty.textContent =
        "Aucun avis publié pour le moment. Le premier témoignage peut être le vôtre.";

      section.appendChild(empty);
    }

    const actions =
      document.createElement("div");

    actions.className =
      "lana-home-reviews-actions";

    actions.innerHTML = `
      <a class="btn secondary" href="/avis">
        Voir tous les avis
      </a>
      <a class="btn primary" href="/avis#formulaire">
        Laisser un avis
      </a>
    `;

    section.appendChild(actions);

    reservation.insertAdjacentElement(
      "beforebegin",
      section
    );
  }

  addHomepageReviews();

  const style =
    document.createElement("style");

  style.textContent = `    .lana-home-reviews {
      width: min(1120px, calc(100% - 32px));
      margin: 34px auto;
      padding: 30px;
      border: 1px solid rgba(218,181,106,.25);
      border-radius: 24px;
      background:
        radial-gradient(circle at 90% 0%,
        rgba(105,30,50,.18),
        transparent 30%),
        rgba(18,18,23,.96);
      box-shadow: 0 24px 60px rgba(0,0,0,.25);
    }

    .lana-home-reviews-head {
      text-align: center;
      margin-bottom: 22px;
    }

    .lana-home-reviews-head p {
      margin: 0 0 6px;
      color: #d8b56c;
      font-size: .74rem;
      font-weight: 900;
      letter-spacing: .2em;
    }

    .lana-home-reviews-head h2 {
      margin: 0;
      color: #f4eadc;
      font-family: Georgia,"Times New Roman",serif;
      font-size: clamp(2rem,6vw,3.5rem);
      font-weight: 500;
    }

    .lana-home-reviews-head span {
      display: block;
      margin-top: 8px;
      color: #a99fa4;
    }

    .lana-home-reviews-grid {
      display: grid;
      grid-template-columns: repeat(3,minmax(0,1fr));
      gap: 14px;
    }

    .lana-home-review-card {
      padding: 20px;
      border: 1px solid #332f36;
      border-radius: 18px;
      background: #111115;
    }

    .lana-review-stars {
      color: #e2bd70;
      letter-spacing: .12em;
    }

    .lana-home-review-card h3 {
      margin: 10px 0 6px;
      color: #f4eadc;
      font-family: Georgia,"Times New Roman",serif;
      font-size: 1.25rem;
    }

    .lana-home-review-card p {
      margin: 12px 0 0;
      color: #d6cdd2;
      line-height: 1.65;
      white-space: pre-wrap;
    }

    .lana-verified {
      display: inline-flex;
      padding: 4px 8px;
      border: 1px solid rgba(218,181,106,.45);
      border-radius: 999px;
      color: #efd49a;
      font-size: .72rem;
    }

    .lana-home-reviews-empty {
      padding: 24px;
      border: 1px dashed #3a353d;
      border-radius: 16px;
      color: #aaa1a7;
      text-align: center;
    }

    .lana-home-reviews-actions {
      display: flex;
      justify-content: center;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 20px;
    }    html {
      scroll-behavior: smooth;
    }

    .hero-photo-card,
    .hero-text-card,
    .card,
    .lana-home-reviews {
      transition: transform .25s ease,
                  box-shadow .25s ease,
                  border-color .25s ease;
    }

    @media (hover:hover) {
      .hero-photo-card:hover,
      .hero-text-card:hover,
      .card:hover,
      .lana-home-reviews:hover {
        transform: translateY(-3px);
        border-color: rgba(218,181,106,.38);
        box-shadow: 0 28px 70px rgba(0,0,0,.34);
      }
    }

    .lana-header-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
    }

    .lana-practices-link {
      border-color: rgba(218,181,106,.55) !important;
      color: #e7c781 !important;
    }

    .lana-practices-hero {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-top: 12px;
      border: 1px solid rgba(218,181,106,.55);
      color: #e7c781;
      background: rgba(10,10,12,.42);
    }

    .lana-practices-hero:hover,
    .lana-practices-link:hover {
      border-color: #e7c781 !important;
      background: rgba(218,181,106,.10);
    }

    @media (max-width: 900px) {
      .lana-home-reviews-grid {
        grid-template-columns: 1fr;
      }
    }    @media (max-width: 680px) {
      body {
        overflow-x: hidden;
      }

      body > header {
        align-items: flex-start;
        gap: 12px;
      }

      .hero.hero-lana {
        gap: 14px;
        padding-left: 12px;
        padding-right: 12px;
      }

      .hero-photo-card,
      .hero-text-card,
      .wrap .card,
      .lana-home-reviews {
        border-radius: 20px;
      }

      .hero-text-card {
        padding: 22px 18px !important;
      }

      .hero-text-card h1 {
        font-size: clamp(2.35rem, 12vw, 3.7rem) !important;
        line-height: .98;
      }

      .hero-text-card p {
        font-size: .98rem;
        line-height: 1.65;
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

      .booking-calendar {
        padding: 12px !important;
      }

      .calendar-days {
        gap: 5px !important;
      }

      .calendar-days button {
        min-height: 42px;
        border-radius: 11px !important;
      }

      input,
      select,
      textarea,
      button {
        font-size: 16px !important;
      }

      .times {
        gap: 8px;
      }

      .timebtn {
        min-height: 44px;
        padding: 10px 13px;
      }

      .lana-home-reviews {
        width: calc(100% - 24px);
        margin: 24px auto;
        padding: 22px 15px;
      }

      .lana-home-reviews-actions .btn {
        width: 100%;
      }
    }
  `;

  document.head.appendChild(style);
});
