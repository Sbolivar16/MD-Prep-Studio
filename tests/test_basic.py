"""Quick checks that do not need GROMACS (run with:  python -m pytest tests)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mdprep as M  # noqa: E402


def test_languages():
    M.set_lang("es"); assert M.nombres()["continuar"] == "continuar.sh"
    M.set_lang("en"); assert M.nombres()["continuar"] == "continue.sh"


def test_slurm_script():
    s = M.script_slurm({"job_name": "test", "time": "24:00:00"}, incluir_npt=True)
    assert "#SBATCH --job-name=test" in s and "step4.2_equilibration.tpr" in s and "-maxh" in s
    c = M.script_slurm({"job_name": "test", "time": "24:00:00"}, continuacion=True)
    assert "-cpi step5.cpt" in c


def test_mdp(tmp_path):
    n = M.mdp_produccion(tmp_path / "p.mdp", ns=250)
    assert n == 125_000_000 and "C-rescale" in (tmp_path / "p.mdp").read_text()


def test_references():
    bib = M.bibtex()
    for r in M.REFERENCIAS:
        assert r["key"] in bib and r["doi"]
    assert "(Abraham et al., 2015)" == M.cita("Abraham2015")
