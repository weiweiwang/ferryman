#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
LOCAL_RELEASE_ENV="$ROOT_DIR/.env.release.local"

if [[ -f "$LOCAL_RELEASE_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$LOCAL_RELEASE_ENV"
  set +a
fi

APP_NAME="Ferryman.app"
APP_PATH="$ROOT_DIR/src-tauri/target/release/bundle/macos/$APP_NAME"
BACKEND_SIDECAR="$APP_PATH/Contents/Resources/gen/backend-sidecar"
PLAYWRIGHT_NODE="$BACKEND_SIDECAR/_internal/playwright/driver/node"
PLAYWRIGHT_CLI="$BACKEND_SIDECAR/_internal/playwright/driver/package/cli.js"
PLAYWRIGHT_NODE_ENTITLEMENTS="$ROOT_DIR/src-tauri/entitlements/playwright-node.plist"
DMG_DIR="$ROOT_DIR/src-tauri/target/release/bundle/dmg"
VERSION="$(python3 -c 'import json, pathlib; print(json.loads(pathlib.Path("src-tauri/tauri.conf.json").read_text())["version"])')"
BUILD_TIMESTAMP="${BUILD_TIMESTAMP:-$(date +%m%d-%H%M)}"
ARCH="$(uname -m)"
DMG_NAME="Ferryman_${VERSION}_${BUILD_TIMESTAMP}_${ARCH}.dmg"
DMG_PATH="$DMG_DIR/$DMG_NAME"
VOLUME_NAME="Ferryman"
DIST_DIR="$PROJECT_ROOT/dist"
SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
NOTARY_ISSUER_ID="${APPLE_NOTARY_ISSUER_ID:-}"
NOTARY_KEY_ID="${APPLE_NOTARY_KEY_ID:-}"
NOTARY_KEY_PATH="${APPLE_NOTARY_KEY_PATH:-}"

if [[ -z "$NOTARY_KEY_PATH" && -n "$NOTARY_KEY_ID" ]]; then
  DEFAULT_NOTARY_KEY_PATH="$HOME/.private_keys/AuthKey_${NOTARY_KEY_ID}.p8"
  if [[ -f "$DEFAULT_NOTARY_KEY_PATH" ]]; then
    NOTARY_KEY_PATH="$DEFAULT_NOTARY_KEY_PATH"
  fi
fi

NOTARY_CONFIGURED=0
if [[ -n "$NOTARY_ISSUER_ID" || -n "$NOTARY_KEY_ID" || -n "$NOTARY_KEY_PATH" ]]; then
  if [[ -z "$SIGNING_IDENTITY" ]]; then
    echo "APPLE_SIGNING_IDENTITY is required when notarization is configured." >&2
    exit 1
  fi
  if [[ -z "$NOTARY_ISSUER_ID" || -z "$NOTARY_KEY_ID" || -z "$NOTARY_KEY_PATH" ]]; then
    echo "APPLE_NOTARY_ISSUER_ID, APPLE_NOTARY_KEY_ID, and APPLE_NOTARY_KEY_PATH must be set together." >&2
    exit 1
  fi
  if [[ ! -f "$NOTARY_KEY_PATH" ]]; then
    echo "Notary API key not found at $NOTARY_KEY_PATH" >&2
    exit 1
  fi
  NOTARY_CONFIGURED=1
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found at $APP_PATH" >&2
  exit 1
fi

if [[ ! -d "$BACKEND_SIDECAR" ]]; then
  echo "Backend sidecar bundle not found at $BACKEND_SIDECAR" >&2
  exit 1
fi

STEALTH_JS="$APP_PATH/Contents/Resources/gen/backend-sidecar/_internal/playwright_stealth/js/generate.magic.arrays.js"
PYINSTALLER_WARN_FILE="$ROOT_DIR/src-tauri/gen/build/work/ferryman_backend/warn-ferryman_backend.txt"

if [[ -f "$PYINSTALLER_WARN_FILE" ]] && grep -q "playwright.sync_api" "$PYINSTALLER_WARN_FILE"; then
  echo "PyInstaller reported missing playwright.sync_api in $PYINSTALLER_WARN_FILE" >&2
  exit 1
fi

if [[ ! -f "$STEALTH_JS" ]]; then
  echo "Missing packaged playwright_stealth JS resource at $STEALTH_JS" >&2
  exit 1
fi

if [[ ! -x "$PLAYWRIGHT_NODE" ]]; then
  echo "Missing executable Playwright node driver at $PLAYWRIGHT_NODE" >&2
  exit 1
fi

if [[ ! -f "$PLAYWRIGHT_CLI" ]]; then
  echo "Missing Playwright driver CLI at $PLAYWRIGHT_CLI" >&2
  exit 1
fi

PACKAGED_CHROMIUM="$(find "$APP_PATH" -type d \( -name "chromium-*" -o -name "chromium_headless_shell-*" -o -name "chrome-*" \) -print -quit)"
if [[ -n "$PACKAGED_CHROMIUM" ]]; then
  echo "Unexpected bundled Chromium payload found at $PACKAGED_CHROMIUM" >&2
  exit 1
fi

sign_macho_payloads() {
  local root="$1"
  echo "Signing Mach-O payloads under $root"
  while IFS= read -r candidate; do
    if file "$candidate" | grep -q "Mach-O"; then
      if [[ "$candidate" == "$PLAYWRIGHT_NODE" ]]; then
        codesign --force --options runtime --timestamp --entitlements "$PLAYWRIGHT_NODE_ENTITLEMENTS" --sign "$SIGNING_IDENTITY" "$candidate"
      else
        codesign --force --options runtime --timestamp --sign "$SIGNING_IDENTITY" "$candidate"
      fi
    fi
  done < <(find "$root" -type f)
}

if [[ -n "$SIGNING_IDENTITY" ]]; then
  echo "Signing app with Developer ID identity: $SIGNING_IDENTITY"
  sign_macho_payloads "$BACKEND_SIDECAR"
  codesign --force --deep --options runtime --timestamp --sign "$SIGNING_IDENTITY" "$APP_PATH"
else
  # Tauri's unsigned app bundle can contain an ad-hoc executable signature that
  # does not seal bundled resources. Re-sign locally so macOS accepts the copied
  # app bundle from the DMG during install smoke tests.
  echo "APPLE_SIGNING_IDENTITY is not set; using ad-hoc signing for local smoke tests."
  codesign --force --deep --sign - "$APP_PATH"
fi
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
"$PLAYWRIGHT_NODE" "$PLAYWRIGHT_CLI" --version >/dev/null

mkdir -p "$DMG_DIR"
TMP_DIR="$(mktemp -d /tmp/ferryman-dmg.XXXXXX)"
MOUNT_DIR=""
cleanup() {
  if [[ -n "$MOUNT_DIR" && -d "$MOUNT_DIR" ]]; then
    hdiutil detach "$MOUNT_DIR" >/dev/null 2>&1 || true
    rmdir "$MOUNT_DIR" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

cp -R "$APP_PATH" "$TMP_DIR/$APP_NAME"
ln -s /Applications "$TMP_DIR/Applications"
rm -f "$DMG_PATH"

hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$TMP_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

if [[ -n "$SIGNING_IDENTITY" ]]; then
  echo "Signing DMG with Developer ID identity: $SIGNING_IDENTITY"
  codesign --force --timestamp --sign "$SIGNING_IDENTITY" "$DMG_PATH"
  codesign --verify --verbose=2 "$DMG_PATH"
fi

if [[ "$NOTARY_CONFIGURED" -eq 1 ]]; then
  echo "Submitting DMG for Apple notarization."
  NOTARY_RESULT="$(xcrun notarytool submit "$DMG_PATH" \
    --key "$NOTARY_KEY_PATH" \
    --key-id "$NOTARY_KEY_ID" \
    --issuer "$NOTARY_ISSUER_ID" \
    --wait 2>&1)"
  echo "$NOTARY_RESULT"
  if [[ "$NOTARY_RESULT" != *"status: Accepted"* ]]; then
    echo "Apple notarization did not return Accepted." >&2
    exit 1
  fi
  xcrun stapler staple "$DMG_PATH"
  xcrun stapler validate "$DMG_PATH"
fi

hdiutil verify "$DMG_PATH"

MOUNT_DIR="$(mktemp -d /tmp/ferryman-dmg-mount.XXXXXX)"
hdiutil attach "$DMG_PATH" -mountpoint "$MOUNT_DIR" -nobrowse -readonly
if [[ ! -d "$MOUNT_DIR/$APP_NAME" ]]; then
  echo "Mounted DMG does not contain $APP_NAME" >&2
  exit 1
fi
hdiutil detach "$MOUNT_DIR"
rmdir "$MOUNT_DIR"
MOUNT_DIR=""

if [[ "$NOTARY_CONFIGURED" -eq 1 ]]; then
  spctl --assess --type open --context context:primary-signature --verbose "$DMG_PATH"
fi

mkdir -p "$DIST_DIR"
rm -rf "$DIST_DIR/$APP_NAME"
cp -R "$APP_PATH" "$DIST_DIR/$APP_NAME"
cp -f "$DMG_PATH" "$DIST_DIR/$DMG_NAME"

echo "Created DMG at $DMG_PATH"
echo "Synced app bundle to $DIST_DIR/$APP_NAME"
echo "Synced DMG to $DIST_DIR/$DMG_NAME"
