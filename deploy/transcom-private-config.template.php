<?php
return [
    'secret' => '__SECRET__',
    'storage_dir' => __DIR__ . '/data',
    'version' => '0.2.0-beta.1',
    // Ausschließlich einen R2-Token mit Leserechten für den Bucket transcom verwenden.
    'r2_account_id' => '9f1287d71ea12b31e411a2dbe14ce956',
    'r2_access_key_id' => '__R2_READ_ACCESS_KEY_ID__',
    'r2_secret_access_key' => '__R2_READ_SECRET_ACCESS_KEY__',
    'r2_bucket' => 'transcom',
    'r2_object_key' => 'releases/0.2.0-beta.1/TransCom-Beta-0.2.0-beta.1-arm64-mac.zip',
    'download_ttl' => 21600,
    'download_size' => '2,0 GB',
    'sha256' => '8cd33adefae44975ff5a1225d7ac2413376c811e70085dd145c1ac83fa412493',
];
