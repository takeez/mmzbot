#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 MMZBOT 部署到目标机器，并重启她。

═══ 三种目标（`--target`，或者 local-config.json 的 `deploy.target`）═══

    --target local    就在本机：把仓库里的代码复制到数据目录 → 重启。
                      云端、废旧主机、Windows 都用这一条（不需要 SSH）。
    --target ssh      远程 Linux：host / port / user / key / 目录全部可配。
                      有 paramiko 就用它；没有就退回系统自带的 ssh / sftp（一个都不用装）。
    --target termux   手机 proot：保留原来的行为（上传 → 容器里校验 → 换入 → 重启），
                      但**路径全部可配**（默认：容器里 `/root/mmzbot`，
                      Termux 侧 `$HOME/<rootfs>/root/mmzbot`）。

⛔ **不写死任何平台路径 / 端口 / 重启方式**：所有东西从 `local-config.json` 的
   `deploy` 一节、环境变量、命令行参数来，优先级 **命令行 > 环境变量 > 配置文件 > 默认**。

═══ 它保证的几件事（都是踩过坑才写下来的）═══

· **先暂存、再校验、最后换入**：校验没过就一个字节都不碰正在跑的那份。
· ⛔ **不推状态 / 密钥文件**（`NEVER` 名单）：memory.json、reminders.json、users.json、
  settings.json、local-config.json、plan-*、bot.log、llm-key.txt…… 推上去就是覆盖用户数据。
· ⛔ **不拿仓库里的 personality.md 覆盖线上那份**：目标目录里已经有就跳过，
  **没有**才推一份初版（用户是在机器上直接改人设的）。
· `--dry` 只打印要做的事，**一个文件都不写、一次网络都不连**。
· `--help` 只打印帮助，**绝不触发部署**（以前踩过：`--help` 把东西推上去了）。
· 缺依赖（比如没装 paramiko、也没有系统 ssh）时给**一句人话**，不是 traceback。

═══ 用法 ═══

    python deploy.py --target local --dry             # 只看要做啥
    python deploy.py --target local                   # 本机部署 + 重启
    python deploy.py --target ssh --host 1.2.3.4 --ssh-user mmz --dir /home/mmz/mmzbot
    python deploy.py --target ssh --dry               # 配置全从 local-config.json 读
    python deploy.py --target termux --dry
    python deploy.py --selfcheck                      # 离线验部署规则（不联网、不碰盘）

`local-config.json` 里的样子（所有键都可省，省了就按下面的默认值）：

    {
      "dataDir": "/home/mmz/mmzbot",           ← 数据目录（local 目标默认往这儿部署）
      "port": 17383,
      "deploy": {
        "target": "ssh",
        "restart": "systemd",                  ← auto / systemd / task / script / termux / manual / none
        "service": "mmzbot",                   ← systemd 单元名 / Windows 任务名
        "ssh": {"host": "1.2.3.4", "port": 22, "user": "mmz", "key": "~/.ssh/id_ed25519",
                "dir": "/home/mmz/mmzbot", "python": "python3"},
        "termux": {"rootfs": "bookworm-arm64", "dir": "/root/mmzbot",
                   "runinc": "runinc.sh", "startScript": "fg-bot-v2-start.sh"}
      }
    }

环境变量（方便 CI / agent）：`MMZBOT_DEPLOY_TARGET`、`MMZBOT_SSH_HOST`、
`MMZBOT_SSH_PORT`、`MMZBOT_SSH_USER`、`MMZBOT_SSH_KEY`、`MMZBOT_DEPLOY_DIR`、
`MMZBOT_PORT`、`MMZBOT_SERVICE`、`MMZBOT_PYTHON`。
"""

import argparse
import io
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


# ── 清单：推什么 / 绝不推什么 ────────────────────────────────────────

# 「代码」= 要重启才生效的那部分
#
# ⚠️ 仓库自带的扩展包（`capabilities/<包名>/`：SKILL.md + tool.py）
#    也算代码 —— 不推的话手机上那个 `capabilities/` 是空的，`pack-manager` 直接消失。
#    `examples/packages/`（示例包的源码 + 安装包 zip）也一起推：README / 文档里
#    `--install-capability examples/packages/pc-status-1.0.0.zip` 那条命令要在手机上能用。
#    ⚠️ 用户在手机上**装的**包也在同一个目录（代码目录 = 数据目录时会混在一起）：
#       这里只**覆盖清单里那些文件**，不删目标上多出来的目录，所以装的包不会被清掉；
#       装成 `<名字>.bak-*` 的备份目录在 `_collect` 里跳过（不算代码）。
CODE_FILES = ["phone-bot-v2.py"]
CODE_DIRS = {"fgbot": ".py",
             "capabilities": (".md", ".py"),
             "examples": (".md", ".py", ".zip"),
             # ⚠ `tools/` 也要推——用户装完要跑 `tools/fetch_model.py`放模型；
             #   而且 -—selftest 验证示例包时会 import 它里面那个生成脚本。
             "tools": ".py"}

# 「启动辅助文件」：四套启动方式用到的脚本 / 单元模板。它们不是状态，可以覆盖。
#   ⚠️ 手机上真正被调用的那份在 Termux 侧（`$HOME/fg-bot-v2-start.sh`），
#      TermuxTarget 会在预检时单独补一份到 `$HOME`（见 `_ensure_launch_files`）。
LAUNCH_FILES = ["mmzbot.ps1", "fg-bot-v2-start.sh", "mmzbot-watchdog.sh", "run.sh",
                "runinc.sh", "requirements.txt",
                "mmzbot.service"]

# ⚠ 目录整理后，这几份脚本放进了 `scripts/<平台>/`。
#   部署到远程时**仍然按原来那个平铺名字**落地（$HOME/fg-bot-v2-start.sh 这类路径不变），
#   所以这里是"源路径 → 目标名字"的映射；upload() 会据此把子目录展平。
LAUNCH_SRC = {
    "mmzbot.ps1": "scripts/windows/mmzbot.ps1",
    "fg-bot-v2-start.sh": "scripts/termux/fg-bot-v2-start.sh",
    "mmzbot-watchdog.sh": "scripts/termux/mmzbot-watchdog.sh",
    "runinc.sh": "scripts/termux/runinc.sh",
    "run.sh": "scripts/linux/run.sh",
    "mmzbot.service": "scripts/linux/mmzbot.service",
}
LAUNCH_FLAT = {v: k for k, v in LAUNCH_SRC.items()}

# ⚠️ personality.md 是**用户手改的人设**，只在目标目录里**没有**的时候才推初版
#    （见各 Target 的 `swap()`）。config.json 是部署事实（出厂模板），照推。
CONTENT_FILES = ["config.json", "personality.md"]
CONTENT_DIRS = {}

FILES = ["phone-bot-v2.py", "config.json", "personality.md"] + LAUNCH_FILES
DIRS = {"fgbot": ".py", "capabilities": (".md", ".py"),
        "examples": (".md", ".py", ".zip"), "tools": ".py"}

# 绝不推的（**状态 / 密钥**：推上去会覆盖用户机器上的数据）
#
#   ⚠️ 自检（phone-bot-v2.py）会**直接读这段源码**核对几个名字，加新状态文件时
#      记得同步进这里；`NEVER_PREFIXES` 管"名字里带变量"的那些。
NEVER = {"bot.log",
         "pc-address.txt",
         "llm-key.txt",
         "llm-apis.txt",
         "search-key.txt",
         "restart.txt",
         "control.txt",
         "memory.json",
         "names.json",
         "vectors.json",
         "reminders.json",
         "status-cache.json",
         "runtime.json",
         "settings.json",
         "users.json",
         "local-config.json",
         "groups.json",
         "seen-groups.json",
         "group-names.json",
         "requests.json",
         # 扩展包的停用名单：用户在这台机器上停用了谁，绝不能被 deploy 抹掉
         "capabilities-state.json",
         # 部署自己的东西（备份 / 暂存）也绝不推
         "deploy.json",
         ".env",
         }
# 名字里带变量的状态：`plan-<会话>.json`、`memory-backup-<时间>.json`
NEVER_PREFIXES = ("plan-", "memory-backup-", ".tmp-", ".mmzbot-")

# 扩展名层面的硬拦：密钥 / 证书 / 日志 / 备份 / 字节码
NEVER_EXT = (".log", ".pyc", ".pem", ".key", ".p12", ".bak", ".swp", ".tmp")


def _is_never(name):
    n = os.path.basename(name)
    if n in NEVER:
        return True
    if any(n.startswith(p) for p in NEVER_PREFIXES):
        return True
    low = n.lower()
    if low.endswith(NEVER_EXT):
        return True
    # 轮转出来的日志（`bot.log.1`）也算日志
    return ".log." in low


def dest_rel(rel):
    """源目录里的相对路径 → 目标上的相对路径。

    ⚠ 2026-11-02：启动脚本从根目录搬进了 `scripts/<平台>/`，
    但远程那边就认平铺名字（$HOME/fg-bot-v2-start.sh 这类），所以落地时展平。
    """
    return LAUNCH_FLAT.get(rel, rel)


def _collect(files, dirs):
    """要推的文件清单（相对路径，`/` 分隔，已排掉 NEVER）。"""
    out = []
    for f in files:
        src = LAUNCH_SRC.get(f, f)
        if os.path.isfile(os.path.join(HERE, src)) and not _is_never(src):
            out.append(src)
    for d, ext in dirs.items():
        exts = (ext,) if isinstance(ext, str) else tuple(ext)
        base = os.path.join(HERE, d)
        if not os.path.isdir(base):
            continue
        for root, subdirs, names in os.walk(base):
            # 备份目录（`<包名>.bak-<时间>`）/ 字节码不进清单
            subdirs[:] = [x for x in subdirs if x != "__pycache__" and ".bak-" not in x]
            for n in sorted(names):
                if n.startswith(".") or not n.endswith(exts):
                    continue
                rel = os.path.relpath(os.path.join(root, n), HERE).replace(os.sep, "/")
                if _is_never(rel) or ".bak-" in rel:
                    continue
                out.append(rel)
    return sorted(set(out))


def collect_code():
    return _collect(CODE_FILES, CODE_DIRS)


def collect_content():
    return _collect(CONTENT_FILES, CONTENT_DIRS)


def collect_all():
    return _collect(FILES, DIRS)


def want_personality(remote_has):
    """人设文件推不推：**目标上已经有就不推**（别覆盖用户手改的那份）。

    纯函数（自检直接用）：`remote_has=True` → 不推；`False` → 推初版。
    """
    return not remote_has


# ── 小工具 ─────────────────────────────────────────────────────────

class DeployError(Exception):
    """部署能预期到的错误：带一句人话，不打印 traceback。"""

    def __init__(self, msg, hint=""):
        Exception.__init__(self, msg)
        self.msg = msg
        self.hint = hint


def say(msg=""):
    print(msg)


def step(n, msg):
    print()
    print("%s. %s" % (n, msg))


def warn(msg):
    print("  ⚠️ %s" % msg)


def die(msg, hint=""):
    print()
    print("✗ %s" % msg)
    if hint:
        print("  %s" % hint)
    sys.exit(1)


def _abspath(p):
    return os.path.abspath(os.path.expanduser(str(p)))


def _same_dir(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except Exception:
        return False


def _stamp():
    """备份目录名（也当时间戳用）。走本地时间即可 —— 这是给**人**看的。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _fmt_size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1024.0 / 1024.0)


# ── 配置：命令行 > 环境变量 > local-config.json > 默认 ──────────────

def load_local_cfg():
    """读本机那份 `local-config.json`（数据目录优先，其次仓库里那份）。"""
    cands = []
    try:
        from fgbot import base as _base
        cands.append(_base.LOCAL_CFG_PATH)
        cands.append(os.path.join(HERE, "local-config.json"))
    except Exception:
        cands.append(os.path.join(HERE, "local-config.json"))
    for p in cands:
        try:
            with open(p, encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                return obj, p
        except Exception:
            continue
    return {}, ""


def default_data_dir():
    """本机数据目录的默认值（和运行期**同一套**规则：`fgbot/base.py`）。"""
    try:
        from fgbot import base as _base
        return _base.DATA_DIR
    except Exception:
        home = os.path.expanduser("~")
        if os.name == "nt":
            return os.path.join(os.environ.get("LOCALAPPDATA") or
                                os.path.join(home, "AppData", "Local"), "MMZBOT")
        return os.path.join(home, "mmzbot")


def project_port():
    """配置里的端口（`port`）——**只读**，不联网。"""
    for p in (os.path.join(HERE, "config.json"),):
        try:
            with open(p, encoding="utf-8") as f:
                obj = json.load(f)
            v = obj.get("port")
            if v:
                return int(v)
        except Exception:
            pass
    return 17383


def _env(name, default=""):
    return os.environ.get(name) or default


def build_options(args):
    """把命令行 / 环境变量 / 配置文件合成一份 `opts`。返回 dict（不碰盘、不联网）。"""
    cfg, cfg_path = load_local_cfg()
    dep = cfg.get("deploy") or {}
    if not isinstance(dep, dict):
        dep = {}
    ssh_cfg = dep.get("ssh") or {}
    tx_cfg = dep.get("termux") or {}
    local_cfg = dep.get("local") or {}

    def pick(cli, envname, cfgval, default):
        if cli not in (None, ""):
            return cli
        e = _env(envname)
        if e:
            return e
        if cfgval not in (None, ""):
            return cfgval
        return default

    target = pick(args.target, "MMZBOT_DEPLOY_TARGET", dep.get("target"), "")
    opts = {
        "target": (target or "").strip().lower(),
        "dry": bool(args.dry),
        "no_restart": bool(args.no_restart),
        "code_only": bool(args.code_only),
        "content_only": bool(args.content_only),
        "restart": pick(args.restart, "MMZBOT_DEPLOY_RESTART", dep.get("restart"), "auto"),
        "service": pick(args.service, "MMZBOT_SERVICE", dep.get("service"), "mmzbot"),
        # ⚠️ 本机的解释器默认用**跑着 deploy.py 的这个**（Windows 上叫 python、
        #    Linux 上叫 python3，别互相假设）。远程那边仍然默认 python3。
        "python": pick(args.python, "MMZBOT_PYTHON", dep.get("python"), sys.executable),
        "port": int(pick(args.port, "MMZBOT_PORT", dep.get("port"), project_port())),
        "keep_backups": int(pick(None, "", dep.get("keepBackups"), 5)),
        "backup": bool(dep.get("backup", True)),
        "restart_cmd": str(dep.get("restartCmd") or "").strip(),
        "cfg_path": cfg_path,
        "local_dir": _abspath(pick(args.dir, "MMZBOT_DEPLOY_DIR", local_cfg.get("dir"),
                                   cfg.get("dataDir") or default_data_dir())),
        "ssh": {
            "host": str(pick(getattr(args, "host", None), "MMZBOT_SSH_HOST",
                             ssh_cfg.get("host"), "")).strip(),
            "port": int(pick(getattr(args, "ssh_port", None), "MMZBOT_SSH_PORT",
                             ssh_cfg.get("port"), 22)),
            "user": str(pick(getattr(args, "ssh_user", None), "MMZBOT_SSH_USER",
                             ssh_cfg.get("user"), "")).strip(),
            "key": str(pick(getattr(args, "ssh_key", None), "MMZBOT_SSH_KEY",
                            ssh_cfg.get("key"), "")).strip(),
            "dir": str(pick(args.dir, "MMZBOT_DEPLOY_DIR", ssh_cfg.get("dir"),
                            "~/mmzbot")).strip() or "~/mmzbot",
            "python": str(pick(args.python, "MMZBOT_PYTHON", ssh_cfg.get("python"),
                               "python3")).strip() or "python3",        },
        "termux": {
            "host": str(pick(getattr(args, "host", None), "MMZBOT_SSH_HOST",
                             tx_cfg.get("host") or ssh_cfg.get("host"), "")).strip(),
            "port": int(pick(getattr(args, "ssh_port", None), "MMZBOT_SSH_PORT",
                             tx_cfg.get("port") or ssh_cfg.get("port"), 22)),
            "user": str(pick(getattr(args, "ssh_user", None), "MMZBOT_SSH_USER",
                             tx_cfg.get("user") or ssh_cfg.get("user"), "")).strip(),
            "key": str(pick(getattr(args, "ssh_key", None), "MMZBOT_SSH_KEY",
                            tx_cfg.get("key") or ssh_cfg.get("key"), "")).strip(),
            "rootfs": str(pick(getattr(args, "rootfs", None), "MMZBOT_TERMUX_ROOTFS",
                               tx_cfg.get("rootfs"), "")).strip(),
            "dir": str(pick(args.dir, "MMZBOT_DEPLOY_DIR", tx_cfg.get("dir"),
                            "/root/mmzbot")).strip() or "/root/mmzbot",
            "hostDir": str(pick(getattr(args, "host_dir", None), "MMZBOT_TERMUX_HOST_DIR",
                                tx_cfg.get("hostDir"), "")).strip(),
            "runinc": str(tx_cfg.get("runinc") or "runinc.sh").strip(),
            "startScript": str(tx_cfg.get("startScript") or "fg-bot-v2-start.sh").strip(),
            "killPattern": str(tx_cfg.get("killPattern") or "phone-bot-v2.py").strip(),
            "python": str(pick(args.python, "MMZBOT_PYTHON", tx_cfg.get("python"),
                               "python3")).strip() or "python3",
            "watchdog": str(tx_cfg.get("watchdog") or "").strip(),
        },
    }
    if opts["code_only"]:
        opts["content_only"] = False
    if opts["content_only"]:
        opts["no_restart"] = True          # 内容文件热重载，不重启
    return opts


# ── 本地命令执行 ────────────────────────────────────────────────────

def run_argv(argv, cwd=None, timeout=300, env=None):
    """跑一条本地命令，返回 `(rc, stdout, stderr)`。**不抛**（除了超时）。

    ⚠️ 输出用**临时文件**接，不用管道：`systemd` / `schtasks` / `mmzbot.ps1` 这类命令
       会再拉起一个长期运行的子进程（她自己）。管道的话那个孙进程会继承写端口，
       我们这边永远等不到 EOF —— `deploy.py` 会挂在那儿不返回（真踩过）。
    """
    fo = fe = None
    try:
        fo = tempfile.TemporaryFile()
        fe = tempfile.TemporaryFile()
        p = subprocess.run(argv, cwd=cwd, timeout=timeout, env=env,
                           stdout=fo, stderr=fe, stdin=subprocess.DEVNULL)
        fo.seek(0)
        fe.seek(0)
        return (p.returncode,
                fo.read().decode("utf-8", "replace"),
                fe.read().decode("utf-8", "replace"))
    except FileNotFoundError:
        return 127, "", "找不到命令：%s" % argv[0]
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时（%ss）：%s" % (timeout, " ".join(argv[:3]))
    finally:
        for f in (fo, fe):
            try:
                f.close()
            except Exception:
                pass


def _python_ok(python):
    rc, out, _ = run_argv([python, "-c", "import sys;print(sys.version.split()[0])"], timeout=30)
    return (rc == 0, out.strip())


# ── SSH：paramiko 优先，没有就用系统 ssh ────────────────────────────

class SSH:
    """一条 SSH 连接。`mode` = `paramiko` 或 `ssh`（系统命令）。

    ⚠️ 两条路都只用**标准的客户端认证**（key / ssh-agent），不自己存密码。
    """

    def __init__(self, host, port=22, user="", key="", timeout=15):
        if not host:
            raise DeployError("没配 SSH 主机（`deploy.ssh.host` / --host）",
                              "例：python deploy.py --target ssh --host 1.2.3.4 --ssh-user mmz")
        self.host = host
        self.port = int(port or 22)
        self.user = user
        self.key = os.path.expanduser(key) if key else ""
        self.timeout = timeout
        self._cli = None
        self._sftp = None
        self.mode = ""
        self._connect()

    # — 连接 —
    def _connect(self):
        try:
            import paramiko                                    # noqa: F401
        except Exception:
            paramiko = None
        if paramiko is not None:
            try:
                c = paramiko.SSHClient()
                # ⚠️ 第一次连一台新机器要记它的指纹（TOFU）。想严格校验就自己维护
                #    known_hosts —— 这里不静默忽略，连上会打一行提示。
                try:
                    c.load_system_host_keys()
                except Exception:
                    pass
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                kwargs = {"hostname": self.host, "port": self.port,
                          "username": self.user or None, "timeout": self.timeout,
                          "allow_agent": True, "look_for_keys": True}
                if self.key:
                    kwargs["key_filename"] = self.key
                c.connect(**kwargs)
                self._cli = c
                self.mode = "paramiko"
                return
            except Exception as e:
                raise DeployError("SSH 连不上 %s:%s（%s）" % (self.host, self.port,
                                                             str(e)[:160]),
                                  "先手动试：ssh -p %s %s%s"
                                  % (self.port, (self.user + "@") if self.user else "", self.host))
        if not shutil.which("ssh"):
            raise DeployError(
                "既没有 paramiko，也没有系统 ssh —— 没法走远程部署",
                "装一个就行：`pip install paramiko`（可选依赖），"
                "或者装系统的 OpenSSH 客户端（Windows：设置 → 可选功能 → OpenSSH 客户端）")
        self.mode = "ssh"

    # — 执行 —
    def run(self, cmd, timeout=300):
        if self._cli is not None:
            try:
                stdin, stdout, stderr = self._cli.exec_command(cmd, timeout=timeout)
                out = stdout.read().decode("utf-8", "replace")
                err = stderr.read().decode("utf-8", "replace")
                rc = stdout.channel.recv_exit_status()
                return rc, out, err
            except Exception as e:
                raise DeployError("远程命令执行失败：%s" % str(e)[:160], "命令：%s" % cmd[:200])
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=%d" % self.timeout, "-p", str(self.port)]
        if self.key:
            argv += ["-i", self.key]
        argv += [("%s@%s" % (self.user, self.host)) if self.user else self.host, cmd]
        try:
            p = subprocess.run(argv, timeout=timeout + 20, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise DeployError("找不到系统 ssh 命令", "装 OpenSSH 客户端，或者 `pip install paramiko`")
        except subprocess.TimeoutExpired:
            return 124, "", "SSH 命令超时"
        if p.returncode == 255:
            # ssh 自己失败（连不上 / 认证不过）用的是 255；别把它说成"远程命令失败"
            err = p.stderr.decode("utf-8", "replace").strip()[:200]
            raise DeployError("SSH 连不上 %s:%s（%s）" % (self.host, self.port,
                                                          err or "退出码 255"),
                              "先手动试：ssh -p %s %s%s"
                              % (self.port, (self.user + "@") if self.user else "", self.host))
        return (p.returncode, p.stdout.decode("utf-8", "replace"),
                p.stderr.decode("utf-8", "replace"))

    def check(self, cmd, what=""):
        """跑一条命令，非 0 就抛一句人话。"""
        rc, out, err = self.run(cmd)
        if rc != 0:
            raise DeployError("远程命令失败%s：%s" % (("（" + what + "）") if what else "",
                                                      (err or out).strip()[:200]),
                              "命令：%s" % cmd[:200])
        return out

    # — 上传 —
    def upload(self, files, src_root, dest_dir):
        """把 `files`（相对 `src_root`）传到远程 `dest_dir`，保留子目录结构。"""
        if self._cli is not None:
            if self._sftp is None:
                self._sftp = self._cli.open_sftp()
            self.check("mkdir -p %s" % shlex.quote(dest_dir), "建暂存目录")
            for rel in files:
                remote = dest_dir.rstrip("/") + "/" + LAUNCH_FLAT.get(rel, rel)
                parent = os.path.dirname(remote)
                if parent:
                    self.check("mkdir -p %s" % shlex.quote(parent), "建子目录")
                self._sftp.put(os.path.join(src_root, rel), remote)
            return
        # 系统 ssh：本地打一个 tar 从 stdin 灌进去（不依赖远程有 scp）
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for rel in files:
                tf.add(os.path.join(src_root, rel), arcname=dest_rel(rel))
        data = buf.getvalue()
        cmd = "mkdir -p %s && tar -xf - -C %s" % (shlex.quote(dest_dir),
                                                  shlex.quote(dest_dir))
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=%d" % self.timeout, "-p", str(self.port)]
        if self.key:
            argv += ["-i", self.key]
        argv += [("%s@%s" % (self.user, self.host)) if self.user else self.host, cmd]
        p = subprocess.run(argv, input=data, timeout=300,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise DeployError("上传失败：%s" % p.stderr.decode("utf-8", "replace").strip()[:200],
                              "检查目标目录权限：%s" % dest_dir)

    def close(self):
        try:
            if self._sftp is not None:
                self._sftp.close()
        except Exception:
            pass
        try:
            if self._cli is not None:
                self._cli.close()
        except Exception:
            pass


# ── 目标：local ─────────────────────────────────────────────────────

class LocalTarget:
    """就在本机：文件复制 + 本地进程管理。**不经过 shell**（Windows 上 shell 语法不一样）。"""

    kind = "local"

    def __init__(self, opts):
        self.opts = opts
        self.dir = opts["local_dir"]
        self.python = opts["python"]
        self.port = opts["port"]

    def describe(self):
        return "本机 %s（python: %s）" % (self.dir, self.python)

    # — 只读检查 —
    def preflight(self):
        ok, ver = _python_ok(self.python)
        if not ok:
            raise DeployError("找不到 Python（试的是 %r）" % self.python,
                              "装 Python 3.11+，或者用 --python 指定解释器路径")
        if os.path.isdir(self.dir):
            if not os.access(self.dir, os.W_OK):
                raise DeployError("目标目录写不进去：%s" % self.dir,
                                  "换一个目录（--dir），或者把权限改对")
        else:
            parent = os.path.dirname(self.dir) or "."
            if not os.path.isdir(parent):
                try:
                    os.makedirs(parent, exist_ok=True)
                except Exception as e:
                    raise DeployError("建不了目标目录的上级：%s（%r）" % (parent, e),
                                      "换一个已存在的目录（--dir）")
            if not os.access(parent, os.W_OK):
                raise DeployError("上级目录写不进去：%s" % parent,
                                  "换一个目录（--dir），或者把权限改对")
        return "Python %s 可用" % (ver or "?")

    def exists(self, rel):
        return os.path.exists(os.path.join(self.dir, rel))

    def in_place(self):
        return _same_dir(HERE, self.dir)

    # — 暂存 / 校验 / 换入 —
    def stage(self, files):
        """把要推的文件复制到一个临时目录里先验证（**不碰目标目录**）。"""
        self.files = files
        if self.in_place():
            return HERE
        stage = tempfile.mkdtemp(prefix=".mmzbot-stage-")
        for rel in files:
            dst = os.path.join(stage, dest_rel(rel))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(HERE, rel), dst)
        return stage

    def validate(self, stage):
        py = [rel for rel in self.files if rel.endswith(".py")]
        if py:
            rc, out, err = run_argv([self.python, "-m", "py_compile"] +
                                    [os.path.join(stage, rel) for rel in py])
            if rc != 0:
                raise DeployError("语法检查没过：\n%s" % (err or out).strip()[:600],
                                  "本地先跑 python phone-bot-v2.py --selftest 看是哪里的问题")
        if any(rel == "phone-bot-v2.py" for rel in py):
            say("    跑一遍 --selftest（离线，不写状态）...")
            # ⚠️ 显式把数据目录指到**暂存目录**：部署的人可能带着 MMZBOT_DATA=/线上目录
            #    在跑，自检会读到线上配置，断言（端口 / 群 / 她自己）就全乱了。
            env = dict(os.environ)
            env["MMZBOT_DATA"] = stage
            env["PYTHONIOENCODING"] = "utf-8"
            rc, out, err = run_argv([self.python, "phone-bot-v2.py", "--selftest"],
                                    cwd=stage, timeout=300, env=env)
            if rc != 0:
                tail = "\n".join((out or err).strip().splitlines()[-12:])
                raise DeployError("自检没过（退出码 %s）—— 目标目录一个字节都没动" % rc,
                                  "本地先跑 python phone-bot-v2.py --selftest\n" + tail)
            say("    自检通过")

    def backup(self):
        if not os.path.isdir(self.dir):
            return ""
        bakdir = os.path.join(os.path.dirname(self.dir) or ".", ".%s.bak"
                              % os.path.basename(self.dir.rstrip(os.sep)))
        os.makedirs(bakdir, exist_ok=True)
        name = _stamp()
        path = os.path.join(bakdir, name)
        try:
            os.makedirs(path, exist_ok=True)
            for item in ("phone-bot-v2.py", "fgbot", "config.json", "personality.md"):
                src = os.path.join(self.dir, item)
                if not os.path.exists(src):
                    continue
                dst = os.path.join(path, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                else:
                    shutil.copy2(src, dst)
        except Exception as e:
            warn("备份没做成（不影响部署）：%r" % (e,))
            return ""
        self.prune_backups(bakdir)
        return path

    def prune_backups(self, bakdir):
        try:
            names = [n for n in os.listdir(bakdir) if BAK_NAME_RE.match(n)]
        except Exception:
            return
        kept, drop, _others = keep_recent_backups(names, self.opts["keep_backups"])
        for n in drop:
            shutil.rmtree(os.path.join(bakdir, n), ignore_errors=True)

    def swap(self, stage, files):
        """把暂存的东西逐个换入目标目录（同目录临时名 + rename，写一半不会坏）。"""
        if self.in_place():
            say("    源和目标是同一个目录 —— 就地部署，不用复制")
            return
        os.makedirs(self.dir, exist_ok=True)
        for rel in files:
            if rel == "personality.md" and self.exists("personality.md"):
                say("    跳过 personality.md（目标已有，不覆盖用户改的那份）")
                continue
            src = os.path.join(stage, dest_rel(rel))
            dst = os.path.join(self.dir, dest_rel(rel))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".tmp-%d" % os.getpid()
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
        for d in (os.path.join(self.dir, "__pycache__"),
                  os.path.join(self.dir, "fgbot", "__pycache__")):
            shutil.rmtree(d, ignore_errors=True)

    def cleanup(self, stage):
        if not self.in_place() and stage and os.path.isdir(stage):
            shutil.rmtree(stage, ignore_errors=True)

    # — 重启 / 验证 —
    def detect_restart(self):
        if os.name == "nt":
            rc, out, _ = run_argv(["schtasks", "/Query", "/TN", self.opts["service"]], timeout=30)
            return "task" if rc == 0 else "manual"
        rc, out, _ = run_argv(["systemctl", "cat", self.opts["service"]], timeout=20)
        return "systemd" if rc == 0 else "manual"

    def restart(self, method):
        if method == "auto":
            method = self.detect_restart()
        if self.opts["restart_cmd"]:
            return self._restart_cmd()
        if method in ("none", "manual"):
            return self._manual(method)
        if method == "systemd":
            rc, out, err = run_argv(["systemctl", "restart", self.opts["service"]])
            if rc != 0:
                raise DeployError("systemd 重启失败：%s" % (err or out).strip()[:200],
                                  "是不是要 sudo？把 `deploy.restartCmd` 配成 "
                                  "`sudo systemctl restart %s`" % self.opts["service"])
            return "systemd 已重启 %s" % self.opts["service"]
        if method == "task":
            rc, out, err = run_argv(["schtasks", "/Run", "/TN", self.opts["service"]])
            if rc != 0:
                raise DeployError("任务计划启动失败：%s" % (err or out).strip()[:200],
                                  "先注册任务：见 README「Windows」那一节")
            return "任务计划已触发 %s" % self.opts["service"]
        if method == "script":
            script = self.start_script()
            if not script or not os.path.isfile(script):
                raise DeployError("找不到启动脚本（试的是 %r）" % script,
                                  "用 `deploy.termux.startScript` / --dir 指定，"
                                  "或者先把 mmzbot.ps1 / fg-bot-v2-start.sh 放到机器上")
            argv = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
                    if script.lower().endswith(".ps1") else ["bash", script])
            rc, out, err = run_argv(argv, timeout=60)
            if rc != 0:
                raise DeployError("启动脚本退出码 %s：%s" % (rc, (err or out).strip()[:200]))
            return "已执行启动脚本 %s" % script
        if method == "termux":
            raise DeployError("termux 这种重启方式只对 --target termux 有意义",
                              "本机请用 --restart systemd / task / script")
        raise DeployError("不认识的重启方式：%r" % method,
                          "可选：auto / systemd / task / script / termux / manual / none")

    def start_script(self):
        for name in ("mmzbot.ps1", "mmzbot.sh", "fg-bot-v2-start.sh"):
            p = os.path.join(self.dir, name)
            if os.path.isfile(p):
                return p
        return ""

    def _restart_cmd(self):
        say("    跑配置里的 restartCmd：%s" % self.opts["restart_cmd"])
        rc, out, err = run_argv([self.opts["restart_cmd"]], timeout=120)
        if rc != 0:
            raise DeployError("restartCmd 失败：%s" % (err or out).strip()[:200])
        return "restartCmd 成功"

    def _manual(self, method):
        if method == "none":
            return "按 --no-restart 没重启"
        say("    没配自动重启（--restart manual）。手动启动：")
        if os.name == "nt":
            say("      powershell -ExecutionPolicy Bypass -File \"%s\\mmzbot.ps1\""
                % self.dir)
        else:
            say("      cd %s && %s phone-bot-v2.py" % (self.dir, self.python))
        return "需要手动重启"

    def port_open(self):
        try:
            s = socket.create_connection(("127.0.0.1", int(self.port)), timeout=2)
            s.close()
            return True
        except Exception:
            return False

    def tail_log(self, n=8):
        p = os.path.join(self.dir, "bot.log")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.read().strip().splitlines()
            return lines[-n:]
        except Exception:
            return []


# ── 目标：ssh（远程 Linux）──────────────────────────────────────────

class RemoteTarget:
    """远程 Linux（`--target ssh`）：上传 → 远程校验 → 备份 → 换入 → 重启。"""

    kind = "ssh"
    wrapper = ""            # termux 用 runinc.sh 包一层

    def __init__(self, opts):
        self.opts = opts
        self.ssh = None
        self.dir = ""
        self.port = opts["port"]
        self.python = opts["python"]
        self.files = []

    def describe(self):
        return "SSH %s@%s:%s → %s" % (self.opts["ssh"]["user"] or "(当前用户)",
                                     self.opts["ssh"]["host"],
                                     self.opts["ssh"]["port"],
                                     self.opts["ssh"]["dir"])

    # — 连接 / 解析绝对路径 —
    def preflight(self):
        s = self.opts["ssh"]
        self.ssh = SSH(s["host"], s["port"], s["user"], s["key"])
        self.dir = self._resolve_dir(s["dir"])
        rc, out, err = self.ssh.run("%s -c 'import sys;print(sys.version.split()[0])'"
                                    % shlex.quote(self.python))
        if rc != 0:
            raise DeployError("远程找不到 Python（%s）" % self.python,
                              "在那边装 Python 3.11+，或者用 deploy.ssh.python 指个绝对路径")
        self.check_writable()
        return "Python %s 可用" % out.strip()

    def _resolve_dir(self, raw):
        """把 `~/mmzbot` 这类路径在**远程**展开成绝对路径。"""
        cmd = ('sh -c %s' % shlex.quote('d=%s; cd "$d" 2>/dev/null || '
                                        'mkdir -p "$d"; cd "$d" && pwd -P' % raw))
        rc, out, err = self.ssh.run(cmd)
        if rc != 0 or not out.strip():
            raise DeployError("远程目录用不了：%s（%s）" % (raw, (err or out).strip()[:160]),
                              "检查 deploy.ssh.dir 或者先手动建好那个目录")
        return out.strip().splitlines()[-1]

    def check_writable(self):
        probe = self.dir.rstrip("/") + "/.mmzbot-write-test"
        rc, out, err = self.ssh.run("touch %s && rm -f %s && echo OK"
                                    % (shlex.quote(probe), shlex.quote(probe)))
        if "OK" not in out:
            raise DeployError("远程目录写不进去：%s" % self.dir,
                              "把 deploy.ssh.dir 换成一个当前用户能写的目录")

    # — 命令（termux 会包一层 runinc）—
    def cmd(self, inner):
        if not self.wrapper:
            return inner
        return "%s %s" % (self.wrapper, shlex.quote(inner))

    def run(self, inner, timeout=300, wrapped=True):
        return self.ssh.run(self.cmd(inner) if wrapped else inner, timeout=timeout)

    def exists(self, rel):
        p = self.dir.rstrip("/") + "/" + rel
        rc, out, _ = self.run("test -e %s && echo YES || echo NO" % shlex.quote(p))
        return "YES" in out

    def stage_path(self):
        parent = os.path.dirname(self.dir)
        return "%s/.mmzbot-stage-%s" % (parent, _stamp())

    def upload(self, files, stage):
        self.files = files
        say("    上传 %d 个文件 → %s" % (len(files), stage))
        self.ssh.upload(files, HERE, stage)

    def validate(self, stage):
        py = [r for r in self.files if r.endswith(".py")]
        if py:
            inner = "cd %s && %s -m py_compile %s" % (
                shlex.quote(stage), shlex.quote(self.python),
                " ".join(shlex.quote(os.path.join(stage, r)) for r in py))
            rc, out, err = self.run(inner)
            if rc != 0:
                raise DeployError("远程语法检查没过：\n%s" % (err or out).strip()[:600])
        if "phone-bot-v2.py" in py:
            say("    跑一遍 --selftest（远程、离线）...")
            inner = "cd %s && MMZBOT_DATA=%s %s phone-bot-v2.py --selftest" % (
                shlex.quote(stage), shlex.quote(stage), shlex.quote(self.python))
            rc, out, err = self.run(inner, timeout=420)
            if rc != 0:
                tail = "\n".join((out or err).strip().splitlines()[-12:])
                raise DeployError("远程自检没过（退出码 %s）—— 目标目录一个字节都没动" % rc,
                                  tail)
            say("    自检通过")

    def backup(self):
        if not self.exists("phone-bot-v2.py"):
            return ""
        bakdir = os.path.dirname(self.dir) + "/." + os.path.basename(self.dir.rstrip("/")) + ".bak"
        name = _stamp()
        target = "%s/%s" % (bakdir, name)
        excludes = ("--exclude=./models --exclude=./__pycache__ --exclude=./fgbot/__pycache__ "
                    "--exclude=./*.log --exclude=./.tmp-* --exclude=./local-config.json")
        inner = ("mkdir -p %s && mkdir -p %s && (cd %s && tar cf - %s .) | (cd %s && tar xf -)"
                 % (shlex.quote(bakdir), shlex.quote(target), shlex.quote(self.dir),
                    excludes, shlex.quote(target)))
        rc, out, err = self.run(inner, timeout=600)
        if rc != 0:
            warn("备份没做成（不影响部署）：%s" % (err or out).strip()[:160])
            return ""
        self.prune_backups(bakdir)
        return target

    def prune_backups(self, bakdir):
        rc, out, _ = self.run("ls -1 %s 2>/dev/null" % shlex.quote(bakdir))
        if rc != 0:
            return
        names = [n.strip() for n in out.splitlines() if n.strip()]
        _kept, drop, _others = keep_recent_backups(names, self.opts["keep_backups"])
        if not drop:
            return
        # 只删名字被正则筛过的（8 位数字-6 位数字），逐个列名，不用通配符
        for n in drop:
            self.run("rm -rf %s" % shlex.quote("%s/%s" % (bakdir, n)), timeout=120)

    def swap(self, stage, files):
        # 先清掉自检在暂存目录里留下的运行时残留（第二道防线：selfcheck 自己也会清）
        junk = " ".join(("bot.log reminders.json memory.json status-cache.json users.json "
                         "local-config.json settings.json groups.json seen-groups.json "
                         "requests.json runtime.json llm-key.txt llm-apis.txt control.txt "
                         "restart.txt search-key.txt").split())
        inner = ("cd %s && rm -rf __pycache__ fgbot/__pycache__ && rm -f %s"
                 % (shlex.quote(stage), junk))
        self.run(inner)
        # personality：目标已经有就不动（用户在机器上改的那份是最终版）。
        # ⚠️ 它刚才一起传进暂存区了（暂存区的自检需要有这份文件）—— 换入前删掉。
        if self.exists("personality.md"):
            say("    跳过 personality.md（目标已有，不覆盖用户改的那份）")
            self.run("rm -f %s" % shlex.quote(stage.rstrip("/") + "/personality.md"))
        inner = "cp -rf %s/. %s/ && rm -rf %s/__pycache__ %s/fgbot/__pycache__" % (
            shlex.quote(stage), shlex.quote(self.dir),
            shlex.quote(self.dir), shlex.quote(self.dir))
        rc, out, err = self.run(inner)
        if rc != 0:
            raise DeployError("换入失败：%s" % (err or out).strip()[:200],
                              "目标目录可能没有写权限，或者磁盘满了")

    def cleanup(self, stage):
        self.run("rm -rf %s" % shlex.quote(stage), timeout=120)

    # — 重启 —
    def restart(self, method):
        if method == "auto":
            method = self.detect_restart()
        if self.opts["restart_cmd"]:
            say("    跑配置里的 restartCmd：%s" % self.opts["restart_cmd"])
            rc, out, err = self.ssh.run(self.opts["restart_cmd"], timeout=180)
            if rc != 0:
                raise DeployError("restartCmd 失败：%s" % (err or out).strip()[:200])
            return "restartCmd 成功"
        if method in ("none", "manual"):
            return self._manual(method)
        if method == "systemd":
            inner = "systemctl restart %s" % shlex.quote(self.opts["service"])
            rc, out, err = self.ssh.run(inner, timeout=120)
            if rc != 0:
                raise DeployError("systemd 重启失败：%s" % (err or out).strip()[:200],
                                  "要不要 sudo？把 `deploy.restartCmd` 配成 "
                                  "`sudo systemctl restart %s`" % self.opts["service"])
            return "systemd 已重启 %s" % self.opts["service"]
        raise DeployError("这个目标不支持重启方式 %r" % method,
                          "远程 Linux 用 systemd / manual；手机用 termux")

    def _manual(self, method):
        if method == "none":
            return "按 --no-restart 没重启"
        say("    没配自动重启（--restart manual）。手动启动：")
        say("      ssh %s 'cd %s && %s phone-bot-v2.py'"
            % (self.opts["ssh"]["host"], self.dir, self.python))
        return "需要手动重启"

    def detect_restart(self):
        rc, out, _ = self.run("command -v systemctl >/dev/null && "
                              "systemctl cat %s >/dev/null 2>&1 && echo YES || echo NO"
                              % shlex.quote(self.opts["service"]))
        return "systemd" if "YES" in out else "manual"

    def port_open(self):
        # 远程用 Python 探端口（远程一定有 python —— 预检已经验过了）；不拼接引号地雷
        inner = ("cd %s && %s -c \"import socket,sys;"
                 "sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',%d))==0 else 1)\""
                 % (shlex.quote(self.dir), shlex.quote(self.python), int(self.port)))
        rc, _out, _err = self.run(inner, timeout=30)
        return rc == 0

    def tail_log(self, n=8):
        rc, out, _ = self.run("tail -n %d %s" % (n, shlex.quote(self.dir + "/bot.log")))
        return [l for l in (out or "").strip().splitlines() if l.strip()][-n:]


# ── 目标：termux（手机 proot）───────────────────────────────────────

class TermuxTarget(RemoteTarget):
    """手机：和 ssh 共用一套上传 / 校验，差异在**路径映射**和**重启方式**。

    映射：容器里 `/root/mmzbot` ↔ Termux 侧 `$HOME/<rootfs>/root/mmzbot`。
    `rootfs` 不给就自己探（`$HOME/*/root` 里第一个存在的），探不到就报人话。
    """

    kind = "termux"

    def describe(self):
        t = self.opts["termux"]
        return "Termux %s@%s → 容器 %s（Termux 侧 %s）" % (
            t["user"] or "(当前用户)", t["host"], t["dir"],
            t["hostDir"] or "(自动探测 $HOME/<rootfs>/root/mmzbot)")

    def preflight(self):
        t = self.opts["termux"]
        self.ssh = SSH(t["host"], t["port"], t["user"], t["key"])
        # Termux 家目录（绝对路径）
        rc, out, err = self.ssh.run('printf "%s\\n" "$HOME"')
        if rc != 0 or not out.strip().startswith("/"):
            raise DeployError("连上了，但读不到 Termux 的 $HOME：%s"
                              % (err or out).strip()[:160],
                              "确认登的是 Termux 用户（不是别的机器）")
        self.home = out.strip().splitlines()[-1]
        # proot rootfs：`$HOME/<rootfs>/root`
        rootfs = t["rootfs"]
        if rootfs:
            root_home = (rootfs if rootfs.startswith("/")
                         else self.home.rstrip("/") + "/" + rootfs.strip("/"))
            root_home = root_home.rstrip("/") + "/root"
        else:
            rc, out, _ = self.ssh.run(
                'for d in "$HOME"/*/root; do [ -d "$d" ] && echo "$d" && break; done')
            root_home = (out or "").strip().splitlines()[-1] if out.strip() else ""
            if not root_home:
                raise DeployError("找不到 proot 的 rootfs（`$HOME/*/root` 里一个都没有）",
                                  "配一下 deploy.termux.rootfs（例如 bookworm-arm64），"
                                  "或者直接配 deploy.termux.hostDir")
        self.root_home = root_home.rstrip("/")   # 容器 `/` 在 Termux 侧的路径
        self.container_dir = t["dir"].rstrip("/") or "/root/mmzbot"
        host_dir = t["hostDir"]
        if host_dir:
            host_dir = host_dir.replace("$HOME", self.home).rstrip("/")
        else:
            host_dir = self.root_home + self.container_dir
        self.dir = host_dir                      # ← 上传 / 备份在 Termux 侧路径上做
        self.container = self.container_dir      # ← 容器里跑命令用这个
        # runinc.sh：Termux 侧进容器的入口（默认 $HOME/runinc.sh）
        runinc = t["runinc"].replace("$HOME", self.home)
        if not runinc.startswith("/"):
            runinc = self.home.rstrip("/") + "/" + runinc.lstrip("./")
        self.runinc = runinc
        rc, out, _ = self.ssh.run("test -f %s && echo YES || echo NO" % shlex.quote(self.runinc))
        if "YES" not in out:
            raise DeployError("Termux 侧没有进容器的脚本：%s" % self.runinc,
                              "那是 proot 的入口（例如 `~/runinc.sh`）。"
                              "用 deploy.termux.runinc 指定它的位置")
        self.wrapper = "bash %s" % shlex.quote(self.runinc)
        # 容器里 python 可用？目录在不在？
        rc, out, err = self.run("%s -c 'import sys;print(sys.version.split()[0])'"
                                % shlex.quote(t["python"]))
        if rc != 0:
            raise DeployError("容器里找不到 Python（%s）：%s"
                              % (t["python"], (err or out).strip()[:160]),
                              "proot 里先 `apt install python3`")
        # 保证容器里的目标目录存在（Termux 侧就是 self.dir）
        self.ssh.check("mkdir -p %s" % shlex.quote(self.dir), "建目标目录")
        self._ensure_launch_files()
        return "Python %s 可用（容器 %s）" % (out.strip(), self.container)

    def _ssh_exists(self, path):
        rc, out, _ = self.ssh.run("test -f %s && echo YES || echo NO" % shlex.quote(path))
        return "YES" in out

    def _ensure_launch_files(self):
        """Termux 侧的启动脚本 / 看门狗**缺了就补一份**（有就绝不覆盖）。

        ⚠️ 它们必须活在 **Termux 侧**（不是容器里）：手机重启后是 Termux 拉她起来的。
           `--target termux` 第一次跑就能把四套启动里的手机那条装好，不用手抄。
        """
        t = self.opts["termux"]
        start = t["startScript"].replace("$HOME", self.home)
        if not start.startswith("/"):
            start = self.home.rstrip("/") + "/" + start.lstrip("./")
        self.start_host = start
        if not self._ssh_exists(start) and os.path.isfile(
                os.path.join(HERE, LAUNCH_SRC["fg-bot-v2-start.sh"])):
            say("    Termux 侧没有启动脚本 → 补一份到 %s" % start)
            self.ssh.upload([LAUNCH_SRC["fg-bot-v2-start.sh"]], HERE, self.home)
        wd = self.home.rstrip("/") + "/mmzbot-watchdog.sh"
        if not self._ssh_exists(wd) and os.path.isfile(os.path.join(HERE, "mmzbot-watchdog.sh")):
            self.ssh.upload([LAUNCH_SRC["mmzbot-watchdog.sh"]], HERE, self.home)

    def check_writable(self):
        pass    # preflight 里已经 mkdir 过；Termux 侧目录建得出来就说明能写

    def exists(self, rel):
        """目标文件在不在 —— 问 **Termux 侧**（不套容器）。"""
        p = self.dir.rstrip("/") + "/" + rel
        rc, out, _ = self.ssh.run("test -e %s && echo YES || echo NO" % shlex.quote(p))
        return "YES" in out

    def _to_container(self, host_path):
        """Termux 侧路径 → 容器里看到的路径。

        只有 rootfs 里的路径才有对应（暂存目录刻意放在那儿：`<rootfs>/root/.mmzbot-stage-*`），
        所以两边看到的是同一份文件，但**路径字符串不一样** —— 上传用 Termux 侧，
        进容器跑命令用容器侧。
        """
        host_path = host_path.rstrip("/")
        root = self.root_home
        if host_path == root:
            return "/"
        if host_path.startswith(root + "/"):
            return host_path[len(root):]
        return host_path

    def validate(self, stage):
        inner_stage = self._to_container(stage)
        py = [r for r in self.files if r.endswith(".py")]
        qpy = shlex.quote(self.opts["termux"]["python"])
        if py:
            inner = "cd %s && %s -m py_compile %s" % (
                shlex.quote(inner_stage), qpy,
                " ".join(shlex.quote(inner_stage + "/" + r) for r in py))
            rc, out, err = self.run(inner)
            if rc != 0:
                raise DeployError("容器里语法检查没过：\n%s" % (err or out).strip()[:600])
        say("    在容器里跑一遍 --selftest（离线）...")
        inner = "cd %s && MMZBOT_DATA=%s %s phone-bot-v2.py --selftest" % (
            shlex.quote(inner_stage), shlex.quote(inner_stage), qpy)
        rc, out, err = self.run(inner, timeout=420)
        if rc != 0:
            tail = "\n".join((out or err).strip().splitlines()[-12:])
            raise DeployError("容器里自检没过（退出码 %s）—— 目标目录一个字节都没动" % rc,
                              tail)
        say("    自检通过")

    def stage_path(self):
        # ⚠️ 暂存目录放在**容器 rootfs 里面**（`<rootfs>/root/.mmzbot-stage-*`）：
        #    这样它既有 Termux 侧路径（上传用），也有容器侧路径（跑命令用）。
        return self.root_home + "/root/.mmzbot-stage-" + _stamp()

    def swap(self, stage, files):
        inner_stage = self._to_container(stage)
        inner = self.container
        junk = ("bot.log reminders.json memory.json status-cache.json users.json "
                "local-config.json settings.json groups.json seen-groups.json "
                "requests.json runtime.json llm-key.txt llm-apis.txt control.txt "
                "restart.txt search-key.txt").split()
        if self.exists("personality.md"):
            say("    跳过 personality.md（目标已有，不覆盖用户改的那份）")
            junk.append(inner_stage.rstrip("/") + "/personality.md")
        inner_cmd = ("cd %s && rm -rf __pycache__ fgbot/__pycache__ && rm -f %s"
                     % (shlex.quote(inner_stage), " ".join(junk)))
        self.run(inner_cmd)
        rc, out, err = self.run(
            "cp -rf %s/. %s/ && rm -rf %s/__pycache__ %s/fgbot/__pycache__"
            % (shlex.quote(inner_stage), shlex.quote(inner),
               shlex.quote(inner), shlex.quote(inner)))
        if rc != 0:
            raise DeployError("换入失败：%s" % (err or out).strip()[:200])

    def cleanup(self, stage):
        self.ssh.run("rm -rf %s" % shlex.quote(stage))

    def backup(self):
        if not self.exists("phone-bot-v2.py"):
            return ""
        bakdir = os.path.dirname(self.dir) + "/." + os.path.basename(self.dir) + ".bak"
        target = "%s/%s" % (bakdir, _stamp())
        inner = ("mkdir -p %s && mkdir -p %s && (cd %s && tar cf - "
                 "--exclude=./models --exclude=./__pycache__ --exclude=./fgbot/__pycache__ .) "
                 "| (cd %s && tar xf -)" % (shlex.quote(bakdir), shlex.quote(target),
                                            shlex.quote(self.dir), shlex.quote(target)))
        rc, out, err = self.ssh.run(inner, timeout=600)
        if rc != 0:
            warn("备份没做成（不影响部署）：%s" % (err or out).strip()[:160])
            return ""
        self.prune_backups(bakdir)
        return target

    def prune_backups(self, bakdir):
        """Termux 侧清理（**不套容器**：备份目录在 Termux 的文件系统上）。"""
        rc, out, _ = self.ssh.run("ls -1 %s 2>/dev/null" % shlex.quote(bakdir))
        if rc != 0:
            return
        names = [n.strip() for n in out.splitlines() if n.strip()]
        _kept, drop, _others = keep_recent_backups(names, self.opts["keep_backups"])
        for n in drop:
            self.ssh.run("rm -rf %s" % shlex.quote("%s/%s" % (bakdir, n)), timeout=120)

    def restart(self, method):
        t = self.opts["termux"]
        if method == "auto":
            method = "termux"
        if self.opts["restart_cmd"]:
            say("    跑配置里的 restartCmd：%s" % self.opts["restart_cmd"])
            rc, out, err = self.ssh.run(self.opts["restart_cmd"], timeout=180)
            if rc != 0:
                raise DeployError("restartCmd 失败：%s" % (err or out).strip()[:200])
            return "restartCmd 成功"
        if method in ("none", "manual"):
            return self._manual(method)
        if method != "termux":
            raise DeployError("手机上的重启方式只能是 termux（给的是 %r）" % method)
        # 杀旧进程（Termux 侧的 pkill 对 proot 里的进程也有效）
        rc, out, _ = self.ssh.run("pgrep -f %s" % shlex.quote(t["killPattern"]))
        before = [x.strip() for x in out.splitlines() if x.strip().isdigit()]
        if before:
            self.ssh.run("pkill -f %s" % shlex.quote(t["killPattern"]))
            time.sleep(2.0)
            rc2, out2, _ = self.ssh.run("pgrep -f %s" % shlex.quote(t["killPattern"]))
            still = [x.strip() for x in out2.splitlines() if x.strip().isdigit()]
            if set(still) & set(before):
                raise DeployError("旧进程没杀掉（%s 还在）" % ", ".join(sorted(set(still) & set(before))),
                                  "手动：pkill -9 -f %s" % t["killPattern"])
        start = getattr(self, "start_host", "") or t["startScript"].replace("$HOME", self.home)
        if not start.startswith("/"):
            start = self.home.rstrip("/") + "/" + start.lstrip("./")
        rc, out, err = self.ssh.run(
            "MMZBOT_DATA=%s MMZBOT_DIR=%s setsid nohup bash %s >/dev/null 2>&1 & echo STARTED"
            % (shlex.quote(self.container), shlex.quote(self.container), shlex.quote(start)))
        if "STARTED" not in out:
            raise DeployError("启动脚本没跑起来：%s" % (err or out).strip()[:200],
                              "先手动跑：bash %s" % start)
        time.sleep(5.0)
        after = [x.strip() for x in self.ssh.run(
            "pgrep -f %s" % shlex.quote(t["killPattern"]))[1].splitlines() if x.strip().isdigit()]
        if not after:
            warn("PID 列表是空的 —— 她可能没起来，看下面的日志")
        elif before and not (set(after) - set(before)):
            warn("PID 没变 —— 跑着的可能还是旧进程（端口通不代表生效）")
        return "已通过 %s 拉起（PID %s）" % (start, ", ".join(after) or "?")

    def port_open(self):
        # 容器里探（端口在容器的网络命名空间里；proot 和 Termux 共享同一个）
        inner = ("cd %s && %s -c \"import socket,sys;"
                 "sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',%d))==0 else 1)\""
                 % (shlex.quote(self.container),
                    shlex.quote(self.opts["termux"]["python"]), int(self.port)))
        rc, _out, _err = self.run(inner, timeout=30)
        return rc == 0

    def tail_log(self, n=8):
        rc, out, _ = self.run("tail -n %d %s" % (n, shlex.quote(self.container + "/bot.log")))
        return [l for l in (out or "").strip().splitlines() if l.strip()][-n:]


# ── 备份清理：永远只留最近 N 个 ─────────────────────────────────────
#
# ⚠️ 为什么要有：以前 `/root/fg-bot-v2.bak/` 每部署一次多一个（每个 ~1.7M），
#    实测攒到 80 个 / 76M。用户拍板「保留最近 5 个」。
#
# 规矩（一条都不许松）：
#   · **永远保留最近 N 个**（含这次刚做出来的那个）；
#   · **只认 `^\d{8}-\d{6}$` 这种名字** —— 别的名字一律**不删**（不是备份，不占名额）；
#   · 删的时候**逐个列名**，不用通配符；名字都被上面的正则筛过，只可能是数字和横杠；
#   · 清理**绝不影响部署**：出任何事只打印一行，绝不抛、绝不 die。
BAK_NAME_RE = re.compile(r"^\d{8}-\d{6}$")
BAK_KEEP = 5


def keep_recent_backups(names, keep=BAK_KEEP):
    """纯函数（**不碰盘、不联网**）：一堆名字里哪些留、哪些删。

    ⚠️ 自己**按名字倒序**排 —— `20261003-131831` 这种名字本身就是时间，字典序 = 时间序。
       不信 mtime / `ls -1t` 的顺序：mtime 是可以被糊弄的（`touch` 一下、从别处拷回来），
       名字不会。（自检里造过 `20000101-*` 的空目录，`ls -1t` 把它们排到最前面 ——
       真按它删，删掉的就是真备份。）
    返回 `(留, 删, 不认识)`；`不认识` = 名字不像备份的那些，**永远不删**。
    """
    backups = sorted((n for n in names if BAK_NAME_RE.match(n)), reverse=True)
    others = [n for n in names if not BAK_NAME_RE.match(n)]
    k = max(0, int(keep))
    return backups[:k], backups[k:], others


# ── 计划 / 打印（`--dry` 只用这一套，保证不写任何文件）──────────────

def plan_files(opts, target):
    """要推的文件清单（**人设也先放进来**）。

    ⚠️ personality.md 走"先推进暂存区、再决定装不装"：暂存区里有它，自检才跑得起来
       （她找不到人设文件会自检红）；真换入的时候，目标上已经有那份就**跳过**
       （见各 Target 的 `swap()`）。
    """
    if opts["content_only"]:
        return collect_content()
    if opts["code_only"]:
        return collect_code()
    return collect_all()


def show_plan(opts, target, files, stage):
    say()
    say("目标：%s" % target.describe())
    say("重启方式：%s%s" % (opts["restart"],
                          "（--no-restart）" if opts["no_restart"] else ""))
    say("端口：%s" % opts["port"])
    say("清单：%d 个文件%s" % (len(files),
                              "（只代码）" if opts["code_only"] else
                              "（只内容，不重启）" if opts["content_only"] else ""))
    total = 0
    for f in files:
        try:
            n = os.path.getsize(os.path.join(HERE, f))
        except Exception:
            n = 0
        total += n
        say("  %-42s %8s" % (f, _fmt_size(n)))
    say("  合计 %s" % _fmt_size(total))
    if "personality.md" in files:
        if target.kind == "local":
            if target.exists("personality.md"):
                say("  （personality.md 目标上已经有 → 只进暂存区给自检用，**不覆盖**）")
            else:
                say("  （personality.md 目标上没有 → 推一份初版）")
        else:
            say("  （--dry 不连目标：personality.md 目标上已有就跳过，没有才推初版）")
    say("暂存目录：%s" % stage)
    if opts["dry"]:
        say()
        say("（--dry：只打印，不写文件、不连网络）")
        return
    say()
    say("步骤：① 上传 → ② 校验（py_compile + --selftest）→ ③ 备份 → ④ 换入 → ⑤ 重启")


# ── 主流程 ─────────────────────────────────────────────────────────

def make_target(opts):
    if opts["target"] == "local":
        return LocalTarget(opts)
    if opts["target"] == "ssh":
        return RemoteTarget(opts)
    if opts["target"] == "termux":
        return TermuxTarget(opts)
    raise DeployError("没选部署目标（现在 %r）" % opts["target"],
                      "加 `--target local|ssh|termux`，或者在 local-config.json 的 "
                      "deploy.target 里配一个")


def deploy(opts):
    target = make_target(opts)

    if opts["dry"]:
        # ⚠️ --dry **绝不连网络、绝不建目录**：这里只做本地只读检查
        files = plan_files(opts, target)
        show_plan(opts, target, files, "(不创建，--dry 只看)")
        return 0

    # — ① 预检（只读）—
    step("①", "预检")
    say("    目标：%s" % target.describe())
    say("    %s" % target.preflight())
    files = plan_files(opts, target)
    if not files:
        raise DeployError("没有要推的文件（清单是空的）", "是不是在错误的目录里跑？")

    # — ② 暂存 + 上传 —
    step("②", "暂存 / 上传")
    stage = target.stage_path() if target.kind != "local" else None
    if target.kind == "local":
        stage = target.stage(files)
        say("    暂存到 %s" % stage)
    else:
        target.upload(files, stage)

    # — ③ 校验 —
    step("③", "校验（还没碰正在跑的那份）")
    target.validate(stage)

    # — ④ 备份 —
    step("④", "备份")
    bak = target.backup() if opts["backup"] else ""
    if bak:
        say("    旧代码备份到 %s" % bak)
    else:
        say("    没有旧代码要备份（第一次部署）")

    # — ⑤ 换入 —
    step("⑤", "换入")
    target.swap(stage, files)
    target.cleanup(stage)
    say("    OK")

    # — ⑥ 重启 + 验证 —
    step("⑥", "重启 / 验证")
    if opts["no_restart"]:
        say("    按 --no-restart 没重启")
        say("    手动启动：")
        if target.kind == "local":
            say("      cd %s && %s phone-bot-v2.py" % (target.dir, target.python))
        else:
            say("      ssh %s 'cd %s && %s phone-bot-v2.py'"
                % (opts["ssh"]["host"], target.dir, target.python))
        return 0
    msg = target.restart(opts["restart"])
    say("    %s" % msg)
    say("    等 6 秒，看她起没起来 ...")
    time.sleep(6.0)
    up = target.port_open()
    say("    端口 %s：%s" % (opts["port"], "通 ✓" if up else "**不通 ✗**"))
    tail = target.tail_log(8)
    if tail:
        say("    她的日志：")
        for line in tail:
            say("      %s" % line)
    if not up:
        print()
        if opts["backup"] and bak:
            say("✗ 端口没起来。先看日志；要回滚就恢复 %s" % bak)
        else:
            say("✗ 端口没起来。先看日志（上面那几行）。")
        return 1
    say()
    say("✓ 部署完成（%s）" % target.describe())
    return 0


# ── 离线自检 ───────────────────────────────────────────────────────

def selfcheck():
    """`--selfcheck`：部署规则**离线**验一遍（不连网、不碰盘、不写文件）。"""
    ok = True

    def ck(cond, what, detail=""):
        nonlocal ok
        print("  %s %s%s" % ("✓" if cond else "✗", what, ("  ｜ " + str(detail)) if detail else ""))
        ok = ok and bool(cond)

    print("=== deploy.py --selfcheck：清单 / 人设 / 备份 / 目标 ===")
    # ① NEVER 名单
    for n in ("memory.json", "vectors.json", "reminders.json", "settings.json", "users.json",
              "groups.json", "seen-groups.json", "group-names.json", "requests.json",
              "local-config.json", "llm-key.txt", "llm-apis.txt", "search-key.txt",
              "bot.log", "status-cache.json", "runtime.json", "restart.txt", "control.txt"):
        ck(n in NEVER, "NEVER 名单里有 %s（推代码不会覆盖机器上的状态）" % n)
    for n in ("plan-123456789.json", "memory-backup-20261031-120000.json"):
        ck(_is_never(n), "前缀拦得住状态文件：%s" % n)
    for n in ("llm-key.txt.bak", "server.key", "bot.log.1", "x.pem", "a.pyc"):
        ck(_is_never(n), "扩展名拦得住密钥 / 日志 / 备份：%s" % n)
    ck(not _is_never("phone-bot-v2.py") and not _is_never("fgbot/base.py"),
       "正常代码文件不会被误拦")
    ck(not _is_never("config.json") and not _is_never("personality.md"),
       "config.json / personality.md 不在 NEVER 里")

    # ② 清单本身
    got = collect_code()
    ck("phone-bot-v2.py" in got, "代码清单里有 phone-bot-v2.py")
    ck("fgbot/base.py" in got, "代码清单里有 fgbot/base.py", "%d 个代码文件" % len(got))
    ck("examples/packages/pc-status-1.0.0.zip" in got,
       "代码清单里有示例包的安装包（手机上也找得到 --install-capability 那个路径）")
    ck(all(not f.endswith(".pyc") and "__pycache__" not in f for f in got),
       "清单里没有 .pyc / __pycache__")
    ck(all(not _is_never(f) for f in collect_all()), "整份清单里没有一个 NEVER 文件")

    # ③ 人设只推初版
    ck(want_personality(True) is False, "目标上已有 personality.md → **不推**（不覆盖用户改的）")
    ck(want_personality(False) is True, "目标上没有 → 推一份初版")

    # ④ 备份只留最近 N 个
    names = ["20261003-131831", "20261003-131119", "20261003-130829", "20261003-120219",
             "20261003-115955", "20261003-115451", "20261003-113200", "20261003-112923",
             "不是备份", "2026-10-03", "README.txt"]
    kept, drop, others = keep_recent_backups(names)
    ck(kept == names[:5], "8 个合法备份 → 只留最近 5 个", "留 = %s" % kept)
    ck(drop == names[5:8], "其余 3 个旧备份进「该删」名单", "删 = %s" % drop)
    ck(sorted(others) == sorted(["不是备份", "2026-10-03", "README.txt"]),
       "名字不像备份的一个都不删", "others = %s" % others)
    ck(keep_recent_backups(["20261003-131831"])[1] == [], "只有 1 个时什么都不删")
    ck(keep_recent_backups([]) == ([], [], []), "空目录不炸")
    ck(keep_recent_backups(names, keep=3)[1] == names[3:8], "keep 参数可调（keep=3 → 删 5 个）")
    ck(keep_recent_backups(names, keep=0)[0] == [], "keep=0 时一个都不留（但不认识的还是不动）")
    _k1, _d1, _o1 = keep_recent_backups(names)
    _k2, _d2, _o2 = keep_recent_backups(names[::-1])
    ck(_k1 == _k2 and _d1 == _d2 and sorted(_o1) == sorted(_o2),
       "打乱顺序结果一样（自己按名字排序，不信 mtime / ls -1t）")
    for bad in ("20261003-13183", "2026103-131831", "20261003_131831", "20261003-1318311",
                "20261003-13183a", "备份20261003-131831", "20261003-131831.bak",
                "..", "../../etc", "/root/x/y", "a b"):
        _k, d2, o2 = keep_recent_backups([bad])
        ck(d2 == [] and o2 == [bad], "非法名字绝不上删除名单：%r" % bad)
    ck(BAK_KEEP == 5, "保留数写死在常量里（用户定的 5）", BAK_KEEP)

    # ⑤ 三种目标都能"只解析、不连接"
    base_opts = {"dry": True, "target": "local", "local_dir": default_data_dir(),
                 "ssh": {"host": "", "port": 22, "user": "", "key": "", "dir": "~/mmzbot",
                         "python": "python3"},
                 "termux": {"host": "", "port": 22, "user": "", "key": "", "rootfs": "",
                            "dir": "/root/mmzbot", "hostDir": "", "runinc": "runinc.sh",
                            "startScript": "fg-bot-v2-start.sh",
                            "killPattern": "phone-bot-v2.py", "python": "python3",
                            "watchdog": ""},
                 "port": 17383, "python": "python3", "restart": "auto", "service": "mmzbot",
                 "no_restart": False, "code_only": False, "content_only": False,
                 "keep_backups": 5, "backup": True, "restart_cmd": "",
                 "cfg_path": ""}
    lt = LocalTarget(dict(base_opts))
    ck(lt.kind == "local" and "本机" in lt.describe(), "local 目标能构造（不碰盘）",
       lt.describe())
    rt = RemoteTarget(dict(base_opts, target="ssh"))
    ck(rt.kind == "ssh" and "SSH" in rt.describe(), "ssh 目标能构造（不连接）", rt.describe())
    tt = TermuxTarget(dict(base_opts, target="termux"))
    ck(tt.kind == "termux" and "Termux" in tt.describe(), "termux 目标能构造（不连接）",
       tt.describe())
    try:
        make_target(dict(base_opts, target=""))
        ck(False, "没选目标时应报人话")
    except DeployError as e:
        ck("--target" in (e.hint or ""), "没选目标 → 一句人话（不是 traceback）", e.msg)

    # ⑥ 缺依赖时的说法（这里只查源码里没有顶层 import paramiko / 没有那行 import）
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    ck(not re.search(r"^\s*(import|from)\s+phone\b", src, re.M),
       "不再 import 一个不存在的模块（以前那行 `import phone` 已经删掉）")
    top = src.split("# ── SSH", 1)[0]
    ck("import paramiko" not in top,
       "paramiko 是**可选依赖**（模块顶层不 import 它）")

    print()
    print("部署规则自检%s" % ("通过 ✓" if ok else "**没过**"))
    return 0 if ok else 1


# ── 命令行 ─────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="deploy.py",
        description="把 MMZBOT 部署到本机 / 远程 Linux / 手机 Termux，并重启她。",
        epilog="所有路径、端口、重启方式都能用参数或 local-config.json 的 deploy 一节配；"
               "优先级：命令行 > 环境变量 > 配置文件 > 默认。")
    p.add_argument("--target", choices=["local", "ssh", "termux"],
                   help="部署到哪：local=本机，ssh=远程 Linux，termux=手机 proot")
    p.add_argument("--dry", "--dry-run", dest="dry", action="store_true",
                   help="只打印要做什么（不写文件、不连网络、不重启）")
    p.add_argument("--no-restart", action="store_true", help="换入后不重启")
    p.add_argument("--code-only", action="store_true", help="只推 .py（不碰 config / 人设）")
    p.add_argument("--content-only", action="store_true",
                   help="只推 config / 人设（热重载，不重启）")
    p.add_argument("--restart", default=None,
                   choices=["auto", "systemd", "task", "script", "termux", "manual", "none"],
                   help="重启方式（默认 auto：本机看有没有 systemd / 任务计划）")
    p.add_argument("--service", default=None, help="systemd 单元名 / Windows 任务名")
    p.add_argument("--dir", default=None, help="目标数据目录（local / ssh / termux 共用）")
    p.add_argument("--port", default=None, type=int, help="部署后验证的端口")
    p.add_argument("--python", default=None, help="目标上的 Python 解释器")
    p.add_argument("--host", default=None, help="SSH 主机（ssh / termux）")
    p.add_argument("--ssh-port", dest="ssh_port", default=None, type=int, help="SSH 端口")
    p.add_argument("--ssh-user", dest="ssh_user", default=None, help="SSH 用户")
    p.add_argument("--ssh-key", dest="ssh_key", default=None, help="SSH 私钥路径")
    p.add_argument("--rootfs", default=None,
                   help="Termux 里 proot rootfs 的名字（默认自动探 $HOME/*/root）")
    p.add_argument("--host-dir", dest="host_dir", default=None,
                   help="Termux 侧的目标目录（默认 $HOME/<rootfs>/root + 容器目录）")
    p.add_argument("--selfcheck", "--selftest", dest="selfcheck", action="store_true",
                   help="离线验部署规则（不联网、不碰盘）")
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Windows 上输出被重定向时默认是 GBK，✓ / ✗ 会直接 UnicodeEncodeError —— 统一成 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.selfcheck:
        return selfcheck()
    opts = build_options(args)
    if not opts["target"]:
        # ⛔ 没选目标：只打印用法，**什么部署动作都不做**
        parser.print_help()
        print()
        print("✗ 没选部署目标：加 --target local|ssh|termux，"
              "或者在 local-config.json 的 deploy.target 里配一个")
        return 2
    if opts["code_only"] and opts["content_only"]:
        print("✗ --code-only 和 --content-only 只能选一个")
        return 2
    try:
        return deploy(opts)
    except DeployError as e:
        print()
        print("✗ %s" % e.msg)
        if e.hint:
            print("  %s" % e.hint)
        return 1
    except KeyboardInterrupt:
        print()
        print("✗ 被中断了（目标那边可能停在半路；看上面的步骤号）")
        return 130


if __name__ == "__main__":
    sys.exit(main())
