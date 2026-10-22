"""
MD-Prep Studio — protein–ligand molecular dynamics setup for GROMACS
Run:  streamlit run app.py
"""
import json
import re
import time
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import mdprep as M

BASE = Path(__file__).resolve().parent
AZUL = "#1f5aa6"

st.set_page_config(page_title="MD-Prep Studio", page_icon="🧬", layout="wide")
st.markdown(f"""<style>
.block-container {{padding-top: 1.4rem; max-width: 1350px;}}
.kpi {{border:1px solid rgba(31,90,166,.25); border-radius:12px; padding:12px 16px; background:rgba(31,90,166,.04)}}
.kpi .v {{font-size:1.7rem; font-weight:700; color:{AZUL}; line-height:1.1}}
.kpi .l {{font-size:.75rem; opacity:.75; text-transform:uppercase; letter-spacing:.05em}}
.sub {{opacity:.8; margin-top:-.5rem; margin-bottom:1rem}}
</style>""", unsafe_allow_html=True)

# ---------------------------------------------------------------- language
IDIOMAS = {"en": "English", "es": "Español"}
if "lang" not in st.session_state:
    st.session_state["lang"] = M.CONFIG["lang"]
M.set_lang(st.session_state["lang"])
T = M.tr

TRABAJO = M.carpeta_trabajo()
TRABAJO.mkdir(parents=True, exist_ok=True)


def kpi(col, v, l):
    col.markdown(f"<div class='kpi'><div class='v'>{v}</div><div class='l'>{l}</div></div>", unsafe_allow_html=True)


def num(x):
    return f"{x:,}".replace(",", "." if M.LANG == "es" else ",")


def guardar(up, carpeta):
    carpeta.mkdir(parents=True, exist_ok=True)
    p = carpeta / re.sub(r"[^A-Za-z0-9_.\-]+", "_", up.name)
    p.write_bytes(up.getvalue())
    return p


def nombre_job(s):
    s = re.sub(r"[^A-Za-z0-9_\-]+", "_", s).strip("_")
    return s[:40] or "MD_complex"


def en_wsl():
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return False


PAGINAS = {"prep": T("Preparar sistema", "Prepare system"), "lista": T("Sistemas preparados", "Prepared systems"),
           "metodo": T("Método y citas", "Method and citations")}

with st.sidebar:
    st.markdown("## 🧬 MD-Prep Studio")
    st.caption(T("Del complejo post-docking a una dinámica molecular en caja de agua lista para el clúster (GROMACS).",
                 "From a post-docking complex to a solvated molecular dynamics system ready for your cluster (GROMACS)."))
    pagina = st.radio(T("Sección", "Section"), list(PAGINAS), format_func=PAGINAS.get, label_visibility="collapsed")
    st.divider()
    nuevo = st.selectbox("🌐 " + T("Idioma", "Language"), list(IDIOMAS), format_func=IDIOMAS.get,
                         index=list(IDIOMAS).index(st.session_state["lang"]))
    if nuevo != st.session_state["lang"]:
        st.session_state["lang"] = nuevo
        st.rerun()
    st.caption(T("Resultados en:", "Results in:") + f"\n`{TRABAJO}`")
    if en_wsl():
        st.caption(T("Desde el Explorador de Windows:", "From Windows File Explorer:") +
                   f"\n`\\\\wsl$\\MD-Prep{str(TRABAJO).replace('/', chr(92))}`")
    st.caption(f"v{M.APP_VERSION}")

# ============================================================================
if pagina == "prep":
    st.title(T("Preparar una dinámica molecular", "Prepare a molecular dynamics simulation"))
    st.markdown("<div class='sub'>" + T(
        "Sube el complejo proteína–ligando del docking. La plataforma prepara la proteína (AMBER99SB-ILDN) y el ligando (GAFF2, "
        "cargas AM1-BCC), lo solvata en agua TIP3P con NaCl o KCl, y genera los archivos y el script SLURM para el clúster.",
        "Upload the protein–ligand complex from docking. The platform prepares the protein (AMBER99SB-ILDN) and the ligand (GAFF2, "
        "AM1-BCC charges), solvates it in TIP3P water with NaCl or KCl, and writes the GROMACS files and the SLURM script for your cluster.")
        + "</div>", unsafe_allow_html=True)

    # ---------------------------------------------------------------- 1. files
    st.subheader(T("1 · Complejo post-docking", "1 · Post-docking complex"))
    c1, c2 = st.columns(2)
    up = c1.file_uploader(T("Complejo proteína–ligando (.pdb)", "Protein–ligand complex (.pdb)"), type=["pdb"])
    up_lig = c2.file_uploader(T("Ligando con su química correcta (.sdf o .mol2) — recomendado",
                                "Ligand with correct chemistry (.sdf or .mol2) — recommended"), type=["sdf", "mol2", "mol"],
                              help=T("El SDF de la pose del docking. Asegura los órdenes de enlace y la carga del ligando.",
                                     "The SDF of the docked pose. It guarantees the correct bond orders and charge of the ligand."))
    if not up:
        st.info(T("Sube el PDB del complejo para empezar. Debe contener la proteína y el ligando en la pose del docking.",
                  "Upload the PDB of the complex to start. It must contain the protein and the ligand in its docked pose."))
        st.stop()
    sesion = TRABAJO / "_input" / datetime.now().strftime("%Y%m%d")
    pdb = guardar(up, sesion)
    lig_file = guardar(up_lig, sesion) if up_lig else None
    hets, cadenas = M.residuos_hetero(pdb)
    if not cadenas:
        st.error(T("No se encontraron aminoácidos en el PDB.", "No amino acids were found in the PDB.")); st.stop()
    if not hets:
        st.error(T("No se encontró ningún ligando (residuo HETATM) en el PDB.", "No ligand (HETATM residue) was found in the PDB.")); st.stop()
    c1, c2 = st.columns(2)
    het_i = c1.selectbox(T("Ligando", "Ligand"), range(len(hets)),
                         format_func=lambda i: f"{hets[i]['resname']} · {T('cadena', 'chain')} {hets[i]['chain']} · "
                                               f"{T('residuo', 'residue')} {hets[i]['resid']} · {hets[i]['n_atoms']} {T('átomos', 'atoms')}",
                         index=next((i for i, h in enumerate(hets) if h["resname"] in ("LIG", "UNL", "UNK", "MOL")), 0))
    cads = c2.multiselect(T("Cadenas de proteína", "Protein chains"), sorted(cadenas), default=sorted(cadenas),
                          format_func=lambda c: f"{c} ({cadenas[c]} {T('átomos', 'atoms')})")
    smiles = ""
    if not lig_file:
        smiles = st.text_input(T("SMILES del ligando (opcional, si no subes el SDF)", "Ligand SMILES (optional, if you do not upload the SDF)"),
                               help=T("Se usa como plantilla para asignar los órdenes de enlace a la pose del PDB. Sin SDF ni SMILES, "
                                      "la química se infiere con Open Babel a partir de la geometría.",
                                      "Used as a template to assign bond orders to the PDB pose. Without SDF or SMILES, the chemistry "
                                      "is inferred by Open Babel from the geometry."))

    # ---------------------------------------------------------------- 2. options
    st.subheader(T("2 · Sistema", "2 · System"))
    c1, c2, c3, c4 = st.columns(4)
    ph = c1.number_input(T("pH (proteína)", "pH (protein)"), 0.0, 14.0, 7.4, 0.1,
                         help=T("PROPKA asigna el estado de protonación de cada residuo a este pH.",
                                "PROPKA assigns the protonation state of each residue at this pH."))
    prot_lig = c2.selectbox(T("Ligando", "Ligand"), ["keep", "ph"],
                            format_func={"keep": T("Mantener la del archivo", "Keep as in the file"),
                                         "ph": T("Protonar a pH 7.4", "Protonate at pH 7.4")}.get,
                            help=T("Mantén la del docking si ya la ajustaste; si no, protónalo (p. ej., aminas → NH⁺).",
                                   "Keep the docking state if you already set it; otherwise protonate it (e.g. amines → NH⁺)."))
    caja = c3.selectbox(T("Caja", "Box"), ["dodecahedron", "cubic", "triclinic"],
                        format_func={"dodecahedron": T("Dodecaedro rómbico (menos agua)", "Rhombic dodecahedron (less water)"),
                                     "cubic": T("Cúbica", "Cubic"), "triclinic": T("Rectangular", "Rectangular")}.get)
    dist = c4.number_input(T("Distancia soluto–borde (nm)", "Solute–edge distance (nm)"), 0.8, 2.0, 1.2, 0.1,
                           help=T("1.2 nm: margen recomendado para simulaciones largas (la proteína puede rotar o abrir lazos). "
                                  "1.0 nm es el mínimo habitual.",
                                  "1.2 nm: recommended margin for long simulations (the protein may rotate or open loops). "
                                  "1.0 nm is the usual minimum."))
    c0, c1, c2, c3, c4 = st.columns(5)
    sal = c0.selectbox(T("Sal", "Salt"), ["NaCl", "KCl"],
                       help=T("NaCl: medio extracelular/plasma (lo más usado). KCl: proteínas intracelulares (citosol rico en K⁺).",
                              "NaCl: extracellular medium/plasma (most common). KCl: intracellular proteins (K⁺-rich cytosol)."))
    conc = c1.number_input(f"{sal} (mol/L)", 0.0, 1.0, 0.15, 0.01,
                           help=T("0.15 M ≈ fuerza iónica fisiológica. Además se añaden los iones necesarios para neutralizar.",
                                  "0.15 M ≈ physiological ionic strength. Counter-ions for neutrality are added on top."))
    temp = c2.number_input(T("Temperatura (K)", "Temperature (K)"), 250, 400, 310, 1)
    ff = c3.selectbox(T("Campo de fuerza (proteína)", "Force field (protein)"), ["amber99sb-ildn", "amber99sb", "amber03"])
    carga_man = c4.text_input(T("Carga neta del ligando (opcional)", "Ligand net charge (optional)"), "",
                              help=T("Déjalo vacío para calcularla a partir de la estructura.", "Leave empty to compute it from the structure."))

    st.subheader(T("3 · Protocolo", "3 · Protocol"))
    c1, c2, c3, c4 = st.columns(4)
    ns = c1.number_input(T("Producción (ns)", "Production (ns)"), 1.0, 5000.0, 250.0, 10.0)
    nvt_ps = c2.number_input(T("Equilibrado NVT step4.1 (ps)", "NVT equilibration step4.1 (ps)"), 50, 2000, 125, 25)
    npt = c3.checkbox(T("Añadir equilibrado NPT step4.2", "Add NPT equilibration step4.2"), True,
                      help=T("Recomendado: 1 ns a presión constante con restricciones antes de la producción.",
                             "Recommended: 1 ns at constant pressure with restraints before production."))
    npt_ps = c3.number_input("NPT (ps)", 100, 10000, 1000, 100, disabled=not npt)
    guardar_ps = c4.number_input(T("Guardar coordenadas cada (ps)", "Save coordinates every (ps)"), 1.0, 1000.0, 10.0, 1.0)
    grupo_xtc = c4.selectbox(T("Guardar en la trayectoria", "Atoms saved in the trajectory"), ["System", "SOLU"],
                             format_func={"System": T("Todo el sistema", "Whole system"),
                                          "SOLU": T("Solo proteína + ligando (archivo mucho más pequeño)",
                                                    "Protein + ligand only (much smaller file)")}.get)
    nframes = int(ns * 1000 / guardar_ps)
    st.caption(T(f"Producción: {num(int(ns * 1000 / 0.002))} pasos de 2 fs · {num(nframes)} fotogramas en step5.xtc",
                 f"Production: {num(int(ns * 1000 / 0.002))} steps of 2 fs · {num(nframes)} frames in step5.xtc"))

    # ---------------------------------------------------------------- 4. cluster
    st.subheader(T("4 · Script para el clúster (SLURM)", "4 · Cluster script (SLURM)"))
    d = M.SLURM_PREDETERMINADO
    nm = M.nombres()
    c1, c2, c3, c4 = st.columns(4)
    job = c1.text_input(T("Nombre del job", "Job name"), nombre_job(Path(up.name).stem))
    part = c2.text_input(T("Partición", "Partition"), d["partition"])
    ntasks = c3.number_input(T("ntasks (núcleos)", "ntasks (cores)"), 1, 256, int(d["ntasks"]))
    gpus = c4.number_input("GPUs", 0, 8, int(d["gpus"]))
    c1, c2, c3, c4 = st.columns(4)
    tiempo = c1.text_input(T("Tiempo máximo (hh:mm:ss)", "Wall time (hh:mm:ss)"), d["time"])
    nodes = c2.number_input(T("Nodos", "Nodes"), 1, 16, int(d["nodes"]))
    out_log = c3.text_input("--output", nm["out"])
    err_log = c4.text_input("--error", nm["err"])
    modulos = st.text_area(T("Módulos / entorno", "Modules / environment"), d["modules"], height=70,
                           help=T("Líneas que cargan GROMACS en tu clúster (module load …, source …).",
                                  "Lines that load GROMACS on your cluster (module load …, source …)."))
    c1, c2, c3 = st.columns(3)
    nombre_script = c1.text_input(T("Nombre del script", "Script name"), "gmxgpu.sh")
    maxh = c2.checkbox(T("Cortar ordenadamente antes del límite de tiempo (-maxh)", "Stop cleanly before the wall time (-maxh)"), bool(d.get("maxh", True)),
                       help=T(f"mdrun guarda un punto de control y termina unos minutos antes del límite, para poder continuar con {nm['continuar']}.",
                              f"mdrun writes a checkpoint and stops a few minutes before the limit, so you can continue with {nm['continuar']}."))
    gpu_full = c3.checkbox(T("Usar GPU también para PME, enlaces y actualización", "Also use the GPU for PME, bonded and update"),
                           bool(d.get("gpu_full", False)),
                           help=T("Añade -pme gpu -bonded gpu -update gpu. Suele ser 1.5–2× más rápido con GROMACS ≥ 2023.",
                                  "Adds -pme gpu -bonded gpu -update gpu. Usually 1.5–2× faster with GROMACS ≥ 2023."))
    with st.expander(T("Estimar cuántos envíos necesitará la producción", "Estimate how many job submissions the production needs")):
        c1, c2 = st.columns(2)
        nsdia = c1.number_input(T("Rendimiento esperado (ns/día)", "Expected performance (ns/day)"), 1.0, 2000.0, 100.0, 10.0,
                                help=T("Para ~50 000 átomos en una GPU moderna suele estar entre 80 y 200 ns/día. Usa el valor real de step5.log.",
                                       "For ~50,000 atoms on a modern GPU it is usually 80–200 ns/day. Use the real value from step5.log."))
        est = M.estimar_tiempo(ns, nsdia, M._horas(tiempo))
        c2.markdown(T(f"**{ns:g} ns a {nsdia:g} ns/día ≈ {est['hours']} h ({est['days']} días).**  \n"
                      f"Con un límite de {tiempo} se necesitarán unos **{est['jobs']} envío(s)**: el script principal y "
                      f"{est['continuations']} vez/veces `{nm['continuar']}`.",
                      f"**{ns:g} ns at {nsdia:g} ns/day ≈ {est['hours']} h ({est['days']} days).**  \n"
                      f"With a {tiempo} limit you will need about **{est['jobs']} submission(s)**: the main script and "
                      f"`{nm['continuar']}` {est['continuations']} time(s)."))
    cfg = {"job_name": job, "partition": part, "ntasks": int(ntasks), "gpus": int(gpus), "time": tiempo, "nodes": int(nodes),
           "output": out_log, "error": err_log, "modules": modulos, "maxh": maxh, "gpu_full": gpu_full, "continue_name": nm["continuar"]}
    with st.expander(T("Vista previa del script", "Script preview")):
        st.code(M.script_slurm(cfg, npt), language="bash")

    # ---------------------------------------------------------------- run
    st.divider()
    if st.button(T("Preparar sistema", "Prepare system"), type="primary"):
        carpeta = TRABAJO / f"{job}_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        opciones = {"chains": cads, "ligand_file": str(lig_file) if lig_file else None, "smiles": smiles.strip() or None,
                    "ph": ph, "ligand_ph": 7.4 if prot_lig == "ph" else None,
                    "manual_charge": int(carga_man) if carga_man.strip().lstrip("+-").isdigit() else None,
                    "box": caja, "distance": dist, "conc": conc, "salt": sal, "temp": temp, "ff": ff, "ns": ns, "nvt_ps": nvt_ps,
                    "npt": npt, "npt_ps": npt_ps, "save_ps": guardar_ps, "xtc_group": grupo_xtc}
        bar = st.progress(0.0, text=T("Iniciando…", "Starting…"))
        t0 = time.time()
        try:
            R = M.preparar_sistema(pdb, hets[het_i], carpeta, opciones, progreso=lambda f, t: bar.progress(min(f, 1.0), text=t))
        except Exception as e:
            st.error(T("**No se pudo preparar el sistema:** ", "**The system could not be prepared:** ") + str(e))
            with st.expander(T("Detalle técnico", "Technical details")):
                st.code(traceback.format_exc())
                lg = carpeta / nm["log"]
                if lg.exists():
                    st.code(lg.read_text()[-6000:])
            st.stop()
        script = M.script_slurm(cfg, npt)
        cont = M.script_slurm(cfg, npt, continuacion=True)
        readme = M.leeme(R, cfg, nombre_script, ns)
        zp = carpeta.parent / f"{carpeta.name}.zip"
        M.paquete_cluster(carpeta, script, cont, nombre_script, readme, M.metodos_y_citas(R), zp, job)
        st.session_state["ultimo"] = {"carpeta": str(carpeta), "zip": str(zp), "R": R, "tiempo": time.time() - t0, "job": job,
                                      "script": nombre_script}

    u = st.session_state.get("ultimo")
    if u and Path(u["zip"]).exists():
        R = u["R"]; s = R["system"]
        st.success(T(f"Sistema listo en {u['tiempo']:.0f} s · ", f"System ready in {u['tiempo']:.0f} s · ") + f"`{u['carpeta']}`")
        for a in R.get("warnings", []):
            st.warning(a)
        c = st.columns(5)
        kpi(c[0], num(s["atoms"]), T("átomos", "atoms")); kpi(c[1], num(s["waters"]), T("aguas TIP3P", "TIP3P waters"))
        kpi(c[2], f"{s['n_cation']} / {s['Cl-']}", f"{s['cation']} / Cl⁻")
        kpi(c[3], f"{R['ligand']['net_charge']:+d}", T("carga del ligando", "ligand charge"))
        kpi(c[4], f"{R['options']['ns']:g} ns", T("producción", "production"))
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(T("**Ligando**", "**Ligand**"))
            L = R["ligand"]
            st.write({T("método", "method"): L["method"], T("carga neta", "net charge"): L["net_charge"],
                      T("carga esperada a pH 7.4", "expected charge at pH 7.4"): L["expected_charge_pH7.4"],
                      T("átomos", "atoms"): L["atoms"], T("residuo original", "original residue"): L["original_residue"]})
            st.markdown(T("**Proteína**", "**Protein**"))
            P = R["protein"]
            st.write({T("protonación (PROPKA)", "protonation (PROPKA)"): P["protonation"] or T("estados estándar", "standard states"),
                      T("átomos pesados añadidos", "heavy atoms added"): P["repair"]["heavy_atoms_added"],
                      T("huecos tratados como extremos", "gaps treated as chain ends"): len(P["gaps"])})
        with c2:
            st.markdown(T("**Verificación con `grompp` (como en el clúster)**", "**`grompp` check (as on the cluster)**"))
            filas = [{T("etapa", "stage"): k, T("advertencias", "warnings"): len(v["warnings"]), T("notas", "notes"): v["notes"],
                      T("carga total", "total charge"): v["total_charge"]} for k, v in R["verification"].items()]
            st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
            for k, v in R["verification"].items():
                for w in v["warnings"]:
                    st.caption(f"⚠️ {k}: {w}")
        zbytes = Path(u["zip"]).read_bytes()
        st.download_button(T("⬇️ Descargar paquete para el clúster", "⬇️ Download cluster package") + f" ({Path(u['zip']).name})", zbytes,
                           file_name=Path(u["zip"]).name, mime="application/zip", type="primary")
        z = Path(u["zip"]).name
        st.markdown(T(f"""**Cómo correrla en el clúster**
```bash
# 1. Sube el ZIP y descomprímelo en el clúster
scp {z} usuario@clúster:~/
ssh usuario@clúster
unzip {z} && cd {u['job']}
# 2. Lanza la simulación
sbatch {u['script']}
# 3. Si la producción no termina dentro del tiempo máximo, continúa desde el punto de control
sbatch {nm['continuar']}
```""", f"""**How to run it on the cluster**
```bash
# 1. Upload the ZIP and unzip it on the cluster
scp {z} user@cluster:~/
ssh user@cluster
unzip {z} && cd {u['job']}
# 2. Submit the simulation
sbatch {u['script']}
# 3. If the production does not finish within the wall time, continue from the checkpoint
sbatch {nm['continuar']}
```"""))
        t1, t2, t3, t4 = st.tabs([T("Script SLURM", "SLURM script"), "step5_production.mdp",
                                  T("Métodos y citas", "Methods and citations"), T("Estructura", "Structure")])
        with t1:
            st.code((Path(u["carpeta"]) / u["script"]).read_text(), language="bash")
        with t2:
            st.code((Path(u["carpeta"]) / "step5_production.mdp").read_text(), language="ini")
        with t3:
            st.caption(T("Este texto también va en el ZIP (con las referencias en BibTeX).", "This text is also in the ZIP (with BibTeX references)."))
            st.markdown(M.parrafo_metodos(R))
            st.download_button("references.bib", M.bibtex(), file_name="references.bib", key="bib_res")
        with t4:
            try:
                import py3Dmol
                gro = (Path(u["carpeta"]) / "step3_input.gro").read_text()
                v = py3Dmol.view(width=900, height=520); v.addModel(gro, "gro")
                v.setStyle({"cartoon": {"color": "spectrum"}})
                v.addStyle({"resn": "LIG"}, {"stick": {"colorscheme": "greenCarbon", "radius": 0.25}})
                v.addStyle({"resn": ["NA", "K"]}, {"sphere": {"radius": 0.8, "color": "purple"}})
                v.addStyle({"resn": "CL"}, {"sphere": {"radius": 0.8, "color": "green"}})
                v.addStyle({"resn": "SOL"}, {"line": {"opacity": 0.15, "color": "lightblue"}})
                v.zoomTo()
                html = v._make_html()
                (st.iframe(html, height=540) if hasattr(st, "iframe") else st.components.v1.html(html, height=540))
            except Exception as e:
                st.caption(T("Visor no disponible: ", "Viewer not available: ") + str(e))

# ============================================================================
elif pagina == "lista":
    st.title(PAGINAS["lista"])
    zips = sorted(TRABAJO.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        st.info(T("Aún no has preparado ningún sistema.", "You have not prepared any system yet."))
    for z in zips:
        carpeta = z.with_suffix("")
        rj = next((p for p in (carpeta / "prep_summary.json", carpeta / "resumen_preparacion.json") if p.exists()), None)
        R = json.loads(rj.read_text()) if rj else {}
        s = R.get("system", R.get("sistema", {}))
        o = R.get("options", R.get("opciones", {}))
        with st.expander(f"{z.stem} · {s.get('atoms', s.get('atomos', '?'))} {T('átomos', 'atoms')} · {o.get('ns', '?')} ns"):
            st.write({T("ligando", "ligand"): R.get("ligand", R.get("ligando")), T("sistema", "system"): s,
                      T("avisos", "warnings"): R.get("warnings", R.get("avisos"))})
            st.download_button(T("Descargar ZIP", "Download ZIP"), z.read_bytes(), file_name=z.name, key=f"dl_{z.name}")
            st.caption(T("Carpeta: ", "Folder: ") + f"`{carpeta}`")

# ============================================================================
else:
    st.title(PAGINAS["metodo"])
    st.markdown(T("Cada paquete incluye un **párrafo de métodos** con los parámetros reales del sistema, estas referencias y un "
                  "archivo `references.bib` para importarlas en Zotero, Mendeley o LaTeX.",
                  "Every package includes a **methods paragraph** with the actual parameters of the system, these references and a "
                  "`references.bib` file to import them into Zotero, Mendeley or LaTeX."))
    st.download_button("⬇️ references.bib", M.bibtex(), file_name="references.bib")
    st.subheader(T("Protocolo", "Protocol"))
    st.markdown(M.metodo_md())
    st.subheader(T("Referencias", "References"))
    st.markdown(M.referencias_md())
    st.subheader(T("Versiones instaladas", "Installed versions"))
    st.dataframe(pd.DataFrame([M.versiones()]).T.rename(columns={0: T("versión", "version")}), width="stretch")
