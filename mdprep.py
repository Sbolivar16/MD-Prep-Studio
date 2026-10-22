# -*- coding: utf-8 -*-
"""
MD-Prep Studio — protein–ligand system preparation for GROMACS
==============================================================
From a post-docking complex (PDB) to a solvated, neutralized system ready for an HPC cluster:
  protein : PDBFixer (missing atoms) → PDB2PQR/PROPKA (protonation at pH) → pdb2gmx (AMBER99SB-ILDN, TIP3P)
  ligand  : RDKit (chemistry + H) → ACPYPE/antechamber (GAFF2, AM1-BCC charges)
  system  : box (editconf) → TIP3P water (solvate) → 0.15 M NaCl or KCl + neutralization (genion) → SOLU/SOLV index
  output  : step3_input.gro, topol.top, index.ndx, step4.0/4.1/4.2/5 .mdp files and a SLURM script

The user interface and every generated text are available in English and Spanish (see mdprep_config.json).
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np

APP_NAME = "MD-Prep Studio"
APP_VERSION = "1.1.1"
APP_URL = "https://github.com/Sbolivar16/MD-Prep-Studio"

AGUAS = {"HOH", "WAT", "H2O", "DOD", "SOL", "TIP", "TIP3"}
IONES = {"NA", "K", "CL", "CA", "MG", "ZN", "MN", "FE", "CU", "CO", "NI", "CD", "HG", "IOD", "BR", "F", "LI", "SO4", "PO4"}
AA = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR",
      "TRP", "TYR", "VAL", "HID", "HIE", "HIP", "HSD", "HSE", "HSP", "CYX", "CYM", "ASH", "GLH", "LYN", "MSE", "SEC"}


# =====================================================================
# configuration and language
# =====================================================================
BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "mdprep_config.json"
SLURM_GENERICO = {
    "job_name": "MD_complex", "nodes": 1, "partition": "gpu", "ntasks": 8, "time": "48:00:00", "gpus": 1,
    "modules": "# Load GROMACS as your cluster requires, for example:\nmodule load GROMACS",
    "gpu_full": False, "maxh": True,
}


def cargar_config():
    cfg = {"lang": "en", "workdir": "", "slurm": dict(SLURM_GENERICO)}
    try:
        user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in user.items() if k != "slurm"})
        cfg["slurm"].update(user.get("slurm") or {})
    except Exception:
        pass
    if os.environ.get("MDPREP_LANG"):
        cfg["lang"] = os.environ["MDPREP_LANG"]
    if os.environ.get("MDPREP_WORKDIR"):
        cfg["workdir"] = os.environ["MDPREP_WORKDIR"]
    cfg["lang"] = "es" if str(cfg["lang"]).lower().startswith("es") else "en"
    return cfg


CONFIG = cargar_config()
LANG = CONFIG["lang"]
SLURM_PREDETERMINADO = CONFIG["slurm"]


def set_lang(lang):
    global LANG
    LANG = "es" if str(lang).lower().startswith("es") else "en"


def tr(es, en):
    """Return the text in the active language."""
    return es if LANG == "es" else en


def carpeta_trabajo():
    if CONFIG.get("workdir"):
        return Path(os.path.expanduser(CONFIG["workdir"]))
    return Path.home() / ("MD-Prep_sistemas" if CONFIG["lang"] == "es" else "MD-Prep_systems")


def nombres():
    """File names that depend on the language of the package."""
    return {
        "readme": tr("LEEME_simulacion.txt", "README_simulation.txt"),
        "metodos": tr("METODOS_y_CITAS.md", "METHODS_and_CITATIONS.md"),
        "bib": "references.bib",
        "continuar": tr("continuar.sh", "continue.sh"),
        "log": tr("preparacion.log", "preparation.log"),
        "resumen": tr("resumen_preparacion.json", "prep_summary.json"),
        "intermedios": tr("intermedios", "intermediate"),
        "out": tr("simulacion.log", "simulation.log"),
        "err": "error.log",
    }


# =====================================================================
# utilities
# =====================================================================
def env_bin():
    return Path(sys.executable).parent


def herramienta(*nombres_):
    for n in nombres_:
        p = shutil.which(n)
        if p:
            return p
        for cand in (env_bin() / n, env_bin() / (n + ".exe"), env_bin() / "Scripts" / (n + ".exe")):
            if cand.exists():
                return str(cand)
    return None


def GMX():
    g = herramienta("gmx", "gmx_mpi")
    if not g:
        raise RuntimeError(tr("No se encontró GROMACS (gmx). Ejecuta el instalador.", "GROMACS (gmx) was not found. Run the installer."))
    return g


def run(cmd, cwd, stdin=None, log=None, timeout=None, env=None):
    e = dict(os.environ); e.update(env or {})
    e.setdefault("GMX_MAXBACKUP", "-1")      # do not create #file.1# backups
    # always use the tools of this environment (without tleap in PATH, ACPYPE falls back to bundled binaries that fail)
    e["PATH"] = str(env_bin()) + os.pathsep + e.get("PATH", "")
    if (env_bin() / "tleap").exists() or (env_bin() / "antechamber").exists():
        e["AMBERHOME"] = str(env_bin().parent)
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd), input=stdin, text=True, capture_output=True,
                       timeout=timeout, env=e, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    if log is not None:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n$ {' '.join(map(str, cmd))}\n{out}\n")
    if p.returncode != 0:
        err = "\n".join(l for l in out.splitlines() if l.strip())[-2500:]
        raise RuntimeError(f"{tr('Falló', 'Failed')}: {Path(str(cmd[0])).name} {' '.join(map(str, cmd[1:3]))}\n{err}")
    return out


def versiones():
    v = {tr("plataforma", "platform"): f"{APP_NAME} {APP_VERSION}", "python": sys.version.split()[0]}
    try:
        out = subprocess.run([GMX(), "--version"], capture_output=True, text=True).stdout
        m = re.search(r"GROMACS version:\s*(\S+)", out); v["GROMACS (local)"] = m.group(1) if m else "?"
    except Exception:
        v["GROMACS (local)"] = tr("no instalado", "not installed")
    from importlib.metadata import version as _v
    for pkg in ["acpype", "pdbfixer", "openmm", "pdb2pqr", "propka", "rdkit"]:
        try:
            v[pkg] = _v(pkg)
        except Exception:
            v[pkg] = "n/a"
    try:
        o = subprocess.run([herramienta("obabel"), "-V"], capture_output=True, text=True).stdout
        v["openbabel"] = (re.search(r"Open Babel\s+(\S+)", o) or [None, "?"])[1]
    except Exception:
        v["openbabel"] = "n/a"
    a = herramienta("antechamber")
    v["AmberTools (antechamber)"] = tr("instalado", "installed") if a else tr("no instalado", "not installed")
    return v


# =====================================================================
# reading the complex
# =====================================================================
def residuos_hetero(pdb):
    """HETATM residues (ligand candidates) and protein chains."""
    het, cadenas = {}, {}
    for l in open(pdb, errors="ignore"):
        if not l.startswith(("ATOM  ", "HETATM")):
            continue
        rn = l[17:20].strip().upper(); ch = l[21]; ri = l[22:27].strip()
        if rn in AA and l.startswith("ATOM"):
            cadenas[ch] = cadenas.get(ch, 0) + 1
            continue
        if rn in AGUAS:
            continue
        k = (rn, ch, ri)
        het.setdefault(k, 0); het[k] += 1
    hets = [{"resname": k[0], "chain": k[1], "resid": k[2], "n_atoms": n} for k, n in het.items()]
    return hets, cadenas


def lineas_residuo(pdb, resname, chain, resid):
    out = []
    for l in open(pdb, errors="ignore"):
        if l.startswith(("ATOM  ", "HETATM")) and l[17:20].strip().upper() == resname and l[21] == chain and l[22:27].strip() == str(resid):
            if l[16] not in (" ", "A"):
                continue
            out.append(l[:16] + " " + l[17:])
    return out


def separar_proteina(pdb, salida, cadenas=None, conservar_hetero=()):
    """Write only the amino acids (and the requested hetero residues, e.g. structural ions)."""
    keep = []
    for l in open(pdb, errors="ignore"):
        if not l.startswith(("ATOM  ", "HETATM")):
            continue
        rn = l[17:20].strip().upper()
        if cadenas and l[21] not in cadenas:
            continue
        if l[16] not in (" ", "A"):
            continue
        if rn in AA or (rn, l[21], l[22:27].strip()) in conservar_hetero:
            keep.append("ATOM  " + l[6:16] + " " + l[17:] if rn in AA else l)
    Path(salida).write_text("".join(keep) + "END\n")
    return salida


# =====================================================================
# 1. LIGAND
# =====================================================================
def construir_ligando(pdb, het, carpeta, sdf_quimica=None, smiles=None, protonar_ph=None, log=None):
    """Return (RDKit mol with H and pose coordinates, net charge, method, warnings)."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    carpeta = Path(carpeta); avisos = []
    lines = lineas_residuo(pdb, het["resname"], het["chain"], het["resid"])
    if not lines:
        raise ValueError(tr("No se encontraron los átomos del ligando en el PDB.", "The ligand atoms were not found in the PDB."))
    pdb_mol = Chem.MolFromPDBBlock("".join(lines), removeHs=False, sanitize=False, proximityBonding=True)
    pose_xyz = None
    if pdb_mol is not None:
        heavy = Chem.RemoveHs(pdb_mol, sanitize=False)
        pose_xyz = heavy.GetConformer().GetPositions()

    mol, metodo = None, None
    if sdf_quimica:
        suf = Path(sdf_quimica).suffix.lower()
        if suf == ".mol2":
            m = Chem.MolFromMol2File(str(sdf_quimica), removeHs=False)
        else:
            m = next((x for x in Chem.SDMolSupplier(str(sdf_quimica), removeHs=False) if x is not None), None)
        if m is None:
            raise ValueError(tr("No se pudo leer el archivo del ligando (SDF/MOL2).", "The ligand file (SDF/MOL2) could not be read."))
        if pose_xyz is not None:
            hv = Chem.RemoveHs(m).GetConformer().GetPositions()
            if len(hv) == len(pose_xyz):
                d = float(np.linalg.norm(hv.mean(0) - pose_xyz.mean(0)))
                if d > 1.0:
                    avisos.append(tr(f"El archivo del ligando no coincide con la pose del PDB (centroides a {d:.1f} Å). "
                                     "Se usan las coordenadas del archivo del ligando.",
                                     f"The ligand file does not match the pose in the PDB (centroids {d:.1f} Å apart). "
                                     "The coordinates of the ligand file are used."))
            else:
                avisos.append(tr(f"El ligando del PDB tiene {len(pose_xyz)} átomos pesados y el archivo {len(hv)}; se usa el archivo.",
                                 f"The PDB ligand has {len(pose_xyz)} heavy atoms and the file has {len(hv)}; the file is used."))
        mol = m
        metodo = tr(f"química y coordenadas del archivo {Path(sdf_quimica).name}", f"chemistry and coordinates from {Path(sdf_quimica).name}")
        if not any(a.GetAtomicNum() == 1 for a in mol.GetAtoms()):
            mol = Chem.AddHs(mol, addCoords=True); metodo += tr(" · H añadidos con coordenadas", " · H added with coordinates")
    elif pdb_mol is not None:
        heavy = Chem.RemoveHs(pdb_mol, sanitize=False)
        if smiles:
            tpl = Chem.MolFromSmiles(smiles)
            if tpl is None:
                raise ValueError(tr("SMILES de plantilla inválido.", "Invalid template SMILES."))
            mol = AllChem.AssignBondOrdersFromTemplate(tpl, heavy)
            Chem.SanitizeMol(mol)
            Chem.AssignStereochemistryFrom3D(mol)
            mol = Chem.AddHs(mol, addCoords=True)
            metodo = tr("órdenes de enlace desde la SMILES de plantilla · H añadidos con coordenadas",
                        "bond orders from the template SMILES · H added with coordinates")
        else:
            # with hydrogens from the PDB (docking outputs are usually protonated): perception with Open Babel
            tmp_pdb = carpeta / "lig_pdb.pdb"; tmp_pdb.write_text("".join(lines) + "END\n")
            tmp_sdf = carpeta / "lig_obabel.sdf"
            ob = herramienta("obabel")
            has_h = any(l[76:78].strip() == "H" or l[12:16].strip().startswith("H") for l in lines)
            run([ob, tmp_pdb, "-O", tmp_sdf] + ([] if has_h else ["-h"]), carpeta, log=log)
            mol = Chem.MolFromMolFile(str(tmp_sdf), removeHs=False)
            if mol is None:
                raise ValueError(tr("No se pudo interpretar la química del ligando. Sube el SDF del docking o escribe la SMILES.",
                                    "The ligand chemistry could not be interpreted. Upload the docking SDF or type the SMILES."))
            metodo = tr("química percibida por Open Babel a partir del PDB", "chemistry perceived by Open Babel from the PDB") + \
                ("" if has_h else tr(" · H añadidos", " · H added"))
            avisos.append(tr("La química (órdenes de enlace y cargas) se infirió de la geometría. Revisa la carga neta; "
                             "para mayor seguridad sube el SDF del docking o la SMILES.",
                             "The chemistry (bond orders and charges) was inferred from the geometry. Check the net charge; "
                             "for safety, upload the docking SDF or the SMILES."))
    if mol is None:
        raise ValueError(tr("No se pudo construir el ligando.", "The ligand could not be built."))
    if protonar_ph is not None:
        ob = herramienta("obabel")
        tin = carpeta / "lig_in.sdf"; tout = carpeta / "lig_ph.sdf"
        w = Chem.SDWriter(str(tin)); w.write(Chem.RemoveHs(mol)); w.close()
        run([ob, tin, "-O", tout, "-p", str(protonar_ph)], carpeta, log=log)
        m2 = Chem.MolFromMolFile(str(tout), removeHs=False)
        if m2 is not None:
            m2, nc = corregir_diaminas(m2)
            mol = m2; metodo += tr(f" · protonado a pH {protonar_ph} (Open Babel)", f" · protonated at pH {protonar_ph} (Open Babel)")
            if nc:
                metodo += tr(f" · {nc} amina(s) vecina(s) desprotonada(s) (piperazina/diamina: solo la más básica queda protonada)",
                             f" · {nc} neighbouring amine(s) deprotonated (piperazine/diamine: only the most basic one stays protonated)")
    Chem.SanitizeMol(mol)
    carga = Chem.GetFormalCharge(mol)
    # expected charge at pH 7.4 (reference used to warn the user)
    carga_ph = None
    try:
        ob = herramienta("obabel")
        tin = carpeta / "lig_ref.sdf"; tout = carpeta / "lig_ref74.sdf"
        w = Chem.SDWriter(str(tin)); w.write(Chem.RemoveHs(mol)); w.close()
        run([ob, tin, "-O", tout, "-p", "7.4"], carpeta, log=log)
        mref = Chem.MolFromMolFile(str(tout), removeHs=False)
        if mref is not None:
            carga_ph = Chem.GetFormalCharge(corregir_diaminas(mref)[0])
    except Exception:
        pass
    if carga_ph is not None and carga_ph != carga and protonar_ph is None:
        avisos.append(tr(f"La carga neta del ligando es {carga:+d}, pero a pH 7.4 se esperaría {carga_ph:+d} "
                         "(p. ej., aminas protonadas o ácidos desprotonados). Si corresponde, elige «Protonar a pH 7.4».",
                         f"The ligand net charge is {carga:+d}, but {carga_ph:+d} would be expected at pH 7.4 "
                         "(e.g. protonated amines or deprotonated acids). If appropriate, choose “Protonate at pH 7.4”."))
    mol.SetProp("carga_ph74", str(carga_ph))
    elems = {a.GetSymbol() for a in mol.GetAtoms()}
    raros = elems - {"H", "C", "N", "O", "S", "P", "F", "Cl", "Br", "I"}
    if raros:
        raise ValueError(tr(f"GAFF2 no tiene parámetros para: {', '.join(sorted(raros))}.",
                            f"GAFF2 has no parameters for: {', '.join(sorted(raros))}."))
    mol.SetProp("_Name", "LIG")
    return mol, carga, metodo, avisos


def corregir_diaminas(mol):
    """Open Babel protonates both N of piperazines and neighbouring diamines at a given pH; after the first protonation the
    second N is much less basic. If two protonated amines are ≤ 3 bonds apart, only the most basic one stays protonated."""
    from rdkit import Chem
    patt = Chem.MolFromSmarts("[NX4+;!H0;!$(N~[!#6;!#1])]")
    rw = Chem.RWMol(Chem.AddHs(mol, addCoords=True) if not any(a.GetAtomicNum() == 1 for a in mol.GetAtoms()) else mol)
    cambios = 0
    while True:
        idx = [m[0] for m in rw.GetSubstructMatches(patt)]
        dm = Chem.GetDistanceMatrix(rw)
        par = next(((i, j) for k, i in enumerate(idx) for j in idx[k + 1:] if dm[i][j] <= 3), None)
        if not par:
            break
        def basicidad(i):
            a = rw.GetAtomWithIdx(i); sc = 0
            for nb in a.GetNeighbors():
                if nb.GetAtomicNum() != 6:
                    continue
                if nb.GetIsAromatic():
                    sc -= 3                                    # aniline
                elif any(x.GetIsAromatic() for x in nb.GetNeighbors() if x.GetIdx() != i):
                    sc -= 1                                    # benzylic
                elif any(b.GetBondTypeAsDouble() == 2 and b.GetOtherAtom(nb).GetAtomicNum() == 8 for b in nb.GetBonds()):
                    sc -= 3                                    # amide / neighbouring carbonyl
                elif nb.GetDegree() == 1:
                    sc += 1                                    # N-methyl
            return sc
        i, j = par
        quitar = i if basicidad(i) < basicidad(j) else j
        a = rw.GetAtomWithIdx(quitar)
        h = next((nb.GetIdx() for nb in a.GetNeighbors() if nb.GetAtomicNum() == 1), None)
        a.SetFormalCharge(0)
        if h is not None:
            rw.RemoveAtom(h)
        else:
            a.SetNumExplicitHs(max(a.GetNumExplicitHs() - 1, 0))
        Chem.SanitizeMol(rw)
        cambios += 1
    return rw.GetMol(), cambios


def parametrizar_ligando(mol, carga, carpeta, metodo_carga="bcc", log=None, timeout=3600):
    """ACPYPE (antechamber, GAFF2). Returns paths to LIG.itp, LIG_atomtypes.itp, posre_LIG.itp and LIG.gro."""
    from rdkit import Chem
    carpeta = Path(carpeta); carpeta.mkdir(parents=True, exist_ok=True)
    work = carpeta / "acpype"; shutil.rmtree(work, ignore_errors=True); work.mkdir()
    # unique atom names (C1, C2, H1…) and residue LIG
    cont = {}
    for a in mol.GetAtoms():
        s = a.GetSymbol(); cont[s] = cont.get(s, 0) + 1
        nombre = f"{s}{cont[s]}"[:4]
        info = Chem.AtomPDBResidueInfo(); info.SetName(f"{nombre:<4}"[:4] if len(s) == 2 else f" {nombre:<3}"[:4])
        info.SetResidueName("LIG"); info.SetResidueNumber(1); info.SetChainId("Z"); info.SetIsHeteroAtom(True)
        a.SetMonomerInfo(info)
    sdf = work / "LIG.sdf"; w = Chem.SDWriter(str(sdf)); w.write(mol); w.close()
    mol2 = work / "LIG.mol2"
    run([herramienta("obabel"), sdf, "-O", mol2], work, log=log)
    # the mol2 residue must be called LIG
    txt = mol2.read_text().splitlines()
    sec = None; out = []
    for l in txt:
        if l.startswith("@<TRIPOS>"):
            sec = l.strip()
        elif sec == "@<TRIPOS>ATOM" and l.strip():
            parts = l.split()
            if len(parts) >= 8:
                parts[7] = "LIG"; parts[6] = "1"
                l = f"{int(parts[0]):>7} {parts[1]:<8} {float(parts[2]):>10.4f} {float(parts[3]):>10.4f} {float(parts[4]):>10.4f} {parts[5]:<6} {parts[6]:>4} {parts[7]:<6} {float(parts[8]) if len(parts) > 8 else 0.0:>9.4f}"
        elif sec == "@<TRIPOS>MOLECULE" and l.strip() and not l.startswith("@") and out and out[-1].startswith("@<TRIPOS>MOLECULE"):
            l = "LIG"
        out.append(l)
    mol2.write_text("\n".join(out) + "\n")
    cmd = [herramienta("acpype"), "-i", "LIG.mol2", "-b", "LIG", "-c", metodo_carga, "-n", str(carga), "-a", "gaff2", "-o", "gmx"]
    run(cmd, work, log=log, timeout=timeout)
    d = work / "LIG.acpype"
    itp, gro = d / "LIG_GMX.itp", d / "LIG_GMX.gro"
    if not itp.exists() or not gro.exists():
        raise RuntimeError(tr("ACPYPE no generó la topología del ligando (revisa el registro).",
                              "ACPYPE did not produce the ligand topology (check the log)."))
    # split [ atomtypes ] so it can be included before the molecule definitions
    t = itp.read_text().splitlines()
    at, resto, en_at = [], [], False
    for l in t:
        if l.strip().startswith("[") and "atomtypes" in l:
            en_at = True; at.append(l); continue
        if en_at and l.strip().startswith("["):
            en_at = False
        (at if en_at else resto).append(l)
    (carpeta / "LIG_atomtypes.itp").write_text("\n".join(at) + "\n")
    lig_itp = "\n".join(resto) + "\n"
    lig_itp += tr("\n; Restricciones de posición del ligando", "\n; Ligand position restraints") + \
        "\n#ifdef POSRES\n#include \"posre_LIG.itp\"\n#endif\n"
    (carpeta / "LIG.itp").write_text(lig_itp)
    pos = d / "posre_LIG.itp"
    if pos.exists():
        shutil.copy2(pos, carpeta / "posre_LIG.itp")
    else:
        raise RuntimeError(tr("ACPYPE no generó posre_LIG.itp", "ACPYPE did not produce posre_LIG.itp"))
    shutil.copy2(gro, carpeta / "LIG.gro")
    return {"itp": carpeta / "LIG.itp", "atomtypes": carpeta / "LIG_atomtypes.itp", "posre": carpeta / "posre_LIG.itp",
            "gro": carpeta / "LIG.gro", "mol2": mol2}


# =====================================================================
# 2. PROTEIN
# =====================================================================
def huecos(pdb, umbral=2.0):
    """Detect chain breaks (C(i)–N(i+1) distance > threshold, Å)."""
    C, N, orden = {}, {}, []
    for l in open(pdb, errors="ignore"):
        if not l.startswith("ATOM"):
            continue
        k = (l[21], int(l[22:26]), l[26])
        if k not in orden:
            orden.append(k)
        nm = l[12:16].strip()
        xyz = np.array([float(l[30:38]), float(l[38:46]), float(l[46:54])])
        if nm == "C":
            C[k] = xyz
        elif nm == "N":
            N[k] = xyz
    out = []
    for a, b in zip(orden, orden[1:]):
        if a[0] != b[0] or a not in C or b not in N:
            continue
        d = float(np.linalg.norm(C[a] - N[b]))
        if d > umbral:
            out.append({"chain": a[0], "after": a[1], "before": b[1], "distance_A": round(d, 2), "missing": b[1] - a[1] - 1})
    return out


def reparar_proteina(pdb_in, pdb_out, log=None):
    """PDBFixer: replace non-standard residues and add missing heavy atoms (missing loops are not modelled)."""
    from pdbfixer import PDBFixer
    from openmm.app import PDBFile
    fx = PDBFixer(filename=str(pdb_in))
    fx.findMissingResidues()
    fx.missingResidues = {}          # missing loops are not modelled (treated as chain breaks)
    fx.findNonstandardResidues()
    nonstd = [(r.name, r.id, rep) for r, rep in fx.nonstandardResidues]
    fx.replaceNonstandardResidues()
    fx.removeHeterogens(keepWater=False)
    fx.findMissingAtoms()
    faltan = sum(len(v) for v in fx.missingAtoms.values())
    term = sum(len(v) for v in fx.missingTerminals.values())
    fx.addMissingAtoms()
    with open(pdb_out, "w") as f:
        PDBFile.writeFile(fx.topology, fx.positions, f, keepIds=True)
    return {"heavy_atoms_added": faltan, "terminal_atoms_added": term, "nonstandard_replaced": nonstd}


def protonar_proteina(pdb_in, pdb_out, ph, carpeta, log=None):
    """PDB2PQR + PROPKA with AMBER residue names (HID/HIE/HIP, ASH, GLH, LYN, CYX)."""
    pdb2pqr = herramienta("pdb2pqr30", "pdb2pqr")
    cmd = ([pdb2pqr] if pdb2pqr else [sys.executable, "-m", "pdb2pqr"]) + [
        "--ff", "AMBER", "--ffout", "AMBER", "--titration-state-method", "propka", "--with-ph", str(ph),
        "--keep-chain", "--pdb-output", str(pdb_out), str(pdb_in), str(Path(carpeta) / "protein.pqr")]
    run(cmd, carpeta, log=log)
    estados = {}
    for l in open(pdb_out):
        if l.startswith("ATOM"):
            rn = l[17:20].strip()
            if rn in ("HID", "HIE", "HIP", "ASH", "GLH", "LYN", "CYX", "CYM"):
                estados[(l[21], l[22:26].strip(), rn)] = rn
    resumen = {}
    for (_, _, rn) in estados:
        resumen[rn] = resumen.get(rn, 0) + 1
    return resumen


def pdb_para_pdb2gmx(pdb_in, pdb_out, cortes):
    """Prepare the PDB for pdb2gmx (AMBER) and split the chain with TER at each gap."""
    corte_set = {(c["chain"], c["after"]) for c in cortes}
    out, prev = [], None
    for l in open(pdb_in):
        if not l.startswith("ATOM"):
            continue
        key = (l[21], int(l[22:26]))
        if prev is not None and prev != key and (prev[0], prev[1]) in corte_set:
            out.append("TER\n")
        if prev is not None and prev[0] != key[0]:
            out.append("TER\n")
        prev = key
        out.append(l if l.endswith("\n") else l + "\n")
    out.append("TER\nEND\n")
    Path(pdb_out).write_text("".join(out))


def topologia_proteina(pdb_in, carpeta, ff="amber99sb-ildn", agua="tip3p", log=None):
    run([GMX(), "pdb2gmx", "-f", pdb_in, "-o", "protein.gro", "-p", "topol.top", "-i", "posre.itp",
         "-ff", ff, "-water", agua, "-ignh", "-chainsep", "id_or_ter", "-merge", "no"], carpeta, log=log)
    return Path(carpeta) / "protein.gro", Path(carpeta) / "topol.top"


# =====================================================================
# 3. ASSEMBLY, BOX, WATER AND IONS
# =====================================================================
def leer_gro(p):
    l = Path(p).read_text().splitlines()
    n = int(l[1].strip())
    return l[0], l[2:2 + n], l[2 + n]


def unir_gro(prot, lig, salida):
    t, a1, box = leer_gro(prot)
    _, a2, _ = leer_gro(lig)
    # renumber the ligand residue after the last protein residue
    last_res = int(a1[-1][:5])
    a2n = [f"{(last_res + 1) % 100000:>5}" + l[5:] for l in a2]
    atoms = a1 + a2n
    atoms = [l[:15] + f"{(i + 1) % 100000:>5}" + l[20:] for i, l in enumerate(atoms)]
    Path(salida).write_text(f"Protein + LIG\n{len(atoms):>5}\n" + "\n".join(atoms) + "\n" + box + "\n")
    return salida


def incluir_ligando_en_top(top):
    t = Path(top).read_text()
    # ligand atom types right after the force field
    t = re.sub(r'(#include\s+"[^"]*forcefield\.itp"\s*\n)',
               r'\1\n; ' + tr("Tipos de átomo GAFF2 del ligando", "GAFF2 atom types of the ligand") + r'\n#include "LIG_atomtypes.itp"\n', t, count=1)
    # ligand topology before the water model
    t = re.sub(r'(\n; Include water topology)', r'\n; ' + tr("Topología del ligando", "Ligand topology") + r'\n#include "LIG.itp"\n\1', t, count=1)
    if '#include "LIG.itp"' not in t:
        t = t.replace("[ system ]", '#include "LIG.itp"\n\n[ system ]', 1)
    t = t.rstrip() + "\nLIG                 1\n"
    Path(top).write_text(t)


def mdp_iones(path):
    Path(path).write_text("""; genion only
integrator  = steep
nsteps      = 0
cutoff-scheme = Verlet
coulombtype = PME
rcoulomb    = 1.0
rvdw        = 1.0
pbc         = xyz
""")


def solvatar(carpeta, caja="dodecahedron", distancia=1.2, conc=0.15, sal="NaCl", log=None):
    g = GMX(); c = Path(carpeta)
    run([g, "editconf", "-f", "complex.gro", "-o", "box.gro", "-c", "-d", str(distancia), "-bt", caja], c, log=log)
    run([g, "solvate", "-cp", "box.gro", "-cs", "spc216.gro", "-o", "solvated.gro", "-p", "topol.top"], c, log=log)
    mdp_iones(c / "ions.mdp")
    run([g, "grompp", "-f", "ions.mdp", "-c", "solvated.gro", "-p", "topol.top", "-o", "ions.tpr", "-maxwarn", "2"], c, log=log)
    out = run([g, "genion", "-s", "ions.tpr", "-o", "step3_input.gro", "-p", "topol.top", "-pname", "K" if sal == "KCl" else "NA",
               "-nname", "CL", "-neutral", "-conc", str(conc)], c, stdin="SOL\n", log=log)
    return out


def construir_indice(carpeta, log=None):
    """Default GROMACS groups + SOLU (protein+ligand) and SOLV (water+ions), as in CHARMM-GUI."""
    c = Path(carpeta)
    run([GMX(), "make_ndx", "-f", "step3_input.gro", "-o", "index.ndx"], c, stdin="q\n", log=log)
    _, atoms, _ = leer_gro(c / "step3_input.gro")
    solv = {"SOL", "NA", "CL", "K", "HOH", "WAT"}
    solu_idx = [i + 1 for i, l in enumerate(atoms) if l[5:10].strip() not in solv]
    solv_idx = [i + 1 for i, l in enumerate(atoms) if l[5:10].strip() in solv]
    lig_idx = [i + 1 for i, l in enumerate(atoms) if l[5:10].strip() == "LIG"]
    def grupo(nombre, idx):
        s = f"[ {nombre} ]\n"
        for i in range(0, len(idx), 15):
            s += " ".join(f"{x:>6}" for x in idx[i:i + 15]) + "\n"
        return s
    with open(c / "index.ndx", "a") as f:
        f.write(grupo("SOLU", solu_idx)); f.write(grupo("SOLV", solv_idx))
        if lig_idx and "[ LIG ]" not in (c / "index.ndx").read_text():
            f.write(grupo("LIG", lig_idx))
    return {"atoms": len(atoms), "solute": len(solu_idx), "solvent": len(solv_idx)}


def resumen_sistema(carpeta):
    c = Path(carpeta)
    _, atoms, box = leer_gro(c / "step3_input.gro")
    res = {}
    for l in atoms:
        rn = l[5:10].strip(); rid = l[:5]
        res.setdefault(rn, set()).add(rid)
    b = [float(x) for x in box.split()]
    if len(b) == 3:
        vol = b[0] * b[1] * b[2]
    else:  # triclinic: v1(x) v2(y) v3(z) v1(y) v1(z) v2(x) v2(z) v3(x) v3(y)
        v1 = np.array([b[0], b[3], b[4]]); v2 = np.array([b[5], b[1], b[6]]); v3 = np.array([b[7], b[8], b[2]])
        vol = abs(np.dot(v1, np.cross(v2, v3)))
    cat = "K" if "K" in res else "NA"
    return {"atoms": len(atoms), "waters": len(res.get("SOL", [])), "cation": "K+" if cat == "K" else "Na+",
            "n_cation": len(res.get(cat, [])), "Na+": len(res.get("NA", [])), "K+": len(res.get("K", [])), "Cl-": len(res.get("CL", [])),
            "volume_nm3": round(vol, 2), "box_nm": b}


# =====================================================================
# 4. MDP FILES
# =====================================================================
COMUN = """cutoff-scheme           = Verlet
nstlist                 = 20
pbc                     = xyz
coulombtype             = PME
rcoulomb                = {rc}
vdwtype                 = Cut-off
vdw-modifier            = Potential-shift
rvdw                    = {rc}
DispCorr                = EnerPres
fourierspacing          = 0.12
pme-order               = 4
"""


def mdp_minimizacion(p, rc=1.0, nsteps=50000):
    Path(p).write_text(f"""; step4.0 · {tr('Minimización de energía (descenso más pronunciado) con restricciones de posición',
                                         'Energy minimization (steepest descent) with position restraints')}
define                  = -DPOSRES
integrator              = steep
emtol                   = 1000.0
emstep                  = 0.01
nsteps                  = {nsteps}
nstlog                  = 1000
nstenergy               = 1000
{COMUN.format(rc=rc)}""")


def mdp_nvt(p, temp=310, ps=125, dt=0.001, rc=1.0):
    Path(p).write_text(f"""; step4.1 · {tr(f'Equilibrado NVT ({ps} ps, {temp} K) con restricciones de posición en proteína y ligando',
                                         f'NVT equilibration ({ps} ps, {temp} K) with position restraints on protein and ligand')}
define                  = -DPOSRES
integrator              = md
dt                      = {dt}
nsteps                  = {int(round(ps / dt))}
nstxout-compressed      = 5000
nstlog                  = 1000
nstenergy               = 1000
nstcalcenergy           = 100
continuation            = no
constraint-algorithm    = lincs
constraints             = h-bonds
lincs-iter              = 1
lincs-order             = 4
{COMUN.format(rc=rc)}tcoupl                  = V-rescale
tc-grps                 = SOLU SOLV
tau-t                   = 1.0 1.0
ref-t                   = {temp} {temp}
pcoupl                  = no
gen-vel                 = yes
gen-temp                = {temp}
gen-seed                = -1
""")


def mdp_npt(p, temp=310, ps=1000, dt=0.002, rc=1.0):
    Path(p).write_text(f"""; step4.2 · {tr(f'Equilibrado NPT ({ps} ps, {temp} K, 1 bar) con restricciones de posición',
                                         f'NPT equilibration ({ps} ps, {temp} K, 1 bar) with position restraints')}
define                  = -DPOSRES
integrator              = md
dt                      = {dt}
nsteps                  = {int(round(ps / dt))}
nstxout-compressed      = 5000
nstlog                  = 5000
nstenergy               = 5000
nstcalcenergy           = 100
continuation            = yes
constraint-algorithm    = lincs
constraints             = h-bonds
lincs-iter              = 1
lincs-order             = 4
{COMUN.format(rc=rc)}tcoupl                  = V-rescale
tc-grps                 = SOLU SOLV
tau-t                   = 1.0 1.0
ref-t                   = {temp} {temp}
pcoupl                  = C-rescale
pcoupltype              = isotropic
tau-p                   = 5.0
ref-p                   = 1.0
compressibility         = 4.5e-5
refcoord-scaling        = com
gen-vel                 = no
""")


def mdp_produccion(p, ns=250.0, temp=310, dt=0.002, rc=1.0, guardar_ps=10.0, grupo_xtc="System"):
    nsteps = int(round(ns * 1000 / dt))
    nout = int(round(guardar_ps / dt))
    Path(p).write_text(f"""; step5 · {tr(f'Producción NPT: {ns:g} ns a {temp} K y 1 bar (dt = {dt} ps → {nsteps} pasos)',
                                       f'NPT production: {ns:g} ns at {temp} K and 1 bar (dt = {dt} ps → {nsteps} steps)')}
integrator              = md
dt                      = {dt}
nsteps                  = {nsteps}
nstxout                 = 0
nstvout                 = 0
nstfout                 = 0
nstxout-compressed      = {nout}
compressed-x-grps       = {grupo_xtc}
nstlog                  = {nout}
nstenergy               = {nout}
nstcalcenergy           = 100
continuation            = yes
constraint-algorithm    = lincs
constraints             = h-bonds
lincs-iter              = 1
lincs-order             = 4
{COMUN.format(rc=rc)}tcoupl                  = V-rescale
tc-grps                 = SOLU SOLV
tau-t                   = 1.0 1.0
ref-t                   = {temp} {temp}
pcoupl                  = C-rescale
pcoupltype              = isotropic
tau-p                   = 5.0
ref-p                   = 1.0
compressibility         = 4.5e-5
gen-vel                 = no
""")
    return nsteps


# =====================================================================
# 5. SLURM SCRIPT
# =====================================================================
def _horas(t):
    try:
        h, m, s = [int(x) for x in t.split(":")]
        return h + m / 60 + s / 3600
    except Exception:
        try:
            d, rest = t.split("-"); h, m, s = [int(x) for x in rest.split(":")]
            return 24 * int(d) + h + m / 60 + s / 3600
        except Exception:
            return None


def script_slurm(cfg, incluir_npt=True, continuacion=False):
    n = nombres()
    c = {**SLURM_PREDETERMINADO, "output": n["out"], "error": n["err"], "continue_name": n["continuar"], **cfg}
    flags = "-nb gpu" + (" -pme gpu -bonded gpu -update gpu" if c.get("gpu_full") else "")
    h = _horas(c["time"])
    # in the main job, minimization and equilibration also consume time before the production run
    margen = 0.25 if continuacion else min(2.0, max(0.25, 0.1 * h)) if h else 0.25
    maxh = f" -maxh {max(h - margen, 0.1):.2f}" if (c.get("maxh") and h) else ""
    pre = tr("continuar_", "continue_") if continuacion else ""
    cab = f"""#!/bin/bash
#SBATCH --job-name={c['job_name']} # {tr('nombre del job', 'job name')}
#SBATCH --nodes={c['nodes']} # {tr('Correr el job en N nodes', 'number of nodes')}
#SBATCH --partition={c['partition']} # {tr('nombre de la partición solicitada', 'partition (queue)')}
#SBATCH --ntasks={c['ntasks']} # {tr('Cantidad de tareas (~ numero de cores)', 'number of tasks (~ CPU cores)')}
#SBATCH --time={c['time']} # {tr('Tiempo hrs:min:sec', 'wall time hrs:min:sec')}
#SBATCH --output={pre + c['output']} # Standard output log
#SBATCH --error={pre + c['error']} # Standard error log
#SBATCH --gres=gpu:{c['gpus']} # {tr(f"Especifica {c['gpus']} GPU(s)", f"{c['gpus']} GPU(s)")}

{str(c.get('modules', '')).strip()}


"""
    if continuacion:
        return cab + tr(f"""# Continúa la producción desde el último punto de control (step5.cpt).
# Envíalo con: sbatch {c['continue_name']}  (repítelo hasta que step5.log diga "Finished mdrun")
""", f"""# Continues the production run from the last checkpoint (step5.cpt).
# Submit with: sbatch {c['continue_name']}  (repeat until step5.log says "Finished mdrun")
""") + f"gmx mdrun -v -deffnm step5 -cpi step5.cpt {flags}{maxh}\n"
    s = cab
    s += "gmx grompp -f step4.0_minimization.mdp -o step4.0_minimization.tpr -c step3_input.gro -r step3_input.gro -p topol.top -n index.ndx  -maxwarn 3\n"
    s += "gmx mdrun -v -deffnm step4.0_minimization -nb gpu\n"
    s += "gmx grompp -f step4.1_equilibration.mdp -o step4.1_equilibration.tpr -c step4.0_minimization.gro -r step3_input.gro -p topol.top -n index.ndx -maxwarn 3\n"
    s += f"gmx mdrun -v -deffnm step4.1_equilibration {flags}\n"
    prev = "step4.1_equilibration"
    if incluir_npt:
        s += "gmx grompp -f step4.2_equilibration.mdp -o step4.2_equilibration.tpr -c step4.1_equilibration.gro -t step4.1_equilibration.cpt -r step3_input.gro -p topol.top -n index.ndx -maxwarn 3\n"
        s += f"gmx mdrun -v -deffnm step4.2_equilibration {flags}\n"
        prev = "step4.2_equilibration"
    s += f"gmx grompp -f step5_production.mdp -o step5.tpr -c {prev}.gro -t {prev}.cpt -p topol.top -n index.ndx -maxwarn 3\n"
    s += f"gmx mdrun -v -deffnm step5 {flags}{maxh}\n"
    return s


def estimar_tiempo(ns_total, ns_dia, horas_job, horas_equil=1.0):
    horas = ns_total / ns_dia * 24 if ns_dia > 0 else float("nan")
    envios = max(1, math.ceil((horas + horas_equil) / (horas_job or 1e9))) if horas_job else 1
    return {"hours": round(horas, 1), "days": round(horas / 24, 1), "jobs": envios, "continuations": max(envios - 1, 0)}


# =====================================================================
# 6. COMPLETE WORKFLOW
# =====================================================================
OPCIONES_PREDETERMINADAS = {
    "chains": None, "ligand_file": None, "smiles": None, "ph": 7.4, "ligand_ph": None, "manual_charge": None,
    "box": "dodecahedron", "distance": 1.2, "conc": 0.15, "salt": "NaCl", "temp": 310, "ff": "amber99sb-ildn",
    "ns": 250.0, "nvt_ps": 125, "npt": True, "npt_ps": 1000, "save_ps": 10.0, "xtc_group": "System", "charge_method": "bcc",
}


def preparar_sistema(pdb, het, carpeta, opciones, progreso=lambda f, t: None):
    """Run the whole workflow and return a summary dict. `opciones`: see OPCIONES_PREDETERMINADAS."""
    o = {**OPCIONES_PREDETERMINADAS, **{k: v for k, v in opciones.items() if v is not None or k in ("ligand_ph", "manual_charge")}}
    n = nombres()
    c = Path(carpeta); shutil.rmtree(c, ignore_errors=True); c.mkdir(parents=True)
    log = c / n["log"]; log.write_text(f"{APP_NAME} {APP_VERSION} — {datetime.now().isoformat(timespec='seconds')}\n")
    tmp = c / n["intermedios"]; tmp.mkdir()
    shutil.copy2(pdb, tmp / "complex_input.pdb")
    R = {"app": f"{APP_NAME} {APP_VERSION}", "language": LANG, "warnings": [], "options": o}

    progreso(0.05, tr("Ligando: química y protonación", "Ligand: chemistry and protonation"))
    mol, carga, metodo, av = construir_ligando(pdb, het, tmp, o["ligand_file"], o["smiles"], o["ligand_ph"], log)
    R["warnings"] += av
    if o.get("manual_charge") is not None:
        carga = int(o["manual_charge"])
    R["ligand"] = {"method": metodo, "net_charge": carga, "expected_charge_pH7.4": mol.GetProp("carga_ph74"), "atoms": mol.GetNumAtoms(),
                   "original_residue": f"{het['resname']} {het['chain']}:{het['resid']}"}

    progreso(0.12, tr("Ligando: parametrización GAFF2 + AM1-BCC (ACPYPE/antechamber), puede tardar varios minutos",
                      "Ligand: GAFF2 + AM1-BCC parameters (ACPYPE/antechamber), this can take several minutes"))
    parametrizar_ligando(mol, carga, c, o.get("charge_method", "bcc"), log)
    lig_gro = c / "LIG.gro"

    progreso(0.45, tr("Proteína: PDBFixer (átomos faltantes)", "Protein: PDBFixer (missing atoms)"))
    separar_proteina(pdb, tmp / "protein_raw.pdb", o["chains"])
    fix = reparar_proteina(tmp / "protein_raw.pdb", tmp / "protein_fixed.pdb", log)
    R["protein"] = {"repair": fix}
    cortes = huecos(tmp / "protein_fixed.pdb")
    R["protein"]["gaps"] = cortes
    if cortes:
        R["warnings"].append(tr(
            f"La proteína tiene {len(cortes)} hueco(s) de residuos faltantes; cada hueco se trató como extremo de cadena "
            "(terminales cargados). Para modelarlos, usa la estructura completa (MODELLER, AlphaFold o CHARMM-GUI).",
            f"The protein has {len(cortes)} gap(s) of missing residues; each gap was treated as a chain end "
            "(charged termini). To model them, use a complete structure (MODELLER, AlphaFold or CHARMM-GUI)."))

    progreso(0.55, tr(f"Proteína: protonación a pH {o['ph']} (PDB2PQR + PROPKA)", f"Protein: protonation at pH {o['ph']} (PDB2PQR + PROPKA)"))
    R["protein"]["protonation"] = protonar_proteina(tmp / "protein_fixed.pdb", tmp / "protein_protonated.pdb", o["ph"], tmp, log)
    pdb_para_pdb2gmx(tmp / "protein_protonated.pdb", c / "protein_gmx.pdb", cortes)

    progreso(0.65, tr(f"Proteína: topología {o['ff']} (pdb2gmx)", f"Protein: {o['ff']} topology (pdb2gmx)"))
    topologia_proteina(c / "protein_gmx.pdb", c, o["ff"], "tip3p", log)

    progreso(0.72, tr("Ensamblando complejo y topología", "Assembling complex and topology"))
    unir_gro(c / "protein.gro", lig_gro, c / "complex.gro")
    incluir_ligando_en_top(c / "topol.top")

    progreso(0.78, tr("Caja, agua TIP3P e iones", "Box, TIP3P water and ions"))
    solvatar(c, o["box"], o["distance"], o["conc"], o["salt"], log)

    progreso(0.88, tr("Índice SOLU / SOLV", "SOLU / SOLV index"))
    R["index"] = construir_indice(c, log)
    R["system"] = resumen_sistema(c)

    progreso(0.92, tr("Archivos .mdp y script SLURM", ".mdp files and SLURM script"))
    mdp_minimizacion(c / "step4.0_minimization.mdp")
    mdp_nvt(c / "step4.1_equilibration.mdp", o["temp"], o["nvt_ps"])
    if o["npt"]:
        mdp_npt(c / "step4.2_equilibration.mdp", o["temp"], o["npt_ps"])
    R["nsteps_production"] = mdp_produccion(c / "step5_production.mdp", o["ns"], o["temp"], guardar_ps=o["save_ps"], grupo_xtc=o["xtc_group"])

    progreso(0.95, tr("Verificando con grompp", "Checking with grompp"))
    R["verification"] = verificar(c, o["npt"], log)
    limpiar(c)
    R["versions"] = versiones()
    (c / n["resumen"]).write_text(json.dumps(R, indent=2, ensure_ascii=False, default=str))
    progreso(1.0, tr("Listo", "Done"))
    return R


def verificar(c, npt, log):
    """Run grompp for every stage (as on the cluster) to catch errors before uploading the files."""
    g = GMX(); c = Path(c); res = {}
    etapas = ["step4.0_minimization", "step4.1_equilibration"] + (["step4.2_equilibration"] if npt else []) + ["step5_production"]
    for nombre in etapas:
        out = run([g, "grompp", "-f", f"{nombre}.mdp", "-o", f"_check_{nombre}.tpr", "-c", "step3_input.gro", "-r", "step3_input.gro",
                   "-p", "topol.top", "-n", "index.ndx", "-maxwarn", "3", "-po", "_check_mdout.mdp"], c, log=log)
        res[nombre] = _notas_grompp(out)
    return res


def _notas_grompp(out):
    warns = re.findall(r"WARNING \d+ \[.*?\]:\s*\n(.*?)(?:\n\n)", out, re.S)
    notes = len(re.findall(r"^NOTE \d+", out, re.M))
    q = re.search(r"System has non-zero total charge:\s*([-\d.eE+]+)", out)
    return {"warnings": [w.strip().replace("\n", " ")[:300] for w in warns], "notes": notes,
            "total_charge": float(q.group(1)) if q else 0.0}


def limpiar(c):
    c = Path(c)
    for p in list(c.glob("_check_*")) + list(c.glob("#*#")) + [c / "mdout.mdp", c / "ions.tpr"]:
        try:
            p.unlink()
        except Exception:
            pass


ARCHIVOS_CLUSTER = ["step3_input.gro", "topol.top", "index.ndx", "step4.0_minimization.mdp", "step4.1_equilibration.mdp",
                    "step4.2_equilibration.mdp", "step5_production.mdp", "LIG.itp", "LIG_atomtypes.itp", "posre_LIG.itp"]


def paquete_cluster(c, slurm_txt, continuar_txt, nombre_script, readme, metodos, salida_zip, carpeta_zip):
    c = Path(c); n = nombres()
    (c / nombre_script).write_text(slurm_txt.replace("\r\n", "\n"))
    (c / n["continuar"]).write_text(continuar_txt.replace("\r\n", "\n"))
    (c / n["readme"]).write_text(readme)
    (c / n["metodos"]).write_text(metodos)
    (c / n["bib"]).write_text(bibtex())
    files = [f for f in ARCHIVOS_CLUSTER if (c / f).exists()]
    files += sorted(p.name for p in c.glob("topol_*.itp")) + sorted(p.name for p in c.glob("posre*.itp") if p.name != "posre_LIG.itp")
    files += [nombre_script, n["continuar"], n["readme"], n["metodos"], n["bib"], n["resumen"], n["log"]]
    files = list(dict.fromkeys(files))
    with zipfile.ZipFile(salida_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            if (c / f).exists():
                info = zipfile.ZipInfo(f"{carpeta_zip}/{f}", date_time=datetime.now().timetuple()[:6])
                info.external_attr = (0o755 if f.endswith(".sh") else 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, (c / f).read_bytes())
    return files


# =====================================================================
# 7. REFERENCES (all checked against Crossref)
# =====================================================================
# role: what each reference supports in the workflow (used in the methods text and the README)
REFERENCIAS = [
    dict(key="Abraham2015", role="gromacs", authors=["Abraham, M. J.", "Murtola, T.", "Schulz, R.", "Páll, S.", "Smith, J. C.", "Hess, B.", "Lindahl, E."],
         year=2015, title="GROMACS: High performance molecular simulations through multi-level parallelism from laptops to supercomputers",
         journal="SoftwareX", volume="1–2", pages="19–25", doi="10.1016/j.softx.2015.06.001"),
    dict(key="Hornak2006", role="ff", authors=["Hornak, V.", "Abel, R.", "Okur, A.", "Strockbine, B.", "Roitberg, A.", "Simmerling, C."],
         year=2006, title="Comparison of multiple Amber force fields and development of improved protein backbone parameters",
         journal="Proteins: Structure, Function, and Bioinformatics", volume="65", issue="3", pages="712–725", doi="10.1002/prot.21123"),
    dict(key="LindorffLarsen2010", role="ff", authors=["Lindorff-Larsen, K.", "Piana, S.", "Palmo, K.", "Maragakis, P.", "Klepeis, J. L.", "Dror, R. O.", "Shaw, D. E."],
         year=2010, title="Improved side-chain torsion potentials for the Amber ff99SB protein force field",
         journal="Proteins: Structure, Function, and Bioinformatics", volume="78", issue="8", pages="1950–1958", doi="10.1002/prot.22711"),
    dict(key="Jorgensen1983", role="water", authors=["Jorgensen, W. L.", "Chandrasekhar, J.", "Madura, J. D.", "Impey, R. W.", "Klein, M. L."],
         year=1983, title="Comparison of simple potential functions for simulating liquid water",
         journal="The Journal of Chemical Physics", volume="79", issue="2", pages="926–935", doi="10.1063/1.445869"),
    dict(key="Wang2004", role="gaff", authors=["Wang, J.", "Wolf, R. M.", "Caldwell, J. W.", "Kollman, P. A.", "Case, D. A."],
         year=2004, title="Development and testing of a general amber force field",
         journal="Journal of Computational Chemistry", volume="25", issue="9", pages="1157–1174", doi="10.1002/jcc.20035"),
    dict(key="Jakalian2000", role="bcc", authors=["Jakalian, A.", "Bush, B. L.", "Jack, D. B.", "Bayly, C. I."],
         year=2000, title="Fast, efficient generation of high-quality atomic charges. AM1-BCC model: I. Method",
         journal="Journal of Computational Chemistry", volume="21", issue="2", pages="132–146",
         doi="10.1002/(SICI)1096-987X(20000130)21:2<132::AID-JCC5>3.0.CO;2-P"),
    dict(key="Jakalian2002", role="bcc", authors=["Jakalian, A.", "Jack, D. B.", "Bayly, C. I."],
         year=2002, title="Fast, efficient generation of high-quality atomic charges. AM1-BCC model: II. Parameterization and validation",
         journal="Journal of Computational Chemistry", volume="23", issue="16", pages="1623–1641", doi="10.1002/jcc.10128"),
    dict(key="Case2023", role="amber", authors=["Case, D. A.", "Aktulga, H. M.", "Belfon, K.", "Cerutti, D. S.", "Cisneros, G. A.", "Cruzeiro, V. W. D."],
         etal=True, year=2023, title="AmberTools", journal="Journal of Chemical Information and Modeling", volume="63", issue="20",
         pages="6183–6191", doi="10.1021/acs.jcim.3c01153"),
    dict(key="SousaDaSilva2012", role="acpype", authors=["Sousa da Silva, A. W.", "Vranken, W. F."],
         year=2012, title="ACPYPE - AnteChamber PYthon Parser interfacE", journal="BMC Research Notes", volume="5", issue="1", pages="367",
         doi="10.1186/1756-0500-5-367"),
    dict(key="OBoyle2011", role="obabel", authors=["O'Boyle, N. M.", "Banck, M.", "James, C. A.", "Morley, C.", "Vandermeersch, T.", "Hutchison, G. R."],
         year=2011, title="Open Babel: An open chemical toolbox", journal="Journal of Cheminformatics", volume="3", pages="33",
         doi="10.1186/1758-2946-3-33"),
    dict(key="RDKit", role="rdkit", authors=["RDKit contributors"], year=None, software=True,
         title="RDKit: Open-source cheminformatics", journal="https://www.rdkit.org", doi="10.5281/zenodo.591637"),
    dict(key="Eastman2024", role="pdbfixer", authors=["Eastman, P.", "Galvelis, R.", "Peláez, R. P.", "Abreu, C. R. A.", "Farr, S. E.", "Gallicchio, E."],
         etal=True, year=2024, title="OpenMM 8: Molecular dynamics simulation with machine learning potentials",
         journal="The Journal of Physical Chemistry B", volume="128", issue="1", pages="109–116", doi="10.1021/acs.jpcb.3c06662"),
    dict(key="Dolinsky2004", role="pdb2pqr", authors=["Dolinsky, T. J.", "Nielsen, J. E.", "McCammon, J. A.", "Baker, N. A."],
         year=2004, title="PDB2PQR: An automated pipeline for the setup of Poisson–Boltzmann electrostatics calculations",
         journal="Nucleic Acids Research", volume="32", issue="Web Server", pages="W665–W667", doi="10.1093/nar/gkh381"),
    dict(key="Jurrus2018", role="pdb2pqr", authors=["Jurrus, E.", "Engel, D.", "Star, K.", "Monson, K.", "Brandi, J.", "Felberg, L. E."],
         etal=True, year=2018, title="Improvements to the APBS biomolecular solvation software suite",
         journal="Protein Science", volume="27", issue="1", pages="112–128", doi="10.1002/pro.3280"),
    dict(key="Olsson2011", role="propka", authors=["Olsson, M. H. M.", "Søndergaard, C. R.", "Rostkowski, M.", "Jensen, J. H."],
         year=2011, title="PROPKA3: Consistent treatment of internal and surface residues in empirical pKa predictions",
         journal="Journal of Chemical Theory and Computation", volume="7", issue="2", pages="525–537", doi="10.1021/ct100578z"),
    dict(key="Darden1993", role="pme", authors=["Darden, T.", "York, D.", "Pedersen, L."],
         year=1993, title="Particle mesh Ewald: An N·log(N) method for Ewald sums in large systems",
         journal="The Journal of Chemical Physics", volume="98", issue="12", pages="10089–10092", doi="10.1063/1.464397"),
    dict(key="Essmann1995", role="pme", authors=["Essmann, U.", "Perera, L.", "Berkowitz, M. L.", "Darden, T.", "Lee, H.", "Pedersen, L. G."],
         year=1995, title="A smooth particle mesh Ewald method",
         journal="The Journal of Chemical Physics", volume="103", issue="19", pages="8577–8593", doi="10.1063/1.470117"),
    dict(key="Hess1997", role="lincs", authors=["Hess, B.", "Bekker, H.", "Berendsen, H. J. C.", "Fraaije, J. G. E. M."],
         year=1997, title="LINCS: A linear constraint solver for molecular simulations",
         journal="Journal of Computational Chemistry", volume="18", issue="12", pages="1463–1472",
         doi="10.1002/(SICI)1096-987X(199709)18:12<1463::AID-JCC4>3.0.CO;2-H"),
    dict(key="Bussi2007", role="vrescale", authors=["Bussi, G.", "Donadio, D.", "Parrinello, M."],
         year=2007, title="Canonical sampling through velocity rescaling", journal="The Journal of Chemical Physics",
         volume="126", issue="1", pages="014101", doi="10.1063/1.2408420"),
    dict(key="Bernetti2020", role="crescale", authors=["Bernetti, M.", "Bussi, G."],
         year=2020, title="Pressure control using stochastic cell rescaling", journal="The Journal of Chemical Physics",
         volume="153", issue="11", pages="114107", doi="10.1063/5.0020514"),
    dict(key="Lee2016", role="charmmgui", authors=["Lee, J.", "Cheng, X.", "Swails, J. M.", "Yeom, M. S.", "Eastman, P. K.", "Lemkul, J. A."],
         etal=True, year=2016,
         title="CHARMM-GUI Input Generator for NAMD, GROMACS, AMBER, OpenMM, and CHARMM/OpenMM simulations using the CHARMM36 additive force field",
         journal="Journal of Chemical Theory and Computation", volume="12", issue="1", pages="405–413", doi="10.1021/acs.jctc.5b00935"),
    dict(key="Braun2018", role="practice", authors=["Braun, E.", "Gilmer, J.", "Mayes, H. B.", "Mobley, D. L.", "Monroe, J. I.", "Prasad, S.", "Zuckerman, D. M."],
         year=2018, title="Best practices for foundations in molecular simulations [Article v1.0]",
         journal="Living Journal of Computational Molecular Science", volume="1", issue="1", pages="5957", doi="10.33011/livecoms.1.1.5957"),
]

GRUPOS_REF = [  # (role, Spanish label, English label)
    ("gromacs", "Motor de simulación", "Simulation engine"),
    ("ff", "Campo de fuerza de la proteína (AMBER99SB-ILDN)", "Protein force field (AMBER99SB-ILDN)"),
    ("water", "Modelo de agua (TIP3P)", "Water model (TIP3P)"),
    ("gaff", "Campo de fuerza del ligando (GAFF2)", "Ligand force field (GAFF2)"),
    ("bcc", "Cargas parciales del ligando (AM1-BCC)", "Ligand partial charges (AM1-BCC)"),
    ("amber", "AmberTools (antechamber, sqm)", "AmberTools (antechamber, sqm)"),
    ("acpype", "Conversión de la topología del ligando a GROMACS", "Ligand topology conversion to GROMACS"),
    ("obabel", "Percepción química y protonación del ligando", "Ligand chemistry perception and protonation"),
    ("rdkit", "Manejo de la estructura del ligando", "Ligand structure handling"),
    ("pdbfixer", "Reparación de la proteína (PDBFixer, parte del ecosistema OpenMM)", "Protein repair (PDBFixer, part of the OpenMM ecosystem)"),
    ("pdb2pqr", "Asignación de protonación de la proteína", "Protein protonation assignment"),
    ("propka", "Predicción de pKa", "pKa prediction"),
    ("pme", "Electrostática de largo alcance (PME)", "Long-range electrostatics (PME)"),
    ("lincs", "Restricción de enlaces con H (LINCS)", "H-bond constraints (LINCS)"),
    ("vrescale", "Termostato (V-rescale)", "Thermostat (V-rescale)"),
    ("crescale", "Barostato (C-rescale)", "Barostat (C-rescale)"),
    ("charmmgui", "Protocolo y nombres de archivo de equilibrado", "Equilibration protocol and file naming"),
    ("practice", "Buenas prácticas de preparación y equilibrado", "Best practices for setup and equilibration"),
]


def _cita_corta(r):
    a = r["authors"]
    if r.get("software"):
        return "RDKit"
    fam = [x.split(",")[0] for x in a]
    if len(a) == 1:
        s = fam[0]
    elif len(a) == 2 and not r.get("etal"):
        s = f"{fam[0]} & {fam[1]}"
    else:
        s = f"{fam[0]} et al."
    return f"{s}, {r['year']}"


def cita(*keys):
    """In-text citation, e.g. (Abraham et al., 2015; Bussi et al., 2007)."""
    d = {r["key"]: r for r in REFERENCIAS}
    return "(" + "; ".join(_cita_corta(d[k]) for k in keys) + ")"


def apa(r):
    a = r["authors"]
    if r.get("software"):
        return f"{a[0]}. {r['title']}. {r['journal']}. https://doi.org/{r['doi']}"
    if r.get("etal"):
        aut = ", ".join(a) + ", et al."
    elif len(a) == 1:
        aut = a[0]
    else:
        aut = ", ".join(a[:-1]) + ", & " + a[-1]
    vol = f"*{r['journal']}*, *{r['volume']}*" + (f"({r['issue']})" if r.get("issue") else "") + f", {r['pages']}"
    return f"{aut} ({r['year']}). {r['title']}. {vol}. https://doi.org/{r['doi']}"


def bibtex():
    out = []
    for r in REFERENCIAS:
        if r.get("software"):
            out.append(f"@misc{{{r['key']},\n  author = {{{{RDKit contributors}}}},\n  title = {{{r['title']}}},\n"
                       f"  howpublished = {{\\url{{https://www.rdkit.org}}}},\n  doi = {{{r['doi']}}}\n}}")
            continue
        aut = " and ".join(r["authors"]) + (" and others" if r.get("etal") else "")
        campos = [f"  author = {{{aut}}}", f"  title = {{{{{r['title']}}}}}", f"  journal = {{{r['journal']}}}",
                  f"  year = {{{r['year']}}}", f"  volume = {{{r['volume'].replace('–', '--')}}}"]
        if r.get("issue"):
            campos.append(f"  number = {{{r['issue']}}}")
        campos += [f"  pages = {{{r['pages'].replace('–', '--')}}}", f"  doi = {{{r['doi']}}}"]
        out.append(f"@article{{{r['key']},\n" + ",\n".join(campos) + "\n}")
    return "\n\n".join(out) + "\n"


def referencias_md():
    d = {}
    for r in REFERENCIAS:
        d.setdefault(r["role"], []).append(r)
    s = ""
    for role, es, en in GRUPOS_REF:
        s += f"\n**{tr(es, en)}**\n" + "".join(f"- {apa(r)}\n" for r in d.get(role, []))
    return s


# =====================================================================
# 8. DOCUMENTATION
# =====================================================================
def metodo_md():
    if LANG == "es":
        return f"""
**Proteína.** Se conservan las cadenas elegidas; PDBFixer {cita('Eastman2024')} añade los átomos pesados faltantes y reemplaza
residuos no estándar (p. ej., MSE → MET). Los huecos de residuos ausentes no se modelan: se tratan como extremos de cadena.
PDB2PQR {cita('Dolinsky2004', 'Jurrus2018')} con PROPKA {cita('Olsson2011')} asigna el estado de protonación de cada residuo al pH
elegido (HID/HIE/HIP, ASH, GLH, LYN, CYX) y `gmx pdb2gmx` genera la topología AMBER99SB-ILDN {cita('Hornak2006', 'LindorffLarsen2010')}
con agua TIP3P {cita('Jorgensen1983')}.

**Ligando.** Se usa la química del SDF/MOL2 del docking (o la SMILES de plantilla) con las coordenadas de la pose, procesada con
RDKit y Open Babel {cita('OBoyle2011')}; se añaden los hidrógenos y ACPYPE {cita('SousaDaSilva2012')} con antechamber de
AmberTools {cita('Case2023')} asigna parámetros GAFF2 {cita('Wang2004')} y cargas AM1-BCC {cita('Jakalian2000', 'Jakalian2002')}.

**Sistema.** Caja (dodecaedro rómbico por defecto) con 1.2 nm entre el soluto y el borde, agua TIP3P, NaCl 0.15 M (o KCl, para
proteínas intracelulares) y los contraiones necesarios para neutralizar. El índice incluye los grupos `SOLU` (proteína + ligando)
y `SOLV` (agua + iones), y las etapas siguen los nombres de CHARMM-GUI {cita('Lee2016')}.

**Protocolo.**
| Archivo | Etapa | Detalles |
|---|---|---|
| `step4.0_minimization.mdp` | Minimización | descenso más pronunciado, Fmax < 1000 kJ mol⁻¹ nm⁻¹, restricciones de posición |
| `step4.1_equilibration.mdp` | NVT | 125 ps, dt 1 fs, V-rescale {cita('Bussi2007')} a 310 K, restricciones de posición |
| `step4.2_equilibration.mdp` | NPT (opcional) | 1 ns, dt 2 fs, C-rescale {cita('Bernetti2020')} a 1 bar, restricciones de posición |
| `step5_production.mdp` | Producción NPT | 250 ns por defecto, dt 2 fs, V-rescale + C-rescale, sin restricciones |

Parámetros comunes: esquema Verlet, PME {cita('Darden1993', 'Essmann1995')}, cortes de 1.0 nm, corrección de dispersión y enlaces
con H restringidos con LINCS {cita('Hess1997')}. Simulación con GROMACS {cita('Abraham2015')}; el protocolo de equilibrado sigue
las recomendaciones de Braun et al. (2018). Los `.mdp` solo usan opciones válidas en GROMACS 2021 o superior.

**Por qué no se entregan `.tpr`.** `grompp` se ejecuta en el clúster: los `.tpr` de una versión más nueva de GROMACS no se pueden
leer en una más antigua. La plataforma sí ejecuta `grompp` localmente para verificar que todo es válido.
"""
    return f"""
**Protein.** The selected chains are kept; PDBFixer {cita('Eastman2024')} adds missing heavy atoms and replaces non-standard
residues (e.g. MSE → MET). Gaps of missing residues are not modelled: they are treated as chain ends. PDB2PQR
{cita('Dolinsky2004', 'Jurrus2018')} with PROPKA {cita('Olsson2011')} assigns the protonation state of every residue at the chosen pH
(HID/HIE/HIP, ASH, GLH, LYN, CYX) and `gmx pdb2gmx` builds the AMBER99SB-ILDN topology {cita('Hornak2006', 'LindorffLarsen2010')}
with TIP3P water {cita('Jorgensen1983')}.

**Ligand.** The chemistry of the docking SDF/MOL2 (or the template SMILES) is used with the coordinates of the pose, handled with
RDKit and Open Babel {cita('OBoyle2011')}; hydrogens are added and ACPYPE {cita('SousaDaSilva2012')} with antechamber from
AmberTools {cita('Case2023')} assigns GAFF2 parameters {cita('Wang2004')} and AM1-BCC charges {cita('Jakalian2000', 'Jakalian2002')}.

**System.** Box (rhombic dodecahedron by default) with 1.2 nm between the solute and the box edge, TIP3P water, 0.15 M NaCl (or
KCl, for intracellular proteins) and the counter-ions needed for neutrality. The index file contains the `SOLU` (protein + ligand)
and `SOLV` (water + ions) groups, and the stages follow the CHARMM-GUI file naming {cita('Lee2016')}.

**Protocol.**
| File | Stage | Details |
|---|---|---|
| `step4.0_minimization.mdp` | Minimization | steepest descent, Fmax < 1000 kJ mol⁻¹ nm⁻¹, position restraints |
| `step4.1_equilibration.mdp` | NVT | 125 ps, dt 1 fs, V-rescale {cita('Bussi2007')} at 310 K, position restraints |
| `step4.2_equilibration.mdp` | NPT (optional) | 1 ns, dt 2 fs, C-rescale {cita('Bernetti2020')} at 1 bar, position restraints |
| `step5_production.mdp` | NPT production | 250 ns by default, dt 2 fs, V-rescale + C-rescale, unrestrained |

Common settings: Verlet scheme, PME {cita('Darden1993', 'Essmann1995')}, 1.0 nm cut-offs, dispersion correction and H-bond
constraints with LINCS {cita('Hess1997')}. Simulations run with GROMACS {cita('Abraham2015')}; the equilibration protocol follows
the recommendations of Braun et al. (2018). The `.mdp` files only use options valid in GROMACS 2021 or newer.

**Why no `.tpr` files are shipped.** `grompp` is run on the cluster: `.tpr` files written by a newer GROMACS cannot be read by an
older one. The platform still runs `grompp` locally to check that everything is valid.
"""


def parrafo_metodos(R):
    """A methods paragraph with the actual parameters of this system, ready to adapt for a paper (one line, easy to paste)."""
    return " ".join(_parrafo_metodos(R).split())


def _parrafo_metodos(R):
    o = R["options"]; s = R["system"]; l = R["ligand"]
    caja_es = {"dodecahedron": "dodecaédrica rómbica", "cubic": "cúbica", "triclinic": "rectangular"}.get(o["box"], o["box"])
    caja_en = {"dodecahedron": "rhombic dodecahedron", "cubic": "cubic", "triclinic": "rectangular"}.get(o["box"], o["box"])
    ff = {"amber99sb-ildn": "AMBER99SB-ILDN", "amber99sb": "AMBER99SB", "amber03": "AMBER03"}.get(o["ff"], o["ff"])
    ffc = cita("Hornak2006", "LindorffLarsen2010") if o["ff"] == "amber99sb-ildn" else cita("Hornak2006") if o["ff"] == "amber99sb" else ""
    ion = s.get("cation", "Na+")
    npt_es = f" y {o['npt_ps'] / 1000:g} ns en NPT a 1 bar con el barostato C-rescale {cita('Bernetti2020')}" if o["npt"] else ""
    npt_en = f" and {o['npt_ps'] / 1000:g} ns in the NPT ensemble at 1 bar with the C-rescale barostat {cita('Bernetti2020')}" if o["npt"] else ""
    if LANG == "es":
        return f"""El complejo proteína–ligando obtenido por docking se preparó con {APP_NAME} {APP_VERSION}. Se añadieron los átomos
pesados faltantes de la proteína con PDBFixer {cita('Eastman2024')} y los estados de protonación a pH {o['ph']} se asignaron con
PDB2PQR {cita('Dolinsky2004', 'Jurrus2018')} y PROPKA {cita('Olsson2011')}. La proteína se describió con el campo de fuerza {ff} {ffc}
y el ligando (carga neta {l['net_charge']:+d}) con GAFF2 {cita('Wang2004')} y cargas AM1-BCC {cita('Jakalian2000', 'Jakalian2002')},
generados con antechamber {cita('Case2023')} y ACPYPE {cita('SousaDaSilva2012')}. El sistema se colocó en una caja {caja_es} con
{o['distance']} nm entre el soluto y el borde, se solvató con {s['waters']} moléculas de agua TIP3P {cita('Jorgensen1983')} y se
añadieron {o['salt']} {o['conc']} M y los contraiones necesarios para neutralizarlo ({s['n_cation']} {ion} y {s['Cl-']} Cl⁻;
{s['atoms']} átomos en total). Tras una minimización de energía por descenso más pronunciado, el sistema se equilibró
{o['nvt_ps']} ps en NVT a {o['temp']} K con el termostato V-rescale {cita('Bussi2007')}{npt_es}, con restricciones de posición en los
átomos pesados del soluto. La producción se realizó durante {o['ns']:g} ns en NPT ({o['temp']} K, 1 bar) con GROMACS
{cita('Abraham2015')}, paso de integración de 2 fs, enlaces con hidrógeno restringidos con LINCS {cita('Hess1997')}, electrostática
de largo alcance por PME {cita('Darden1993', 'Essmann1995')} y cortes de 1.0 nm.
"""
    return f"""The protein–ligand complex obtained by docking was prepared with {APP_NAME} {APP_VERSION}. Missing heavy atoms of the protein
were added with PDBFixer {cita('Eastman2024')}, and protonation states at pH {o['ph']} were assigned with PDB2PQR
{cita('Dolinsky2004', 'Jurrus2018')} and PROPKA {cita('Olsson2011')}. The protein was described with the {ff} force field {ffc} and
the ligand (net charge {l['net_charge']:+d}) with GAFF2 {cita('Wang2004')} and AM1-BCC charges {cita('Jakalian2000', 'Jakalian2002')},
generated with antechamber {cita('Case2023')} and ACPYPE {cita('SousaDaSilva2012')}. The system was placed in a {caja_en} box with
{o['distance']} nm between the solute and the box edge, solvated with {s['waters']} TIP3P water molecules {cita('Jorgensen1983')},
and {o['conc']} M {o['salt']} plus the counter-ions required for neutrality were added ({s['n_cation']} {ion} and {s['Cl-']} Cl⁻;
{s['atoms']} atoms in total). After steepest-descent energy minimization, the system was equilibrated for {o['nvt_ps']} ps in the
NVT ensemble at {o['temp']} K with the V-rescale thermostat {cita('Bussi2007')}{npt_en}, with position restraints on the solute heavy atoms.
Production was run for {o['ns']:g} ns in the NPT ensemble ({o['temp']} K, 1 bar) with GROMACS {cita('Abraham2015')}, a 2 fs time
step, LINCS constraints on bonds involving hydrogen {cita('Hess1997')}, PME long-range electrostatics {cita('Darden1993', 'Essmann1995')}
and 1.0 nm cut-offs.
"""


def metodos_y_citas(R):
    return (f"# {tr('Métodos y referencias', 'Methods and references')} — {APP_NAME} {APP_VERSION}\n\n"
            f"## {tr('Párrafo de métodos (adáptalo a tu artículo)', 'Methods paragraph (adapt it to your paper)')}\n\n"
            f"{parrafo_metodos(R)}\n\n"
            f"## {tr('Detalle del protocolo', 'Protocol details')}\n{metodo_md()}\n"
            f"## {tr('Referencias', 'References')}\n"
            f"{tr('El archivo references.bib contiene las mismas referencias en BibTeX.', 'references.bib contains the same references in BibTeX format.')}\n"
            f"{referencias_md()}")


def leeme(R, cfg, nombre_script, ns):
    s = R["system"]; l = R["ligand"]; o = R["options"]; n = nombres()
    av = "\n".join(f"- {a}" for a in R.get("warnings", [])) or tr("- ninguno", "- none")
    prot = R["protein"]["protonation"] or tr("estados estándar", "standard states")
    if LANG == "es":
        return f"""{APP_NAME} {APP_VERSION} — sistema preparado el {datetime.now().strftime('%Y-%m-%d %H:%M')}
================================================================================

SISTEMA
  Átomos totales ............ {s['atoms']}
  Aguas TIP3P ............... {s['waters']}
  Iones ..................... {s['n_cation']} {s['cation']} / {s['Cl-']} Cl-  ({o['salt']} {o['conc']} M + neutralización)
  Caja ...................... {o['box']} · {o['distance']} nm del soluto al borde · {s['volume_nm3']} nm3
  Proteína .................. {o['ff']} · protonación PROPKA a pH {o['ph']}: {prot}
  Ligando ................... GAFF2 + AM1-BCC · carga neta {l['net_charge']:+d} · {l['method']}
  Temperatura ............... {o['temp']} K · presión 1 bar
  Producción ................ {ns:g} ns ({R['nsteps_production']} pasos de 2 fs)

AVISOS
{av}

ARCHIVOS
  step3_input.gro ........... sistema solvatado y neutralizado (coordenadas iniciales)
  topol.top + *.itp ......... topología (proteína, ligando LIG, agua e iones)
  index.ndx ................. grupos por defecto + SOLU (proteína+ligando) y SOLV (agua+iones)
  step4.0_minimization.mdp .. minimización
  step4.1_equilibration.mdp . equilibrado NVT
  step4.2_equilibration.mdp . equilibrado NPT (si se incluyó)
  step5_production.mdp ...... producción
  {nombre_script:<26}  script SLURM (minimización → equilibrado → producción)
  {n['continuar']:<26}  continúa la producción desde step5.cpt si se acabó el tiempo del job
  {n['metodos']:<26}  párrafo de métodos y referencias para tu artículo
  references.bib ............ referencias en BibTeX

CÓMO CORRERLA
  scp <este_zip> usuario@clúster:~/   →   unzip <este_zip> && cd {cfg.get('job_name')}
  sbatch {nombre_script}
  Si la producción no terminó (step5.log no dice "Finished mdrun"):  sbatch {n['continuar']}   (repetir hasta terminar)

CÓMO CITAR
  Cita las referencias de {n['metodos']} (motor, campos de fuerza, cargas y herramientas de preparación).
"""
    return f"""{APP_NAME} {APP_VERSION} — system prepared on {datetime.now().strftime('%Y-%m-%d %H:%M')}
================================================================================

SYSTEM
  Total atoms ............... {s['atoms']}
  TIP3P waters .............. {s['waters']}
  Ions ...................... {s['n_cation']} {s['cation']} / {s['Cl-']} Cl-  ({o['conc']} M {o['salt']} + neutralization)
  Box ....................... {o['box']} · {o['distance']} nm solute–edge distance · {s['volume_nm3']} nm3
  Protein ................... {o['ff']} · PROPKA protonation at pH {o['ph']}: {prot}
  Ligand .................... GAFF2 + AM1-BCC · net charge {l['net_charge']:+d} · {l['method']}
  Temperature ............... {o['temp']} K · pressure 1 bar
  Production ................ {ns:g} ns ({R['nsteps_production']} steps of 2 fs)

WARNINGS
{av}

FILES
  step3_input.gro ........... solvated, neutralized system (starting coordinates)
  topol.top + *.itp ......... topology (protein, ligand LIG, water and ions)
  index.ndx ................. default groups + SOLU (protein+ligand) and SOLV (water+ions)
  step4.0_minimization.mdp .. minimization
  step4.1_equilibration.mdp . NVT equilibration
  step4.2_equilibration.mdp . NPT equilibration (if included)
  step5_production.mdp ...... production
  {nombre_script:<26}  SLURM script (minimization → equilibration → production)
  {n['continuar']:<26}  continues the production run from step5.cpt if the job ran out of time
  {n['metodos']:<26}  methods paragraph and references for your paper
  references.bib ............ references in BibTeX format

HOW TO RUN
  scp <this_zip> user@cluster:~/   →   unzip <this_zip> && cd {cfg.get('job_name')}
  sbatch {nombre_script}
  If the production did not finish (step5.log does not say "Finished mdrun"):  sbatch {n['continuar']}   (repeat until done)

HOW TO CITE
  Cite the references listed in {n['metodos']} (engine, force fields, charges and preparation tools).
"""
