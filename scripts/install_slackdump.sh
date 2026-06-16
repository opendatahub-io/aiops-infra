#!/usr/bin/env bash
# Install slackdump binary from GitHub releases into .work/bin/ (project-local).
#
# Usage:
#   ./scripts/install_slackdump.sh                      # install latest to .work/bin/
#   ./scripts/install_slackdump.sh --version 4.4.0      # install specific version
#   ./scripts/install_slackdump.sh --install-dir /path  # custom directory
#
# After install, authenticate with:
#   .work/bin/slackdump login

set -euo pipefail

REPO="rusq/slackdump"
VERSION=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="${REPO_ROOT}/.work/bin"
USE_SUDO="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--install-dir DIR] [--version VERSION]"
            echo ""
            echo "Options:"
            echo "  --install-dir  Install directory (default: .work/bin/)"
            echo "  --version      Install a specific version (default: latest)"
            echo ""
            echo "After install, authenticate with: .work/bin/slackdump login"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$ARCH" in
    x86_64|amd64) ARCH="x86_64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    i386|i686) ARCH="i386" ;;
    *)
        echo "Unsupported architecture: $ARCH" >&2
        exit 1
        ;;
esac

case "$OS" in
    linux) OS_LABEL="Linux" ;;
    darwin) OS_LABEL="macOS" ;;
    *)
        echo "Unsupported OS: $OS" >&2
        exit 1
        ;;
esac

CURL_AUTH_HEADER=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    CURL_AUTH_HEADER=(-H "Authorization: token ${GITHUB_TOKEN}")
elif [[ -n "${GH_TOKEN:-}" ]]; then
    CURL_AUTH_HEADER=(-H "Authorization: token ${GH_TOKEN}")
fi

if [[ -z "$VERSION" ]]; then
    echo "Fetching latest release version..."
    VERSION=$(curl -fsSL "${CURL_AUTH_HEADER[@]}" "https://api.github.com/repos/${REPO}/releases/latest" | \
        grep '"tag_name"' | sed -E 's/.*"v?([^"]+)".*/\1/')
    if [[ -z "$VERSION" ]]; then
        echo "Failed to determine latest version. Use --version to specify." >&2
        exit 1
    fi
fi

echo "Installing slackdump v${VERSION} (${OS_LABEL}/${ARCH})"

ARCHIVE_NAME="slackdump_${OS_LABEL}_${ARCH}.tar.gz"

DOWNLOAD_URL="https://github.com/${REPO}/releases/download/v${VERSION}/${ARCHIVE_NAME}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "Downloading ${DOWNLOAD_URL}..."
if ! curl -fsSL -o "${TMPDIR}/${ARCHIVE_NAME}" "$DOWNLOAD_URL"; then
    echo "Download failed. Check version and network connectivity." >&2
    echo "Available releases: https://github.com/${REPO}/releases" >&2
    exit 1
fi

echo "Extracting..."
tar -xzf "${TMPDIR}/${ARCHIVE_NAME}" -C "$TMPDIR"

mkdir -p "$INSTALL_DIR"

install -m 755 "${TMPDIR}/slackdump" "${INSTALL_DIR}/slackdump"

echo ""
echo "Installed: ${INSTALL_DIR}/slackdump"
"${INSTALL_DIR}/slackdump" version
echo ""
echo "Next steps — authenticate with one of:"
echo ""
echo "  Method A (universal — works in WSL, Docker, CI, headless):"
echo "    1. Open https://redhat-internal.slack.com in your browser"
echo "    2. Extract token (DevTools Console):"
echo "       JSON.parse(localStorage.localConfig_v2).teams[document.location.pathname.match(/^\\/client\\/([A-Z0-9]+)/)[1]].token"
echo "    3. Extract cookie: DevTools → Application → Cookies → 'd' cookie value"
echo "    4. Write to .work/.slack-secrets:"
echo "       SLACK_TOKEN=xoxc-..."
echo "       SLACK_COOKIE=xoxd-..."
echo "    5. Run: slackdump workspace import .work/.slack-secrets && rm -f .work/.slack-secrets"
echo ""
echo "  Method B (requires local Chromium browser):"
echo "    Run: slackdump workspace new https://redhat-internal.slack.com"
echo ""
echo "  Verify: python3 scripts/slack_ops.py verify-auth"
