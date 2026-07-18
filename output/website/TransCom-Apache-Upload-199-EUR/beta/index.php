<?php
declare(strict_types=1);
require __DIR__ . '/lib.php';
beta_headers();

$status = 'form';
$message = '';
$emailValue = '';

try {
    beta_ensure_storage();
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        $emailValue = trim((string) ($_POST['email'] ?? ''));
        $honeypot = trim((string) ($_POST['website'] ?? ''));
        $started = (string) ($_POST['started'] ?? '');
        $signature = (string) ($_POST['form_token'] ?? '');
        $acknowledged = (string) ($_POST['acknowledge'] ?? '') === 'yes';

        if ($honeypot !== '') {
            $status = 'sent';
        } elseif (!beta_form_is_valid($started, $signature)) {
            $message = 'Das Formular ist abgelaufen. Bitte lade die Seite neu und versuche es noch einmal.';
        } elseif (!$acknowledged) {
            $message = 'Bitte bestätige die Beta- und Datenschutzhinweise.';
        } elseif (strlen($emailValue) > 254 || !filter_var($emailValue, FILTER_VALIDATE_EMAIL)) {
            $message = 'Bitte gib eine gültige E-Mail-Adresse ein.';
        } elseif (!beta_rate_limit($emailValue)) {
            $message = 'Für diese Adresse wurde gerade bereits ein Link angefordert. Bitte prüfe dein Postfach oder versuche es später erneut.';
        } else {
            $token = beta_create_request($emailValue);
            if (!beta_send_confirmation($emailValue, $token)) {
                beta_remove_request($token);
                throw new RuntimeException('Die Bestätigungs-E-Mail konnte nicht versendet werden.');
            }
            $status = 'sent';
        }
    }
    [$startedAt, $formToken] = beta_form_fields();
} catch (Throwable $error) {
    error_log('TransCom beta request error: ' . $error->getMessage());
    $status = 'error';
    $message = 'Der Download-Service ist momentan nicht erreichbar. Bitte versuche es später erneut oder schreibe an info@amazinglighting.design.';
    [$startedAt, $formToken] = [time(), ''];
}
?>
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,follow">
  <title>TransCom Beta herunterladen</title>
  <meta name="description" content="Mit E-Mail anmelden und die TransCom Beta für macOS herunterladen.">
  <link rel="stylesheet" href="/transcom/beta/style.css">
</head>
<body>
  <main class="shell">
    <a class="brand" href="/transcom/" aria-label="Zurück zur TransCom Startseite">
      <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
      <span>TransCom</span>
    </a>

    <section class="panel">
      <div class="copy">
        <p class="eyebrow"><span></span> Private Beta · Apple Silicon</p>
        <h1>Jetzt ist Beta-Zeit.</h1>
        <p class="lead">Melde dich mit deiner E-Mail-Adresse an und erhalte nach der Bestätigung den aktuellen TransCom-Beta-Build für macOS.</p>
        <ul class="facts">
          <li><b>✓</b> Verarbeitung und Speicherung lokal auf dem Mac</li>
          <li><b>✓</b> Deutsch und Englisch</li>
          <li><b>✓</b> Neue Sessions bis 60 Sekunden</li>
          <li><b>–</b> Nicht signierter Beta-Build, nur Apple Silicon</li>
        </ul>
      </div>

      <div class="form-card">
        <?php if ($status === 'sent'): ?>
          <p class="kicker">Fast geschafft</p>
          <h2>Bitte E-Mail bestätigen.</h2>
          <p>Wir haben dir einen Link geschickt. Prüfe bitte auch den Spam-Ordner. Der Bestätigungslink ist 24 Stunden gültig.</p>
          <a class="button secondary" href="/transcom/">Zurück zu TransCom</a>
        <?php elseif ($status === 'error'): ?>
          <p class="kicker error">Vorübergehend nicht verfügbar</p>
          <h2>Das hat leider nicht geklappt.</h2>
          <p><?= beta_escape($message) ?></p>
          <a class="button secondary" href="/transcom/beta/">Erneut versuchen</a>
        <?php else: ?>
          <p class="kicker">Beta-Download</p>
          <h2>Melde dich mit deiner E-Mail an.</h2>
          <?php if ($message !== ''): ?><p class="notice" role="alert"><?= beta_escape($message) ?></p><?php endif; ?>
          <form method="post" action="/transcom/beta/" novalidate>
            <label for="email">E-Mail-Adresse</label>
            <input id="email" name="email" type="email" maxlength="254" autocomplete="email" inputmode="email" required value="<?= beta_escape($emailValue) ?>" placeholder="name@beispiel.de">
            <div class="trap" aria-hidden="true">
              <label for="website">Website</label>
              <input id="website" name="website" type="text" tabindex="-1" autocomplete="off">
            </div>
            <input type="hidden" name="started" value="<?= (int) $startedAt ?>">
            <input type="hidden" name="form_token" value="<?= beta_escape($formToken) ?>">
            <label class="check">
              <input type="checkbox" name="acknowledge" value="yes" required>
              <span>Ich habe die <a href="/transcom/beta/privacy.php" target="_blank" rel="noopener">Datenschutzhinweise</a> und die <a href="/transcom/#hinweise">Beta-Hinweise</a> zur Kenntnis genommen.</span>
            </label>
            <button class="button" type="submit">Bestätigungslink senden <span aria-hidden="true">→</span></button>
          </form>
          <p class="fineprint">Nur für diesen Download. Keine Newsletter- oder Werbeanmeldung.</p>
        <?php endif; ?>
      </div>
    </section>

    <footer>
      <span>© 2026 TransCom</span>
      <a href="/imprint/">Impressum</a>
      <a href="/transcom/beta/privacy.php">Datenschutz</a>
    </footer>
  </main>
</body>
</html>
