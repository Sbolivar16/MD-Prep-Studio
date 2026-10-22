#!/bin/bash
# Builds the Windows installer.  Run from anywhere; needs NSIS (makensis) and python3.
#   windows/build_windows.sh en                 -> English installer
#   windows/build_windows.sh es                 -> Spanish installer
#   windows/build_windows.sh es my_config.json  -> Spanish installer with your own defaults (cluster, language)
set -e
L="${1:-en}"; CFG="${2:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
B="$ROOT/windows/build/$L"
rm -rf "$B"; mkdir -p "$B/app/.streamlit"
cp "$ROOT/app.py" "$ROOT/mdprep.py" "$ROOT/environment.yml" "$B/app/"
cp "$ROOT/.streamlit/config.toml" "$B/app/.streamlit/"
if [ -n "$CFG" ]; then
  cp "$CFG" "$B/app/mdprep_config.json"
else
  python3 -c "import json,sys; c=json.load(open(sys.argv[1])); c['lang']=sys.argv[2]; json.dump(c, open(sys.argv[3],'w'), indent=2, ensure_ascii=False)" \
    "$ROOT/mdprep_config.json" "$L" "$B/app/mdprep_config.json"
fi
# Windows PowerShell 5.1 needs a UTF-8 BOM to read accents; .cmd/.txt files use CRLF; the WSL script must keep LF
printf '\xef\xbb\xbf' > "$B/install_windows.ps1"; sed 's/\r$//; s/$/\r/' "$ROOT/windows/install_windows.ps1" >> "$B/install_windows.ps1"
sed 's/\r$//' "$ROOT/windows/wsl_setup.sh" > "$B/wsl_setup.sh"
sed 's/\r$//; s/$/\r/' "$ROOT/LICENSE" > "$B/LICENSE.txt"
cp "$ROOT/windows/setup.nsi" "$ROOT/windows/mdprep.ico" "$B/"
VER=$(python3 -c "import re,sys; print(re.search(r'APP_VERSION = \"(.*?)\"', open(sys.argv[1]).read()).group(1))" "$ROOT/mdprep.py")
EXTRA=""; [ "$L" = "es" ] && EXTRA="-DLANG_ES"
(cd "$B" && makensis -V2 -DVERSION="$VER" $EXTRA setup.nsi)
mv "$B"/MD-Prep_Studio_*.exe "$ROOT/windows/build/"
ls -la "$ROOT/windows/build/"*.exe
