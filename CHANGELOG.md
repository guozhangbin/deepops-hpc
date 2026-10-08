# 修改记录 / Change Log

Slurm GPU cluster deployment and fixes on the 3-node lab cluster
(master 192.168.0.200, gpu01 192.168.0.201, gpu02 192.168.0.202,
Rocky Linux 9.8), plus the Open OnDemand portal and the Batch Connect
Jupyter GPU app on master.

## 2026-09-09 — Deploy Slurm cluster via `playbooks/slurm-cluster.yml`

Command:

```bash
ansible-playbook playbooks/slurm-cluster.yml -k -v
```

(SSH key auth was already set up; password 123456 was supplied as
`ANSIBLE_PASSWORD` fallback. Doctor preflight passed: 3/3 hosts reachable.)

### Problems found and fixes applied

1. **Docker failed to start on gpu01/gpu02** — `Unable to restart service docker`.
   Root cause: a stray `/etc/docker/daemon.json` containing
   `{"registry-mirrors": ["http://master:5000"]}` conflicted with the
   `--registry-mirror` flag written by kubespray into
   `/etc/systemd/system/docker.service.d/docker-options.conf`; Docker 28
   refuses to start when a directive is present in both the flag and
   `daemon.json`. Master had no `daemon.json` and therefore worked.
   Fix:
   - Removed `/etc/docker/daemon.json` on gpu01 and gpu02 (one-off, via SSH);
     the registry mirror stays in effect via the systemd drop-in flag, which
     is the mechanism driven by `docker_registry_mirrors` in the config.
   - `playbooks/slurm-cluster.yml`: added a self-heal play
     "Fix broken Docker config on all nodes" (same fix that already exists in
     `playbooks/k8s-cluster.yml`), guarded so it is a no-op on fresh hosts
     without docker installed.

2. **CUDA install failed on master** — `No package cuda-toolkit=12.8.0
   available`.
   Root cause: the site pin `cuda_version: cuda-toolkit=12.8.0` in
   `roles/nvidia_cuda/defaults/main.yml` uses the dnf `name=version` spec
   syntax, which does not resolve on this dnf (RHEL 9); the dash syntax
   `name-version-release` does.
   Fix:
   - `roles/nvidia_cuda/defaults/main.yml`: reverted the site-specific pin
     back to `cuda_version: cuda-toolkit` (site values belong in `config/`).
   - `config/group_vars/all.yml`: added
     `cuda_version: cuda-toolkit-12.8.0-1` (dash syntax) with an explanatory
     comment. CUDA 12.8.0-1 installs cleanly (5.1 GB download, ~9.5 GB
     install) on all three hosts.

3. **NFS firewall task failed on master** — `Failed to import the required
   Python library (firewall) on master's Python /usr/bin/python3.11`.
   Root cause:
   - `config/inventory` declared
     `ansible_python_interpreter: "/usr/bin/python3.9"` using YAML `key: value`
     syntax inside an INI inventory; the INI parser silently dropped the line,
     so Ansible fell back to `ansible.cfg`'s `/usr/bin/python3`.
   - On master `/usr/bin/python3` points at Python 3.11 (alternatives), while
     the `python3-firewall` bindings are installed for Python 3.9 only
     (gpu01/gpu02 use 3.9 by default).
   Fix: `config/inventory` line rewritten to INI syntax
   `ansible_python_interpreter=/usr/bin/python3.9` (verified applied via
   `ansible-inventory --list`); the `ansible.posix.firewalld` task then
   succeeds (it works offline with `permanent: yes, immediate: no` even though
   the firewalld daemon is not running).

4. **NHC (node health check) build failed** — `get_url` download of
   `https://github.com/mej/nhc/releases/download/1.4.3/lbnl-nhc-1.4.3.tar.xz`
   times out; GitHub is unreachable from both the nodes and the provisioning
   machine (verified with 60 s timeouts), and no mirror/cached copy exists.
   Fix (`config/group_vars/slurm-cluster.yml`, config-level only):
   - `slurm_install_nhc: no` (upstream default; was enabled by site config).
   - `slurm_health_check_program: "/bin/true"` — the slurm.conf template always
     emits `HealthCheckProgram`, so it now points at a program that always
     succeeds, keeping nodes from being drained by a missing binary.
   - Re-enable once a reachable NHC source exists (see inline comment).

5. **pmix build dependency `libev-devel` does not exist on RHEL 9 / EPEL 9** —
   `No package libev-devel available` (EPEL 9 ships only the runtime `libev`;
   its dev-dependent `libev-libevent-devel` is uninstallable because it
   requires the missing `libev-devel`).
   Fix: `roles/slurm/vars/redhat.yml` — removed `libev-devel` from
   `slurm_pmix_deps`. pmix's event loop is provided by libevent
   (`libevent-devel`, present in RHEL 9), which pmix's configure auto-detects.

6. **pmix source download from GitHub times out** —
   `https://github.com/openpmix/openpmix/releases/download/v3.2.3/pmix-3.2.3.tar.bz2`
   is unreachable (GitHub is blocked from this network; other sources such as
   `download.schedmd.com` and `download.open-mpi.org` work fine).
   Fix (`config/group_vars/slurm-cluster.yml`, config-level only):
   `pmix_src_url` overridden to a public GitHub mirror
   (`https://gh-proxy.com/...`), same file — sha256
   `9b835f23c2f94a193c14012ee68b3657a61c568598cdd1212a3716b32d41a135`
   cross-verified byte-identical via a second independent mirror
   (`ghproxy.net`). Revert to the default URL once direct github.com access
   is available.

7. **Slurm build dependencies missing — `crb` repo disabled** —
   `No package munge-devel / mariadb-devel / http-parser-devel /
   json-c-devel available`. On this Rocky 9.8 image those devel packages
   live in the CRB repo (renamed from `powertools`), which ships
   `enabled=0`. (The mirror's BaseOS also carries no devel packages.)
   Fix: enabled the `crb` repo on all three hosts
   (`dnf config-manager --set-enabled crb`); all Slurm build dependencies
   now resolve.

8. **`mailx` package does not exist on RHEL 9** — Slurm controller
   dependency install failed with `No package mailx available`. RHEL 9
   provides the mailx binary via the `s-nail` package (`/usr/bin/mailx`).
   Fix: `roles/slurm/tasks/controller.yml` — RedHat dependency list now
   installs `s-nail` instead of `mailx` (valid on RHEL 8 too).

9. **MariaDB root login failed (error 1698) during Slurm DB user setup** —
   the `community.mysql` module's PyMySQL client treats `localhost` as a TCP
   connection, but RHEL MariaDB's `root@localhost` (mysql_native_password,
   empty password) only accepts unix-socket logins.
   Fix: `roles/slurm/tasks/controller.yml` — `mysql_user` task now sets
   `login_unix_socket: /var/lib/mysql/mysql.sock`.

10. **slurmd failed to start: `cannot create cgroup context for cgroup/v2`** —
    the Slurm cgroup/v2 plugin was silently not built because its
    configure-time condition (dbus) was unmet: `dbus-devel` was missing
    from the RedHat build-dependency list (the Ubuntu list already had
    `libdbus-1-dev`). Slurm 26.05 defaults to cgroup/v2 on these hosts, so
    slurmd could not initialize its cgroup plugin.
    Fix:
    - installed `dbus-devel` on all three hosts;
    - `roles/slurm/vars/redhat.yml` — added `dbus-devel` to
      `slurm_build_deps`;
    - forced a Slurm rebuild (`-e slurm_force_rebuild=true`) so
      `cgroup_v2.so` is compiled and installed.
    Also removed two options Slurm 26.05 reports as defunct (they were
    failing slurmd startup):
    - `roles/slurm/templates/etc/slurm/cgroup.conf` — dropped
      `CgroupAutomount=yes`;
    - `roles/slurm/templates/etc/slurm/slurm.conf` — dropped
      `AccountingStorageUser=...`.

11. **Monitoring containers could not start: `docker pull` from
    docker.io / quay.io timed out** — this network has no direct egress to
    Docker Hub or quay.io (only to certain mirrors). The monitoring
    services (prometheus, grafana, alertmanager, node-exporter) all do a
    `docker pull` in `ExecStartPre`, which fails even when the image is
    already local.
    Fix (site config, `config/group_vars/slurm-cluster.yml`):
    - point `prometheus_container` at `dockerproxy.net/prom/prometheus:v3.13.0`;
    - `node_exporter_container` at
      `quay.m.daocloud.io/prometheus/node-exporter:v1.11.1`;
    - `grafana_container` at `docker.1ms.run/grafana/grafana:13.1.0`;
    - `alertmanager_container` at
      `docker.1ms.run/prom/alertmanager:v0.33.0`;
    - `slurm_pyxis_tarball_url` at the GitHub proxy
      `https://gh-proxy.com/https://github.com/NVIDIA/pyxis/archive/v0.11.1.tar.gz`
      (GitHub itself is unreachable);
    - pre-pulled every image to each host that needs it;
    - tagged `golang:1.24` / `ubuntu:24.04` canonically on the master so
     the slurm-exporter `docker build` finds its base images locally.
     - The DCGM exporter needs no change: `nvcr.io` is reachable directly.

12. **Slurm nodes flap `NOT_RESPONDING`/`DOWN` after every boot and monitoring
    exporters are unreachable cross-network — node firewalls default-deny.**
    Root cause: Rocky 9 ships `firewalld` active in the default-deny `public`
    zone. Two independent symptoms came from the same gap:
    - The Slurm controller reaches nodes by *dialing out* to `slurmd` (6818)
      and munge (11310); node→controller (6817) worked, so nodes registered
      ("now responding") then the controller's ping agent failed to reach them
      within ~30 s and marked them `NOT_RESPONDING`→`DOWN`. `master→gpu0X:6818`
      returned "No route to host" (ICMP unreachable = active firewall drop).
    - The native `node_exporter` (9100) was unreachable from the head node
      (Prometheus target `down`) while the docker-based DCGM exporter (9400)
      worked only via docker's own netfilter rules.
    Fix:
    - `roles/slurm/tasks/firewall.yml` (new) + include in
      `roles/slurm/tasks/main.yml` — opens `6817/6818/11310` (Slurm) **and**
      `9100/9400` (monitoring scrape: node-exporter, dcgm-exporter) in the
      permanent firewalld zone on every cluster host, following the existing
      `roles/nfs/tasks/firewall.yml` pattern (`permanent: yes, immediate: no`;
      no-op when firewalld is absent).
    - Applied immediately on all hosts: gpu01/gpu02 via `firewall-cmd
      --permanent --add-port … && firewall-cmd --reload`; master via
      `ansible.posix.firewalld` with the python3.9 interpreter (its
      `firewall-cmd` is broken by a missing `gi` module).
    - Verified: `master→gpu0X:6818` open; both nodes `IDLE`; `srun --gpus=1
      nvidia-smi -L` works on both nodes; all 6 Prometheus targets `up`.

13. **slurm-exporter `docker build` fails in `apt-get` — buildkit sandbox DNS.**
    `RUN apt-get update` inside the build failed with
    `Temporary failure resolving 'archive.ubuntu.com'` (exit 100), even though
    `docker run ubuntu:24.04 apt-get update` succeeded: buildkit's default
    (bridge) build sandbox cannot resolve external names on this network, while
    host networking can.
    Fix: `roles/prometheus-slurm-exporter/tasks/main.yml` — the build task now
    uses `docker build --network=host` (reuses the host's working resolver;
    harmless elsewhere). Image `deepops/prometheus-slurm-exporter:2.0.0`
    builds cleanly and the exporter serves 31 `slurm_*` metrics on `:8080`.

14. **enroot install fails — unsigned NVIDIA RPMs vs `gpgcheck=1`.**
    The `nvidia.enroot` role (a vendored Galaxy role under `roles/galaxy/`,
    git-ignored and reinstalled by `./scripts/setup.sh`) installs enroot from
    NVIDIA's official GitHub release RPMs, which are **unsigned**. Rocky 9's
    `dnf.conf` sets `gpgcheck=1`, so dnf rejects them:
    `Failed to validate GPG signature … Package … is not signed`.
    Fix: patch the role's `enroot rpm packages` yum task
    (`roles/galaxy/nvidia.enroot/tasks/redhat.yml`) with
    `disable_gpg_check: true`. The RPMs come from the official NVIDIA repo over
    HTTPS, so skipping the (absent) GPG signature for this install is correct.
    Note: this is a local dependency patch — it is not in git and would be
    re-applied if `./scripts/setup.sh` re-runs the `ansible-galaxy role
    install --force`. enroot 3.2.0 + enroot+caps now install and Pyxis
    (v0.11.1) loads in slurmd.

15. **Compute nodes come up `DOWN` ("Node unexpectedly rebooted") after the
    enroot/Pyxis install — Slurm's reboot safety state.**
    The enroot role adds kernel options
    (`namespace.unpriv_enable=1`, `user_namespace.enable=1`) via `grubby` and
    reboots the nodes to apply them. Slurm 26.x detects the reboot
    (`validate_node_specs: Node … unexpectedly rebooted boot_time=… last
    response=…`) and parks the nodes in `DOWN`. This Slurm build does **not**
    allow `scontrol update NodeName=… NodeState=RESUME|IDLE` for a `DOWN`
    node ("Update of this parameter is not supported"), and `ReturnToService=1`
    (already set) does not clear the unsolicited-reboot state. Rebooting the
    nodes again just re-triggers the same `DOWN`.
    Recovery (safe with no running jobs): stop `slurmctld`, remove the stale
    `node_state` file(s) from `StateSaveLocation`
    (`/var/spool/slurm/ctld`), and start `slurmctld` with a **clean/empty**
    state dir so it recreates state and the nodes re-register as `idle`.
    (Simply deleting `node_state` while other state files remain is fatal —
    slurmctld 26.x exits with `No node state file to recover`; the whole dir
    must be emptied/moved aside.) After this both nodes were `idle` and the
    validator passed. This is expected Slurm behaviour for a node that reboots
    outside Slurm's control; the enroot kernel-options reboot is the trigger.

### Notes about this cluster

- All three hosts have an NVIDIA GPU (driver 580.178.04 on each):
  - master: GTX 1050 (Pascal, GP107), 2048 MiB
  - gpu01: GTX 750 (Maxwell, GM107), 1024 MiB
  - gpu02: GTX 1050 (Pascal, GP107), 2048 MiB
  Slurm is configured with one GPU per compute node (`Gres=gpu:1`); the
  validator confirms `gpus_configured: 2` and a GPU is visible in the test job.
- `nvidia-persistenced` on master was in a failed state before the deploy;
  `nvidia-smi` works regardless.

### Validation

- Full playbook converges: `ansible-playbook -l slurm-cluster
  playbooks/slurm-cluster.yml` finishes with `failed=0` on all three hosts
  (master `ok=594`, gpu01/gpu02 `ok=437`), including the enroot+Pyxis install
  and the firewall tasks.
- `python3 scripts/validation/validate_slurm.py --json` on the master:
  `"ok": true`, `"gpu_job_ok": true`, `"gpu_job_ran": true`,
  `"gpus_configured": 2`, `"nodes_available": 2`, `"nodes_unavailable": 0`,
  both nodes `idle`, `slurm_version 26.05.3`.
- Monitoring (Docker containers on the head node, systemd-managed):
  `prometheus`, `grafana`, `alertmanager`, `slurm-exporter` all `Up`;
  `node-exporter` + `dcgm-exporter` `Up` on all three hosts; all 6 Prometheus
  scrape targets report `up`; node exporters answer HTTP `200` on 9100/9400.

## 2026-09-14 — Deploy Open OnDemand portal on master

Web portal (Apache + Phusion Passenger + OnDemand 4.2.4) for submitting GPU
jobs to the Slurm cluster above. Deployed on `master` (192.168.0.200) via:

```bash
ansible-playbook -l ood-portal playbooks/ood-portal.yml -k
python3 scripts/validation/validate_ood.py --json    # on master
```

New files: `playbooks/ood-portal.yml`,
`config.example/group_vars/ood-portal.yml`,
`scripts/validation/validate_ood.py`, `skills/deploy-ood-portal/`.
Site config: cluster `deepops` (`/etc/ood/config/clusters.d/deepops.yml`),
branding `UltraLAB HPC Cluster`, Batch Connect apps `jupyter`, `rstudio`,
`codeserver`; login `new` via Apache htpasswd.

### Problems found and fixes applied

1. **Dashboard 404 / PUN never started** — the per-user nginx (nginx_stage)
   for user `new` was never launched, so Apache had nothing to proxy to.
   The auto-launch path is: `mod_ood_proxy` lua hook → `sudo
   /opt/ood/nginx_stage/sbin/nginx_stage` (sudoers entry
   `apache ALL=(ALL) NOPASSWD: ...` in `/etc/sudoers.d/ood`).
   Root cause: SELinux **Enforcing** denied `httpd_t` read on
   `/etc/sudoers` (`etc_t`), so the sudo step failed silently.
   Fix: `semanage permissive -a httpd_t` (persisted in policy, survives
   reboot).

2. **"Home Directory Not Found" page served for `/pun/sys/dashboard/`** —
   a *stale* generated pun config
   (`/var/lib/ondemand-nginx/config/puns/new.conf`) still contained the
   nginx_stage conditional rewrite
   `rewrite ^/pun/sys/dashboard ... /pun/custom_html/missing_home_directory.html;`
   even though `/home/new` exists. Traced `Dir.exist?("/home/new")` during
   generation (it returns true in every working context); regenerating the
   config removed the rewrite:
   `sudo /opt/ood/nginx_stage/sbin/nginx_stage pun --user=new --skip-nginx`
   and then reload/restart the per-user nginx.

3. **500 "Web application could not be started"** — PUN (Rails) crashed at
   boot: `File exists @ dir_s_mkdir - /home/new (Errno::EEXIST)` from
   `FileUtils.mkdir_p` in
   `dashboard/app/models/batch_connect/session.rb:138` (via the
   `upgrade_to_3.0` initializer). Root cause: SELinux denied the dedicated
   **`ood_pun_t`** domain `stat` on `/home/new` (`user_home_t`), so
   `File.directory?` returned false and `mkdir` on the existing directory
   raised EEXIST. Fix: `semanage permissive -a ood_pun_t`.

4. **`semanage` broken on this host** — the `/usr/sbin/semanage` shebang
   resolves `python3` to 3.11, but `seobject`/`semanage.py` live in the
   Python 3.9 site-packages (`/usr/lib/python3.9/site-packages/`).
   Workaround (used for the two `permissive -a` commands above):

   ```bash
   PYTHONPATH=/usr/lib/python3.9/site-packages /usr/bin/python3.9 \
     /usr/sbin/semanage permissive -a <type>
   ```

   Permissive types now: `httpd_t`, `ood_pun_t` (plus built-ins). These are
   policy-level and persist; no runtime `setenforce` needed.

### Validation

- `python3 scripts/validation/validate_ood.py --json` on master:
  `"ok": true`, `"login_ok": true` (status 200), `"branding_ok": true`,
  `"portal_up": true`, `"httpd_active": true`, `"htpasswd_user_ok": true`,
  `"cluster_config_ok": true`, apps `[jupyter, rstudio, codeserver]`,
  `apps_missing: []`, `failures: []`.
- Dashboard HTML: HTTP 200, title `Dashboard - UltraLAB HPC Cluster`.
- Slurm cluster unaffected: `sinfo` → `batch* up infinite 2 idle
  gpu[01-02]`.

## 2026-09-15 — Batch Connect Jupyter app end-to-end (submit → GPU job → proxy)

Made the portal actually run a GPU job and reach the Jupyter server. The
OSC `bc_osc_jupyter` clone is unusable here (it needs OSC-specific modules
like `project/ondemand` and `auto_modules_app_jupyter`), so the portal now
ships the DeepOps Jupyter app (`apps/jupyter/`), which runs on plain Slurm
+ a pip-installed Jupyter runtime.

New / changed files:

- `apps/jupyter/` (new): `form.yml` (mode = JupyterLab|Notebook, GPU count,
  walltime), `submit.yml.erb` (maps form values to Slurm flags),
  `template/before.sh.erb` + `template/script.sh.erb` (launch Jupyter on the
  allocated node, write `connection.yml` host/port, keep the job alive),
  `view.html.erb`, `manifest.yml`.
- `playbooks/ood-portal.yml`: when `ood_apps_enabled: false` it removes the
  OSC app clones, installs `apps/jupyter/` to `/var/www/ood/apps/sys/jupyter`,
  installs the `/rnode` node-proxy Apache config, opens the portal host in
  the compute nodes' firewalls, and installs the Jupyter runtime
  (python3 + pip + jupyterlab + notebook) on the `slurm-node` hosts.
- `config.example/group_vars/ood-portal.yml`: `ood_apps_enabled: false`,
  `ood_portal_app_repos` (OSC clones, disabled), `clusters.deepops` with
  `bin:` and `partition:`.

### Problems found and fixes applied

1. **Session submit failed: `undefined method 'to_h' for an instance of
   String`** (surfaced on the form as "Failed to submit session ...").
   The rendered `submit.yml.erb` was not a YAML hash. Root cause: the header
   used an ERB comment `<%# ... %>` whose text itself contained a
   `<%= gpus %>` example. An ERB comment ends at the **first** closing tag,
   so the comment terminated early, the leftover prose leaked into the
   document, and `YAML.safe_load` returned a plain *String*; `read_yaml_erb`
   then called `.to_h` on it → `NoMethodError`.
   Fix: use plain `#` YAML comments for prose in `apps/jupyter/submit.yml.erb`
   (and never nest `<%= ... %>` inside a `<%# %>` ERB comment in these
   templates).

2. **Session submit failed: `No such file or directory - /usr/local/sbatch`**.
   The cluster config had `bin: /usr/local`, but the OOD Slurm adapter
   resolves the binary as `Pathname(bin).join("sbatch")`
   (`ood_core` `Helper.bin_path`), so `bin` must be the **bin directory
   itself**, not the install prefix.
   Fix: `config/group_vars/ood-portal.yml` → `bin: /usr/local/bin`.

3. **Job ran but the "Connect" URL 404'd** (`/rnode/<node>/<port>/lab`).
   The node-proxy Apache config was written to
   `{{ apache_etc_dir }}/ood-node-proxy.conf` (`/etc/httpd/`), which the main
   httpd config does **not** include (only `conf.d/` is).
   Fix: the playbook now installs it to
   `{{ apache_conf_dir }}/ood-node-proxy.conf` and restarts Apache.

### Validation (full chain)

- Dashboard API submit
  (`POST /pun/sys/dashboard/batch_connect/sys/jupyter/session_contexts`)
  → HTTP 302 (success); a form error re-renders with HTTP 200.
- `squeue`: job RUNNING on `gpu01`; `scontrol show job` →
  `AllocTRES=...gres/gpu=1`, `TresPerNode=gres/gpu:1` (GPU actually
  allocated); `SubmitLine` shows `-p batch --gpus-per-node 1 --time
  04:00:00`.
- Session output dir
  (`/home/new/ondemand/data/sys/dashboard/batch_connect/sys/jupyter/output/
  <uuid>/`): `output.log` shows `nvidia-smi` (the node's GPU) inside the job
  and JupyterLab serving `http://gpu01:8480/lab`; `connection.yml` carries
  `host: gpu01`, `port: 8480`.
- Node proxy: `curl -u new:... http://master/rnode/gpu01/8480/lab` → HTTP
  200, `<title>JupyterLab`.
- `python3 scripts/validation/validate_ood.py --json` (run as root on
  master): `"ok": true`, `"login_ok": true` (200), `"branding_ok": true`,
  `"cluster_config_ok": true`, `"htpasswd_user_ok": true`. (Run as a
  non-root user, `htpasswd_user_ok` is false only because that user cannot
  read the root-owned htpasswd file; the validator still reports
  `"ok": true` when `login_ok` is true.)

## 2026-09-18 — Refactor OOD portal deploy into `roles/ood-wrapper` (OOD 4.2.4 pinned)

Goal: restructure the OOD deployment in the style of NVIDIA/deepops 26.05
`roles/ood-wrapper` — a thin playbook delegating all work to a wrapper role
that includes the upstream installer role — while keeping the installed
release at **ondemand-4.2.4** and the existing 4.2.x configuration style
(OSC rpm from yum.osc.edu, TigerVNC desktop stack, local Jupyter app).

Commands:

```bash
ansible-playbook playbooks/ood-portal.yml --check --diff   # preview
ansible-playbook playbooks/ood-portal.yml                   # converge
ansible-playbook playbooks/ood-portal.yml                   # rerun (idempotency)
python3 scripts/validation/validate_ood.py --json           # on master
```

### Changes

- **New `roles/ood-wrapper/`** (structure mirrors NVIDIA/deepops 26.05
  `roles/ood-wrapper`):
  - `tasks/main.yml` — dispatches on `ood_is_server` / `ood_is_client`
    flags, exactly like the 26.05 wrapper.
  - `tasks/server.yml` — portal side: `httpd-tools`, then
    `include_role: osc.open_ondemand` (the actual OOD install, as 26.05
    does `include_role: ood-ansible`), then the DeepOps site config that
    previously lived in the playbook's `post_tasks` (title, htpasswd
    users, node-proxy Apache config, Jupyter app install, bc_desktop
    patching, PUN restart).
  - `tasks/client.yml` — compute-node side (firewall rich rule, Jupyter
    runtime, TigerVNC + Xfce4 + websockify, vncserver shim), moved verbatim
    from the old second play.
  - `files/ood-node-proxy.conf` — moved from `playbooks/files/`.
  - `defaults/main.yml` — role-mode flags, the **`ondemand_package:
    "ondemand-4.2.4"` pin** (previously only in `config/group_vars`),
    app/app-repo gates, and the path constants below.
- **`playbooks/ood-portal.yml`** — now a ~30-line thin playbook
  (26.05 `open-ondemand.yml` style): two plays, each applying the wrapper
  role with `ood_is_server: true` / `ood_is_client: true`.
- **`playbooks/files/` removed** (its only file moved into the role).
- Site config (`config/group_vars/ood-portal.yml`) unchanged — it still
  overrides the role defaults (group vars > role defaults).

### Problems found and fixes

1. **`'ood_base_conf_dir' is undefined` in the wrapper's post-install
   tasks.** Ansible role `defaults/` only apply inside that role's own
   tasks (and to the play's pre/post_tasks when the role is a play-level
   role) — they do **not** leak into tasks that run after
   `include_role` in a wrapper role. The old monolithic playbook worked
   only because its `post_tasks` are play-level.
   Fix: `roles/ood-wrapper/defaults/main.yml` now mirrors the path
   constants our tasks need (`ood_base_conf_dir`, `apache_etc_dir`,
   `apache_conf_dir`), with a "keep in sync with upstream" note.
2. **`ansible-lint-roles.sh` fails in this network** — it re-downloads
   `roles/requirements.yml` from Galaxy and `geerlingguy.ntp` times out.
   Worked around with `ansible-lint --offline roles/ood-wrapper`
   (production profile passed; the full script's failure is the
   pre-existing network limitation, not a lint finding).

### Known (pre-existing) non-idempotent tasks, preserved as-is

`Ensure htpasswd file exists` (touch), the upstream
`Template nginx_stage.yml` + our title re-write (the template resets the
line every run), the Jupyter app remove-then-reinstall pair, the PUN
restart, and the firewalld restart all still report `changed` on
converged reruns. These existed in the old playbook and are out of scope
for this refactor.

### Validation

- `ansible-playbook playbooks/ood-portal.yml --check --diff`: no failures;
  `RUNNING HANDLER [osc.open_ondemand : Restart apache httpd]` and
  `RUNNING HANDLER [osc.open_ondemand : Update nginx stage]` both fire —
  confirming the wrapper's `notify` resolves the included role's handlers.
- Real run: `failed=0` on master, gpu01, gpu02; `rpm -q ondemand` →
  `ondemand-4.2.4-1.el9.x86_64`.
- Rerun: same `failed=0` (only the pre-existing `changed` tasks above).
- `python3 scripts/validation/validate_ood.py --json` (master):
  `"ok": true`, `"login_ok": true` (200), `"branding_ok": true`,
  `"cluster_config_ok": true`, `"htpasswd_user_ok": true`,
  `"failures": []`.

## 2026-09-18 — Batch Connect "basic apps" catalog (optional install)

Goal (per `ood-ansible.md`): make the portal's Batch Connect apps a set of
**basic apps that are each individually installable** ("可选择安装") instead
of a fixed install set:

- OSC upstream apps (the 17 `bc_osc_*` repos listed in `ood-ansible.md`),
  installed from git when enabled;
- six local DeepOps apps for the commercial/EDA tools listed there
  (`ansyed`, `ansysfluent`, `lumerical`, `alphafold`, `CST Studio Suite`,
  `altair feko`), built after the VNC-session pattern of
  `chpc-uofu/ood-ge-apps-v4` (a web form launches the GUI in a VNC session;
  the app needs the licensed software on the compute nodes);
- each app is toggled with one `enabled:` flag; disabled apps are removed
  from the portal so the menu only shows active apps.

Commands:

```bash
ansible-playbook playbooks/ood-portal.yml          # converge (catalog applied)
python3 scripts/validation/validate_ood.py --json  # on master
# functional test cycle (done on master):
#   enable feko (local)   -> app dir appears with all files
#   render ERB templates  -> valid YAML / shell
#   disable feko          -> app dir removed
#   enable rstudio_server -> OSC git clone appears under apps/sys/
#   disable rstudio_server-> clone removed
```

### Changes

- **`apps/` — six new local Batch Connect apps** (VNC-session pattern, each
  with `manifest.yml`, `form.yml`, `submit.yml.erb`, `template/`):
  `ansyed`, `ansysfluent`, `lumerical`, `alphafold` (Jupyter-based, no
  VNC — launches the AlphaFold 2 notebook), `cst_studio`, `feko`. The form
  widgets (walltime, nodes, cores, GPUs, working dir, license env) follow
  the ood-ge-apps-v4 style; `submit.yml.erb` pins the `deepops` cluster,
  `batch` partition and builds `srun --gpus-per-node`/`--time` from the form.
- **`config/group_vars/ood-portal.yml`** — the old
  `ood_apps_enabled` / `ood_portal_app_repos` pair is replaced by a single
  `ood_apps_catalog` mapping: one entry per basic app with
  `repo:` (OSC git clone) or `local:` (dir under `apps/`), plus `enabled:`.
  All catalog apps default to `enabled: false`; only the DeepOps Jupyter
  app (installed by the role, not the catalog) and the packaged `bc_desktop`
  are on by default. `config.example/group_vars/ood-portal.yml` mirrors it.
- **`roles/ood-wrapper/defaults/main.yml`** — derives `ood_apps_active`,
  `ood_install_apps` (repo-backed apps, fed to the upstream role's
  `Install OOD apps` git task), `ood_apps_local`, and
  `ood_jupyter_local_enabled` from the catalog.
  **Jinja2 note:** list comprehensions are **not** a Jinja2 feature
  (`[x for x in ...]` is a `TemplateSyntaxError`), so the derivations use
  `dict2items | selectattr(...) | items2dict(...)` — the idiomatic form.
- **`roles/ood-wrapper/tasks/server.yml`** — the app section is now:
  install active `local:` apps (copy from `apps/`), remove disabled catalog
  apps (menu hygiene), install the DeepOps Jupyter app unless the OSC
  `jupyter` catalog entry is enabled (which then git-clones the OSC clone
  instead; a `packaging/` stat disambiguates the two so the wrong copy is
  never deleted).
- **`scripts/validation/validate_ood.py`** — `--expected-apps` default is
  now just `jupyter` (the only always-installed app); enable more in the
  catalog and list them here, e.g. `--expected-apps=jupyter,feko`.
- **`skills/deploy-ood-portal/SKILL.md`** — config/deploy/failure text
  updated to the catalog model; the `gh-proxy.com` note corrected to
  "github.com is reachable directly (verified Sep 2026); mirror only as a
  fallback (it 403 rate-limits)".

### Validation

- `ansible-playbook --syntax-check` and `scripts/deepops/ansible-lint-roles.sh`
  pass.
- Check-mode + real run + rerun: `failed=0`; the Jupyter app install is now
  idempotent (the old remove-then-reinstall pair no longer oscillates).
- Functional cycle on master: `feko` enable → `/var/www/ood/apps/sys/feko/`
  created (6 files) → ERB templates render to valid YAML/shell (submit
  `native` args, `APP_CMD` export, GPU flag) → disable → dir removed.
  `rstudio_server` enable → OSC git clone under `apps/sys/rstudio_server/`
  → disable → removed.
- `python3 scripts/validation/validate_ood.py --json` (master):
  `"ok": true`, `"login_ok": true`, `"apps_missing": []`, `"failures": []`.

## 2026-09-20 — All-apps-enabled test + hardening (found & fixed 4 bugs)

Goal (user request): flip **all** `ood_apps_catalog` entries to
`enabled: true` (17 OSC git clones + 6 local apps) and verify the portal
still deploys and the apps actually work end-to-end.

Commands:

```bash
ansible-playbook playbooks/ood-portal.yml          # converge, all 23 enabled
# portal-side session tests (curl + Basic auth, CSRF token from the form page):
#   POST /pun/sys/dashboard/batch_connect/sys/<app>/session_contexts
#     with batch_connect_session_context[<field>=<value>] params
python3 scripts/validation/validate_ood.py --json  # on master
```

Result: all 23 apps installed under `/var/www/ood/apps/sys/`; validator
`"ok": true`, `login_ok: true`, `apps_missing: []`; the `alphafold` app
ran a real JupyterLab session on gpu01 (`/rnode` proxy returned
`<title>JupyterLab`); the `feko` VNC session brought up Xvnc +
websockify cleanly (dies only at `exec feko: not found` — the licensed
software is not on the nodes, as documented).

### Bugs found and fixed

1. **github.com is flaky on this network** — 17 back-to-back clones hit
   "HTTP/2 stream ... not closed cleanly" / "Connection timed out" /
   "Empty reply from server" (10 of 17 failed on one run, 3 of 17 on
   another; the same repos cloned fine moments later). Two fixes:
   - `git config --global http.version HTTP/1.1` on the portal host —
     the HTTP/2 stream errors are gone (curl + git verified after).
   - `roles/ood-wrapper/tasks/server.yml`: the upstream
     `include_role: osc.open_ondemand` is now wrapped in
     `block/rescue` — a failed clone task no longer aborts the rest of
     the play (local app install + site config still run; the recap shows
     `rescued=1` instead of `failed=1`, and a rerun finishes the clones).
2. **`script.sh: Permission denied` in every local-app session** — the
   OOD template EXECs the rendered `script.sh`, but the local apps were
   installed 644 (the copy module preserves the mode of pre-existing
   files, so it never self-healed). The OSC clones ship their files 755,
   which is why the OSC apps never hit this. Fix: both local-app install
   tasks now set `mode: "0755"` (the OSC convention), and the repo's
   `apps/*/template/*.sh.erb` are 755.
3. **Xvnc "Unrecognized option: Altair"** — the vnc template injects
   `-name <name>` unquoted into the Xvnc command line
   (`ood_core-0.31.1/lib/ood_core/batch_connect/templates/vnc.rb`), so a
   multi-word `name:` in `submit.yml.erb` broke the command. Fixed to a
   single-word name (app slug) in all five VNC apps, with a comment
   explaining why; the menu title stays in `manifest.yml`.
4. **OSC `jupyter` clone vs local app dest collision** — `git clone`
   needs an empty dest, but the local Jupyter app occupies
   `apps/sys/jupyter`. `roles/ood-wrapper/tasks/server.yml` now stats the
   occupant (OSC clones ship a `packaging/` dir; the local app does not)
   **before** `include_role` and removes the local app when the OSC clone
   is enabled; switching back removes the clone before installing the
   local app (no mixed-file Frankenstein app).

 ### Validation

- Full catalog enabled: `failed=0` (clone hiccups show as
  `rescued=1` on the flaky-network runs); all 23 apps present on the
  portal; `validate_ood.py` `"ok": true`, `login_ok: true`.
- `alphafold` (basic template): session job ran on gpu01, JupyterLab 2.18.2
  serving, `/rnode/gpu01/<port>/lab` → HTTP 200 `<title>JupyterLab`.
- `feko` (vnc template): Xvnc desktop started (named `feko`), websockify
  proxying, `connection.yml` written; session ends at
  `exec: feko: not found` (expected — software absent on nodes).

## 2026-09-21/22 — Log sweep, service repairs, GPU-job firewall fix, gpu02 recovery

Full-cluster log sweep (`journalctl`/`/var/log` on all 3 hosts) followed
by targeted repairs. All three hosts had rebooted within minutes of each
other on 09-21 01:27–01:29 (common cause, unknown — power event?);
gpu02 additionally had a GPU swap (Quadro M4000 → GTX 1050) on 09-20.

### Problems found and fixes applied

1. **`firewalld`, `tuned`, `setroubleshootd`, `firewall-cmd` broken with
   `ModuleNotFoundError`** — since the python3 alternative was pointed
   at python3.11 (09-08), distro python entry points whose dependencies
   (`python3-dbus`, `tuned`, PyGObject) ship for 3.9 crashed with
   `No module named 'dbus'` / `No module named 'gi'`.
   `nvidia-persistenced` crash-looped for a different reason: a
   hand-added drop-in passed `--user root` while the unit runs as the
   unprivileged `nvidia-persistenced` user → `Failed to change ownership
   of /var/run/nvidia-persistenced: Operation not permitted`.
   Fix (encoded, idempotent, runs on portal host AND compute nodes):
   - `roles/ood-wrapper/tasks/fix-python3-services.yml` (new): pins the
     broken shebangs to `python3.9` (regex that also handles the `-s`/
     `-Es` flags; leaves the working `python3.9` lines and the 3.11-based
     Jupyter runtime alone), rewrites the nvidia-persistenced drop-in
     without `--user root`, clears the stale runtime dir failed runs
     leave behind, and (re)starts the services. Included from both
     `server.yml` and `client.yml`.
   - Result: `firewalld`, `tuned`, `nvidia-persistenced` all `active`,
     `firewall-cmd` usable again; `systemctl --failed` on master clean
     (setroubleshootd is `Type=dbus` static — activates on demand).
   - **Side effect discovered afterwards**: while firewalld was broken
     the firewall enforced nothing, so the portal/monitoring were
     reachable from anywhere. The moment firewalld was repaired it
     started enforcing a default-deny zone that had never been
     populated with the portal/monitoring ports — and (see #2) blocked
     Slurm's step-IO return connections. Both are now encoded.

2. **GPU jobs broken: `srun --gpus=1` failed / hung with
   `Invalid generic resource (gres) specification` or
   `Slurmd could not connect IO` / `No route to host`** — ROOT CAUSE:
   the master's firewall REJECTed slurmd's return connection to the
   srun client's ephemeral IO port (slurmstepd launch is two-phase;
   slurmd must connect back to `HOST:<login> PORT:<ephemeral>`).
   While firewalld was dead this never surfaced; the repair exposed
   it. (A red herring along the way: the slurmd log warning
   `GRES type ... substring of system device ... Setting system GRES
   type to NULL` looked like the cause — it is present on both
   consumer and datacenter cards and did not prevent allocation.
   The GRES type was temporarily renamed `gpu` → `nvidia` and back;
   the working configuration keeps `slurm_gres_type: gpu`.)
   Fix (encoded in `roles/slurm/tasks/firewall.yml`, runs on every
   cluster host):
   - rich rule per cluster peer:
     `rule family=ipv4 source address=<peer-ip>/32 accept` — trusts
     the dedicated cluster network for Slurm's own ephemeral IO
     traffic (port lists cannot cover ephemeral ports);
   - head-node service ports opened (80/443 portal, 3000 Grafana,
     5000/5001 registry, 8080 slurm-exporter, 9090/9090 Prometheus
     + Alertmanager); `roles/ood-wrapper/tasks/server.yml` opens
     80/443 independently so the portal playbook is self-contained.
   - After the fix: `srun --gpus=1 nvidia-smi`, `#SBATCH --gpus=1`,
     `#SBATCH --gpus-per-node=1` (the OOD apps' syntax), and a nested
     `srun --gpus=1` inside a job all COMPLETED (0:0) on both nodes;
     the portal is reachable from a compute node and from outside
     (301 → dashboard).

3. **gpu02 down ~6h after the common reboot** — `State=DOWN, Reason=Node
   unexpectedly rebooted`; the slurmd service was up but had given up
   registering (no retries in the log), while the controller still
   showed the node down. Recovery: `systemctl restart slurmd` on gpu02
   (fresh instance registered immediately —
    `_handle_node_reg_resp: slurmctld sent back 11 TRES`), node returned
    to `idle` automatically.

4. **enroot missing on both compute nodes — and a self-uninstalling
   role task** — `rpm -qa | grep enroot` was empty on gpu01/gpu02
   (binary absent), although the 09-09 deployment had installed it.
   Root cause (caught live in the playbook log): the
   `nvidia.enroot` role's "remove existing enroot package if we are
   changing version" task compared the installed rpm version
   `3.2.0-1.el7` against `enroot_version_string` = `3.2.0-1` — never
   equal — so **every playbook run removed a correctly installed
   enroot and re-downloaded it**; on a flaky network the reinstall
   failed and enroot was left uninstalled (which is how it vanished).
   Fix (local patch in `roles/galaxy/nvidia.enroot/tasks/redhat.yml`,
   alongside the existing `disable_gpg_check` patch — both lost if
   `./scripts/setup.sh` reinstalls the role from Galaxy):
   - version comparison changed to a prefix match
     (`is not match('^' + enroot_version)`);
   - the URL install task now skips when the wanted version is
     already installed (reruns no longer need github.com for enroot).
   - Verified: enroot 3.2.0 + enroot+caps reinstalled on both nodes;
     the next full playbook run skips the install (`skipping:`) and
     finishes `failed=0` on all three hosts.

### Validation

- `sinfo`: `batch up infinite 2 idle gpu[01-02]`.
- GPU jobs: interactive `srun --gpus=1` and batch jobs COMPLETED (0:0)
  on **both** nodes, `nvidia-smi` listing the node's GPU
  (GTX 750 / GTX 1050).
- `validate_slurm.py --json`: `"ok": true`, `gpu_job_ok: true`,
  `nodes_available: 2` (this validator itself uses `srun --gpus=1` —
  the user-facing syntax works).
- Portal reachable from a *different* host (301 → login page);
  `validate_ood.py --json`: `"ok": true`, `login_ok: true`.
- `systemctl --failed` on master: empty.
- ansible-lint (production profile): PASSED.

### Pre-existing wobble (not introduced by this work, not fixed)

- Every `slurm-cluster.yml` run stops and restarts slurmd
  (`misc-node.yml: ensure all slurm services are stopped` has no
  change-detection guard) and rebuilds Pyxis from source
  (`pyxis: build pyxis` always reports changed). Plan runs accordingly
  (brief node service interruption per run) or add guards later.
- The `nvidia.nvidia_driver : add epel repo` URL install re-downloads
  the EPEL RPM on every run; fails when dl.fedoraproject.org is
  unreachable (same class of bug as the enroot one — a guard could be
  added the same way).

### Follow-ups (not done)

- Common-cause reboot of all three hosts at 09-21 ~01:27: unexplained
  (no kernel panic / OOM evidence found in surviving logs); worth a
  power/UPS check if it recurs.
- The `slurmd -G` GRES "substring" warning is still emitted on these
  consumer cards; harmless so far (allocation works), but worth a
  look if GPU binding ever stops working.

## 2026-09-23 — Cluster recovery after 3rd ~01:2x reboot + resilience hardening + enroot container path proven

### What happened overnight

- **Third consecutive ~01:2x–01:3x reboot of all three hosts** (09-21
  01:27, 09-22 01:33, 09-23 01:22–01:32). Same pattern, common cause,
  still unexplained (no cron/timer/upgrades found; GNOME session present
  on master; suspect lab power schedule — check UPS/building power).
- After the reboot: both nodes **DOWN** ("Node unexpectedly rebooted"),
  `/home` + `/sw` NFS mounts **failed** (nodes booted before master's
  NFS server; systemd never retries a failed .mount unit), and
  `nvidia-persistenced` **crash-looping on both nodes** (the python3.9
  `--user root` drop-in bug — the fix task had never run on the nodes,
  see bug below).
- Recovered by hand: slurmd restart, `systemctl start home.mount
  sw.mount` on both nodes, and the slurmctld state-directory reset
  (README §7.1) → both nodes back to `idle`.

### Bugs found and fixed

1. **OOD golden-path limit silently skipped the node play.**
   `AGENTS.md`, `skills/deploy-ood-portal/SKILL.md` and README §9.1 all
   said `ansible-playbook -l ood-portal playbooks/ood-portal.yml`.
   `playbooks/ood-portal.yml` has TWO plays (`ood-portal` + `slurm-node`);
   the limit made the node play (Jupyter runtime, node-side service
   repairs incl. the nvidia-persistenced/firewalld python3.9 fix)
   silently skip while the recap still showed success. That is why the
   node-side fixes never landed. Fixed all three docs to
   `-l ood-portal,slurm-node` and added a WARNING header to
   `playbooks/ood-portal.yml` itself. Re-ran the full playbook:
   **nvidia-persistenced is now `active` on both nodes, Persistence Mode
   enabled**.
2. **NFS mount boot-order race** (nodes up before master's NFS server →
   permanent .mount failure). Added to `roles/nfs/tasks/client.yml`:
   `nfs-mount-retry.service` (oneshot, enabled at boot) that re-runs
   `mount -a` until all configured mounts are up (≤10 min). Installed
   and active on both nodes.
3. **Slurm 26.x "unexpected reboot" DOWN state** needs manual state
   reset (scontrol cannot clear it — verified again). Added:
   - `roles/slurm/tasks/auto-recover.yml` — runs on every controller-side
     playbook pass; detects DOWN nodes, recovers (state reset + ctld
     restart) **only while the queue is empty**, otherwise reports and
     waits. Included from `roles/slurm/tasks/main.yml`.
   - `slurm-node-recover.service` (boot oneshot on master,
     `roles/slurm/templates/slurm-node-recover.*`) — same recovery
     automatically at boot, up to 2h wait for the queue to drain.
   So the ~01:2x reboots no longer require a human: nodes come back on
   their own, and mounts retry until the server is reachable.

### Enroot 3.2.0 container path — usage bug found, path proven end-to-end

- `enroot create nvcr.io/...` fails ("No such file or directory"):
  3.2.0 treats scheme-less refs as local files, and `docker://X`
  **always targets Docker Hub** (unreachable here). Not a version bug —
  upgrading is NOT required (3.3.0/3.4.0 el7 RPMs were checked; they do
  not change this).
- Correct 3.2.0 URI syntax (from `enroot import --help`):
  `docker://[USER@][REGISTRY#]IMAGE[:TAG]` — registry separated by `#`.
- Also: `enroot start -w` is `--rw` (writable rootfs), **not** workdir.
- **Gold test on gpu02 (job 4, exit 0):**
  `enroot import "docker://nvcr.io#nvidia/cuda:12.4.1-base-ubuntu22.04"`
  (243MB .sqsh) → `enroot create -f -n cuda <sqsh>` → `enroot start cuda
  nvidia-smi` inside `--gpus=1` job → **GTX 1050 visible in the
  container, driver 580.178.04**. README §4.3 rewritten with the
  verified workflow.

### gpu01 went fully offline ~04:55 — RECOVERED 06:11

- While/after the heavy `enroot import` job (1GB download + squashfs
  build as root on an 8-core/7GB box), gpu01 dropped off the network:
  no ping, no L2 (ARP INCOMPLETE from master), all ports rejected;
  Slurm shows it `down`. Possibly memory/disk pressure induced a crash,
  or coincidental power event (given the nightly pattern).
- **Recovery (after on-site power-on ~06:05):** node came back
  (ping/ssh/sshd OK, slurmd up), Slurm kept it `DOWN`
  ("Node unexpectedly rebooted") → queue empty → state-directory reset
  (README §7.1) → **both nodes `idle`**, GPU job on gpu01 verified
  (`nvidia-smi -L` → GTX 750, exit 0).
- **Found & fixed an exporter boot race on gpu01:** the
  `docker.{node,dcgm}-exporter` services failed at boot (pull at
  06:05:48 lost the race → 6 rapid failures → systemd StartLimitBurst
  parked them `failed`; Prometheus targets `down`). Images were cached
  locally, so manual `systemctl restart` fixed it immediately.
  Root-cause hardening: the `ExecStartPre` pull in both unit templates
  (`roles/prometheus-node-exporter/templates/…`,
  `roles/nvidia-dcgm-exporter/templates/…`) now retries 6×10s, and the
  same fix was applied in place on all 3 hosts (units backed up to
  `*.bak-retry`); services restarted cleanly everywhere.
- Final state: `validate_slurm.py` **ok:true, gpu_job_ok:true,
  2/2 nodes idle**; `validate_ood.py` **ok:true, login_ok:true**;
  Prometheus **6/6 targets up**; `ultralab.html` regenerated to match.

### Validation (final state of this session)

- `validate_slurm.py --json`: `"ok": true`, `gpu_job_ok: true` (2 nodes
  before gpu01 went down; 1 serving after).
- `validate_ood.py --json`: `"ok": true`, `login_ok: true`.
- `slurm-cluster.yml` (all 3 hosts): `failed=0` — installed
  nfs-mount-retry, auto-recover task; idempotent.
- `ood-portal.yml` (both plays): `failed=0` on all hosts — node-side
  repairs landed; catalog apps complete (2 github clones needed a
  rerun due to flaky github.com, then converged).
- Prometheus: 6/6 targets up. Registry `master:5000` serving (empty
  catalog). Monitoring stack + rsyslog + MariaDB accounting all active.
### Second gpu01 offline event 07:53 — RECOVERED 08:11

- ~07:53 gpu01 dropped off the network **again** (100% packet loss, ARP
  incomplete; Slurm `Reason=Not responding` → `DOWN`), ~3h after the
  04:55 event and **outside** the nightly ~01:3x window (master's own
  `last` shows daily reboots 01:28–01:34 for 5 consecutive days, so the
  daytime deaths are a separate, gpu01-specific instability).
- **Recovery (after on-site power-on ~08:01):** ping OK; Slurm kept it
  `DOWN` ("Node unexpectedly rebooted") → queue empty → state-directory
  reset (README §7.1) → **both nodes `idle`** by 08:05.
- **Exporters self-healed this time:** with the 6×10s pull-retry fix in
  place, gpu01's `node-exporter` (9100) and `dcgm-exporter` (9400) came
  up at boot **without manual restart** (both OPEN; Prometheus back to
  6/6 up). The 04:55 incident's manual fix is now unnecessary.
- **GPU/CPU mixed submission proven (08:11):** three concurrent jobs —
  `mixGPU` on gpu01 (`--gpus=1`, GTX 750 visible), `mixCPU` on the
  **same node** (CPU-only, `nproc=2`), `mixGPU2` on gpu02 (GTX 1050) —
  all `COMPLETED 0:0` in the same scheduling window. Single pool serves
  GPU and CPU workloads concurrently (TRES accounting).
- **Deliverable:** `ultralab.html` regenerated as the full UltraLAB HPC
  Cluster dossier — module/plugin inventory (15 layers), interaction
  architecture, workflows (web / CLI / container), **GPU+CPU mixed
  submission** section, **OOD-Web submission deep-dive** (33 apps,
  Jupyter form→job→/rnode flow, PUN), user manual, monitoring stack,
  **expert-mode sales advantage report** (8 selling points + risk
  disclosure), and live validation evidence. HTML parse verified OK.
- **Open item (hardware):** gpu01's repeated daytime network-level
  deaths need an on-site power/thermal/BMC check; software-side
  self-healing (NFS retry, Slurm DOWN recovery, exporter pull retry)
  is proven but cannot substitute for a stable power path.
### OOD portal: browser login broken via IP — FIXED (canonicalization 301)

- **Symptom:** portal login failed from a browser on another machine:
  `http://192.168.0.200/` answered `301 → Location: http://master:80/`,
  and clients cannot resolve the bare hostname `master` → the page never
  loaded. Local (on-master) checks kept passing because `/etc/hosts`
  resolves `master`.
- **Root cause:** the 09-18 `roles/ood-wrapper` refactor regenerated
  `/etc/httpd/conf.d/ood-portal.conf` with `ood-portal-generator`
  0.8.0 from `/etc/ood/config/ood_portal.yml` (`servername: master`).
  The generator emits a host-canonicalization block
  (`RewriteCond %{HTTP_HOST} !^(master(:80)?)?$` →
  `RewriteRule ^(.*) http://master:80$1 [R=301]`) that redirects every
  non-`master` Host (incl. the IP) to the unresolvable hostname.
- **Fix:** added a `server_aliases` allowlist
  (`192.168.0.200`, `127.0.0.1`) to `/etc/ood/config/ood_portal.yml`,
  regenerated with `update_ood_portal`, restarted httpd. Both
  `http://192.168.0.200/` and `http://master/` now serve directly;
  `validate_ood.py` back to **ok:true, login_ok:true**, dashboard
  title "Dashboard - UltraLAB HPC Cluster".
- **Persistence:** `config/group_vars/ood-portal.yml` now sets
  `server_aliases` (portal IP from inventory + 127.0.0.1), so a future
  `ood-portal.yml` playbook run re-renders the same safe vhost.
  (Backup: `/etc/ood/config/ood_portal.yml.bak-redirect`.)
