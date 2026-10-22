#!/bin/sh
cd "$(dirname "$0")"
. ./_find_conda.sh || exit 1
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then mkdir -p "$HOME/.streamlit"; printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"; fi
conda run --no-capture-output -n md-prep streamlit run app.py "$@"
