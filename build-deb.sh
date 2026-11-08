#!/usr/bin/env bash
# Builds dist/tux-software-suite_<version>_all.deb, a package Ubuntu/Debian users can double-click to install.
set -euo pipefail

VERSION="1.14.0"
HERE="$(cd "$(dirname "$0")" && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"

install -Dm755 "$HERE/tux_software_suite.py" "$STAGE/usr/share/tux-software-suite/tux_software_suite.py"
install -Dm644 "$HERE/tux-software-suite.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/tux-software-suite.svg"

install -Dm755 /dev/stdin "$STAGE/usr/bin/tux-software-suite" <<'EOF'
#!/bin/sh
exec python3 /usr/share/tux-software-suite/tux_software_suite.py "$@"
EOF

install -Dm644 /dev/stdin "$STAGE/usr/share/applications/tux-software-suite.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Tux Software Suite
Comment=Install dev tools one at a time
Exec=tux-software-suite
Icon=tux-software-suite
StartupWMClass=local.tuxsoftwaresuite
Terminal=false
Categories=Development;
EOF

mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: tux-software-suite
Provides: dev-installer
Conflicts: dev-installer
Replaces: dev-installer
Version: $VERSION
Section: devel
Priority: optional
Architecture: all
Depends: python3, python3-gi, gir1.2-gtk-4.0, policykit-1 | pkexec, curl, software-properties-common
Maintainer: Ryan <rysplumbingandai1995@gmail.com>
Description: Ninite-style panel for installing Linux software
 One-click buttons for developer tools, AI coding agents, everyday apps and gaming software
 on Ubuntu/Debian, each installed from an official source.
EOF

mkdir -p "$HERE/dist"
dpkg-deb --build --root-owner-group "$STAGE" "$HERE/dist/tux-software-suite_${VERSION}_all.deb"
