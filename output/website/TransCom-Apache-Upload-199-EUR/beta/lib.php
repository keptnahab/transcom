<?php
declare(strict_types=1);

const TRANSCOM_ROOT_URL = 'https://amazinglighting.design/transcom';

function beta_config(): array
{
    static $config;
    if (is_array($config)) {
        return $config;
    }

    $path = dirname(__DIR__, 2) . '/transcom-private/config.php';
    if (!is_file($path)) {
        throw new RuntimeException('Beta-Konfiguration fehlt.');
    }

    $loaded = require $path;
    if (!is_array($loaded) || empty($loaded['secret']) || empty($loaded['storage_dir'])) {
        throw new RuntimeException('Beta-Konfiguration ist ungültig.');
    }

    $config = $loaded;
    return $config;
}

function beta_headers(): void
{
    header('X-Content-Type-Options: nosniff');
    header('Referrer-Policy: no-referrer');
    header('X-Frame-Options: DENY');
    header("Permissions-Policy: camera=(), microphone=(), geolocation=()");
    header("Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'");
    header('Cache-Control: no-store, max-age=0');
}

function beta_escape(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function beta_r2_presigned_download_url(?int $ttl = null): string
{
    $config = beta_config();
    $accountId = strtolower(trim((string) ($config['r2_account_id'] ?? '')));
    $accessKeyId = trim((string) ($config['r2_access_key_id'] ?? ''));
    $secretAccessKey = (string) ($config['r2_secret_access_key'] ?? '');
    $bucket = trim((string) ($config['r2_bucket'] ?? ''));
    $objectKey = ltrim((string) ($config['r2_object_key'] ?? ''), '/');

    if (!preg_match('/\A[a-f0-9]{32}\z/', $accountId)
        || $accessKeyId === ''
        || $secretAccessKey === ''
        || !preg_match('/\A[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\z/', $bucket)
        || $objectKey === '') {
        throw new RuntimeException('R2-Download-Konfiguration ist unvollständig.');
    }

    $expires = $ttl ?? (int) ($config['download_ttl'] ?? 21600);
    $expires = max(60, min(604800, $expires));
    $host = $accountId . '.r2.cloudflarestorage.com';
    $pathParts = array_merge([$bucket], explode('/', $objectKey));
    $canonicalUri = '/' . implode('/', array_map('rawurlencode', $pathParts));
    $amzDate = gmdate('Ymd\THis\Z');
    $shortDate = substr($amzDate, 0, 8);
    $scope = $shortDate . '/auto/s3/aws4_request';
    $query = [
        'X-Amz-Algorithm' => 'AWS4-HMAC-SHA256',
        'X-Amz-Credential' => $accessKeyId . '/' . $scope,
        'X-Amz-Date' => $amzDate,
        'X-Amz-Expires' => (string) $expires,
        'X-Amz-SignedHeaders' => 'host',
    ];
    ksort($query, SORT_STRING);

    $queryParts = [];
    foreach ($query as $key => $value) {
        $queryParts[] = rawurlencode($key) . '=' . rawurlencode($value);
    }
    $canonicalQuery = implode('&', $queryParts);
    $canonicalHeaders = 'host:' . $host . "\n";
    $canonicalRequest = "GET\n"
        . $canonicalUri . "\n"
        . $canonicalQuery . "\n"
        . $canonicalHeaders . "\n"
        . "host\n"
        . 'UNSIGNED-PAYLOAD';
    $stringToSign = "AWS4-HMAC-SHA256\n"
        . $amzDate . "\n"
        . $scope . "\n"
        . hash('sha256', $canonicalRequest);

    $dateKey = hash_hmac('sha256', $shortDate, 'AWS4' . $secretAccessKey, true);
    $regionKey = hash_hmac('sha256', 'auto', $dateKey, true);
    $serviceKey = hash_hmac('sha256', 's3', $regionKey, true);
    $signingKey = hash_hmac('sha256', 'aws4_request', $serviceKey, true);
    $signature = hash_hmac('sha256', $stringToSign, $signingKey);

    return 'https://' . $host . $canonicalUri . '?' . $canonicalQuery
        . '&X-Amz-Signature=' . $signature;
}

function beta_storage_dir(string $child = ''): string
{
    $base = rtrim((string) beta_config()['storage_dir'], '/');
    return $child === '' ? $base : $base . '/' . ltrim($child, '/');
}

function beta_ensure_storage(): void
{
    umask(0077);
    foreach (['', 'pending', 'rate-ip', 'rate-email'] as $child) {
        $path = beta_storage_dir($child);
        if (!is_dir($path) && !mkdir($path, 0700, true) && !is_dir($path)) {
            throw new RuntimeException('Speicherverzeichnis konnte nicht angelegt werden.');
        }
    }
}

function beta_form_fields(): array
{
    $started = time();
    $signature = hash_hmac('sha256', (string) $started, (string) beta_config()['secret']);
    return [$started, $signature];
}

function beta_form_is_valid(string $started, string $signature): bool
{
    if (!ctype_digit($started)) {
        return false;
    }

    $age = time() - (int) $started;
    if ($age < 2 || $age > 7200) {
        return false;
    }

    $expected = hash_hmac('sha256', $started, (string) beta_config()['secret']);
    return hash_equals($expected, $signature);
}

function beta_rate_limit(string $email): bool
{
    $config = beta_config();
    $secret = (string) $config['secret'];
    $now = time();
    $remote = (string) ($_SERVER['REMOTE_ADDR'] ?? 'unknown');
    $ipHash = hash_hmac('sha256', $remote, $secret);
    $emailHash = hash_hmac('sha256', strtolower($email), $secret);
    $checks = [
        [beta_storage_dir('rate-ip/' . $ipHash), 60],
        [beta_storage_dir('rate-email/' . $emailHash), 600],
    ];

    foreach ($checks as [$file, $seconds]) {
        if (is_file($file) && ($now - (int) filemtime($file)) < $seconds) {
            return false;
        }
    }

    foreach ($checks as [$file]) {
        touch($file);
        chmod($file, 0600);
    }
    return true;
}

function beta_cleanup_pending(): void
{
    $files = glob(beta_storage_dir('pending/*.json')) ?: [];
    $now = time();
    foreach (array_slice($files, 0, 50) as $file) {
        $payload = json_decode((string) @file_get_contents($file), true);
        if (!is_array($payload) || (int) ($payload['expires_at'] ?? 0) < $now) {
            @unlink($file);
        }
    }

    foreach (['rate-ip', 'rate-email'] as $folder) {
        foreach (array_slice(glob(beta_storage_dir($folder . '/*')) ?: [], 0, 50) as $file) {
            if ($now - (int) @filemtime($file) > 86400) {
                @unlink($file);
            }
        }
    }
}

function beta_create_request(string $email): string
{
    beta_ensure_storage();
    beta_cleanup_pending();

    $token = bin2hex(random_bytes(32));
    $tokenHash = hash('sha256', $token);
    $config = beta_config();
    $payload = [
        'email' => $email,
        'created_at' => time(),
        'expires_at' => time() + 86400,
        'version' => (string) $config['version'],
        'purpose' => 'beta-download',
    ];
    $file = beta_storage_dir('pending/' . $tokenHash . '.json');
    $json = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($json === false || file_put_contents($file, $json, LOCK_EX) === false) {
        throw new RuntimeException('Anfrage konnte nicht gespeichert werden.');
    }
    chmod($file, 0600);
    return $token;
}

function beta_send_confirmation(string $email, string $token): bool
{
    $config = beta_config();
    $confirmUrl = TRANSCOM_ROOT_URL . '/beta/confirm.php?token=' . rawurlencode($token);
    $subject = 'TransCom Beta-Download bestätigen';
    $message = "Hallo,\n\n"
        . "bitte bestätige deine E-Mail-Adresse, um den aktuellen TransCom-Beta-Download zu erhalten:\n\n"
        . $confirmUrl . "\n\n"
        . "Der Link ist 24 Stunden gültig. Die Adresse wird nur für den Beta-Download verwendet, nicht für Werbung oder Newsletter.\n\n"
        . "Falls du den Download nicht angefordert hast, ignoriere diese Nachricht.\n\n"
        . "TransCom Beta\n"
        . "https://amazinglighting.design/transcom/\n";
    $headers = implode("\r\n", [
        'MIME-Version: 1.0',
        'Content-Type: text/plain; charset=UTF-8',
        'From: TransCom Beta <info@amazinglighting.design>',
        'Reply-To: info@amazinglighting.design',
        'Auto-Submitted: auto-generated',
        'X-Auto-Response-Suppress: All',
    ]);

    return mail($email, $subject, $message, $headers, '-f info@amazinglighting.design');
}

function beta_remove_request(string $token): void
{
    $file = beta_storage_dir('pending/' . hash('sha256', $token) . '.json');
    if (is_file($file)) {
        @unlink($file);
    }
}

function beta_confirm_request(string $token): ?array
{
    if (!preg_match('/\A[a-f0-9]{64}\z/', $token)) {
        return null;
    }

    beta_ensure_storage();
    $file = beta_storage_dir('pending/' . hash('sha256', $token) . '.json');
    if (!is_file($file)) {
        return null;
    }

    $payload = json_decode((string) file_get_contents($file), true);
    if (!is_array($payload) || (int) ($payload['expires_at'] ?? 0) < time()) {
        @unlink($file);
        return null;
    }

    $email = (string) ($payload['email'] ?? '');
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        @unlink($file);
        return null;
    }

    $csv = beta_storage_dir('confirmed.csv');
    $handle = fopen($csv, 'ab');
    if ($handle === false) {
        throw new RuntimeException('Bestätigung konnte nicht gespeichert werden.');
    }
    if (flock($handle, LOCK_EX)) {
        fputcsv($handle, [gmdate('c'), $email, (string) ($payload['version'] ?? ''), 'beta-download'], ',', '"', '\\');
        fflush($handle);
        flock($handle, LOCK_UN);
    }
    fclose($handle);
    chmod($csv, 0600);
    @unlink($file);

    return $payload;
}
