# MD-Prep Studio

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23577063.svg)](https://doi.org/10.5281/zenodo.23577063)

**Del complejo proteína–ligando del docking a una dinámica molecular lista para GROMACS, en pocos clics.**

MD-Prep Studio es una aplicación local: corre en tu computador y se abre en el navegador. Toma el complejo obtenido en el docking
y prepara un sistema solvatado y neutralizado para GROMACS, junto con el script SLURM para correr la simulación en un clúster. Usa
herramientas de código abierto consolidadas y los campos de fuerza y parámetros más usados en la literatura. Cada paquete incluye
además un **párrafo de métodos y las referencias** que debes citar en tu artículo.

Desarrollado en el Grupo de Investigación en Productos Naturales, Universidad Distrital Francisco José de Caldas (Bogotá, Colombia).

La interfaz y todos los archivos generados están en **español e inglés** (selector de idioma en la barra lateral).

## Instalación

### Windows 10 / 11
1. Ejecuta `MD-Prep_Studio_<versión>_Windows_ES.exe`. Si aparece SmartScreen: **Más información → Ejecutar de todas formas**.
2. GROMACS y AmberTools no existen para Windows, así que el instalador crea un pequeño sistema Linux llamado **MD-Prep** dentro de
   WSL (el subsistema de Linux de Windows). Si WSL no está activado, Windows pedirá permiso de administrador y un reinicio. Después
   el instalador continúa solo.
3. Se descargan unos 1.5 GB y la instalación tarda 10–20 minutos.

Para abrirla: icono **MD-Prep Studio** del escritorio, o escribe `prepmd` en una terminal.
Para desinstalarla: *Configuración → Aplicaciones → MD-Prep Studio → Desinstalar*.

### macOS y Linux
1. Descomprime la carpeta y déjala en tu carpeta de usuario.
2. macOS: **clic derecho** en `Instalar MD-Prep.command` → *Abrir* → *Abrir*. Linux: `sh instalar.sh`.
   Usa tu Anaconda/Miniforge si existe; si no, instala Miniforge. Crea el entorno `md-prep` (5–15 min).
3. Para usarla: abre una Terminal **nueva** y escribe `prepmd` (o doble clic en `Abrir MD-Prep.command`).

## Uso
1. Sube el **PDB del complejo** (proteína + ligando en la pose del docking). Se recomienda subir también el **SDF del ligando** de esa
   pose, para que los órdenes de enlace y la carga sean exactos. Sin SDF puedes escribir la SMILES.
2. Revisa las opciones. Todas tienen valores por defecto razonables: pH 7.4, dodecaedro rómbico a 1.2 nm, NaCl 0.15 M, 310 K, 250 ns.
3. Revisa los datos del clúster: partición, núcleos, GPU, tiempo máximo y módulos.
4. **Preparar sistema** (2–10 min). Descarga el ZIP y en el clúster:
   ```bash
   scp sistema.zip usuario@clúster:~/
   ssh usuario@clúster
   unzip sistema.zip && cd <nombre_del_job>
   sbatch gmxgpu.sh
   sbatch continuar.sh      # solo si la producción no terminó dentro del tiempo máximo
   ```

`mdprep_config.json` define el idioma por defecto y los datos de tu clúster que aparecen en el formulario.

## Método

**Proteína.** Se conservan las cadenas elegidas; PDBFixer (Eastman et al., 2024) añade los átomos pesados faltantes y reemplaza
residuos no estándar (p. ej., MSE → MET). Los huecos de residuos ausentes no se modelan: se tratan como extremos de cadena.
PDB2PQR (Dolinsky et al., 2004; Jurrus et al., 2018) con PROPKA (Olsson et al., 2011) asigna el estado de protonación de cada residuo al pH
elegido (HID/HIE/HIP, ASH, GLH, LYN, CYX) y `gmx pdb2gmx` genera la topología AMBER99SB-ILDN (Hornak et al., 2006; Lindorff-Larsen et al., 2010)
con agua TIP3P (Jorgensen et al., 1983).

**Ligando.** Se usa la química del SDF/MOL2 del docking (o la SMILES de plantilla) con las coordenadas de la pose, procesada con
RDKit y Open Babel (O'Boyle et al., 2011); se añaden los hidrógenos y ACPYPE (Sousa da Silva & Vranken, 2012) con antechamber de
AmberTools (Case et al., 2023) asigna parámetros GAFF2 (Wang et al., 2004) y cargas AM1-BCC (Jakalian et al., 2000; Jakalian et al., 2002).

**Sistema.** Caja (dodecaedro rómbico por defecto) con 1.2 nm entre el soluto y el borde, agua TIP3P, NaCl 0.15 M (o KCl, para
proteínas intracelulares) y los contraiones necesarios para neutralizar. El índice incluye los grupos `SOLU` (proteína + ligando)
y `SOLV` (agua + iones), y las etapas siguen los nombres de CHARMM-GUI (Lee et al., 2016).

**Protocolo.**
| Archivo | Etapa | Detalles |
|---|---|---|
| `step4.0_minimization.mdp` | Minimización | descenso más pronunciado, Fmax < 1000 kJ mol⁻¹ nm⁻¹, restricciones de posición |
| `step4.1_equilibration.mdp` | NVT | 125 ps, dt 1 fs, V-rescale (Bussi et al., 2007) a 310 K, restricciones de posición |
| `step4.2_equilibration.mdp` | NPT (opcional) | 1 ns, dt 2 fs, C-rescale (Bernetti & Bussi, 2020) a 1 bar, restricciones de posición |
| `step5_production.mdp` | Producción NPT | 250 ns por defecto, dt 2 fs, V-rescale + C-rescale, sin restricciones |

Parámetros comunes: esquema Verlet, PME (Darden et al., 1993; Essmann et al., 1995), cortes de 1.0 nm, corrección de dispersión y enlaces
con H restringidos con LINCS (Hess et al., 1997). Simulación con GROMACS (Abraham et al., 2015); el protocolo de equilibrado sigue
las recomendaciones de Braun et al. (2018). Los `.mdp` solo usan opciones válidas en GROMACS 2021 o superior.

**Por qué no se entregan `.tpr`.** `grompp` se ejecuta en el clúster: los `.tpr` de una versión más nueva de GROMACS no se pueden
leer en una más antigua. La plataforma sí ejecuta `grompp` localmente para verificar que todo es válido.

## Cómo citar
Cita MD-Prep Studio y, sobre todo, las herramientas y métodos en los que se basa. El archivo `METODOS_y_CITAS.md` de cada paquete
trae un párrafo de métodos con los parámetros reales de tu sistema y estas referencias (también en `references.bib`):

**Motor de simulación**
- Abraham, M. J., Murtola, T., Schulz, R., Páll, S., Smith, J. C., Hess, B., & Lindahl, E. (2015). GROMACS: High performance molecular simulations through multi-level parallelism from laptops to supercomputers. *SoftwareX*, *1–2*, 19–25. https://doi.org/10.1016/j.softx.2015.06.001

**Campo de fuerza de la proteína (AMBER99SB-ILDN)**
- Hornak, V., Abel, R., Okur, A., Strockbine, B., Roitberg, A., & Simmerling, C. (2006). Comparison of multiple Amber force fields and development of improved protein backbone parameters. *Proteins: Structure, Function, and Bioinformatics*, *65*(3), 712–725. https://doi.org/10.1002/prot.21123
- Lindorff-Larsen, K., Piana, S., Palmo, K., Maragakis, P., Klepeis, J. L., Dror, R. O., & Shaw, D. E. (2010). Improved side-chain torsion potentials for the Amber ff99SB protein force field. *Proteins: Structure, Function, and Bioinformatics*, *78*(8), 1950–1958. https://doi.org/10.1002/prot.22711

**Modelo de agua (TIP3P)**
- Jorgensen, W. L., Chandrasekhar, J., Madura, J. D., Impey, R. W., & Klein, M. L. (1983). Comparison of simple potential functions for simulating liquid water. *The Journal of Chemical Physics*, *79*(2), 926–935. https://doi.org/10.1063/1.445869

**Campo de fuerza del ligando (GAFF2)**
- Wang, J., Wolf, R. M., Caldwell, J. W., Kollman, P. A., & Case, D. A. (2004). Development and testing of a general amber force field. *Journal of Computational Chemistry*, *25*(9), 1157–1174. https://doi.org/10.1002/jcc.20035

**Cargas parciales del ligando (AM1-BCC)**
- Jakalian, A., Bush, B. L., Jack, D. B., & Bayly, C. I. (2000). Fast, efficient generation of high-quality atomic charges. AM1-BCC model: I. Method. *Journal of Computational Chemistry*, *21*(2), 132–146. https://doi.org/10.1002/(SICI)1096-987X(20000130)21:2<132::AID-JCC5>3.0.CO;2-P
- Jakalian, A., Jack, D. B., & Bayly, C. I. (2002). Fast, efficient generation of high-quality atomic charges. AM1-BCC model: II. Parameterization and validation. *Journal of Computational Chemistry*, *23*(16), 1623–1641. https://doi.org/10.1002/jcc.10128

**AmberTools (antechamber, sqm)**
- Case, D. A., Aktulga, H. M., Belfon, K., Cerutti, D. S., Cisneros, G. A., Cruzeiro, V. W. D., et al. (2023). AmberTools. *Journal of Chemical Information and Modeling*, *63*(20), 6183–6191. https://doi.org/10.1021/acs.jcim.3c01153

**Conversión de la topología del ligando a GROMACS**
- Sousa da Silva, A. W., & Vranken, W. F. (2012). ACPYPE - AnteChamber PYthon Parser interfacE. *BMC Research Notes*, *5*(1), 367. https://doi.org/10.1186/1756-0500-5-367

**Percepción química y protonación del ligando**
- O'Boyle, N. M., Banck, M., James, C. A., Morley, C., Vandermeersch, T., & Hutchison, G. R. (2011). Open Babel: An open chemical toolbox. *Journal of Cheminformatics*, *3*, 33. https://doi.org/10.1186/1758-2946-3-33

**Manejo de la estructura del ligando**
- RDKit contributors. RDKit: Open-source cheminformatics. https://www.rdkit.org. https://doi.org/10.5281/zenodo.591637

**Reparación de la proteína (PDBFixer, parte del ecosistema OpenMM)**
- Eastman, P., Galvelis, R., Peláez, R. P., Abreu, C. R. A., Farr, S. E., Gallicchio, E., et al. (2024). OpenMM 8: Molecular dynamics simulation with machine learning potentials. *The Journal of Physical Chemistry B*, *128*(1), 109–116. https://doi.org/10.1021/acs.jpcb.3c06662

**Asignación de protonación de la proteína**
- Dolinsky, T. J., Nielsen, J. E., McCammon, J. A., & Baker, N. A. (2004). PDB2PQR: An automated pipeline for the setup of Poisson–Boltzmann electrostatics calculations. *Nucleic Acids Research*, *32*(Web Server), W665–W667. https://doi.org/10.1093/nar/gkh381
- Jurrus, E., Engel, D., Star, K., Monson, K., Brandi, J., Felberg, L. E., et al. (2018). Improvements to the APBS biomolecular solvation software suite. *Protein Science*, *27*(1), 112–128. https://doi.org/10.1002/pro.3280

**Predicción de pKa**
- Olsson, M. H. M., Søndergaard, C. R., Rostkowski, M., & Jensen, J. H. (2011). PROPKA3: Consistent treatment of internal and surface residues in empirical pKa predictions. *Journal of Chemical Theory and Computation*, *7*(2), 525–537. https://doi.org/10.1021/ct100578z

**Electrostática de largo alcance (PME)**
- Darden, T., York, D., & Pedersen, L. (1993). Particle mesh Ewald: An N·log(N) method for Ewald sums in large systems. *The Journal of Chemical Physics*, *98*(12), 10089–10092. https://doi.org/10.1063/1.464397
- Essmann, U., Perera, L., Berkowitz, M. L., Darden, T., Lee, H., & Pedersen, L. G. (1995). A smooth particle mesh Ewald method. *The Journal of Chemical Physics*, *103*(19), 8577–8593. https://doi.org/10.1063/1.470117

**Restricción de enlaces con H (LINCS)**
- Hess, B., Bekker, H., Berendsen, H. J. C., & Fraaije, J. G. E. M. (1997). LINCS: A linear constraint solver for molecular simulations. *Journal of Computational Chemistry*, *18*(12), 1463–1472. https://doi.org/10.1002/(SICI)1096-987X(199709)18:12<1463::AID-JCC4>3.0.CO;2-H

**Termostato (V-rescale)**
- Bussi, G., Donadio, D., & Parrinello, M. (2007). Canonical sampling through velocity rescaling. *The Journal of Chemical Physics*, *126*(1), 014101. https://doi.org/10.1063/1.2408420

**Barostato (C-rescale)**
- Bernetti, M., & Bussi, G. (2020). Pressure control using stochastic cell rescaling. *The Journal of Chemical Physics*, *153*(11), 114107. https://doi.org/10.1063/5.0020514

**Protocolo y nombres de archivo de equilibrado**
- Lee, J., Cheng, X., Swails, J. M., Yeom, M. S., Eastman, P. K., Lemkul, J. A., et al. (2016). CHARMM-GUI Input Generator for NAMD, GROMACS, AMBER, OpenMM, and CHARMM/OpenMM simulations using the CHARMM36 additive force field. *Journal of Chemical Theory and Computation*, *12*(1), 405–413. https://doi.org/10.1021/acs.jctc.5b00935

**Buenas prácticas de preparación y equilibrado**
- Braun, E., Gilmer, J., Mayes, H. B., Mobley, D. L., Monroe, J. I., Prasad, S., & Zuckerman, D. M. (2018). Best practices for foundations in molecular simulations [Article v1.0]. *Living Journal of Computational Molecular Science*, *1*(1), 5957. https://doi.org/10.33011/livecoms.1.1.5957
