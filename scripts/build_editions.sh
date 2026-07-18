#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(node -p "require('$ROOT/package.json').version")"

cd "$ROOT"
npm run build:renderer
npm run build:backend
npm run stage:models

for EDITION in starter full; do
  "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/write_edition_manifest.py" "$EDITION"
  if [ "$EDITION" = "starter" ]; then
    PRODUCT_NAME="TransCom Beta"
    APP_ID="com.transcom.beta"
    LABEL="Beta"
  else
    PRODUCT_NAME="TransCom Full"
    APP_ID="com.transcom.full"
    LABEL="Full"
  fi
  npx electron-builder --mac dir zip \
    --config.productName="$PRODUCT_NAME" \
    --config.appId="$APP_ID" \
    --config.directories.output="dist/$EDITION" \
    --config.artifactName="TransCom-$LABEL-$VERSION-\${arch}-mac.\${ext}"
done

echo "Beta/Full builds: $ROOT/dist/starter and $ROOT/dist/full"
