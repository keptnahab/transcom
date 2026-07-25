#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(node -p "require('$ROOT/package.json').version")"
REQUESTED_RELEASE="${1:-beta}"
case "$REQUESTED_RELEASE" in
  beta)
    DEFAULT_FILE="$ROOT/dist/starter/TransCom-Beta-$VERSION-arm64-mac.zip"
    ;;
  full)
    DEFAULT_FILE="$ROOT/dist/full/TransCom-Full-$VERSION-arm64-mac.zip"
    ;;
  *)
    DEFAULT_FILE="$REQUESTED_RELEASE"
    ;;
esac
SOURCE_FILE="$DEFAULT_FILE"
ACCOUNT_ID="9f1287d71ea12b31e411a2dbe14ce956"
BUCKET="transcom"
REMOTE="transcom_r2"
KEYCHAIN_ACCOUNT="transcom-r2-upload"
ACCESS_SERVICE="TransCom R2 Access Key ID"
SECRET_SERVICE="TransCom R2 Secret Access Key"

if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "Release-Datei nicht gefunden: $SOURCE_FILE" >&2
  exit 1
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "rclone fehlt. Bitte zuerst 'brew install rclone' ausführen." >&2
  exit 1
fi

FILE_NAME="$(basename "$SOURCE_FILE")"
if [[ "$FILE_NAME" =~ ^TransCom-(Beta|Full)-(.*)-arm64-mac\.zip$ ]]; then
  RELEASE_LABEL="${BASH_REMATCH[1]}"
  FILE_VERSION="${BASH_REMATCH[2]}"
else
  echo "Unerwarteter Release-Dateiname: $FILE_NAME" >&2
  exit 1
fi

export RCLONE_CONFIG_TRANSCOM_R2_TYPE="s3"
export RCLONE_CONFIG_TRANSCOM_R2_PROVIDER="Cloudflare"
export RCLONE_CONFIG_TRANSCOM_R2_ENDPOINT="https://${ACCOUNT_ID}.r2.cloudflarestorage.com"
export RCLONE_CONFIG_TRANSCOM_R2_ACL="private"
export RCLONE_CONFIG_TRANSCOM_R2_ACCESS_KEY_ID
export RCLONE_CONFIG_TRANSCOM_R2_SECRET_ACCESS_KEY
RCLONE_CONFIG_TRANSCOM_R2_ACCESS_KEY_ID="$(security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$ACCESS_SERVICE" -w)"
RCLONE_CONFIG_TRANSCOM_R2_SECRET_ACCESS_KEY="$(security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$SECRET_SERVICE" -w)"

OBJECT_KEY="releases/$FILE_VERSION/$FILE_NAME"
DESTINATION="$REMOTE:$BUCKET/$OBJECT_KEY"

echo "Lade TransCom $RELEASE_LABEL ($FILE_NAME) nach R2 hoch ..."
rclone copyto "$SOURCE_FILE" "$DESTINATION" \
  --s3-no-check-bucket \
  --s3-upload-cutoff 100Mi \
  --s3-chunk-size 100Mi \
  --transfers 1 \
  --progress

LOCAL_SIZE="$(stat -f '%z' "$SOURCE_FILE")"
REMOTE_SIZE="$(rclone size "$DESTINATION" --s3-no-check-bucket --json | sed -E 's/.*"bytes":([0-9]+).*/\1/')"
if [[ "$LOCAL_SIZE" != "$REMOTE_SIZE" ]]; then
  echo "Größenprüfung fehlgeschlagen: lokal $LOCAL_SIZE, R2 $REMOTE_SIZE" >&2
  exit 1
fi

echo "Upload vollständig: $OBJECT_KEY ($REMOTE_SIZE Bytes)"
echo "SHA-256 lokal:"
shasum -a 256 "$SOURCE_FILE"
