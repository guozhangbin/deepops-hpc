# Lumerical DEVICE suite (Batch Connect app)

Launches the **Lumerical DEVICE suite** in a VNC session on a Slurm
compute node; the GUI is proxied to the browser through the portal's
noVNC (`batch_connect: template: vnc` — the same OOD template the
Desktop app uses; see `apps/alphafold` for a plain-web variant).

Design follows CHPC's
[chpc-uofu/ood-ge-apps-v4](https://github.com/chpc-uofu/ood-ge-apps-v4)
`lumerical_app`: Xfce session bootstrap, staged desktop configuration,
and the `module` / `additional_environment` form fields (portable form
of CHPC's `auto_modules_*`).

## Requirements

* Lumerical DEVICE suite **installed on the compute node and on `PATH`
  (or available as an environment module)** — licensed commercial
  software, not installed by DeepOps. The launcher binary defaults to
  `lumerical` (CHPC's nodes use `launcher` for the DEVICE suite); if
  yours differs, use the form's "Launch command" field (or change the
  default in `template/script.sh.erb`).
* TigerVNC server + websockify + the portal's `/rnode` proxy — all
  installed by `roles/ood-wrapper` (client mode) on the Slurm nodes.

## Session (what you get)

The OOD vnc template starts Xvnc with `-noxstartup`, so the app's script
starts the Xfce session inside the job (CHPC pattern):

* `xfwm4` window manager (compositor off — software rendering),
* `xfce4-panel` with the staged panel layout (`template/config/xfce4/...`:
  applications menu, tasklist, pager, clock),
* `xfce4-terminal` configured via the staged `terminalrc` (login shell,
  DejaVu Sans Mono 11),
* the app itself in the foreground — closing the app ends the session.

## Form fields

* **Nodes** / **Cores per node** — `sbatch -N` / `--ntasks-per-node`
  (defaults: 1 / 4).
* **GPUs** — `0` = CPU-only job; otherwise `--gpus-per-node <n>`.
* **Max run time (HH:MM:SS)** — `--time` (default `08:00:00`); the session
  is killed when it elapses.
* **Memory per node (GB)** — `0` = cluster default; otherwise
  `sbatch --mem <N>G`.
* **Node list** — restricts the job with `sbatch -w` (e.g. `gpu01`).
* **Environment module** — loaded before launch when set (e.g.
  `lumerical/2025.1`); portable form of CHPC's `auto_modules_*` version
  selector.
* **Launch command** — executed inside the session (default: `lumerical`).
* **Additional environment** — arbitrary shell lines run before launch
  (exports, module loads, tool flags); the CHPC `additional_environment`
  pattern.

## How to enable

The app is part of the optional app catalog
(`config/group_vars/ood-portal.yml`, `ood_apps_catalog.lumerical`):

```yaml
lumerical:
  local: lumerical
  enabled: true
```

then rerun `ansible-playbook playbooks/ood-portal.yml`.
