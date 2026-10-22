#!/bin/bash
# MD-Prep Studio — setup inside the WSL distribution "MD-Prep" (runs as root).
# Called by install_windows.ps1:  wsl -d MD-Prep -u root -e bash <this script> <installer folder as /mnt/... path>
# GROMACS and AmberTools have no native Windows builds, so the platform runs in this small Linux system.
set -e
SRC="$1"
ROOT=/opt/mdprep
CONDA_DIR=/opt/miniforge
ENV="$CONDA_DIR/envs/md-prep"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

echo "== MD-Prep WSL setup: $(date)"
if [ ! -x "$CONDA_DIR/bin/conda" ]; then
  echo "== Installing Miniforge in $CONDA_DIR"
  bash "$SRC/Miniforge3-Linux-x86_64.sh" -b -p "$CONDA_DIR"
fi

echo "== Copying the application"
mkdir -p "$ROOT/app"
cp -r "$SRC/app/." "$ROOT/app/"

echo "== Creating the md-prep environment (GROMACS, AmberTools, ACPYPE, PDBFixer, PDB2PQR, RDKit...)"
if [ -x "$ENV/bin/python" ]; then
  "$CONDA_DIR/bin/conda" env update -n md-prep -f "$ROOT/app/environment.yml" --prune
else
  "$CONDA_DIR/bin/conda" env create -n md-prep -f "$ROOT/app/environment.yml"
fi
"$CONDA_DIR/bin/conda" clean -a -y >/dev/null 2>&1 || true

PORT="${MDPREP_PORT:-8642}"
cat > "$ROOT/start.sh" <<EOF
#!/bin/bash
# Started from Windows by MD-Prep.cmd / prepmd.cmd
export LANG=C.UTF-8 LC_ALL=C.UTF-8
cd "$ROOT/app"
mkdir -p "\$HOME/.streamlit"
[ -f "\$HOME/.streamlit/credentials.toml" ] || printf '[general]\nemail = ""\n' > "\$HOME/.streamlit/credentials.toml"
# stop a previous instance (without procps, which Ubuntu Base does not include)
for p in /proc/[0-9]*; do
  if tr '\\0' ' ' < "\$p/cmdline" 2>/dev/null | grep -q "streamlit run app.py"; then kill "\${p#/proc/}" 2>/dev/null; sleep 1; fi
done
exec "$ENV/bin/python" -m streamlit run app.py --server.headless true --server.port $PORT --server.address 0.0.0.0 \
     --browser.gatherUsageStats false
EOF
chmod +x "$ROOT/start.sh"

echo "== Checking the tools"
cd "$ROOT/app"
"$ENV/bin/python" -c "import mdprep, json; v = mdprep.versiones(); print(json.dumps(v, indent=1, ensure_ascii=False)); \
assert 'not' not in v['GROMACS (local)'] and 'no ' not in v['GROMACS (local)'], 'GROMACS missing'"
echo "== MD-Prep WSL setup finished OK"
