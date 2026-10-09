# AlphaFold 2 (Batch Connect app)

Launches a **Jupyter server for AlphaFold 2 work** on a Slurm compute
node (optionally with 1 GPU); the notebook is proxied to the browser
through the portal's `/rnode` reverse proxy (`batch_connect:
template: basic` — the plain-web variant; the VNC GUI apps in this
catalog use `template: vnc`).

Modeled on CHPC's
[chpc-uofu/ood-ge-apps-v4](https://github.com/chpc-uofu/ood-ge-apps-v4)
`alphafold_nim_app` (NIM-container based upstream; here the AlphaFold 2
environment is a plain pip/conda install or an environment module on the
compute node), plus the CHPC `module` / `additional_environment` form
pattern.

## Requirements

* Jupyter (Lab + Notebook) runtime — installed by `roles/ood-wrapper`
  (client mode) on the Slurm nodes (`pip` under the node's Python 3.9).
* The **AlphaFold 2 environment available on the compute node** (pip/
  conda package on `PATH`, or as an environment module via the form's
  "Environment module" field) — not installed by DeepOps.
* The portal's `/rnode` proxy — installed by `roles/ood-wrapper`
  (server mode).

## Form fields

* **Interface** — Jupyter Lab (default) or classic Notebook.
* **GPUs** — 0 or 1 (the allocation is shown by `nvidia-smi` in the job
  log when present).
* **Memory (GB)** — `0` = cluster default; otherwise `sbatch --mem <N>G`.
* **Environment module** — loaded before launch when set; portable form
  of CHPC's `auto_modules_*` version selector.
* **Additional environment** — arbitrary shell lines run before launch
  (exports, module loads, tool flags); the CHPC `additional_environment`
  pattern.

## How to enable

The app is part of the optional app catalog
(`config/group_vars/ood-portal.yml`, `ood_apps_catalog.alphafold`):

```yaml
alphafold:
  local: alphafold
  enabled: true
```

then rerun `ansible-playbook playbooks/ood-portal.yml`.
