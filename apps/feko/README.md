# Altair Feko (Batch Connect app)

Launches **Altair Feko** in a VNC session on a Slurm compute
node; the GUI is proxied to the browser through the portal's noVNC
(`batch_connect: template: vnc` — the same OOD template the Desktop app
uses, see `apps/jupyter` for the plain-web variant and CHPC's
[chpc-uofu/ood-ge-apps-v4](https://github.com/chpc-uofu/ood-ge-apps-v4)
`ansysedt_app` for the reference design this app follows).

## Requirements

* Altair Feko **installed and on `PATH` on the compute
  node** (licensed commercial software — not installed by DeepOps).
  The launcher binary defaults to `feko`; if yours differs, use the
  form's "Launch command" field (or change the default in
  `template/script.sh.erb`).
* TigerVNC server + websockify + the portal's `/rnode` proxy — all
  installed by `roles/ood-wrapper` (client mode) on the Slurm nodes.

## How to enable

The app is part of the optional app catalog
(`config/group_vars/ood-portal.yml`, `ood_apps_catalog.ansysedt`):

```yaml
ansysedt:
  local: ansysedt
  enabled: true
```

then rerun `ansible-playbook playbooks/ood-portal.yml`.
