---
name: deploy-ood-portal
description: Deploy the Open OnDemand web portal (UltraLAB HPC Cluster) on a DeepOps Slurm cluster and prove it works. Use when asked to install, configure, or rebuild the OOD portal, Batch Connect apps, or web login for GPU jobs.
---

# Deploy the Open OnDemand portal

## Preconditions

- A Slurm cluster deployed and validated with this repository
  (`validate_slurm.py` reports `"ok": true`) — the portal submits jobs to it.
- A portal host listed under `[ood-portal]` in `config/inventory` (usually the
  Slurm master), with ports 80/443 free.
- A local system account on the portal host for every portal login user
  (e.g. `new`) — PUN sessions and Slurm jobs run as that user.
- Network from the portal host: `yum.osc.edu` (OOD packages) and
  `github.com` (app clones) reachable directly (verified from the cluster
  network, Sep 2026 — the `gh-proxy.com` mirror was tried earlier but
  rate-limits with intermittent 403s, so it is not used).

## Procedure

1. Prepare the environment (once per provisioning machine):

   ```bash
   git submodule update --init --recursive
   ./scripts/setup.sh          # installs the osc.open_ondemand role into roles/galaxy/
   ```

2. Configure:

    - `config/inventory`: portal host under `[ood-portal]`.
    - `config/group_vars/ood-portal.yml`: branding
      (`ood_portal_title: "UltraLAB HPC Cluster"`), the Slurm cluster
      (`clusters:` with `adapter: slurm` — note `bin:` must be the bin
      *directory*, e.g. `/usr/local/bin`), the Batch Connect app catalog
      (`ood_apps_catalog`: every catalog app listed with an `enabled`
      toggle — `repo:` apps are git-cloned, `local:` apps are copied from
      `apps/` of this repo; disabled apps are removed so the menu only
      shows active ones), and portal login users (`ood_portal_users`).
      In `config.example` the 10 OSC "basic" apps are enabled by default
      (including the OSC `jupyter` app, which REPLACES the local
      `apps/jupyter` when enabled); the commercial, classroom, and 6 local
      apps (ansysedt, ansysfluent, lumerical, alphafold, cst_studio, feko)
      are disabled until the software is on the nodes.

3. Preflight — must pass before deploying:

   ```bash
   python3 scripts/validation/deepops_doctor.py --remote --json
   ```

4. Deploy:

   ```bash
   # TWO plays: portal host + compute-node runtimes. Limit to BOTH groups —
   # `-l ood-portal` alone silently skips the node-side play (Jupyter
   # runtime, nvidia-persistenced/firewalld repairs) and the nodes stay
   # broken even though the run reports success.
   ansible-playbook -l ood-portal,slurm-node playbooks/ood-portal.yml
   ```

    This installs httpd + OOD 4.2 from yum.osc.edu, the OOD SELinux policy
    (SELinux is enforcing), installs the Batch Connect apps from the catalog
    (any catalog app with `enabled: true` — `repo:` apps git-cloned,
    `local:` apps copied from `apps/`; the OSC `jupyter` app replaces the
    local `apps/jupyter` when enabled), writes the Slurm cluster and
    branding config, installs the `/rnode` node-proxy Apache config, opens
    the portal host in the compute nodes' firewalls, installs the node-side
    runtimes on the `slurm-node` hosts (Jupyter for the web apps; TigerVNC
    + Xfce4 + websockify for the Desktop app and the VNC local apps),
    writes the Shell web-terminal allowlist
    (`/etc/ood/config/apps/shell/env`), and adds the login users to
    `/etc/httpd/.htpasswd`.
    Expect roughly 5–15 minutes on a first run.

5. Validate on the portal host — the success signal is this, not the play
   recap:

   ```bash
   python3 scripts/validation/validate_ood.py --json
   ```

   Require `"ok": true` with `login_ok: true` and `cluster_config_ok: true`.

6. Smoke test the full chain (not just the dashboard):

    - Open `http://<portal-host>/`, log in with the portal user.
    - Launch Jupyter from the dashboard (pick mode, GPU count, walltime).
    - Confirm the session job lands in Slurm on a GPU node:
      `squeue`; `scontrol show job <id>` → `AllocTRES=...gres/gpu=N`
      (proves the GPU was actually allocated), and `SubmitLine` shows
      `-p batch --gpus-per-node N --time HH:MM:SS`.
    - Confirm JupyterLab started inside the job: the session output dir
      (`/home/<user>/ondemand/data/sys/dashboard/batch_connect/sys/jupyter/
      output/<uuid>/`) has `output.log` (Jupyter startup + `nvidia-smi`)
      and `connection.yml` (host/port of the running server).
    - Confirm the "Connect" URL works through the node proxy:
      `curl -s -o /dev/null -w "%{http_code}\n" -u <user>:<pw>
      "http://<portal-host>/rnode/<node>/<port>/lab"` → `200` with
      `<title>JupyterLab`.
    - Open the Shell web terminal
      `http://<portal-host>/pun/sys/shell/ssh/<host>` for EACH cluster
      host (master + compute nodes) and confirm a live prompt (WebSocket
      connects and `hostname` echoes). Requires the allowlist env
      (step 4) and the user in `/etc/localusers` on the nodes
      (see failure branches below).

## Failure branches

- **GPU job hangs or fails with `Slurmd could not connect IO` /
  `No route to host`** (or `srun --gpus=1 …` from the login node never
  returns): the *requesting* host's firewall REJECTs slurmd's
  return connection to the step's ephemeral IO port. A working
  firewalld with a default-deny zone blocks this even when all the
  "Slurm ports" (6817/6818/11310) are open. Fix: trust the cluster
  peer hosts — `firewall-cmd --permanent --add-rich-rule
  "rule family=ipv4 source address=<peer>/32 accept"` (the slurm
  role's `tasks/firewall.yml` does this for every cluster pair).
  Check the node's `slurmd.log` for `connect io:` — that is the
  definitive signature.
- **Portal / Grafana unreachable from outside but fine on the head
  node itself** (`curl 127.0.0.1:80` works, `curl <head-ip>:80` from
  another host times out or is refused): the firewall is enforcing
  and 80/443/3000/… were never opened (common after a firewalld
  repair, which starts enforcing where it previously enforced
  nothing). Test from a *different* machine — the head node
  short-circuits its own firewall. Fix: open the ports
  (`firewall-cmd --permanent --add-port=80/tcp …` + `--reload`);
  encoded in `roles/ood-wrapper/tasks/server.yml` and
  `roles/slurm/tasks/firewall.yml`.
- **Node stays `down` with `Reason=Node unexpectedly rebooted`** even
  though `slurmd` is active: a slurmd that missed the controller's
  restart window can stop retrying registration. `systemctl restart
  slurmd` on the node (it re-registers within seconds) and the node
  returns to service; if not, `scontrol update nodename=<n>
  state=RESUME reason=""`.
- **`firewalld`/`tuned`/`firewall-cmd` failed with
  `ModuleNotFoundError`** after a reboot (python3 → 3.11
  alternative): run the ood-wrapper playbook again —
  `fix-python3-services.yml` pins their shebangs to `python3.9` and
  restarts the services (idempotent).
- **Playbook fails on a transient error** (repo timeout, network blip):
  rerun the same playbook; it is idempotent. A converged rerun ends with
  `changed=0`.
- **App clone fails with a git/HTTPS error** ("HTTP/2 stream ... not
  closed cleanly", "Connection timed out", "Empty reply from server"):
  `github.com` is reachable but flaky on this network. First set
  `git config --global http.version HTTP/1.1` on the portal host (the
  HTTP/2 stream errors disappear with HTTP/1.1), then rerun the playbook —
  the clone task re-fetches/re-clones only what is missing or stale. If
  github stays down, point the `repo:` URLs in `ood_apps_catalog` at a
  mirror (`https://gh-proxy.com/https://github.com/...`); that mirror
  rate-limits with intermittent 403s, so prefer direct github.com.
  The upstream role is wrapped in `block/rescue` in
  `roles/ood-wrapper/tasks/server.yml`, so clone failures do not abort the
  rest of the play (the recap shows `rescued=1`, not `failed=1`).
- **VNC app session dies with Xvnc "Unrecognized option: <word>"**: the
  vnc template injects `-name <name>` **unquoted** into the Xvnc command
  line (`ood_core` `templates/vnc.rb`), so a multi-word `name:` in
  `submit.yml.erb` (e.g. "UltraLAB Altair Feko") breaks the command —
  Xvnc treats the second word as an option. Use a single word (the app
  slug) for `name:` in `submit.yml.erb`; the pretty menu title lives in
  `manifest.yml`.
- **Session job fails with "script.sh: Permission denied"**: the template
  EXECs the rendered `script.sh`, so the app's
  `template/script.sh.erb` must be installed with the execute bit. The
  install tasks in `roles/ood-wrapper/tasks/server.yml` set
  `mode: "0755"` for this reason — a copy without an explicit mode
  preserves whatever the pre-existing file had, so a 644 install never
  self-heals.
- **Portal answers but login returns 401**: the user is missing from
  `/etc/httpd/.htpasswd`. Rerun the playbook (the htpasswd tasks are
  idempotent) or add manually:
  `htpasswd -b /etc/httpd/.htpasswd new <password>`.
- **Session starts then dies, or files are unreadable**: SELinux denials —
  confirm `ondemand-selinux` is installed (`rpm -q ondemand-selinux`, set
  `install_ondemand_selinux: true`) and inspect `ausearch -m avc -ts recent`.
- **Dashboard 404 / per-user nginx (PUN) never starts**: the auto-launch
  path is the `mod_ood_proxy` lua hook → `sudo /opt/ood/nginx_stage/sbin/
  nginx_stage`. SELinux Enforcing can deny `httpd_t` read on
  `/etc/sudoers` (`etc_t`) so the sudo step fails silently. Confirm with
  `ausearch -m avc -c sudo -ts recent`, then `semanage permissive -a httpd_t`.
  Verify the sudoers entry exists:
  `apache ALL=(ALL) NOPASSWD: /opt/ood/nginx_stage/sbin/nginx_stage`.
- **"Home Directory Not Found" page for `/pun/sys/dashboard/`** even though
  the home dir exists: a *stale* generated config
  (`/var/lib/ondemand-nginx/config/puns/<user>.conf`) still has the
  nginx_stage conditional rewrite to
  `missing_home_directory.html`. Regenerate and restart the per-user nginx:
  `sudo /opt/ood/nginx_stage/sbin/nginx_stage pun --user=<user>
  --skip-nginx`, then restart the per-user nginx (or rerun the playbook).
- **500 "Web application could not be started"** with
  `File exists @ dir_s_mkdir - /home/<user> (Errno::EEXIST)` in the PUN log
  (`/var/log/ondemand-nginx/<user>/error.log`): SELinux denied the
  `ood_pun_t` domain `stat` on the home dir, so `File.directory?` returned
  false and `mkdir` on the existing dir raised EEXIST. Fix:
  `semanage permissive -a ood_pun_t`, then restart the per-user nginx.
- **`semanage` crashes with `ModuleNotFoundError: No module named
  'seobject'`**: the shebang resolves `python3` to a version that lacks the
  policycoreutils python module. Run it against the python that has it:
  `PYTHONPATH=/usr/lib/python3.9/site-packages /usr/bin/python3.9
  /usr/sbin/semanage permissive -a <type>` (adjust the path to match the
  installed python).
- **`dnf` cannot find the `ondemand` package**: the repo install failed —
  verify the portal host can reach
  `https://yum.osc.edu/ondemand/4.2/ondemand-release-web-4.2-1.el9.noarch.rpm`.
- **Apps missing from the dashboard**: check the app dir exists
  (`/var/www/ood/apps/sys/<app>`) and the cluster file
  (`/etc/ood/config/clusters.d/deepops.yml`); look at
  `/var/log/httpd/error_log` and `/opt/ood/log`.
- **Shell web terminal closes immediately with 3146 / "Host … not
  specified in allowlist or cluster configs"**: the app validates each
  host against the cluster configs + `OOD_SSHHOST_ALLOWLIST` read from
  `/etc/ood/config/apps/shell/env` (production). The wrapper task writes
  it from the `ood-portal` + `slurm-node` inventory groups — verify the
  file exists and lists the host, then restart the user's PUN (or rerun
  the playbook; the restart task kills the stale Passenger instance that
  still holds the old env).
- **Shell web terminal connects but the node refuses SSH:
  "Access denied by pam_slurm_adopt: you have no active jobs"**: the
  node-side allowlist is `/etc/localusers` (managed from
  `/etc/slurm/localusers.backup` by the slurm prolog/epilog). Put the
  portal user into `slurm_allow_ssh_user` in
  `config/group_vars/slurm-cluster.yml` and rerun the Slurm playbook —
  NOTE the `localusers` tag is NOT targetable with `--tags` (the role's
  `include_tasks` statement is untagged and gets filtered out, so the
  tagged task inside never runs); a full slurm-cluster run is required,
  or append the user to BOTH `/etc/localusers` and
  `/etc/slurm/localusers.backup` on each node directly.
- **Jupyter "Connect" link 404s / POSTs to `/node/<host>/<port>/login`**:
  the OSC upstream `view.html.erb` expects a password login that an
  authless Jupyter launch does not have, and `/node/` does not strip the
  proxy prefix. The wrapper installs a plain-link view pointing at
  `/rnode/<host>/<port>/<jupyter_api>` — if it goes missing, rerun the
  ood-portal playbook (the OSC role re-clones the app on every run, so
  the patch is re-applied on every run; `rescued=1` on the portal host in
  the recap is the expected signature of that clone conflict, not an
  error).
- **Session submit fails with `undefined method 'to_h' for an instance of
  String`** (shown on the form as "Failed to submit session ..."): the
  rendered `submit.yml.erb` is not a YAML hash. Classic cause: an ERB
  comment `<%# ... %>` whose text itself contains a tag such as
  `<%= gpus %>` — an ERB comment ends at the **first** closing tag, so the
  comment terminates early, the leftover prose leaks into the document, and
  `YAML.safe_load` returns a plain String on which `.to_h` is called. Use
  plain `#` YAML comments for prose in `.yml.erb` files (and never nest
  `<%= ... %>` inside `<%# %>`); verify by rendering the file and checking
  the result parses to a Hash.
- **Session submit fails with `No such file or directory -
  /usr/local/sbatch`**: the cluster config's `bin:` must point at the
  *bin directory* — the OOD Slurm adapter resolves binaries as
  `Pathname(bin).join(cmd)` (`ood_core` `Helper.bin_path`), so `bin:
  /usr/local` yields `/usr/local/sbatch`. For DeepOps Slurm set
  `bin: /usr/local/bin` in the `clusters:` block of
  `config/group_vars/ood-portal.yml` and rerun the playbook.
- **Job runs but the "Connect" URL 404s** (`/rnode/<node>/<port>/...`):
  the node proxy Apache config must live in `apache_conf_dir`
  (e.g. `/etc/httpd/conf.d/`) — a file written to `apache_etc_dir`
  (`/etc/httpd/`) itself is not included by the main config. The playbook
  installs `{{ apache_conf_dir }}/ood-node-proxy.conf`; verify with
  `httpd -t && systemctl reload httpd`, then re-test the `/rnode` URL.
- **Wrong or stale host facts after reprovisioning**: rerun with
  `--flush-cache`.
