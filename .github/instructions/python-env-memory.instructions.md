---
description: Python environment and command-running conventions for this repository.
applyTo: "**/*.py"
---

# Python Env Memory

Run all Python tooling inside the `clipmorph` conda environment.

## Use the clipmorph conda env

- Activate with `conda activate clipmorph` before any `python`, `pip`, `unittest`, `ruff`, or `mypy` command.
- The bare `python` / `py` launchers on this machine are not installed; do not fall back to them.
- `conda` is not on the default PATH of the agent shell; use `& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n clipmorph python ...`.
