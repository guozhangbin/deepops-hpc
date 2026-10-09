# DeepOps Slurm GPU 集群部署文档

> 本文档整理基于 [NVIDIA DeepOps](README.md) 在一套 3 节点实验室 GPU 集群上
> 部署并调通 **Slurm GPU 批处理集群** 与 **Open OnDemand Web 门户**
> （UltraLAB HPC Cluster）的完整过程：集群拓扑、已部署组件、
> 日常使用方法、部署中排查并修复的问题、验证结果，以及后续运维注意事项。
> 供集群使用者与运维人员参考。
>
> - 操作系统：Rocky Linux 9.8
> - 调度器：Slurm 26.05.3
> - 网络环境：**出口受限**（`github.com` / `docker.io` / `quay.io` 不可直连，
>   部署通过国内镜像 / GitHub 代理完成）
> - 详细逐条记录见 [CHANGELOG.md](CHANGELOG.md)

## 目录

- [1. 集群概述](#1-集群概述)
- [2. 集群拓扑](#2-集群拓扑)
- [3. 已部署组件](#3-已部署组件)
- [4. 快速使用](#4-快速使用)
  - [4.1 查看集群状态](#41-查看集群状态)
  - [4.2 提交 GPU 作业](#42-提交-gpu-作业)
  - [4.3 容器化 GPU 作业（Enroot / Pyxis）](#43-容器化-gpu-作业enroot--pyxis)
  - [4.4 监控入口](#44-监控入口head-节点-1921680200)
- [5. 部署过程与解决的问题](#5-部署过程与解决的问题)
  - [5.1 容器 / 镜像源](#51-容器--镜像源)
  - [5.2 依赖与离线获取](#52-依赖与离线获取)
  - [5.3 网络 / 防火墙](#53-网络--防火墙)
  - [5.4 Slurm 运行时](#54-slurm-运行时)
- [6. 验证结果](#6-验证结果)
- [7. 运维注意事项](#7-运维注意事项)
  - [7.1 节点重启后进入 `DOWN` 的恢复](#71-节点重启后进入-downnode-unexpectedly-rebooted的恢复)
  - [7.2 离线 / 镜像依赖](#72-离线--镜像依赖重跑需注意)
  - [7.3 防火墙端口](#73-防火墙端口)
  - [7.4 GPU 可见性](#74-gpu-可见性)
  - [7.5 监控缺节点 / GPU 功耗指标缺失](#75-监控缺节点--gpu-功耗指标缺失2026-10-09-修复)
- [8. 重新部署与关键文件](#8-重新部署与关键文件)
  - [8.1 标准部署流程](#81-标准部署流程)
  - [8.2 关键文件位置](#82-关键文件位置)
  - [8.3 参考](#83-参考)
- [9. Open OnDemand 门户（UltraLAB HPC Cluster）](#9-open-ondemand-门户ultralab-hpc-cluster)
  - [9.1 本地应用的通用表单字段](#91-本地应用的通用表单字段)
  - [9.2 部署与校验](#92-部署与校验)
  - [9.3 关键文件](#93-关键文件)


---

## 1. 集群概述

- **类型**：Slurm GPU 批处理集群（单控制节点 + 双计算节点）
- **规模**：3 台物理服务器，共 3 张 NVIDIA GPU（每个计算节点 1 张）
- **驱动**：NVIDIA 580.178.04（三台均已安装）
- **CUDA**：CUDA Toolkit 12.8.0
- **容器化作业**：Enroot 3.2.0 + Pyxis v0.11.1（在 Slurm 作业内运行容器）
- **监控**：Prometheus + Grafana + Alertmanager + 各类 exporter（全部 `up`）
- **存储**：NFS 共享 `/home`（家目录）与 `/sw`（软件栈）

## 2. 集群拓扑

| 主机名 | IP | 角色 | GPU（显存） | Slurm 配置 |
|--------|----|------|------------|-----------|
| `master` | `192.168.0.200` | 控制 / 登录 / 监控 / 镜像仓库 | GTX 1050（Pascal，2048 MiB） | `slurmctld` + `slurmdbd` |
| `gpu01` | `192.168.0.201` | 计算节点 | GTX 750（Maxwell，1024 MiB） | `slurmd`，8 核 / 7249 MB |
| `gpu02` | `192.168.0.202` | 计算节点 | GTX 1050（Pascal，2048 MiB） | `slurmd`，6 核 / 14882 MB |

> GPU 均为消费级卡（Pascal / Maxwell 架构），显存较小，适合功能验证与
> 小规模任务，而非大模型训练。

**Slurm 分组**（定义于 `config/inventory`）：

| 分组 | 成员 |
|------|------|
| `slurm-master` | `master` |
| `slurm-node` | `gpu01`、`gpu02` |
| `slurm-cluster`（整个集群） | `master`、`gpu01`、`gpu02` |
| `slurm-nfs` / `slurm-cache` / `slurm-metric` / `slurm-login` | 均落在 `master` |

每个计算节点配置 1 张 GPU（`Gres=gpu:1`），默认分区 `batch`（`MaxTime=INFINITE`）。

## 3. 已部署组件

| 组件 | 版本 / 说明 |
|------|-----------|
| **Slurm** | 26.05.3（`slurmctld` / `slurmdbd` / `slurmd`，cgroup/v2，MariaDB 记账） |
| **PMIx / hwloc** | PMIx 3.2.3（经 GitHub 代理获取源码）、hwloc（`/opt/deepops/`） |
| **NVIDIA 驱动** | 580.178.04（三台） |
| **CUDA** | CUDA Toolkit 12.8.0 |
| **Enroot + Pyxis** | enroot 3.2.0 + enroot+caps；Pyxis v0.11.1（slurmd 中已加载） |
| **NFS** | `master` 为 NFS 服务端，导出 `/home`、`/sw`；计算节点挂载 |
| **软件栈** | Lmod + EasyBuild（`/sw`）、NVIDIA HPC SDK（以 module 形式） |
| **容器运行时** | Docker（含 registry mirror）+ NVIDIA Container Toolkit |
| **私有镜像仓库** | `master:5000`（已配置为 insecure registry + mirror） |
| **监控** | Prometheus / Grafana / Alertmanager（master，Docker 容器）；node-exporter（9100）、DCGM-exporter（9400）、slurm-exporter（8080，三台） |
| **日志** | rsyslog 集中（server=`master`） |
| **Web 门户** | Open OnDemand 4.2（Apache + Passenger，`master`）：23 个应用目录 + Desktop（Xfce/VNC）+ Shell 网页终端，详见第 9 节 |

## 4. 快速使用

> 以下命令在 `master`（或任意可访问 Slurm 的节点）上以普通用户执行。
> 计算节点默认**限制 SSH**：只有正在运行作业的用户才能登录（`slurm_restrict_node_access: true`）；
> 门户用户 `new` 在 `slurm_allow_ssh_user` 白名单（`/etc/localusers`）中，无作业也可登录
> ——这是 Shell 网页终端（第 9 节）的前提之一。

### 4.1 查看集群状态

```bash
sinfo                     # 分区与节点状态（期望：batch  up  2 idle）
squeue                    # 当前作业队列
scontrol show node gpu01  # 单节点详情
```

### 4.2 提交 GPU 作业

交互式验证 GPU 可见性（在作业内执行，**不要**用裸 SSH `nvidia-smi`）：

```bash
srun --gpus=1 nvidia-smi -L
```

提交一个使用 GPU 的批处理作业（`SBATCH` 请求）：

```bash
cat > gpu_job.sh <<'EOF'
#!/bin/bash
#SBATCH --job-name=demo
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --time=00:10:00

nvidia-smi
# 在此处放置你的 GPU 命令，例如：
# python train.py
EOF
sbatch gpu_job.sh          # 提交
squeue -j <JOBID>          # 查看状态
scancel <JOBID>            # 如需取消
```

> 说明：DeepOps 在计算节点上对普通 SSH 会话隐藏 GPU，GPU 仅在 Slurm 作业内可见。
> 因此验证 GPU 一律用 `srun --gpus=1 …` 或 `validate_slurm.py`，而不是直接 SSH 后跑 `nvidia-smi`。

### 4.3 容器化 GPU 作业（Enroot / Pyxis）

集群已安装 Enroot 3.2.0 + Pyxis，可在 Slurm 作业内运行容器镜像。
**Enroot 3.2.0 的 URI 语法**（`enroot import --help`）：

```
docker://[USER@][REGISTRY#]IMAGE[:TAG]
```

- 非 Docker Hub 的 registry 必须用 **`#`** 分隔 registry 与镜像名；
- 裸引用（`nvcr.io/...`）会被当成本地文件 → `No such file or directory`；
- `docker://` 不带 `#` 时固定走 Docker Hub（本网络不可达）。

正确用法（示例：CUDA 基础镜像，压缩后约 243MB，首次拉取约 9 分钟）：

```bash
# 1) 拉取镜像为 .sqsh（注意：3.2.0 把产物写到当前目录，
#    文件名由 URI 生成，如 nvidia+cuda+12.4.1-base-ubuntu22.04.sqsh）
cd ~/images
enroot import "docker://nvcr.io#nvidia/cuda:12.4.1-base-ubuntu22.04"

# 2) 在作业内创建容器并运行（GPU 经 Pyxis 直通）
#    注意:3.2.0 里 start 的 -w 是 --rw(可写根文件系统),不是工作目录!
sbatch <<'EOF'
#!/bin/bash
#SBATCH --gpus=1
#SBATCH --time=00:30:00
cd ~/images
enroot create -f -n cuda nvidia+cuda+12.4.1-base-ubuntu22.04.sqsh
enroot start cuda nvidia-smi
EOF
```

> 2026-09-23 实测（gpu02）：`import`(nvcr.io) + `create` + 作业内
> `start`+`nvidia-smi` 全链路通过，容器内可见宿主 GPU（GTX 1050 /
> 驱动 580.178.04）。

### 4.4 监控入口（head 节点 `192.168.0.200`）

| 服务 | 地址 |
|------|------|
| Grafana | `http://192.168.0.200:3000` |
| Prometheus | `http://192.168.0.200:9090` |
| Alertmanager | `http://192.168.0.200:9093` |
| slurm-exporter | `http://192.168.0.200:8080` |
| 私有镜像仓库 | `http://192.168.0.200:5000` |

> 监控服务以 **Docker 容器**（systemd 托管）方式运行，用 `docker ps` 查看，
> 而不是 `systemctl`（`systemctl is-active prometheus` 会显示 inactive，属正常现象）。

## 5. 部署过程与解决的问题

部署命令：

```bash
ansible-playbook -l slurm-cluster playbooks/slurm-cluster.yml -k
```

由于本环境**出口受限**且 Rocky 9 / Slurm 26.05 存在若干兼容性差异，部署过程中
共排查并修复 14 类问题（完整逐条见 [CHANGELOG.md](CHANGELOG.md)）。按类别归纳：

### 5.1 容器 / 镜像源
1. **Docker 启动失败**：`/etc/docker/daemon.json` 与 kubespray 写入的
   `--registry-mirror` flag 同时存在 `registry-mirrors`，Docker 28 拒绝启动。
   删除节点上的 `daemon.json`，并在 playbook 中加入自愈 play。
2. **监控容器拉取超时**：`docker.io` / `quay.io` 不可直连。改为经可达镜像
   （`dockerproxy.net` / `docker.1ms.run` / `quay.m.daocloud.io`）拉取并预拉取；
   DCGM exporter 因 `nvcr.io` 可达而保持默认。
3. **slurm-exporter 构建失败**：buildkit 默认 bridge 沙箱无法解析外网域名，
   改为 `docker build --network=host`。

### 5.2 依赖与离线获取
4. **CUDA 版本语法**：RHEL9 的 dnf 不解析 `name=version`，改用 `name-version-release`
   （`cuda-toolkit-12.8.0-1`），版本值放到 `config/`。
5. **PMIx 源码**：`github.com` 不可达，改用 GitHub 代理（sha256 经第二镜像交叉校验）。
6. **Slurm 构建依赖**：启用 Rocky 9 的 `crb` 仓库；RHEL9 无 `libev-devel`
   （改用 libevent）；无 `mailx`（改用 `s-nail`）；补 `dbus-devel`。
7. **enroot GPG 校验失败**：NVIDIA 官方 enroot RPM 未签名，而 `gpgcheck=1`，
   对该 yum 任务加 `disable_gpg_check: true`（源为官方 HTTPS，可信）。

### 5.3 网络 / 防火墙
8. **节点 `NOT_RESPONDING`/`DOWN` + 监控跨网不可达**：Rocky 9 默认 firewalld
   拒绝。新增 `roles/slurm/tasks/firewall.yml`，在永久区放行
   `6817/6818/11310`（Slurm）与 `9100/9400`（监控抓取）。
9. **master 解释器**：inventory 中 `ansible_python_interpreter` 误用 YAML 语法被
   INI 解析器丢弃，改为 INI 语法并指向装有 `python3-firewall` 的 Python 3.9。

### 5.4 Slurm 运行时
10. **cgroup/v2 插件未编译**：缺 `dbus-devel` 导致 configure 条件不满足；补依赖后
    强制重建 Slurm（`cgroup_v2.so`）。
11. **废弃配置项**：移除 Slurm 26.05 报告为 defunct 的 `CgroupAutomount=yes` 与
    `AccountingStorageUser=…`。
12. **MariaDB root 登录（1698）**：PyMySQL 走 TCP 而 root 仅允许 unix-socket，
    `mysql_user` 任务加 `login_unix_socket=/var/lib/mysql/mysql.sock`。
13. **NHC 构建源不可达**：关闭 `slurm_install_nhc`，`HealthCheckProgram` 指向
    恒成功的 `/bin/true`，避免节点被排空。
14. **节点 `DOWN`（"unexpectedly rebooted"）**：enroot 写入内核参数后重启节点，
    Slurm 26.x 将其判为"非预期重启"并置 `DOWN`；该版本不允许 `scontrol update
    NodeState=RESUME|IDLE`，`ReturnToService=1` 也无法清除。恢复方法见
    [§7 运维注意事项](#7-运维注意事项)。

## 6. 验证结果

- **Playbook 收敛**：`ansible-playbook -l slurm-cluster playbooks/slurm-cluster.yml`
  三台主机均 `failed=0`（master `ok=594`，gpu01/gpu02 `ok=437`），含 enroot+Pyxis
  安装与防火墙任务。
- **官方校验器**（在 master 上）：

  ```bash
  python3 scripts/validation/validate_slurm.py --json
  ```

  ```json
  {
    "ok": true,
    "gpu_job_ok": true,
    "gpu_job_ran": true,
    "gpus_configured": 2,
    "nodes_available": 2,
    "nodes_unavailable": 0,
    "node_states": { "idle": 2 },
    "slurm_version": "26.05.3"
  }
  ```

- **监控**：Prometheus / Grafana / Alertmanager / slurm-exporter 均 `Up`；
  node-exporter + DCGM-exporter 三台 `Up`；7 个抓取目标
  （master/gpu01/gpu02 × 9100/9400 + master:8080 slurm-exporter）全部 `up`；
  9100/9400 端口返回 HTTP `200`。
- **门户**：`validate_ood.py --json` 返回 `"ok": true`
  （登录 / 品牌 / 集群配置 / 23 个应用全部在位；Shell 网页终端
  WebSocket 在 `master` / `gpu01` / `gpu02` 三台均验证通过，见第 9 节）。

> 依据本仓库规则：**以校验器的 `"ok": true` 为成功信号**，而不是 playbook 的
> `failed=0`。两者此处均满足。

## 7. 运维注意事项

### 7.1 节点重启后进入 `DOWN`（"Node unexpectedly rebooted"）的恢复

**现象**：节点重启（例如 enroot 写入内核参数 `namespace.unpriv_enable=1`、
`user_namespace.enable=1` 后的重启）后，`sinfo` 显示节点 `down`，
`Reason=Node unexpectedly rebooted`。这是 Slurm 对"非 Slurm 主动重启"的安全态。

**为什么常规手段无效**（Slurm 26.05.3 实测）：
- `scontrol update NodeName=X NodeState=RESUME` → `Update of this parameter is not supported`
- `scontrol update NodeName=X NodeState=IDLE` → 同样被拒绝
- `ReturnToService=1`（已配置）不会清除该非预期重启态
- 再次重启节点只会重新触发同样的 `DOWN`

**恢复步骤**（无运行中作业时安全）：

```bash
# 在 master 上执行
systemctl stop slurmctld
# 关键：整个 StateSaveLocation 目录需清空/移走，而不是只删 node_state
mv /var/spool/slurm/ctld /var/spool/slurm/ctld.bak
mkdir -p /var/spool/slurm/ctld
chown slurm:slurm /var/spool/slurm/ctld
chmod 700 /var/spool/slurm/ctld
systemctl start slurmctld
# 稍候，节点将以 idle 重新注册
sinfo
```

> 注意：仅删除 `node_state`（而保留其余状态文件）会导致 slurmctld 启动失败
> （`fatal: No node state file to recover`）。必须让整个状态目录干净，
> slurmctld 才会重建状态并让节点重新注册为 `idle`。

### 7.2 离线 / 镜像依赖（重跑需注意）

- 本环境 `github.com` / `docker.io` / `quay.io` 不可直连。相关 URL / 镜像已改为
  代理或国内镜像，配置位于 `config/group_vars/`（`pmix_src_url`、
  `slurm_pyxis_tarball_url`、`prometheus_container` 等）。
- **enroot 的 GPG 补丁**是对 git 忽略的 Galaxy 角色
  （`roles/galaxy/nvidia.enroot/tasks/redhat.yml`）的本地修改。
  若重新执行 `./scripts/setup.sh`（会 `ansible-galaxy role install --force`），
  该补丁会被覆盖，需要重新打上 `disable_gpg_check: true`。
- 站点特定值一律放在 `config/`（group_vars / inventory），**不要**改 role 默认值。

### 7.3 防火墙端口

集群主机需在永久 firewalld 区放行以下端口（由 `roles/slurm/tasks/firewall.yml` 维护）：

| 端口 | 用途 |
|------|------|
| 6817/tcp | slurmctld（节点 → 控制器） |
| 6818/tcp | slurmd（控制器 → 节点） |
| 11310/tcp | munge 认证 |
| 9100/tcp | node-exporter（监控抓取） |
| 9400/tcp | DCGM-exporter（监控抓取） |

### 7.4 GPU 可见性

计算节点对普通 SSH 隐藏 GPU，仅在 Slurm 作业内可见。验证 GPU 请用
`srun --gpus=1 nvidia-smi` 或 `validate_slurm.py`，**不要**用裸 SSH `nvidia-smi`。

### 7.5 监控缺节点 / GPU 功耗指标缺失（2026-10-09 修复）

**现象**：Grafana（`http://192.168.0.200:3000`）GPU 仪表盘 `server` 下拉框
只见 `gpu01`，缺 `master` 与 `gpu02`。

**原因**（两条独立问题叠加）：
1. Prometheus 的 file_sd 端点模板（`node-exporter.yml.j2` /
   `dcgm-exporter.yml.j2`）只枚举 `slurm-node` 组——`master` 上运行中的
   node-exporter / DCGM-exporter 从未被抓取；
2. `master` 与 `gpu02` 的 **GTX 1050 无功耗传感器**
   （`nvidia-smi -q -d POWER` 显示 `Average Power Draw: N/A`），DCGM 对这两台
   不导出 `DCGM_FI_DEV_POWER_USAGE`；而原 GPU 仪表盘的 `server` 下拉框正是
   用该指标构建的 → 没有此字段的节点直接从下拉框"消失"（gpu01 的 GTX 750
   可正常读功耗，所以只有它可见）。

**修复**（已合入仓库并生效）：
- 两个端点模板改为枚举 `slurm-master` + `slurm-node`，7 个抓取目标全部 `up`
  （Prometheus file_sd 自动感知文件变化，无需重启）；
- GPU 仪表盘 `server` 下拉框改为由
  `up{job="cluster",instance=~".*:9400"}` 构建
  （`src/dashboards/gpu-dashboard.json`），与具体 DCGM 字段解耦，缺字段的
  节点也保持可见。

**残留现象**：master/gpu02 的功耗面板（GPU Power Usage / Power Total）仍无
数据——硬件限制（该卡无传感器），非软件问题；利用率 / 温度 / 显存面板
三台均正常。

## 8. 重新部署与关键文件

### 8.1 标准部署流程

```bash
git submodule update --init --recursive   # 如需 K8s（本 Slurm 部署不强制）
./scripts/setup.sh                        # 安装 Ansible + Galaxy 依赖
cp -r config.example config               # 首次：复制并编辑配置
python3 scripts/validation/deepops_doctor.py --json   # 部署前体检

ansible-playbook -l slurm-cluster playbooks/slurm-cluster.yml -k   # 部署
python3 scripts/validation/validate_slurm.py --json                # 部署后校验
```

> Playbook 幂等，重跑是正常恢复手段；瞬时故障（镜像超时、网络抖动）后直接重跑即可。

### 8.2 关键文件位置

| 路径 | 说明 |
|------|------|
| `config/inventory` | 主机清单与分组（本集群 3 台） |
| `config/group_vars/all.yml` | 全局站点配置（CUDA 版本、Docker 镜像等） |
| `config/group_vars/slurm-cluster.yml` | Slurm 站点配置（PMIx/Pyxis 代理、监控镜像、NFS、Enroot 等） |
| `playbooks/slurm-cluster.yml` | Slurm 集群顶层部署入口 |
| `roles/slurm/` | Slurm 角色（含新增的 `tasks/firewall.yml`） |
| `roles/galaxy/nvidia.enroot/` | enroot 角色（本地打了 GPG 补丁，git 忽略） |
| `scripts/validation/validate_slurm.py` | Slurm 部署后校验器 |
| `scripts/validation/deepops_doctor.py` | 部署前体检 |
| [CHANGELOG.md](CHANGELOG.md) | 本次部署的逐条问题与修复记录 |

### 8.3 参考

- 项目总览：[README.md](README.md)（英文原版）
- Agent / 新人操作指南：[AGENTS.md](AGENTS.md)
- Slurm 部署文档：`docs/slurm-cluster/`
- 分步操作技能：`skills/`

---

## 9. Open OnDemand 门户（UltraLAB HPC Cluster）

在 `master` 上部署了 **Open OnDemand 4.2**（Apache + Phusion Passenger +
OnDemand），作为通过 Web 提交 GPU 作业的门户：

- 门户地址：`http://master/`（即 `http://192.168.0.200/`），匿名访问
  返回 401（Basic 认证）。
- 登录用户：`new`（密码见 `config/group_vars/ood-portal.yml` 的
  `ood_portal_users`；条目存于 `/etc/httpd/.htpasswd`）。
- **应用目录（23 个，全部启用）**：
  - 17 个 OSC 上游应用：ANSYS Workbench、Jupyter、Jupyter Spark、MATLAB、
    COMSOL、code-server、VMD、Schrödinger、RStudio Server、PyMOL、Ollama、
    MLflow、TensorBoard、ParaView、Abaqus、Classroom Jupyter / RStudio；
  - 6 个本地应用（本仓库 `apps/`，设计参照 CHPC
    [chpc-uofu/ood-ge-apps-v4](https://github.com/chpc-uofu/ood-ge-apps-v4)）：
    ANSYS Electronics Desktop（`ansysedt`）、ANSYS Fluent（`ansysfluent`）、
    Lumerical、AlphaFold、CST Studio Suite（`cst_studio`）、
    Altair FEKO（`feko`）——其中 5 个 GUI 应用在 VNC/Xfce 会话中启动
    （浏览器 noVNC），AlphaFold 为纯 Web 变体；
  - **Desktop** 应用（`bc_desktop`）：完整 Xfce 桌面（TigerVNC +
    websockify + `/rnode` 反代），节点侧运行时由 playbook 安装；
  - 内置应用：Dashboard、My Jobs、Active Jobs、Files、File Editor、
    Module Browser、Projects、**Shell（网页终端）**、System Status。
- **Shell 网页终端**：`http://master/pun/sys/shell/ssh/<master|gpu01|gpu02>`
  （内置 Shell 应用，hterm + WebSocket）。两个前提：
  1. `roles/ood-wrapper` 写
     `/etc/ood/config/apps/shell/env`：
     `OOD_SSHHOST_ALLOWLIST=master:gpu01:gpu02`（由 inventory 组
     `ood-portal` + `slurm-node` 推导）；
  2. 站点配置 `slurm_allow_ssh_user: ["new"]`
     （`config/group_vars/slurm-cluster.yml`）把 `new` 放入计算节点的
     `/etc/localusers`（及 `/etc/slurm/localusers.backup`），使
     `pam_slurm_adopt` 在无作业时放行 SSH。
- **Jupyter**：使用 OSC 上游 `jupyter` 应用（启用后替代本仓库
  `apps/jupyter`）。"Connect to Jupyter" 链接经
  `/rnode/<节点>/<端口>/<jupyter_api>` 反代（配置
  `/etc/httpd/conf.d/ood-node-proxy.conf`）。上游 `view.html.erb` 向
  `/node/.../login` POST（无认证 Jupyter 下 404），故 `roles/ood-wrapper`
  每次运行都安装修正后的 view——OSC 角色每次都会重新 clone 该应用，clone
  与本仓库补丁冲突而进入 rescue，master 的 `rescued=1` 属预期。
- **商业软件注意**：本地应用与 OSC 商业应用（ANSYS / MATLAB / COMSOL /
  CST / FEKO / Abaqus / Schrödinger 等）要求对应软件**已安装在计算节点**
  （在 PATH 或作为 environment module）；DeepOps 不安装授权软件。
  应用会出现在菜单中，但软件就位前作业会启动失败（各应用 README 有
  具体前置条件）。
- 作业去向：提交后 `squeue` 可见作业被调度到 `gpu01`/`gpu02`
  （如 `-p batch --gpus-per-node N --time HH:MM:SS`，`AllocTRES` 含
  `gres/gpu=N`）；会话目录在
  `/home/new/ondemand/data/sys/dashboard/batch_connect/<app>/output/<uuid>/`
  （`connection.yml` 与 `output.log`）。

### 9.1 本地应用的通用表单字段

6 个本地应用在标准作业分配字段（**Nodes** / **Cores per node** / **GPUs** /
**Max run time**，映射到 `sbatch -N` / `--ntasks-per-node` / `--gpus-per-node` /
`--time`，详见各 `apps/<name>/README.md`）之外，共享一组 CHPC 风格的字段：

| 字段 | 效果 |
|------|------|
| Memory per node (GB) | `0` = 集群默认；否则 `sbatch --mem <N>G` |
| Node list | `sbatch -w` 限制节点（如 `gpu01`） |
| Environment module | 启动前加载模块（如 `ansysedt/2025R1`）；CHPC `auto_modules_*` 的可移植形式 |
| Additional environment | 任意 shell 行（exports / module load / 工具开关） |

5 个 VNC 应用还暂存 XFCE 桌面配置（`template/config/xfce4/...`：面板、
终端、菜单）。OOD vnc 模板以 `-noxstartup` 启动 Xvnc，由脚本负责拉起会话：
`dbus-launch` + 后台 `xfwm4` / `xfce4-panel` / `xfsettingsd`——CHPC 子壳
脚本的两个坑（`xfwm4` 前台阻塞后续组件、无 D-Bus 会话总线时面板/设置
退出）均已规避，并在 `gpu01` 上做过真实 VNC 会话验证。

### 9.2 部署与校验

```bash
# 注意:该 playbook 有两个 play(门户主机 + 计算节点运行时)。
# 必须同时限定两个组;只写 -l ood-portal 会静默跳过节点侧 play,
# 节点上的 VNC/Jupyter 运行时 / nvidia-persistenced 修复将不会生效。
ansible-playbook -l ood-portal,slurm-node playbooks/ood-portal.yml
python3 scripts/validation/validate_ood.py --json   # 在 master 上（建议 root）
```

期望 `"ok": true`、`"login_ok": true`，23 个应用全部在位（可用
`--expected-apps=ansysedt,ansysfluent,lumerical,alphafold,cst_studio,feko,...`
显式枚举；已验证 `apps_found: 23`、`apps_missing: []`）。Jupyter 完整链路
（提交 302 → 作业 RUNNING + GPU 已分配 → `/rnode` 代理返回
`<title>JupyterLab`）与 Shell 网页终端（WebSocket → 三台主机均拿到
bash 提示符）已验证通过。分步操作与失败分支见
[`skills/deploy-ood-portal/`](skills/deploy-ood-portal/SKILL.md)，问题与修复
逐条记录见 [CHANGELOG.md](CHANGELOG.md)。

### 9.3 关键文件

| 路径 | 说明 |
|------|------|
| `playbooks/ood-portal.yml` | 门户部署入口（应用目录、`/rnode` 代理、节点防火墙、节点运行时） |
| `roles/ood-wrapper/` | OOD 包装角色：应用安装、Jupyter Connect 链接修正、Shell 白名单、Desktop 应用修补、PUN 预置/重启 |
| `apps/{ansysedt,ansysfluent,lumerical,alphafold,cst_studio,feko}/` | 6 个本地 Batch Connect 应用（表单、提交模板、会话脚本、XFCE 配置、图标、README） |
| `config.example/group_vars/ood-portal.yml` | 站点配置模板（品牌、`deepops` 集群、应用目录、用户） |
| `config/group_vars/slurm-cluster.yml` | `slurm_allow_ssh_user`（Shell 网页终端的节点侧 SSH 白名单） |
| `scripts/validation/validate_ood.py` | 门户部署后校验器 |
| `skills/deploy-ood-portal/SKILL.md` | 分步部署技能与失败分支 |
