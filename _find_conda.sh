# Finds conda even when the shell does not have it in PATH (e.g. double-click on macOS)
if ! command -v conda >/dev/null 2>&1; then
  for d in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/mambaforge" \
           "/opt/miniforge3" "/opt/miniconda3" "/opt/anaconda3" "/opt/homebrew/Caskroom/miniforge/base" \
           "/opt/homebrew/Caskroom/miniconda/base" "/usr/local/Caskroom/miniforge/base" "/usr/local/Caskroom/miniconda/base"; do
    if [ -x "$d/bin/conda" ]; then PATH="$d/bin:$d/condabin:$PATH"; export PATH; break; fi
  done
fi
if ! command -v conda >/dev/null 2>&1; then
  echo "conda was not found. Run «Install MD-Prep.command» (or sh install.sh) first."
  return 1 2>/dev/null || exit 1
fi
