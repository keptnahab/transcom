#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(node -p "require('$ROOT/package.json').version")"
ARCH="$(node -p 'process.arch')"
EDITIONS="${TRANSCOM_EDITIONS:-starter full}"
SIGNING_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/transcom-signing.XXXXXX")"

cleanup() {
  rm -rf "$SIGNING_ROOT"
}
trap cleanup EXIT

cd "$ROOT"
npm run build:renderer
npm run build:backend
npm run stage:models

for EDITION in $EDITIONS; do
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
  npx electron-builder --mac dir \
    --config.productName="$PRODUCT_NAME" \
    --config.appId="$APP_ID" \
    --config.directories.output="dist/$EDITION"

  APP_PATH="$ROOT/dist/$EDITION/mac-$ARCH/$PRODUCT_NAME.app"
  STAGED_DIR="$SIGNING_ROOT/$EDITION"
  STAGED_APP="$STAGED_DIR/$PRODUCT_NAME.app"
  ARTIFACT_NAME="TransCom-$LABEL-$VERSION-$ARCH-mac.zip"
  STAGED_ZIP="$STAGED_DIR/$ARTIFACT_NAME"
  VERIFY_DIR="$STAGED_DIR/verify"

  mkdir -p "$STAGED_DIR" "$VERIFY_DIR"

  # Dropbox/File Provider adds Finder metadata that invalidates macOS bundle
  # signatures. Stage without extended attributes, then sign the final bundle.
  ditto --norsrc --noextattr --noqtn --noacl --clone "$APP_PATH" "$STAGED_APP"
  xattr -cr "$STAGED_APP"
  codesign --force --deep --sign - "$STAGED_APP"
  codesign --verify --deep --strict --verbose=2 "$STAGED_APP"

  ditto -c -k --norsrc --noextattr --noqtn --noacl --keepParent \
    "$STAGED_APP" "$STAGED_ZIP"

  # Verify the downloadable artifact, not only the staging directory.
  ditto -x -k "$STAGED_ZIP" "$VERIFY_DIR"
  codesign --verify --deep --strict --verbose=2 \
    "$VERIFY_DIR/$PRODUCT_NAME.app"

  mv -f "$STAGED_ZIP" "$ROOT/dist/$EDITION/$ARTIFACT_NAME"
done

echo "Beta/Full builds: $ROOT/dist/starter and $ROOT/dist/full"
