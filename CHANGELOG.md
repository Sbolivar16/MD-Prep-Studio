# Changelog

## 1.1.0 — 2026-10-22
- English and Spanish interface and outputs (language selector; default set in `mdprep_config.json`).
- Windows installer (WSL-based, no manual setup) with desktop shortcut and `prepmd` command.
- Default solute–box distance raised to 1.2 nm; KCl available as an alternative to NaCl.
- Every package includes `METHODS_and_CITATIONS.md` (methods paragraph with the actual parameters) and `references.bib`.
- Cluster defaults (partition, modules, …) configurable in `mdprep_config.json`.
- ACPYPE always uses the AmberTools of the environment.

## 1.0.0
- First version: PDBFixer, PDB2PQR/PROPKA, pdb2gmx (AMBER99SB-ILDN/TIP3P), ACPYPE (GAFF2/AM1-BCC), solvation, ions,
  SOLU/SOLV index, CHARMM-GUI-style .mdp files, SLURM script with checkpoint continuation and `grompp` verification.
