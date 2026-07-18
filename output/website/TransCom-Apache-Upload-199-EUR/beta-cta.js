(() => {
  const update = () => {
    const pricing = document.querySelector('.pricing');
    if (pricing) {
      const kicker = pricing.querySelector('.pricing-heading .kicker');
      const heading = pricing.querySelector('.pricing-heading h2');
      const intro = pricing.querySelector('.pricing-heading > p');
      const betaCard = pricing.querySelector('.starter-card');
      const fullCard = pricing.querySelector('.full-card');
      const pricingNote = pricing.querySelector('.pricing-note');

      if (kicker) kicker.textContent = 'BETA-ZUGANG';
      if (heading) heading.innerHTML = 'Jetzt kostenlos die Beta testen.<br><em>Full folgt später.</em>';
      if (intro) intro.textContent = 'Melde dich mit deiner E-Mail-Adresse an und erhalte den aktuellen Beta-Build. Die Full-Version wird nach Abschluss der Beta erhältlich sein.';

      if (betaCard) {
        betaCard.classList.add('beta-primary-card');
        const top = betaCard.querySelector('.price-card-top');
        const title = betaCard.querySelector('h3');
        const subline = betaCard.querySelector('.price-subline');
        const list = betaCard.querySelector('ul');
        if (top) top.innerHTML = '<span>PRIVATE BETA</span><b>JETZT VERFÜGBAR</b>';
        if (title) title.textContent = 'Kostenlos';
        if (subline) subline.textContent = 'Während der Beta-Phase';
        if (list) list.innerHTML = [
          '<li><span>✓</span> E-Mail bestätigen und Beta herunterladen</li>',
          '<li><span>✓</span> Vorhandene Transkripte ansehen und verwalten</li>',
          '<li><span>✓</span> Neue Sessions bis 60 Sekunden testen</li>',
          '<li class="not-included"><span>–</span> Export ist in der Beta nicht enthalten</li>'
        ].join('');
      }

      if (fullCard) {
        fullCard.classList.add('beta-future-card');
        const recommended = fullCard.querySelector('.recommended');
        const top = fullCard.querySelector('.price-card-top');
        const title = fullCard.querySelector('h3');
        const subline = fullCard.querySelector('.price-subline');
        const list = fullCard.querySelector('ul');
        const action = fullCard.querySelector('.button');
        const note = fullCard.querySelector('small');
        if (recommended) recommended.textContent = 'AUSBLICK';
        if (top) top.innerHTML = '<span>FULL-VERSION</span><b>NACH DER BETA</b>';
        if (title) title.textContent = '199 €';
        if (subline) subline.textContent = 'Einmalig – nach Abschluss der Beta';
        if (list) list.innerHTML = [
          '<li><span>✓</span> Alles aus der Beta</li>',
          '<li><span>✓</span> Neue Sessions ohne Zeitlimit</li>',
          '<li><span>✓</span> Export als TXT und CSV</li>',
          '<li><span>✓</span> Lokale Verarbeitung und Speicherung</li>'
        ].join('');
        if (action) {
          const unavailable = document.createElement('span');
          unavailable.className = 'button price-disabled';
          unavailable.setAttribute('aria-disabled', 'true');
          unavailable.textContent = 'Noch nicht erhältlich';
          action.replaceWith(unavailable);
        }
        if (note) note.textContent = 'Die Full-Version wird nach Abschluss der Beta veröffentlicht.';
      }

      if (pricingNote) pricingNote.remove();
    }

    const installationWorkflow = document.querySelector('.workflow');
    const resourcesSection = document.querySelector('.resources');
    const handoffSection = document.querySelector('.handoff');
    const betaKitSection = document.querySelector('.beta-kit');
    if (installationWorkflow && !installationWorkflow.classList.contains('installation-section')) {
      const resourceLinks = resourcesSection ? Array.from(resourcesSection.querySelectorAll('.resource-list a')) : [];
      const handbookHref = resourceLinks[0]?.getAttribute('href') || '/transcom/downloads/TransCom_Beta-Handbuch_DE.pdf';
      const feedbackSource = resourceLinks.find((link) => link.hasAttribute('download'));
      const feedbackHref = feedbackSource?.getAttribute('href') || '#';
      const feedbackDownload = feedbackSource?.getAttribute('download') || 'TransCom_Beta_Feedback.txt';

      installationWorkflow.classList.add('installation-section');
      installationWorkflow.innerHTML = `
        <div class="section-heading installation-heading">
          <span class="kicker">INSTALLATION</span>
          <h2>Vom Download zum<br>ersten <em>Transkript.</em></h2>
          <p>Der Build bringt Backend und Modelle bereits mit. Du musst nichts zusätzlich installieren und brauchst beim späteren Betrieb keine Cloud-API.</p>
        </div>
        <div class="installation-steps">
          <article class="installation-step">
            <span>1</span>
            <div><h3>Download abschließen</h3><p>Bestätige deine E-Mail-Adresse und lade das rund 2 GB große ZIP vollständig herunter. Der persönliche Link ist sechs Stunden gültig und unterstützt das Fortsetzen des Downloads.</p></div>
          </article>
          <article class="installation-step">
            <span>2</span>
            <div><h3>Entpacken und ablegen</h3><p>Öffne das ZIP im Finder und verschiebe <strong>TransCom.app</strong> nach „Programme“ oder in einen lokalen Testordner. Starte die App nicht direkt aus dem ZIP.</p></div>
          </article>
          <article class="installation-step">
            <span>3</span>
            <div><h3>Beim ersten Mal bewusst öffnen</h3><p>Klicke mit der rechten Maustaste auf <strong>TransCom.app</strong> und wähle „Öffnen“. Bestätige die Warnung des nicht signierten Builds. Falls macOS weiter blockiert, erlaube den Start unter „Datenschutz &amp; Sicherheit“.</p></div>
          </article>
          <article class="installation-step">
            <span>4</span>
            <div><h3>Bereit abwarten und Demo starten</h3><p>Erlaube bei Bedarf den Mikrofonzugriff und warte beim ersten Start bis zu 60 Sekunden. Sobald unten „Bereit“ steht, vergib einen Namen, wähle „Demo“ und starte die Transkription.</p></div>
          </article>
          <article class="installation-step">
            <span>5</span>
            <div><h3>Modelle und vollständige Deinstallation</h3><p>Backend und Sprachmodelle sind bereits in der App enthalten und werden nicht nachträglich aus der Cloud geladen. Zum vollständigen Entfernen löscht du die App sowie den zu TransCom gehörenden Ordner unter <strong>~/Library/Application Support/</strong>. Selbst gewählte Session-Ordner und Exporte löschst du separat.</p></div>
          </article>
        </div>
        <div class="installation-help">
          <div><span class="kicker">WENN DU MEHR BRAUCHST</span><h3>Details und Fehlerhilfe</h3><p>Das Handbuch erklärt Installation, Audioquellen und typische Startprobleme. Beobachtungen kannst du direkt in der Feedbackvorlage festhalten.</p></div>
          <div class="installation-links">
            <a class="button button-primary" data-install-handbook>Handbuch öffnen <span aria-hidden="true">↗</span></a>
            <a class="text-link" data-install-feedback>Feedbackvorlage laden ↓</a>
          </div>
        </div>
      `;

      const handbookLink = installationWorkflow.querySelector('[data-install-handbook]');
      const feedbackLink = installationWorkflow.querySelector('[data-install-feedback]');
      if (handbookLink) {
        handbookLink.href = handbookHref;
        handbookLink.target = '_blank';
        handbookLink.rel = 'noopener';
      }
      if (feedbackLink) {
        feedbackLink.href = feedbackHref;
        feedbackLink.setAttribute('download', feedbackDownload);
      }
    }
    if (resourcesSection) resourcesSection.remove();
    if (handoffSection) handoffSection.remove();
    if (betaKitSection) betaKitSection.remove();

    const disabled = document.querySelector('.starter-card .price-disabled');
    if (disabled) {
      const link = document.createElement('a');
      link.className = 'button button-primary';
      link.href = '/transcom/beta/';
      link.innerHTML = 'Zur Beta anmelden <span aria-hidden="true">→</span>';
      disabled.replaceWith(link);
      const note = link.nextElementSibling;
      if (note && note.tagName === 'SMALL') {
        note.textContent = 'Mit E-Mail anmelden und Beta-Download erhalten.';
      }
    }

    const handoff = document.querySelector('.handoff');
    if (handoff) {
      const status = handoff.querySelector('.eyebrow');
      const paragraph = handoff.querySelector('p');
      const primary = handoff.querySelector('.handoff-actions .button');
      if (status) status.innerHTML = '<span class="status-dot"></span> Beta jetzt verfügbar';
      if (paragraph) paragraph.textContent = 'Melde dich mit deiner E-Mail-Adresse an und erhalte nach der Bestätigung den aktuellen Beta-Build. Die Full-Version folgt nach Abschluss der Beta.';
      if (primary) {
        primary.href = '/transcom/beta/';
        primary.innerHTML = 'Zur Beta anmelden <span aria-hidden="true">→</span>';
      }
    }

    const heroPrimary = document.querySelector('.hero-actions .button-primary');
    if (heroPrimary) {
      heroPrimary.href = '/transcom/beta/';
      heroPrimary.innerHTML = 'Jetzt Beta testen <span aria-hidden="true">→</span>';
    }

    const testKitPrimary = document.querySelector('.kit-actions .button-primary');
    if (testKitPrimary) {
      testKitPrimary.href = '/transcom/beta/';
      testKitPrimary.innerHTML = 'Jetzt Beta testen <span aria-hidden="true">→</span>';
    }

    if (!document.getElementById('beta-pricing-overrides')) {
      const style = document.createElement('style');
      style.id = 'beta-pricing-overrides';
      style.textContent = `
        .beta-primary-card { background: var(--navy-900); color: #fff; }
        .beta-primary-card h3 { color: #fff; }
        .beta-primary-card .price-card-top { color: #b8cad6; }
        .beta-primary-card .price-card-top b { color: #d8e4eb; border-color: #ffffff40; }
        .beta-primary-card .price-subline { color: #a9bdca; }
        .beta-primary-card ul,
        .beta-primary-card li { border-color: #ffffff21; }
        .beta-primary-card li { color: #d1dce3; }
        .beta-primary-card li span { color: #8bc2a9; }
        .beta-primary-card li.not-included { color: #93a7b4; }
        .beta-primary-card > small { color: #a9bdca; }
        .beta-future-card { background: #f1ede5; color: var(--navy-950); }
        .beta-future-card h3 { color: var(--navy-950); }
        .beta-future-card .recommended { background: #d8d0c4; color: #667884; }
        .beta-future-card .price-card-top { color: var(--blue); }
        .beta-future-card .price-card-top b { color: #7b8992; border-color: var(--line); }
        .beta-future-card .price-subline { color: var(--muted); }
        .beta-future-card ul,
        .beta-future-card li { border-color: var(--line); }
        .beta-future-card li { color: #5f707c; }
        .beta-future-card li span { color: #7c9b8c; }
        .beta-future-card > small { color: #7b8992; }
        .workflow.installation-section { display: block; padding-top: 35px; }
        .installation-heading { display: grid; grid-template-columns: 1.25fr .75fr; column-gap: 90px; align-items: end; }
        .installation-heading .kicker { grid-column: 1 / -1; }
        .installation-heading h2 { margin: 20px 0 0; }
        .installation-heading > p { color: #586d7d; font-size: 14px; line-height: 1.8; margin: 0 0 6px; }
        .installation-steps { border-top: 1px solid var(--line); margin-top: 48px; }
        .installation-step { display: grid; grid-template-columns: 64px 1fr; gap: 22px; padding: 25px 0; border-bottom: 1px solid var(--line); }
        .installation-step > span { color: var(--orange); font: 600 30px/1 var(--font-display); padding-top: 2px; }
        .installation-step h3 { color: var(--navy-950); margin: 0 0 7px; font-size: 17px; }
        .installation-step p { color: #5e7180; margin: 0; max-width: 920px; font-size: 12px; line-height: 1.7; }
        .installation-step strong { color: var(--navy-950); }
        .installation-help { background: var(--navy-900); color: #fff; display: grid; grid-template-columns: 1.25fr .75fr; gap: 60px; align-items: center; margin-top: 38px; padding: 38px; position: relative; overflow: hidden; }
        .installation-help::after { content: ''; position: absolute; width: 320px; height: 320px; border: 1px solid #ffffff0d; border-radius: 50%; right: -120px; bottom: -210px; }
        .installation-help .kicker { color: #a9c0cf; }
        .installation-help h3 { color: #fff; margin: 8px 0 5px; font: 600 30px/1.1 var(--font-display); }
        .installation-help p { color: #b6c7d2; margin: 0; font-size: 11px; line-height: 1.65; }
        .installation-links { display: grid; gap: 14px; justify-items: stretch; }
        .installation-links .button { width: 100%; padding: 16px 20px; }
        .installation-links .text-link { color: #c5d4dd; text-align: center; position: relative; z-index: 1; }
        @media (width <= 960px) {
          .installation-heading { grid-template-columns: 1fr; gap: 22px; }
          .installation-heading .kicker { grid-column: auto; }
          .installation-help { grid-template-columns: 1fr; gap: 25px; }
        }
        @media (width <= 720px) {
          .installation-step { grid-template-columns: 42px 1fr; gap: 12px; }
          .installation-help { padding: 28px 22px; }
        }
      `;
      document.head.appendChild(style);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', update, { once: true });
  } else {
    update();
  }
  window.setTimeout(update, 500);
})();
