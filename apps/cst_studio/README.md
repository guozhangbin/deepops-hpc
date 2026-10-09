# CST Studio Suite (Batch Connect app)

Launches **CST Studio Suite** in a VNC session on a Slurm compute
node; the GUI is proxied to the browser through the portal's noVNC
(`batch_connect: template: vnc` — the same OOD template the Desktop app
uses; see `apps/alphafold` for a plain-web variant).

Design follows CHPC's
[chpc-uofu/ood-ge-apps-v4](https://github.com/chpc-uofu/ood-ge-apps-v4)
VNC app pattern: Xfce session bootstrap, staged desktop configuration,
and the `module` / `additional_environment` form fields (portable form
of CHPC's `auto_modules_*`).

## Requirements

* CST Studio Suite **installed on the compute node and on `PATH` (or
  available as an environment module)** — licensed commercial software,
  not installed by DeepOps. The launcher binary defaults to `cst-studio`;
  if yours differs, use the form's "Launch command" field (or change the
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

* **Memory per node (GB)** — `0` = cluster default; otherwise
  `sbatch --mem <N>G`.
* **Node list** — restricts the job with `sbatch -w` (e.g. `gpu01`).
* **Environment module** — loaded before launch when set (e.g.
  `cst/2025`); portable form of CHPC's `auto_modules_*` version
  selector.
* **Launch command** — executed inside the session (default: `cst-studio`).
* **Additional environment** — arbitrary shell lines run before launch
  (exports, module loads, tool flags); the CHPC `additional_environment`
  pattern.

## How to enable

The app is part of the optional app catalog
(`config/group_vars/ood-portal.yml`, `ood_apps_catalog.cst_studio`):

```yaml
cst_studio:
  local: cst_studio
  enabled: true
```

then rerun `ansible-playbook playbooks/ood-portal.yml`.
