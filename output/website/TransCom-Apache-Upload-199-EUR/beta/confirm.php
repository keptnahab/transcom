<?php
declare(strict_types=1);
require __DIR__ . '/lib.php';
beta_headers();

$payload = null;
$error = '';
$config = [];
$downloadUrl = '';
$offer = [];
try {
    $config = beta_config();
    $token = strtolower(trim((string) ($_GET['token'] ?? '')));
    $payload = beta_confirm_request($token);
    if ($payload === null) {
        $error = 'Der Bestätigungslink ist ungültig oder bereits abgelaufen.';
    } else {
        $offer = beta_download_offer_for_email((string) $payload['email']);
        $downloadUrl = beta_r2_presigned_download_url((string) $offer['object_key']);
    }
} catch (Throwable $exception) {
    error_log('TransCom beta confirmation error: ' . $exception->getMessage());
    $error = 'Die Bestätigung konnte momentan nicht abgeschlossen werden.';
}
?>
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title><?= $payload ? 'TransCom ' . beta_escape((string) $offer['label']) . '-Download' : 'Bestätigung nicht möglich' ?></title>
  <link rel="stylesheet" href="/transcom/beta/style.css">
</head>
<body>
  <main class="shell narrow">
    <a class="brand" href="/transcom/" aria-label="Zurück zur TransCom Startseite">
      <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
      <span>TransCom</span>
    </a>
    <section class="result-card">
      <?php if ($payload): ?>
        <p class="eyebrow"><span></span> E-Mail bestätigt</p>
        <h1>Dein <?= beta_escape((string) $offer['label']) ?>-Download ist bereit.</h1>
        <p class="lead">TransCom <?= beta_escape((string) $offer['label']) ?> <?= beta_escape((string) $offer['version']) ?> für macOS auf Apple Silicon.</p>
        <a class="button" href="<?= beta_escape($downloadUrl) ?>" rel="nofollow noreferrer">TransCom <?= beta_escape((string) $offer['label']) ?> herunterladen <span aria-hidden="true">↓</span></a>
        <dl>
          <div><dt>Dateigröße</dt><dd><?= beta_escape((string) $offer['download_size']) ?></dd></div>
          <div><dt>SHA-256</dt><dd><code><?= beta_escape((string) $offer['sha256']) ?></code></dd></div>
        </dl>
        <p class="fineprint">Der persönliche Downloadlink ist 6 Stunden gültig und unterstützt das Fortsetzen des Downloads. Nicht signierter und nicht notarisierter Build. Bitte per Rechtsklick → Öffnen starten. Nicht für sicherheitskritische Produktion.</p>
      <?php else: ?>
        <p class="kicker error">Link nicht verfügbar</p>
        <h1>Bitte neuen Link anfordern.</h1>
        <p class="lead"><?= beta_escape($error) ?></p>
        <a class="button secondary" href="/transcom/beta/">Neuen Bestätigungslink anfordern</a>
      <?php endif; ?>
    </section>
  </main>
</body>
</html>
