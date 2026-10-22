#!/bin/sh
# MD-Prep Studio installer (macOS / Linux). Installs Miniforge if conda is not available.
cd "$(dirname "$0")"
DIR="$(pwd)"
echo "=== MD-Prep Studio - installation ($(date)) ==="
if ! . ./_find_conda.sh 2>/dev/null; then
  echo "[1/4] conda not found: downloading Miniforge..."
  OS=$(uname -s); ARCH=$(uname -m)
  case "$OS" in Darwin) OSN=MacOSX ;; *) OSN=Linux ;; esac
  curl -fsSL "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-${OSN}-${ARCH}.sh" -o /tmp/miniforge.sh \
    || { echo "ERROR: Miniforge could not be downloaded. Check your internet connection."; exit 1; }
  bash /tmp/miniforge.sh -b -p "$HOME/miniforge3" || { echo "ERROR: Miniforge could not be installed."; exit 1; }
  rm -f /tmp/miniforge.sh
  . ./_find_conda.sh || exit 1
else
  echo "[1/4] Using conda: $(command -v conda)"
fi
echo "[2/4] Creating the md-prep environment (GROMACS, AmberTools, ACPYPE, PDBFixer, PDB2PQR, RDKit...). 5-15 minutes."
if conda env list | awk '{print $1}' | grep -qx md-prep; then
  conda env update -n md-prep -f environment.yml --prune || exit 1
else
  conda env create -n md-prep -f environment.yml || exit 1
fi
echo "[3/4] Checking the tools..."
conda run --no-capture-output -n md-prep python -c "import mdprep, json; print(json.dumps(mdprep.versiones(), indent=1, ensure_ascii=False))" || exit 1
echo "[4/4] Terminal command «prepmd»..."
case "$(uname -s)" in Darwin) RCS="$HOME/.zshrc $HOME/.bash_profile" ;; *) RCS="$HOME/.bashrc $HOME/.zshrc" ;; esac
FIRST=1
for RC in $RCS; do
  if [ -f "$RC" ] || [ $FIRST = 1 ]; then
    touch "$RC"
    grep -q "alias prepmd=" "$RC" || printf '\n# MD-Prep Studio\nalias prepmd='"'"'sh "%s/start.sh"'"'"'\n' "$DIR" >> "$RC"
  fi
  FIRST=0
done
echo ""
echo "Done. Open a NEW terminal window and type:  prepmd"
echo "(on macOS you can also double-click «Open MD-Prep.command»)"
