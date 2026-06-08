#!/usr/bin/env bash
# Install slackdump binary from GitHub releases.
#
# Usage:
#   ./scripts/install_slackdump.sh              # install latest to /usr/local/bin
#   ./scripts/install_slackdump.sh --user       # install to ~/.local/bin (no root)
#   ./scripts/install_slackdump.sh --version 4.2.0  # install specific version
#
# After install, authenticate with:
#   slackdump login

set -euo pipefail

REPO="rusq/slackdump"
VERSION=""
INSTALL_DIR="/usr/local/bin"
USE_SUDO="true"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)
            INSTALL_DIR="${HOME}/.local/bin"
            USE_SUDO="false"
            shift
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--user] [--version VERSION]"
            echo ""
            echo "Options:"
            echo "  --user       Install to ~/.local/bin instead of /usr/local/bin"
            echo "  --version    Install a specific version (default: latest)"
            echo ""
            echo "After install, authenticate with: slackdump login"
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
    x86_64|amd64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *)
        echo "Unsupported architecture: $ARCH" >&2
        exit 1
        ;;
esac

case "$OS" in
    linux|darwin) ;;
    *)
        echo "Unsupported OS: $OS" >&2
        exit 1
        ;;
esac

if [[ -z "$VERSION" ]]; then
    echo "Fetching latest release version..."
    VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | \
        grep '"tag_name"' | sed -E 's/.*"v?([^"]+)".*/\1/')
    if [[ -z "$VERSION" ]]; then
        echo "Failed to determine latest version. Use --version to specify." >&2
        exit 1
    fi
fi

echo "Installing slackdump v${VERSION} (${OS}/${ARCH})"

ARCHIVE_NAME="slackdump_${OS}_${ARCH}.tar.gz"
if [[ "$OS" == "darwin" ]]; then
    ARCHIVE_NAME="slackdump_macOS_${ARCH}.tar.gz"
fi

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

if [[ "$USE_SUDO" == "true" ]] && [[ ! -w "$INSTALL_DIR" ]]; then
    echo "Installing to ${INSTALL_DIR} (requires sudo)..."
    sudo install -m 755 "${TMPDIR}/slackdump" "${INSTALL_DIR}/slackdump"
else
    install -m 755 "${TMPDIR}/slackdump" "${INSTALL_DIR}/slackdump"
fi

echo ""
echo "Installed: ${INSTALL_DIR}/slackdump"
"${INSTALL_DIR}/slackdump" version
echo ""
echo "Next steps:"
echo "  1. Run: slackdump login"
echo "     (Opens browser — log in with your Red Hat SSO credentials)"
echo "  2. Verify: python3 scripts/slack_ops.py verify-auth"
