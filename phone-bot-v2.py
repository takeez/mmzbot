#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机魂小悦（MMZBOT）v2 的入口。

⚠️ **文件名别改** —— Termux 侧的启动脚本和看门狗按 `phone-bot-v2.py` 找进程。
   （v1 叫 `phone-bot.py`，两个名字分开是有意的：同一个手机里两套互不干扰。）

    python3 phone-bot-v2.py              起服务（监听 config.json 的 host / port）
    python3 phone-bot-v2.py --selftest   离线自检（部署脚本推之前会跑它）
    python3 phone-bot-v2.py --check      打印「能不能跑」检查表（退出码 0 = 可以跑）
    python3 phone-bot-v2.py --set k=v …  无头配置（给 agent / 脚本用；和面板同一份校验）
    python3 phone-bot-v2.py --persona-file F   把人设正文从文件写进去（尖括号注释不动）

═══ 无头配置（2026-10-31，用户定的部署目标）═══

`--set` 和面板「初始化」页走的是**同一条路**（`fgbot/onboard.py` 的 `save()`）：
同一个校验、同一个落点（`local-config.json`，deploy 永不覆盖）、同样**立刻生效**。
所以"照着说明装"的人 / agent 可以完全不碰文件、也不用开浏览器：

    python3 phone-bot-v2.py --set bot.selfId=10001 bot.token=xxx \
        napcat.baseUrl=http://127.0.0.1:3000 agent.name=机魂小悦 \
        bot.groups=123456789,987654321 agent.triggerWords=摸鱼、好累
    python3 phone-bot-v2.py --check          # 还差几项、差在哪
    python3 phone-bot-v2.py --persona-file personality.md

⛔ 它**不打印**任何 token / key 的明文（`--check` 只看"填没填"）。

═══ 自检的两条纪律（v1 踩过，别松）═══

① **绝对不联网、不发消息**：模型那层换成假传输层，图那层换成假下载器。
② **绝对没有副作用**：一开始就把状态目录和日志都指到临时目录，
   结尾再比对正式目录有没有多出/改动文件（§9.21 那条坑：自检写了状态文件，
   deploy 一搬就变成「没人按按钮，她的设定却变了」）。
"""

import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fgbot import base, server   # noqa: E402


# 自检分段账本（供 pytest 拆成逐段用例；不影响断言本身）
_CUR_SECT = ["未分段"]
_SECT_ROWS = []


def _ck(ok, what, detail=""):
    print("  %s %s%s" % ("✓" if ok else "✗", what, ("  ｜ " + detail) if detail else ""))
    _SECT_ROWS.append((_CUR_SECT[0], bool(ok), str(what), str(detail or "")))
    return bool(ok)


def selftest_sections():
    """刚跑过的自检按段汇总：[{name, total, failed: [{what, detail}]}]"""
    out, order = {}, []
    for sect, ok, what, detail in _SECT_ROWS:
        if sect not in out:
            out[sect] = {"name": sect, "total": 0, "failed": []}
            order.append(sect)
        out[sect]["total"] += 1
        if not ok:
            out[sect]["failed"].append({"what": what, "detail": detail})
    return [out[k] for k in order]


def _snapshot(d):
    """正式目录的文件清单（大小 + mtime）。跳过 __pycache__ 和 .pyc。"""
    out = {}
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for n in files:
            if n.endswith(".pyc"):
                continue
            p = os.path.join(root, n)
            try:
                out[os.path.relpath(p, d).replace(os.sep, "/")] = "%d:%d" % (
                    os.path.getsize(p), int(os.path.getmtime(p)))
            except Exception:
                pass
    return out


# 一张真的 PNG（120×60，左红右蓝）—— 自检里当"群里那张图"用
def _fake_png():
    import struct
    import zlib
    rows = b""
    for _y in range(60):
        row = b"\x00"
        for x in range(120):
            row += bytes((255, 0, 0) if x < 60 else (0, 0, 255))
        rows += row

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 120, 60, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


# ── 命令行：无头配置────────────────────────────────────
#
# 给 agent / 脚本 / "照着说明装"的人用：**不碰文件、不开浏览器**也能配完。
# ⚠️ 和面板「初始化」页**同一份实现**（`fgbot/onboard.py`）：
#    同一个校验、同一个落点（local-config.json）、同样立刻生效 —— 不重复两套。
# ⛔ 输出里**永远不打印** token / key 的明文。


def _cli_take(argv, flag):
    """取 `--set a=b c=d` / `--persona-file PATH` 后面那串（到下一个 `--` 开头为止）。"""
    if flag not in argv:
        return None
    out = []
    for x in argv[argv.index(flag) + 1:]:
        if x.startswith("--"):
            break
        out.append(x)
    return out


from fgbot.cli import (cli_cap_check, cli_cap_install, cli_cap_list,  # noqa: E402
                       cli_cap_remove, cli_check, cli_help, cli_init,
                       cli_list_models, cli_persona, cli_set)
from fgbot import selftest as _st      # noqa: E402


def selftest():
    """离线自检（实现在 fgbot/selftest.py）。"""
    return _st.run()


def selftest_sections():
    return _st.sections()


if __name__ == "__main__":
    # Windows 上输出被重定向时默认是 GBK，✓ / ✗ 会 UnicodeEncodeError ——
    # 命令行这条路（--check / --set / --help）是给 agent / 脚本看的，统一成 UTF-8。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    base.load()
    args = sys.argv[1:]
    if "--selftest" in args:
        rc = selftest()
        if "--json" in args:                 # 给 pytest / CI 用：逐段结果
            import json as _json
            print(_json.dumps({"rc": rc, "sections": selftest_sections()},
                              ensure_ascii=False))
        sys.exit(rc)
    if "--help" in args or "-h" in args:
        sys.exit(cli_help())
    if "--check" in args:
        sys.exit(cli_check())
    _pairs = _cli_take(args, "--set")
    if _pairs is not None:
        sys.exit(cli_set(_pairs))
    _pfile = _cli_take(args, "--persona-file")
    if _pfile is not None:
        if len(_pfile) != 1:
            print("✗ --persona-file 后面只跟一个文件名")
            sys.exit(2)
        sys.exit(cli_persona(_pfile[0]))
    _capck = _cli_take(args, "--check-capability")
    if _capck is not None:
        if len(_capck) != 1:
            print("✗ --check-capability 后面只跟一个 zip 或文件夹")
            sys.exit(2)
        sys.exit(cli_cap_check(_capck[0]))
    _capin = _cli_take(args, "--install-capability")
    if _capin is not None:
        if len(_capin) != 1:
            print("✗ --install-capability 后面只跟一个 zip 或文件夹")
            sys.exit(2)
        sys.exit(cli_cap_install(_capin[0]))
    _caprm = _cli_take(args, "--remove-capability")
    if _caprm is not None:
        if len(_caprm) != 1:
            print("✗ --remove-capability 后面只跟一个包名")
            sys.exit(2)
        sys.exit(cli_cap_remove(_caprm[0]))
    if "--list-capabilities" in args:
        sys.exit(cli_cap_list())
    _lm = _cli_take(args, "--list-models")
    if _lm is not None:
        if len(_lm) > 2:
            print("✗ --list-models 后面最多跟两个：地址 密钥（都不给就用配置里的）")
            sys.exit(2)
        sys.exit(cli_list_models(*(_lm + [None, None])[:2]))
    if "--init-config" in args:
        sys.exit(cli_init())
    # ⚠️ 以前不认识的参数会**一路走到 server.serve()** ——
    #    agent 打错一个词就"以为在初始化，其实把服务起来了" ✗
    _unknown = [a for a in args if a.startswith("-")]
    if _unknown:
        print("✗ 不认识这些参数：%s" % " ".join(_unknown))
        print("  看 --help；不带参数才是启动服务")
        sys.exit(2)
    server.serve()
