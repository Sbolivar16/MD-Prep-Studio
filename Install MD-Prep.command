#!/bin/sh
# macOS: double-click to install (first time only)
cd "$(dirname "$0")"
xattr -dr com.apple.quarantine . 2>/dev/null
chmod +x *.sh *.command 2>/dev/null
sh ./install.sh 2>&1 | tee "$HOME/md-prep_install.log"
echo; echo "You can close this window."; read -r _
