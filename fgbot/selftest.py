# -*- coding: utf-8 -*-
"""离线自检：不联网、不发消息、不写正式目录。

从 phone-bot-v2.py 里搬出来的（2026-11-02）；`--selftest` 仍然照旧可用。
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import base
from . import server
from .cli import (cli_cap_check, cli_cap_install, cli_cap_list, cli_cap_remove,
                  cli_check, cli_set)




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


# ── 命令行：无头配置（2026-10-31）────────────────────────────────────
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


def run():
    """离线自检：**不联网、不发消息、不写正式目录**。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.environ["MMZBOT_SELFTEST"] = "1"   # 自检模式：身份字段是空的模板也能跑（见 base._fill_selftest_defaults）
    base.load()
    c = base.cfg()
    ok = True
    # ⚠ 2026-11-02：仓库里只留一份 config.json，出厂模板的身份字段是**空的**。
    #   自检要用一个假群号跑端到端，所以在这里把那个假群固定进内存里的配置
    #   （**不写磁盘**，不影响「出厂模板一个字没动」那条断言）。

    # ══════════════════════════════════════════════════════════════
    # 0. 跨环境：时区（Android/Termux、Linux、Windows 三处都要对）
    # ══════════════════════════════════════════════════════════════
    #
    # ⚠️ 这条是 2026-10-31 加的口子：以前用 IANA 时区 + `time.tzset()`，Windows 上
    #    没有 tzset（IANA 名字也不认），`now` 会静默落到别的时区 —— 而**相对时间全对**，
    #    只有「九点半」这种绝对时刻会错，特别难发现。现在 `base` 自己算偏移
    #    （`time.localtime` / `time.timezone` / `time.altzone`，不依赖 tzdata），
    #    这里**拿 `time.localtime()` 和内部算出来的比**，必须一致。
    import time as _tz_time
    from datetime import datetime as _tz_dt

    print()
    _CUR_SECT[0] = "0. 时区（不依赖 tzdata）"
    print("=== 0. 时区（不依赖 tzdata）===")
    _tz_ok, _tz_what, _tz_detail = base.tz_selfcheck()
    ok &= _ck(_tz_ok, _tz_what, _tz_detail)
    # ⚠️ 用**同一个 epoch** 比（`local_now()` 是另一次取时间：跨秒时会差 1 秒，
    #    那不是算错，是取样时间不同）。比到整秒：time.localtime() 没有微秒。
    _tz_ts = _tz_time.time()
    _skew = abs((base.local_at(_tz_ts).replace(microsecond=0)
                 - _tz_dt(*_tz_time.localtime(_tz_ts)[:6])).total_seconds())
    ok &= _ck(_skew == 0,
              "同一个 epoch 上，`now` 和 `time.localtime()` 逐秒一致（差 %.0f 秒）" % _skew,
              "%s ｜ %s" % (base.local_at(_tz_ts).strftime("%F %T"), base.tz_info()))
    _rt = abs(base.local_stamp(base.local_now()) - _tz_time.time())
    ok &= _ck(_rt <= 3, "stamp(now()) 回到同一个 epoch（往返不漂，差 %.1f 秒）" % _rt)
    print("  %s" % base.tz_info())

    _CUR_SECT[0] = "1. 配置"
    print("=== 1. 配置 ===")
    print("  port = %s ｜ NapCat 上报 token %s ｜ 群 %s ｜ NapCat %s"
          % (c.get("port"), "有" if base.napcat_token() else "**没有**",
             base.bot_cfg().get("groups"), (c.get("napcat") or {}).get("url")))
    print("  %s ｜ 公网地址 %s ｜ 门禁 allowIps %s ｜ 公网 /api %s"
          % ("主人模式开着（role: owner）" if base.owner_mode() else "主人模式关着（role 不是 owner）",
             base.public_url() or "（还没填）",
             (base.bot_cfg().get("control") or {}).get("allowIps") or "（空 = 只认本机）",
             "**开着**（要签名凭据；面板/status/POST / 照旧只许本机+局域网）"
             if server.allow_public() else "关着（公网一律 403）"))
    # ⚠️ 这里的 `users` 名字**后面**（第 5 节）才 import —— 同一个函数里已经有了这个名字，
    #    所以上面这段（配置那节）不能直接用 `users`，会 UnboundLocalError（手机上第一推就踩到）。
    from fgbot import users as _users
    print("  用户表 %s" % _users.stats())
    if not c.get("port"):
        ok = False
        print("  ✗ config.json 里没有 port")
    if not base.napcat_token():
        print("  ⚠️ 没有 token：上报不校验（本机自用可以，开局域网不行）")
    if not base.owner_mode():
        print("  ⚠️ role 不是 owner：只有本机能用共享那把 token，"
              "主人自己那台电脑要连接就得先给它发一条邀请码")
    if not (c.get("agent") or {}):
        ok = False
        print("  ✗ config.json 里没有 agent 那一节")

    print()
    _CUR_SECT[0] = "2. 读 NapCat 上报（含那两个坑）"
    print("=== 2. 读 NapCat 上报（含那两个坑）===")
    from fgbot import napcat
    evt = {
        "post_type": "message", "message_type": "group", "group_id": 123456789,
        "user_id": 10001, "self_id": base.self_id(), "message_id": 12345,
        "raw_message": ("MMZ看看这个[CQ:image,file=/tmp/x.png,sub_type=0,"
                        "url=https://multimedia.nt.qq.com.cn/download?appid=1407&amp;rkey=abc]"),
        "sender": {"user_id": 10001, "card": "阿明", "nickname": "x"},
    }
    raw = napcat.text_of(evt)
    print("  text_of     -> %s" % raw[:60])
    print("  display_text-> %s" % napcat.display_text(raw))
    refs = napcat.image_refs(raw)
    print("  image_refs  -> %s" % refs)
    ok &= _ck(any("&rkey" in r for r in refs), "地址里的 &amp; 还原成 &（不然 QQ 报 invalid rkey）")
    ctx0 = server.build_ctx(evt, b"{}")
    need = ("key", "is_group", "group_id", "user_id", "who", "text", "raw",
            "raw_body", "evt", "images", "files", "message_id", "reply_to")
    miss = [k for k in need if k not in ctx0]
    ok &= _ck(not miss, "build_ctx 字段齐", "缺 %s" % miss if miss else "who=%s" % ctx0["who"])

    # 引用机器码：**剥掉**（2026-09-30 用户批的）——
    #   ① 它是"给模型看的文本"里的一段机器码，对她没意义；
    #   ② 不剥的话「引用之后只叫名字、不 @」**叫不动她**（_why 用 startswith 比名字）。
    #   ⚠️ 剥的只是"给她看/写日志"那份：reply_id() / ctx["reply_to"] 照样拿得到。
    rep_raw = "[CQ:reply,id=1692039722][CQ:at,qq=%d] 召唤师的丑态" % base.self_id()
    ok &= _ck(napcat.display_text(rep_raw) == "召唤师的丑态",
              "引用机器码 [CQ:reply,id=…] 不进给模型看的文本",
              repr(napcat.display_text(rep_raw)))
    ok &= _ck(napcat.reply_id({"raw_message": rep_raw}) == "1692039722",
              "但 reply_id() 那边照样拿得到那个 id（剥的只是「给她看」那份）")

    print()
    _CUR_SECT[0] = "3. 出站那套（im.py）在不在"
    print("=== 3. 出站那套（im.py）在不在 ===")
    from fgbot import im
    for fn in ("send_group", "send_private", "poke", "napcat_alive"):
        ok &= _ck(hasattr(im, fn), "im.%s" % fn)

    print()
    _CUR_SECT[0] = "4. 重启请求（面板/App 按「重启她」）"
    print("=== 4. 重启请求（面板/App 按「重启她」）===")
    real = base.RESTART_PATH
    base.RESTART_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_selftest_restart.txt")
    try:
        try:
            os.remove(base.RESTART_PATH)
        except Exception:
            pass
        with open(base.RESTART_PATH, "w", encoding="utf-8") as f:
            f.write("restart")
        ok &= _ck(os.path.exists(base.RESTART_PATH), "写得出来（看门狗认的就是这个文件）")
    finally:
        try:
            os.remove(base.RESTART_PATH)
        except Exception:
            pass
        base.RESTART_PATH = real

    print()
    _CUR_SECT[0] = "5. 她（agent 层）"
    print("=== 5. 她（agent 层）===")
    import base64
    import json
    import shutil
    import socket
    import tempfile
    import threading
    import time
    from datetime import datetime
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from fgbot import (agent, capabilities, clock, files, fgsig, guards, history, images,
                       keeper, llm, memory, merge, panel, persona, plan, ratelimit,
                       reminders, settings, statuscache, store, toolkit, users)

    def _read_log():
        """自检期间写下的日志（在临时目录里，不进正式目录）。"""
        try:
            with open(base.LOG_PATH, encoding="utf-8") as _f:
                return _f.read()
        except Exception:
            return ""

    def wait_until(fn, timeout=3.0, step=0.05):
        """等一件异步的事发生（后台补发、重试……），最多等 timeout 秒。"""
        end = time.time() + timeout
        while time.time() < end:
            if fn():
                return True
            time.sleep(step)
        return False

    def legacy_set(qq, card):
        """自检用：往记忆里塞**历史残留**的那个单字段 `card`。

        ⚠️ 2026-10-06 起 `memory.touch()` 自己**既不读也不写**它了（群名片改成
           `cards[群号]`）。所以"显示/认人都不许读老 card"这条断言得**手工**把它塞回去 ——
           不然测的是一份根本没写进去的字段。
        """
        d = store.read_json(memory.MEMORY) or {}
        rec = d.get(str(qq)) if isinstance(d.get(str(qq)), dict) else {}
        rec["card"] = card
        d[str(qq)] = rec
        store.write_json(memory.MEMORY, d)

    tmp = tempfile.mkdtemp(prefix="fg-selftest-")
    real_log = base.LOG_PATH
    store.set_dir(tmp)                              # 状态文件全落临时目录
    base.LOG_PATH = os.path.join(tmp, "bot.log")    # 日志也不许落到正式目录
    # ⚠ 2026-11-01：名字/唤醒词改成配置驱动了，而自检下面一大堆用例写死了 MMZ / MMZBOT。
    #   这里把 persona 那两个函数**直接打桩**（只在自检进程内，磁盘上的配置一个字不动）。
    _real_name, _real_wake = persona.name, persona.wake_words
    _STUB_DEFAULT = "机魂小悦"      # 配置默认名：遇到它就用自检的 MMZ
    def _stub_name():
        v = _real_name()
        return "MMZ" if v == _STUB_DEFAULT else v
    def _stub_wake():
        v = list(_real_wake() or [])
        if "MMZBOT" not in v:      # 自检用例里有一批写着「大名 MMZBOT」的，这里补上
            v.append("MMZBOT")
        return v
    persona.name = _stub_name
    persona.wake_words = _stub_wake
    before = _snapshot(base.DIR)
    chime_backup = None
    try:
        # ⭐ 2026-10-31（示例外置化）：`pc-status` 不再是仓库自带的 `capabilities/` 包 ——
        #    全新部署的默认状态是**没装**，自检也照用户的做法：从 examples 的安装包
        #    装一遍（和 `--install-capability examples/packages/pc-status-1.0.0.zip`
        #    走的是**同一条** `capabilities.install()`）。
        _ex_pkg_zip = os.path.join(base.CODE_DIR, "examples", "packages",
                                   "pc-status-1.0.0.zip")
        _ex_install = capabilities.install(_ex_pkg_zip)
        ok &= _ck(_ex_install.get("ok") and capabilities.get("pc-status") is not None,
                  "0. 示例包：pc-status 从 examples/packages/*.zip 装得上"
                  "（全新部署的 capabilities/ 里默认没有它）",
                  _ex_install.get("message"))

        # ── 性格文件
        prof = persona.profile()
        ok &= _ck(not prof.get("_missing"), "性格文件在", persona.profile_path())
        ok &= _ck(bool(persona.name()), "名字读得出来", "%s（别名 %s）"
                  % (persona.name(), "、".join(persona.call_names()[1:]) or "无"))
        print("    这个文件用户可以随便改，认得六个字段：")
        for k, v in persona.fields_help():
            print("      %-5s %s" % (k, v))
        n = persona.prompt_chars()
        ok &= _ck(n <= persona.MAX_CHARS,
                  "运行层提示词 %d 字（上限 %d；性格文件 %d 字不算）"
                  % (n, persona.MAX_CHARS, len(persona.personality_text())))

        # ── 工具目录：只给"办事"的能力，不给"改自己/改环境"的权限
        tools = toolkit.names()
        bad = [x for x in tools if any(k in x.lower() for k in
                                       ("write", "edit", "bash", "shell", "exec", "file",
                                        "config", "prompt", "del", "rm", "code"))]
        ok &= _ck(not bad, "工具目录里没有「改自己/改环境」的工具", "、".join(tools))

        # ── 路由：该搭话 / 不该搭话
        def mk(text, group=True, at=False, uid=10001, gid=123456789):
            raw = ("[CQ:at,qq=%d] " % base.self_id()) + text if at else text
            e = {"post_type": "message", "message_type": "group" if group else "private",
                 "user_id": uid, "self_id": base.self_id(), "message_id": 1,
                 "raw_message": raw, "sender": {"user_id": uid, "card": "已深度思考20秒", "nickname": "x"}}
            if group:
                e["group_id"] = gid
            return server.build_ctx(e, b"{}")

        ok &= _ck(agent._addressed(mk("MMZ你好")), "群里叫名字 → 搭话")
        ok &= _ck(agent._addressed(mk("你好", at=True)), "群里 @她 → 搭话")
        # 引用 + **只叫名字**（不 @）：以前被 `[CQ:reply,id=…]` 挡在最前面、判定落空
        #   （_why 用 startswith 比"她叫什么"）—— 剥掉机器码之后叫得动了。
        rep_ctx = mk("[CQ:reply,id=1891115291]MMZ这图里是谁")
        ok &= _ck(agent._why(rep_ctx) == "名字",
                  "引用之后**只叫名字**（不 @）也叫得动她（以前被机器码挡住）",
                  "text=%r why=%r" % (rep_ctx["text"], agent._why(rep_ctx)))
        ok &= _ck(agent._why(mk("[CQ:reply,id=1891115291]这图里是谁")) == "",
                  "引用之后**没叫她** → 还是不搭话（剥机器码不等于乱接话）")
        ok &= _ck(not agent._addressed(mk("今天天气不错")), "群里没人叫她 → 不搭话")
        ok &= _ck(agent._addressed(mk("在吗", group=False)), "私聊 → 一律搭话")
        ok &= _ck(not agent._in_scope(mk("MMZ", gid=999999)), "不在群名单里的群 → 不理")
        ok &= _ck(agent._is_ping("在吗") and agent._is_ping("ping") and agent._is_ping("在？"),
                  "判活认这些词")
        ok &= _ck(not agent._is_ping("在吗？帮我看下几点了"), "判活只认整条（后面带正事就交给模型）")

        # ── 时间听得懂吗（把「现在」钉死在 2026-09-25 22:00）
        print("    时间基准：%s（%s）｜ %s"
              % (clock.now().strftime("%Y-%m-%d %H:%M"), clock.zone(), clock.how()))
        now = datetime(2026, 9, 25, 22, 0)
        def when(s):
            return reminders.parse_when(s, now=now)
        print("    时间听得懂吗（把现在当成 2026-09-25 星期六 22:00）：")
        for s in ("九点半", "20分钟后", "明天早上7点", "下午三点", "9点30分", "半小时后"):
            try:
                print("      %-9s → %s" % (s, when(s)[1]))
            except ValueError as e:
                ok = False
                print("      %-9s → ✗ %s" % (s, e))
        # ⚠️ 期望值也要走 clock.stamp 算：now 是"墙上时间"，直接 .timestamp() 会按
        #    系统时区解释 —— 本机是 UTC，那就差了 8 小时（这正是 clock.py 要解决的问题）
        base_ts = clock.stamp(now)
        ok &= _ck(abs(when("20分钟后")[0] - (base_ts + 1200)) < 2, "「20分钟后」是准的")
        ok &= _ck(when("九点半")[0] > base_ts + 3600,
                  "22:00 说的「九点半」= 明早九点半（不是今天上午 —— UTC 那个坑）")
        ok &= _ck(abs(when("9点30分")[0] - when("九点半")[0]) < 2,
                  "「9点30分」没被读成「30 分钟后」")

        # ── 两个功能分开验：称呼功能（常驻在前缀里）/ 记忆功能（要用才查）
        good, why = memory.remember_name(10001, "张三")
        ok &= _ck(good and memory.name_of(10001) == "张三", "称呼功能：记得住（按 QQ 号）", why)
        bad_ok, why2 = memory.remember_name(10001, "主人")
        ok &= _ck((not bad_ok) and memory.name_of(10001) == "张三",
                  "称呼功能：「主人」这种不记（还是张三）", why2)

        memory.add_fact(10001, "住在杭州")
        memory.add_fact(10001, "喝咖啡不加糖")
        memory.add_fact(1111111111, "住在北京")
        one = memory.record_of(10001)
        ok &= _ck(one.get("facts") == ["住在杭州", "喝咖啡不加糖"],
                  "记忆功能：查某人**只**带出他自己那一块", str(one.get("facts")))
        ok &= _ck("北京" not in json.dumps(one, ensure_ascii=False),
                  "别人的信息一个字都不在这份结果里")
        r_tool = toolkit.call("memory", {}, mk("MMZ", uid=10001))
        ok &= _ck(r_tool.get("ok") is True and r_tool.get("一共") == 2
                  and r_tool.get("记着他这些") == ["住在杭州", "喝咖啡不加糖"],
                  "memory 工具只返回一个人的那部分", str(r_tool))
        ok &= _ck("他是谁" not in r_tool,
                  "memory 里**没有**称呼字段（用户把「称呼」从这里删掉了）")
        # 「查自己」：她不知道自己的 QQ 号，所以留了「自己」这个词
        memory.add_fact(base.self_id(), "主人的机器人，跑在他旧手机里")
        r_self = toolkit.call("memory", {"who": "自己"}, mk("MMZ", uid=10001))
        ok &= _ck(r_self.get("查到了") is True and r_self.get("这块是") == "你自己"
                  and r_self.get("关于你自己的事") == ["主人的机器人，跑在他旧手机里"],
                  "memory：填「自己」能查到她自己的那块")
        ok &= _ck(toolkit.call("memory", {"who": str(base.self_id())},
                               mk("MMZ", uid=10001)).get("查到了") is True,
                  "memory：用自己的 QQ 号也查得到")
        ok &= _ck(toolkit.call("memory", {"who": "MMZ"},
                               mk("MMZ", uid=10001)).get("这块是") == "你自己",
                  "memory：叫自己名字也算查自己")

        # 删/改：只动他自己的那一块
        # ⚠️ 2026-10-30（A3）：`fix_memory` 那个工具**没了** —— 增删改交给 memory-keeper。
        #    这里验的是底下的 `memory.fix_fact`（面板「记忆」页 / mem_fix 还在用它）。
        fix = memory.fix_fact(10001, "咖啡", "喝茶")
        ok &= _ck(fix[0] and "喝茶" in memory.facts_of(10001)
                  and all("咖啡" not in f for f in memory.facts_of(10001)),
                  "记忆功能：能改（咖啡→喝茶）", str(fix[1]))
        short = memory.fix_fact(10001, "茶")
        ok &= _ck(short[0] is False and "喝茶" in memory.facts_of(10001),
                  "关键词太短时拒绝（免得一下删一片）")
        delr = memory.fix_fact(10001, "喝茶")
        ok &= _ck(delr[0] and memory.facts_of(10001) == ["住在杭州"],
                  "记忆功能：能删（new 留空）")
        ok &= _ck(memory.facts_of(1111111111) == ["住在北京"],
                  "改/删只在说话人自己那块里动，别人的记忆没被碰")

        # 取名那条链（2026-10-06 用户拍板）：前缀 = **一个名字** + `: `，
        # 降级 = 群聊「称呼 → 本群名片 → 昵称 → QQ 号」/ 私聊「称呼 → 昵称 → QQ 号」，
        # ⛔ 以前那截 `[群名片:X]` / `[qq昵称:X]` **整条去掉了**。
        memory.remember_name(1111111111, "")
        memory.touch(1111111111, "小昵称", "小名片", "123456789")   # 名片**按群**存（本群那张）
        legacy_set(1111111111, "别群的历史残留")                    # 老单字段：只当历史残留
        ok &= _ck(memory.display_name(1111111111, True, card_now="小名片") == "小名片",
                  "群聊前缀：**没称呼** = **本群名片**（方括号那截没了）",
                  memory.display_name(1111111111, True, card_now="小名片"))
        ok &= _ck(memory.display_name(1111111111, False) == "小昵称",
                  "私聊前缀：**没称呼** = 昵称", memory.display_name(1111111111, False))
        memory.remember_name(1111111111, "小三")
        ok &= _ck(memory.display_name(1111111111, True, card_now="小名片") == "小三",
                  "群聊前缀：**有称呼** = 称呼（后面的名片/昵称都不再拼）",
                  memory.display_name(1111111111, True, card_now="小名片"))
        ok &= _ck(memory.display_name(1111111111, False) == "小三",
                  "私聊前缀：**有称呼** = 称呼", memory.display_name(1111111111, False))
        # ⭐ 回归断言（本案）：**声明了群**就按"本群那张"降级 ——
        #    传了 `card_now` 用它；没传就退到记忆里**这个群**那张（`cards[群号]`）；
        #    ⛔ 历史残留的单字段 `card` **绝不出现**，⛔ 别的群那张也绝不出现。
        _dn0 = memory.display_name(1111111111, True, card_now="")
        ok &= _ck(_dn0 == "小三",
                  "回归：有称呼时只出称呼（名片不再拼在后面）",
                  "%s（本群名片=%r ｜ 历史残留 card=%r）"
                  % (_dn0, memory.card_in(1111111111, "123456789"),
                     memory.record_of(1111111111).get("card")))
        memory.forget_name(1111111111)                 # 去掉称呼，看名片那一档
        ok &= _ck(memory.display_name(1111111111, True, card_now="",
                                      group_id="123456789") == "小名片",
                  "回归：**不传 card_now** → 退到记忆里**这个群**那张名片",
                  memory.display_name(1111111111, True, card_now="", group_id="123456789"))
        _dn1 = memory.display_name(1111111111, True, group_id="999999999")
        ok &= _ck(_dn1 == "小昵称",
                  "回归：**别的群**那张名片绝不出现（那个群没名片 → 退到昵称）", _dn1)
        ok &= _ck("小名片" not in memory.display_name(1111111111, False),
                  "回归：私聊前缀里**永远没有群名片**")
        memory.remember_name(1111111111, "小三")
        ok &= _ck("[" not in memory.display_name(1111111111, True, card_now="小名片")
                  and "群名片" not in memory.display_name(1111111111, True, card_now="小名片"),
                  "回归：⛔ 不再出现 `[群名片:…]` 那截")
        # 名片是占位符（QQ 对"没设名片"给的就是这个字面值）→ 当作"没名片"，不落那张表
        memory.touch(1111111111, "小昵称", "未设置", "123456789")
        ok &= _ck(memory.display_name(1111111111, True, card_now="未设置") == "小三",
                  "名片是占位符「未设置」→ 当作没有（不出「未设置」这个名字）",
                  memory.display_name(1111111111, True, card_now="未设置"))
        ok &= _ck(memory.card_in(1111111111, "123456789") == "小名片",
                  "占位符**不覆盖**已经存着的那张本群名片（「未设置」不进 cards 表）",
                  repr(memory.card_in(1111111111, "123456789")))
        memory.call_name(mk("MMZ", uid=1111111111))   # 保底：旧接口还能用
        ok &= _ck(memory.call_name(mk("MMZ", uid=1111111111, group=False)) == "小三",
                  "call_name（工具结果/提醒用的单名）不受影响，仍返回称呼")
        memory.forget_name(1111111111)

        # CQ 机器码不进"给她看的文本"
        ok &= _ck(agent._plain('[CQ:at,qq=123] 你好 [CQ:image,file=x.jpg]') == "你好",
                  "CQ 码被剥掉（历史和当前消息里都不该出现 [CQ:at,qq=…]）",
                  agent._plain('[CQ:at,qq=123] 你好 [CQ:image,file=x.jpg]'))
        c_at = mk("你好")
        c_at["raw"] = "[CQ:at,qq=%s] 你好" % base.self_id()
        ok &= _ck(agent._addressed(c_at) is True,
                  "剥 CQ 只动'给她看的文本'：点名判断照样成立（它判在 raw 上）")

        occ = agent._occasion(mk("MMZ", uid=10001), True)
        ok &= _ck(("住在杭州" not in occ) and ("咖啡" not in occ),
                  "记忆**默认不塞进上下文**（要用的时候她自己查）")
        ok &= _ck(str(base.self_id()) not in occ, "场合里不告诉她自己的 QQ 号")

        # ── 群名（`在 QQ 群 X（群名 Y）`）—— 2026-09-28 修过一个**静默失效**
        #    根因：`group_name` 把 `_napcat_post` 的第二个位置（失败原因串）当成了
        #    JSON 正文，而它成功时是空串 → 取不到名字 → 一声不响地 return ""。
        #    所以这里**必须**通过 NapCat 那道缝来测（绝不能真去连 NapCat）。
        real_call = im._napcat_call
        _asked = []
        try:
            def _fake_group_info(ep, payload, **kw):
                _asked.append(ep)
                return (True, {"group_id": 123456789, "group_name": "油库里观察日记"})
            im._napcat_call = _fake_group_info
            im._GROUP_NAMES.clear()
            im._GROUP_TRIED.clear()
            gname = im.group_name(123456789)
            ok &= _ck(gname == "油库里观察日记",
                      "群名：NapCat 正常回 data 时能取到名字（这就是那个 bug 的回归测试）",
                      repr(gname))
            occ_g = agent._occasion(mk("MMZ", uid=10001), True)
            ok &= _ck("在 QQ 群 123456789（群名 油库里观察日记）" in occ_g,
                      "群名：场合那行拼成 `在 QQ 群 X（群名 Y）`", occ_g.splitlines()[0])
            n_asked = len(_asked)
            im.group_name(123456789)
            im.group_name(123456789)
            ok &= _ck(len(_asked) == n_asked, "群名：进程内缓存 —— 同一个群只问一次",
                      "问了 %d 次" % len(_asked))
            # 落盘缓存：新起一个进程（清掉进程内缓存）应该直接读文件，不再问接口
            ok &= _ck(store.read_json("group-names.json") == {"123456789": "油库里观察日记"},
                      "群名：落了盘", str(store.read_json("group-names.json")))
            _asked2 = []
            im._napcat_call = lambda ep, payload, **kw: (_asked2.append(ep) or (False, "network"))
            im._GROUP_NAMES.clear()
            im._GROUP_TRIED.clear()
            ok &= _ck(im.group_name(123456789) == "油库里观察日记" and not _asked2,
                      "群名：新进程直接吃落盘缓存，不再打接口")
            # 查不到 → 安静退回半句，而且不报错。
            # 两种"查不到"都要认：接口失败，以及接口通了但 data 里没有名字
            # （后者正是当初那条静默路径，2026-09-28 之前它连日志都没有）。
            im._GROUP_NAMES.clear()
            im._GROUP_TRIED.clear()
            im._napcat_call = lambda ep, payload, **kw: (True, None)
            ok &= _ck(im.group_name(999999999) == "",
                      "群名：接口通了但 data 里没名字 → 空串（不抛异常）")
            im._GROUP_NAMES.clear()
            im._GROUP_TRIED.clear()
            _asked3 = []
            im._napcat_call = lambda ep, payload, **kw: (_asked3.append(ep) or (False, "network"))
            ok &= _ck(im.group_name(999999999) == "", "群名：接口失败 → 空串（不抛异常）")
            n_after = len(_asked3)
            # 同一个进程里再问几次（等于"之后每条消息都问一次"）→ 不许再打接口
            for _ in range(3):
                im.group_name(999999999)
            ok &= _ck(agent._occasion(
                mk("MMZ", uid=10001, gid=999999999), True).startswith("在 QQ 群 999999999"),
                "群名：查不到时那行**安静退回** `在 QQ 群 X`（形状不变）")
            ok &= _ck(len(_asked3) == n_after,
                      "群名：失败也只试一次，不会每条消息都去打接口",
                      "问了 %d 次" % len(_asked3))
        finally:
            im._napcat_call = real_call
            im._GROUP_NAMES.clear()
            im._GROUP_TRIED.clear()
        ok &= _ck("机主" not in json.dumps(base.cfg().get("agent") or {}, ensure_ascii=False)
                  and "homeCity" not in (base.cfg().get("agent") or {}),
                  "config 里没有机主/默认城市这类常驻附加消息")
        ok &= _ck("learn_skill" not in tools, "没有「她自己迭代自己」的口子（自学 skill 已拆掉）")

        # ── 提醒账本（写临时目录，不发送）
        at, human = reminders.parse_when("20分钟后")
        rec = reminders.add(("g", 123456789), 123456789, 10001, "张三", "喝水", at)
        ok &= _ck(len(reminders.pending()) == 1, "提醒进了账本", human)
        ok &= _ck(reminders.cancel(str(rec["id"]))[0] and not reminders.pending(),
                  "按编号能取消")
        # 响过的要留着（不然「刚那条提醒响了吗」她答不上来）
        reminders.add(("g", 123456789), 123456789, 10001, "张三", "伸个懒腰",
                      time.time() - 1)
        reminders._fire(lambda r: None)
        ok &= _ck(len(reminders.pending()) == 0 and len(reminders.done_recent()) == 1,
                  "响过的提醒留着（她事后答得上「响没响」）")

        # ── 兜底：削内心独白 / 揪谎话
        t1, rm = guards.strip_monologue("（他问我时间，我得先调个工具看看）\n现在十点啦")
        ok &= _ck(t1 == "现在十点啦", "内心独白削得掉", rm)
        t2, _ = guards.strip_monologue("（发呆）")
        ok &= _ck(t2 == "（发呆）", "整句就是括号里的话时，别把她削成哑巴")
        _md_in = "**记性与互动**：能记住\n- **闹钟**：设唤醒\n## 标题\n看[链接](https://x.com)"
        _md_want = "记性与互动：能记住\n闹钟：设唤醒\n标题\n看链接"
        ok &= _ck(agent._timeout_reply({"_trigger": "触发词"}, "x") is None
                  and agent._timeout_reply({"_sends": 1}, "x") is None
                  and agent._timeout_reply({"key": ("p", 1), "user_id": 1}, "x")
                  == "刚才超时了，等下再叫我一遍",
                  "超时才说一句（触发词/已说过话时不说）")
        _md_anchor_marker = 1
        ok &= _ck(guards.strip_markdown(_md_in) == _md_want,
                  "Markdown 剥除：粗体/列表/标题/链接 全去，文字不动",
                  repr(guards.strip_markdown(_md_in)))
        _cq_t, _cq_f = im._cq_clean("好[CQ:face,id=319]坏[CQ:at,qq=all]")
        ok &= _ck(_cq_t == "好坏" and _cq_f == ["319"],
                  "CQ 码：face 转表情，其它静默剥掉", "%r %r" % (_cq_t, _cq_f))
        ok &= _ck(not hasattr(guards, "is_" + "skip")
                  and not hasattr(guards, "SK" + "IP" + "_WORDS"),
                  "沉默哨兵（词表 + 判断函数）已经彻底删掉了（沉默 = end_turn / 空文本）")
        lies = guards.find_lies("行，我私聊发你了", ["wake"], True, user_text="你私聊告诉他吧")
        ok &= _ck(len(lies) == 1 and lies[0]["kind"] == "私聊", "「说做了其实没做」抓得到")
        ok &= _ck(guards.find_lies("行，我私聊发你了", ["send_private"], True, user_text="你私聊告诉他吧") == [],
                  "真调了工具就不算说谎")
        ok &= _ck(guards.find_lies("行，记下了", [], True, user_text="以后叫我张三"),
                  "他说「以后叫我张三」而她说记下了却没调工具 → 抓住")
        ok &= _ck(guards.find_lies("行，记下了", ["callname"], True, user_text="以后叫我张三") == [],
                  "真调了 callname 就不算（A3 合并之后的工具名）")
        ok &= _ck(guards.find_lies("记下了", [], True, user_text="刚那条提醒响了吗") == [],
                  "闲聊里的「记下了」（=知道了）不误伤")
        ok &= _ck(guards.find_lies("我 11:59 会喊你的", [], True, extra=("wake",)) == [],
                  "手上真挂着唤醒时，「我会喊你」不算谎")
        # 这三条都是真机端到端里**真误报过**的句子
        ok &= _ck(guards.find_lies("好，一分钟后叫你喝水。", [], True, user_text="一分钟后叫我喝水"),
                  "答应以后的提醒却没调工具 → 抓住")
        ok &= _ck(guards.find_lies("响了，我喊你喝水了。", [], True, user_text="提醒响了吗") == [],
                  "说的是已经发生过的事 → 不算谎")
        ok &= _ck(guards.find_lies("我可没答应过提醒你啥事。", [], True) == [],
                  "否认句 → 不算谎")

        ok &= _ck(guards.find_lies("我帮你删了那条", [], True,
                                   user_text="把我住哪那条删了吧"),
                  "「说删了其实没删」也抓得到")
        ok &= _ck(guards.find_lies("我帮你删了那条", ["memory"], True,
                                   user_text="把我住哪那条删了吧") == [],
                  "真调了 memory 就不算（A3 之后没有 fix_memory 了）")
        ok &= _ck(guards.find_lies("这条删了就行", [], True, user_text="怎么办？") == [],
                  "「这条删了就行」是建议，不是承诺 → 不误伤")
        ok &= _ck(guards.find_lies("我刚把杭州那条删了", [], True,
                                   user_text="你现在还记得我什么？") == [],
                  "他没让她改/删 → 她在说以前做过的事，不算谎（实测踩过）")

        # ── 消息结构（§9 的两条硬规矩）
        k1 = ("g", 111)
        memory.record(k1, "user", "帮我看看这个", qq=111, name="张三")
        memory.record(k1, "user", "你真可爱", qq=222, name="李四")
        ms = memory.render(k1)
        ok &= _ck(len(ms) == 2 and all(m["role"] == "user" for m in ms),
                  "两个人说话 = 两条消息（绝不合并成一条）")
        ok &= _ck(ms[0]["content"].startswith("张三: ") and ms[1]["content"].startswith("李四: "),
                  "每行都带「谁说的」前缀（有称呼就是称呼，没有就 QQ 号 + 名片/昵称）",
                  ms[0]["content"][:24])
        memory.record(k1, "user", "再说一句", qq=111, name="张三")
        ms2 = memory.render(k1)
        ok &= _ck(len(ms2) == 3, "中间隔了别人的话，同一个人也不许合并")
        k2 = ("g", 222)
        memory.record(k2, "user", "一", qq=111, name="张三")
        memory.record(k2, "user", "二", qq=111, name="张三")
        ok &= _ck(len(memory.render(k2)) == 1, "同一个人连发两条 → 合并成一条")

        # ── 上网搜索：主源（百度千帆「智能搜索生成」）没配 / 出问题会不会崩 ──
        #
        # **全程打桩、绝不联网**：`web._open` 换成假 RSS（回退那套的"网"），
        # `web.set_transport` 换成假千帆（能造正常返回、缺字段、非 200）。
        # key 也一样打桩（直接改它进程内那个缓存），免得本机有没有 key 文件影响自检。
        print()
        print("    上网搜索（百度智能搜索 → 回退抓取；全打桩、不联网）：")
        from fgbot import web
        real_key = (web._KEY, web._KEY_READ)
        real_post = web._POST
        real_open = web._open
        try:
            rss = ('<?xml version="1.0"?><rss><channel><item><title>老路第一条</title>'
                   '<link>https://example.com/a</link><description>老路的摘要</description>'
                   '</item></channel></rss>').encode("utf-8")

            def rss_open(url, data=None, timeout=0, limit=0, ua=None):
                return rss, "text/xml"

            def dead_open(url, data=None, timeout=0, limit=0, ua=None):
                raise OSError("自检：假断网")

            seen = []

            def fake_qf(status, body):
                def fn(url, payload, headers, timeout):
                    seen.append((url, payload, headers, timeout))
                    blob = body if isinstance(body, bytes) else \
                        json.dumps(body, ensure_ascii=False).encode("utf-8")
                    return status, blob
                return fn

            # ① 没 key → 走老路，一个字都不变（千帆一次都不碰）
            web._open = rss_open
            web._KEY, web._KEY_READ = None, True
            seen.clear()
            r = web.search("自检 没key")
            ok &= _ck(r.get("ok") is True and r.get("engine") == "必应RSS" and r.get("results")
                      and not seen,
                      "没 key → 走老路（engine 还是「必应RSS」），千帆一次都没碰", str(r)[:52])
            ok &= _ck(r.get("注意") == web.QF_NOTE,
                      "老路那句「注意」跟新路用的是**同一句原文**（没被顺手改写）")
            web._open = dead_open
            r = web.search("自检 全挂")
            ok &= _ck(r == {"ok": False, "error": web.QF_FAIL},
                      "三个源全挂 → 还是原来那句失败话术（逐字）", str(r)[:44])

            # ② 有 key + 千帆返回缺字段 → 不崩，静默回退老路，日志里留一行
            web._open = rss_open
            web._KEY, web._KEY_READ = "自检假key", True
            seen.clear()
            web.set_transport(fake_qf(200, {"request_id": "x"}))
            r = web.search("自检 缺字段")
            ok &= _ck(r.get("ok") is True and r.get("engine") == "必应RSS" and bool(seen),
                      "千帆返回缺字段 → 不崩、静默回退老路（她看不到报错）", str(r)[:52])
            txt = open(base.LOG_PATH, encoding="utf-8").read() \
                if os.path.isfile(base.LOG_PATH) else ""
            ok &= _ck("搜索走 百度智能搜索 失败，回退抓取" in txt,
                      "回退这件事在 bot.log 里留了一行")

            # ③ 非 200（坏 key / 被挡）→ 一样回退，不崩
            web.set_transport(fake_qf(401, b'{"error_code": 1}'))
            r = web.search("自检 401")
            ok &= _ck(r.get("engine") == "必应RSS",
                      "千帆 401 → 回退老路（不崩）", str(r)[:40])

            # ④ 正常一次：形状逐字对（答案截 1200、摘要截 300、来源 5 条、Bearer 头）
            refs = [{"id": i, "title": "标题%d" % i, "url": "https://e.com/%d" % i,
                     "website": "站点%d" % i, "date": "2026-09-28",
                     "content": "内容" * 400, "snippet": "短的%d" % i} for i in range(8)]
            web.set_transport(fake_qf(200, {"request_id": "r", "choices": [
                {"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "答" * 1300}}],
                "references": refs}))
            seen.clear()
            r = web.search("自检 正常")
            qf = seen[0] if seen else ("", {}, {}, 0)
            ok &= _ck(r.get("engine") == "百度智能搜索" and r.get("ok") is True
                      and len(r.get("答案") or "") == 1200 and len(r.get("来源") or []) == 5
                      and [x["title"] for x in r["来源"]] == ["标题0", "标题1", "标题2",
                                                              "标题3", "标题4"]
                      and len(r["来源"][0]["snippet"]) == 300
                      and list(r["来源"][0]) == ["title", "url", "website", "date", "snippet"]
                      and r.get("注意") == web.QF_NOTE,
                      "千帆正常 → 答案截 1200、来源 5 条（按返回顺序）、摘要截 300、注意原文",
                      "答案 %d 字 / 来源 %d 条" % (len(r.get("答案") or ""),
                                                   len(r.get("来源") or [])))
            ok &= _ck(qf[2].get("Authorization") == "Bearer 自检假key",
                      "请求头是 `Bearer <key>`（裸 key 会 401 —— 这个坑焊死在自检里）",
                      "Authorization=%s…" % str(qf[2].get("Authorization"))[:13])
            ok &= _ck(qf[0] == web.QF_URL and qf[1]["messages"][0]["content"] == "自检 正常"
                      and qf[1]["resource_type_filter"] == [{"type": "web", "top_k": 10},
                                                            {"type": "video", "top_k": 0},
                                                            {"type": "image", "top_k": 0}],
                      "地址与请求体形状对（web top_k=10、视频图片 top_k=0）")
            # 答案空、来源有 → 照样返回，只是不带「答案」这个键
            web.set_transport(fake_qf(200, {"choices": [{"message": {"content": ""}}],
                                            "references": refs[:2]}))
            r = web.search("自检 只有来源")
            ok &= _ck(r.get("ok") is True and "答案" not in r and len(r.get("来源") or []) == 2,
                      "千帆答案空、来源有 → 照样返回（只是不带「答案」键）", str(list(r)))
            # 两者都空 → 走失败话术
            web.set_transport(fake_qf(200, {"choices": [{"message": {"content": "  "}}],
                                            "references": []}))
            ok &= _ck(web.search("自检 全空") == {"ok": False, "error": web.QF_FAIL},
                      "千帆两者都空 → 失败话术（逐字）")
            ok &= _ck(web._key() == "自检假key", "key 读一次就缓存（进程内）")
        finally:
            web._open = real_open
            web._POST = real_post
            web._KEY, web._KEY_READ = real_key

        # ── 端到端：假模型 + 假图，离线跑一整轮 handle
        print()
        _CUR_SECT[0] = "6. 端到端（假模型、假图，离线）"
        print("=== 6. 端到端（假模型、假图，离线）===")
        seen = {}
        png = _fake_png()

        def stub(url, payload, headers, timeout):
            seen["payload"] = payload
            blob = json.dumps(payload["messages"], ensure_ascii=False)
            if "你被唤醒功能唤醒起来执行任务" in blob:
                content = "张三，该喝水啦。"
            elif "摸鱼数据" in blob or "摸鱼管理程序" in blob:
                # 播报那一轮（材料现在是"抬头 + 一行一条记录"，不再出现 PCStatus 这个词）
                content = "" if seen.get("announce_skip") else "又摸上了？我这边可都记着呢。"
            elif any(isinstance(m.get("content"), list) for m in payload["messages"]):
                content = "左边红的，右边蓝的。"
            else:
                content = "嗯嗯，我在。"
            return {"model": "stub-模型", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

        llm.set_transport(stub)
        images.set_fetcher(lambda u: png)
        chime_backup = ((base.cfg().get("agent") or {}).get("chimeIn") or {}).get("enabled")
        if base.cfg().get("agent", {}).get("chimeIn") is not None:
            base.cfg()["agent"]["chimeIn"]["enabled"] = False   # 自检要确定性（1% 会偶发）

        evt2 = {"post_type": "message", "message_type": "group", "group_id": 123456789,
                "user_id": 10001, "self_id": base.self_id(), "message_id": 999,
                "raw_message": "MMZ看看这个[CQ:image,file=/tmp/x.png,sub_type=0,"
                               "url=https://multimedia.nt.qq.com.cn/download?appid=1&amp;rkey=z]",
                "sender": {"user_id": 10001, "card": "已深度思考20秒", "nickname": "x"}}
        ctx = server.build_ctx(evt2, b"{}")
        reply = agent.handle(ctx)
        ok &= _ck(reply == "左边红的，右边蓝的。", "带图那条她回话了（话是模型给的）", repr(reply))
        pl = seen.get("payload") or {}
        ok &= _ck(pl.get("thinking") == {"type": "enabled"} and bool(pl.get("reasoning_effort")),
                  "请求里开着思考", json.dumps({"thinking": pl.get("thinking"),
                                               "reasoning_effort": pl.get("reasoning_effort")},
                                              ensure_ascii=False))
        ok &= _ck(len(pl.get("tools") or []) == len(tools), "请求里带着工具目录",
                  "%d 个" % len(pl.get("tools") or []))
        last = (pl.get("messages") or [{}])[-1]
        ltxt = ((last.get("content") or [{}])[0].get("text") or "")
        ok &= _ck(last.get("role") == "user" and isinstance(last.get("content"), list)
                  and (ltxt.startswith("张三[群名片") or ltxt.startswith("张三: ")),
                  "最后一条是他的原话本身（前缀 = 称呼｜QQ 号 + 群名片｜昵称）", ltxt[:30])
        img = (last.get("content") or [{}, {}])[1].get("image_url", {}).get("url", "")
        ok &= _ck(img.startswith("data:image/png;base64,")
                  and base64.b64decode(img.split(",", 1)[1]) == png,
                  "图真的进了请求（base64 解出来和原图逐字节相同）", "%d 字节" % len(png))
        sysm = [m for m in pl.get("messages") or [] if m.get("role") == "system"]
        ok &= _ck(len(sysm) == 1 and sysm[0]["content"] == persona.system_prompt(),
                  "整份提示词**只发一次**（一条 system，**逐字** = persona.system_prompt()）",
                  "%d 条 system" % len(sysm))
        # A2（2026-10-30）：system 在**最前面**；场合事实单独一条 user 快照，
        # 排在历史之后、他原话之前。
        idx_sys = [i for i, m in enumerate(pl.get("messages") or []) if m.get("role") == "system"]
        ok &= _ck(idx_sys == [0],
                  "A2 system 只在**最前面**这一个位置（不再拼场合、也不再重复）", str(idx_sys))
        _msgs6 = pl.get("messages") or []
        _snap6 = _msgs6[-2] if len(_msgs6) >= 2 else {}
        ok &= _ck(_snap6.get("role") == "user"
                  and isinstance(_snap6.get("content"), str)
                  and ("在 QQ 群" in _snap6["content"] or "的私聊" in _snap6["content"]),
                  "A2 场合事实走**单独一条 user 快照**（在历史之后、他原话之前）",
                  str(_snap6.get("content"))[:40])
        ok &= _ck(not any("刚说话的是" in str(m.get("content")) for m in sysm),
                  "场合里不再重复说话人（用户点名去掉的）")
        ok &= _ck(sum(1 for m in pl.get("messages") or []
                      if m.get("role") == "assistant" and
                      str(m.get("content") or "").startswith(("MMZ", "MMZBOT"))) == 0,
                  "历史里她的行**不带任何前缀**（assistant 就是裸文本）")

        # ── 取图的三条路（2026-09-30 加的：QQ 把群图 CDN 换成 gchat.qpic.cn
        #    之后直连必 400 download url has expired，首选改成「问 NapCat 要」。
        #    这个顺序被谁改回去，这里当场红 —— 理由写在 images.py 开头。）
        tmp_img = os.path.join(tmp, "napcat-给的一张图.png")
        with open(tmp_img, "wb") as fh:
            fh.write(png)
        images.set_puller(lambda name: (True, {"file": tmp_img,
                                               "file_size": str(len(png))}))
        try:
            got, why = images._one({"file": "AABB.jpg", "id": "",
                                    "url": "https://gchat.qpic.cn/download?appid=1407&rkey=死的"})
            ok &= _ck(got == png and why == "NapCat 给的本地文件",
                      "取图首选：问 NapCat 要（它给本地路径，读那个文件）",
                      "拿到 %d 字节、说明=%r" % (len(got) if got else 0, why))
        finally:
            images.set_puller(None)

        # NapCat 那条拿不到 → 落回 CDN 那条（真人真事：地址还没死的年代靠它）
        images.set_puller(lambda name: (False, "retcode"))
        try:
            got, why = images._one({"file": "AABB.jpg", "id": "", "url": "https://x/y"})
            ok &= _ck(got == png and why == "下载成功",
                      "NapCat 拿不到 → 落回 CDN（假下载器给的还是那张图）", repr(why))
        finally:
            images.set_puller(None)

        # 两条都挂 → 给模型看的**还是原来那四句话**，一个字都没变
        images.set_puller(lambda name: (False, "retcode"))
        images.set_fetcher(lambda u: (_ for _ in ()).throw(
            urllib.error.HTTPError(u, 400, "Bad Request", None, None)))
        try:
            got, why = images._one({"file": "AABB.jpg", "id": "", "url": "https://x/y"})
            ok &= _ck(got is None and why == "下载失败（HTTPError）",
                      "两条都挂 → 给模型的那句**逐字不变**（还是「下载失败（HTTPError）」）",
                      repr(why))
            logtxt = open(base.LOG_PATH, encoding="utf-8").read() \
                if os.path.isfile(base.LOG_PATH) else ""
            ok &= _ck("HTTP 400" in logtxt and "响应体=" in logtxt,
                      "状态码 + 响应体进了 bot.log（诊断要的就是它，且不进模型）")
        finally:
            images.set_puller(None)
            images.set_fetcher(lambda u: png)

        # ── 引用（回复）里的图和那句话（2026-09-30 用户批的）────────────────
        #    他引用了一条**带图的老消息**时，把那条里的图挂到这一轮，并附一句**事实**：
        #       （他引用的那条是 <谁> 说的：「<被引用那条的文字>」）
        #    ⛔ 只认引用关系（不许靠关键词猜）、图取不到静默、那句话全是事实没有指令。
        #    全程打桩，不联网。
        print()
        _CUR_SECT[0] = "6b. 引用（回复）里的图（打桩、离线）"
        print("=== 6b. 引用（回复）里的图（打桩、离线）===")
        QRAW = ("看看这张[CQ:image,file=QUOTED.png,sub_type=0,"
                "url=https://gchat.qpic.cn/download?appid=1407&amp;rkey=quote]")

        def qmsg(raw):
            """被引用的那条（形态照抄真机上 get_msg 的返回）。"""
            return {"message_id": 1891115291, "raw_message": raw,
                    "message": [{"type": "text", "data": {"text": "看看这张"}},
                                {"type": "image",
                                 "data": {"file": "QUOTED.png",
                                          "url": "https://gchat.qpic.cn/download?appid=1407&rkey=quote"}}],
                    "sender": {"user_id": 10001, "card": "已深度思考20秒"},
                    "time": 1790768570}

        def reply_evt(raw, mid=2001):
            return {"post_type": "message", "message_type": "group", "group_id": 123456789,
                    "user_id": 10001, "self_id": base.self_id(), "message_id": mid,
                    "raw_message": raw,
                    "sender": {"user_id": 10001, "card": "已深度思考20秒", "nickname": "x"}}

        def imgs_in(payload):
            last = (payload.get("messages") or [{}])[-1]
            return [p for p in (last.get("content") or [])
                    if isinstance(p, dict) and p.get("type") == "image_url"]

        def b64(p):
            return base64.b64decode(p["image_url"]["url"].split(",", 1)[1])

        # ① 有引用 → 会去要那条（get_msg），而且**那张图真的挂上了**
        asked = []
        images.set_quoter(lambda rid: (asked.append(rid) or (True, qmsg(QRAW))))
        try:
            seen.clear()
            ctx_q = server.build_ctx(
                reply_evt("[CQ:reply,id=1891115291][CQ:at,qq=%d] 这张图里是谁" % base.self_id()),
                b"{}")
            ok &= _ck(ctx_q.get("reply_to") == "1891115291",
                      "引用认得出来（CQ 形态 [CQ:reply,id=…] → ctx['reply_to']）",
                      repr(ctx_q.get("reply_to")))
            rq = agent.handle(ctx_q)
            ok &= _ck(rq is not None, "引用了一条带图的老消息：她照常回话", repr(rq))
            ok &= _ck(asked == ["1891115291"], "有引用 → 真去要了被引用那条（get_msg）", str(asked))
            qi = imgs_in(seen.get("payload") or {})
            ok &= _ck(len(qi) == 1 and b64(qi[0]) == png,
                      "被引用那条里的图**真的进了这一轮的请求**（base64 解出来和原图逐字节相同）",
                      "%d 张" % len(qi))
            lq = ((seen.get("payload") or {}).get("messages") or [{}])[-1]
            cq = lq.get("content") or []
            ok &= _ck([p.get("type") for p in cq] == ["text", "text", "image_url"],
                      "这一轮的形状 = 他的话 → 那句话 → 图", str([p.get("type") for p in cq]))
            # ⚠ 2026-11-01：cq 可能只有 1 段（依赖用例）——以前直接 cq[1] 会 IndexError，
            #   把整段自检带崩（部署验收时真崩了）。先判长度。
            ok &= _ck(len(cq) > 1 and cq[1].get("text")
                      == "（他引用的那条是 %s 说的：「看看这张[图片]」）"
                      % memory.display_name(10001, True, card_now="已深度思考20秒"),
                      "被引用那条的**文字**也在，说话人跟前缀同一套（display_name，"
                      "名片认的是**被引用那条消息里那张**）",
                      # ⚠ 2026-11-01：这个提示参数是**无条件求值**的，
                      #   光护住前面的比较没用 ✗ cq 只有 1 段时照样 IndexError。
                      (repr(cq[1].get("text")) if len(cq) > 1 else repr(cq)))
            # ⭐ 回归：被引用那条**没带名片** → 只出称呼/QQ 号，
            #    绝不用记忆里那张（可能是别群的）名片顶上。
            images.set_quoter(lambda rid: (
                True, dict(qmsg(QRAW), sender={"user_id": 10001, "nickname": "x"})))
            seen.clear()
            rq2 = agent.handle(server.build_ctx(
                reply_evt("[CQ:reply,id=1891115292][CQ:at,qq=%d] 这张图里是谁" % base.self_id(),
                          mid=2002), b"{}"))
            lq2 = ((seen.get("payload") or {}).get("messages") or [{}])[-1]
            cq2 = [p.get("text") for p in (lq2.get("content") or [])
                   if isinstance(p, dict) and p.get("type") == "text"]
            ok &= _ck(rq2 is not None and len(cq2) >= 2
                      and cq2[1] == "（他引用的那条是 %s 说的：「看看这张[图片]」）"
                      % memory.display_name(10001, True, card_now=""),
                      "⭐ 回归：被引用那条**没名片** → 说话人只出称呼/QQ 号，"
                      "**记忆里那张名片绝不出现**（也不留 `[群名片:]` 空壳）",
                      repr(cq2[:2]))
        finally:
            images.set_quoter(None)

        # ①b 日志那行：机器码剥了，但**引用 id 留着**（纯日志，不进模型）
        real_send = im.send_group
        im.send_group = lambda *a, **kw: True
        images.set_quoter(lambda rid: (True, qmsg(QRAW)))
        try:
            logp = base.LOG_PATH
            n0 = len(open(logp, encoding="utf-8").read()) if os.path.isfile(logp) else 0
            server._on_message(reply_evt(
                "[CQ:reply,id=1891115291][CQ:at,qq=%d] 这张图里是谁" % base.self_id()), b"{}")
            tail = open(logp, encoding="utf-8").read()[n0:] if os.path.isfile(logp) else ""
            ok &= _ck("（引用 1891115291）" in tail and "CQ:reply" not in tail,
                      "日志：引用 id 留着（纯日志），机器码不在给模型的那份里",
                      repr(tail.strip().splitlines()[:1]))
        finally:
            im.send_group = real_send
            images.set_quoter(None)

        # ② 段数组形态（`raw_message` 万一没有）+ **没引用就不多事**
        evt_arr = reply_evt("x")
        del evt_arr["raw_message"]
        evt_arr["message"] = [{"type": "reply", "data": {"id": "888"}},
                              {"type": "text", "data": {"text": "MMZ这张图"}}]
        ok &= _ck(server.build_ctx(evt_arr, b"{}").get("reply_to") == "888",
                  "段数组形态（type=reply）也认得出来（messagePostFormat=array）")
        asked.clear()
        images.set_quoter(lambda rid: (asked.append(rid) or (True, qmsg(QRAW))))
        try:
            ctx_n = mk("MMZ看看这个")
            ok &= _ck(ctx_n.get("reply_to") is None, "没引用的消息：reply_to 是 None")
            ok &= _ck(images.quoted_refs(ctx_n) == [] and asked == [],
                      "没引用 → **一次都不去问** NapCat（不多事）", str(asked))
        finally:
            images.set_quoter(None)

        # ③ 被引用那条**没图** → 不多事：一张都不挂，也不新增一个字的文本
        asked.clear()
        images.set_quoter(lambda rid: (asked.append(rid) or (True, {
            "message_id": rid, "raw_message": "就是这句话",
            "message": [{"type": "text", "data": {"text": "就是这句话"}}],
            "sender": {"user_id": 10001, "card": "已深度思考20秒"}})))
        try:
            seen.clear()
            ctx_t = server.build_ctx(
                reply_evt("[CQ:reply,id=777][CQ:at,qq=%d] MMZ你看看" % base.self_id()), b"{}")
            rt = agent.handle(ctx_t)
            ok &= _ck(asked == ["777"] and rt is not None,
                      "引用了一条纯文字的老消息：问了，也照常回话", str(asked))
            ok &= _ck(imgs_in(seen.get("payload") or {}) == [],
                      "被引用那条里没图 → **一张都不多挂**")
            bl_t = json.dumps(seen.get("payload") or {}, ensure_ascii=False)
            ok &= _ck("他引用的那条" not in bl_t,
                      "被引用那条里没图 → **那句话一个字都不加**（引用纯文字消息 = 跟以前一样）")
            ok &= _ck(not any(w in bl_t for w in ("引用了", "被引用", "引用里")),
                      "引用这条路上没有别的「引用」那类话")
        finally:
            images.set_quoter(None)

        # ④ 引用里那张图**取不到** → 静默：不崩、不带新文本、也没多一句「没看见」
        bad_quotes = [
            ("get_msg 就没拿到", lambda rid: (False, "retcode")),
            ("拿到了、图取不下来",
             lambda rid: (True, {"message_id": rid,
                                 "raw_message": "看看这张[CQ:image,file=NOPE.png]",
                                 "message": [{"type": "image", "data": {"file": "NOPE.png"}}]})),
        ]
        for why_bad, quoter in bad_quotes:
            images.set_quoter(quoter)
            images.set_puller(lambda n: (False, "retcode"))     # NapCat 那条也挂
            try:
                seen.clear()
                ctx_b = server.build_ctx(
                    reply_evt("[CQ:reply,id=1234][CQ:at,qq=%d] 这张图里是谁" % base.self_id()),
                    b"{}")
                rb = agent.handle(ctx_b)
                ok &= _ck(rb is not None and imgs_in(seen.get("payload") or {}) == [],
                          "引用里的图取不到（%s）→ 静默：不崩、一张也不挂" % why_bad, repr(rb))
                bl_b = json.dumps(seen.get("payload") or {}, ensure_ascii=False)
                ok &= _ck("这条消息带了" not in bl_b and "取不下来" not in bl_b,
                          "引用里的图取不到（%s）→ **没有失败说明**（原来那四种话术一个字不动）" % why_bad)
                ok &= _ck("他引用的那条" not in bl_b,
                          "引用里的图取不到（%s）→ 那句话也不给（她手上没图，就别提）" % why_bad)
            finally:
                images.set_quoter(None)
                images.set_puller(None)

        # 取被引用那条的调用**炸了 / 回来个不是消息的东西** → 一样静默
        images.set_quoter(lambda rid: (_ for _ in ()).throw(RuntimeError("boom")))
        try:
            ok &= _ck(images.quoted_refs(mk("[CQ:reply,id=9] 看看")) == [],
                      "问 NapCat 要那条时炸了 → 静默返回空（不往上抛）")
        finally:
            images.set_quoter(None)
        images.set_quoter(lambda rid: (True, None))
        try:
            ok &= _ck(images.quoted_refs(mk("[CQ:reply,id=9] 看看")) == [],
                      "问 NapCat 要那条、回来的不是一条消息 → 静默返回空")
        finally:
            images.set_quoter(None)

        # ⑤ 上限：一条引用里最多 2 张（防炸）+ 只有图、没话 → 那句话不给
        many = ("[CQ:image,file=A.png,url=https://x/a]"
                "[CQ:image,file=B.png,url=https://x/b]"
                "[CQ:image,file=C.png,url=https://x/c]")
        images.set_quoter(lambda rid: (True, {"message_id": rid, "raw_message": many,
                                              "message": []}))
        images.set_fetcher(lambda u: png)
        try:
            ctx_m = server.build_ctx(reply_evt("[CQ:reply,id=555] 看看"), b"{}")
            ok &= _ck(images.MAX_QUOTED == 2 and images.QUOTE_TEXT_MAX == 100,
                      "上限写死：引用最多 2 张图 / 文字最多 100 字",
                      "%d 张 / %d 字" % (images.MAX_QUOTED, images.QUOTE_TEXT_MAX))
            mparts, mnote = images.load_quoted(ctx_m)
            ok &= _ck(len(images.quoted_refs(ctx_m)) == 2 and len(mparts) == 2,
                      "上限：一条引用里最多取 2 张图（防炸）", "%d 张" % len(mparts))
            ok &= _ck(mnote == "", "被引用那条只有图、没有话 → 图照挂，那句话不给", repr(mnote))
        finally:
            images.set_quoter(None)

        # ⑤a 被引用那条只有**占位**（表情 / 图片）→ 一样不算"有话"，那句话不给
        images.set_quoter(lambda rid: (True, {
            "message_id": rid,
            "raw_message": "[CQ:face,id=1][CQ:image,file=ONLY.png,url=https://x/only]",
            "message": [], "sender": {"user_id": 10001, "card": "已深度思考20秒"}}))
        images.set_fetcher(lambda u: png)
        try:
            oparts, onote = images.load_quoted(
                server.build_ctx(reply_evt("[CQ:reply,id=444] 看"), b"{}"))
            ok &= _ck(len(oparts) == 1 and onote == "",
                      "被引用那条只剩「[表情][图片]」这种占位 → 不算有话，那句话不给", repr(onote))
        finally:
            images.set_quoter(None)

        # ⑤b 被引用那条的文字太长 → 只取前 100 字、末尾加 `…`
        long_txt = "啊" * 130
        images.set_quoter(lambda rid: (True, {
            "message_id": rid, "raw_message": long_txt + "[CQ:image,file=L.png,url=https://x/l]",
            "message": [], "sender": {"user_id": 10001, "card": "已深度思考20秒"}}))
        images.set_fetcher(lambda u: png)
        try:
            _lp, lnote = images.load_quoted(server.build_ctx(reply_evt("[CQ:reply,id=666] 看"), b"{}"))
            ok &= _ck(lnote.endswith("」）") and ("啊" * 100 + "…") in lnote
                      and ("啊" * 101) not in lnote,
                      "被引用那条的文字只取前 100 字、末尾加 `…`", repr(lnote[-14:]))
        finally:
            images.set_quoter(None)

        # ⑥ 他这条自己也有图 + 引用里也有图 → **两张都挂上**（他自己那张在前）
        png_b = png + b"#"                 # 只用来区分是哪一张，不打算真解码
        images.set_quoter(lambda rid: (True, qmsg(QRAW)))
        images.set_fetcher(lambda u: png_b if "quote" in u else png)
        try:
            seen.clear()
            ctx_both = server.build_ctx(
                reply_evt("[CQ:reply,id=1891115291][CQ:at,qq=%d] 这两张"
                          "[CQ:image,file=MINE.png,url=https://x/mine]" % base.self_id()), b"{}")
            rboth = agent.handle(ctx_both)
            bi = imgs_in(seen.get("payload") or {})
            ok &= _ck(rboth is not None and len(bi) == 2 and b64(bi[0]) == png
                      and b64(bi[1]) == png_b,
                      "当前这条的图 + 引用里的图 → **两张都挂上**（他自己那张在前）",
                      "%d 张" % len(bi))
            cb = (((seen.get("payload") or {}).get("messages") or [{}])[-1].get("content")) or []
            ok &= _ck([p.get("type") for p in cb]
                      == ["text", "image_url", "text", "image_url"]
                      and "他引用的那条" in cb[2].get("text", ""),
                      "两拨图都在时：他的话 → 他这张 → 那句话 → 引用那张（那句话紧挨着引用图）",
                      str([p.get("type") for p in cb]))
        finally:
            images.set_quoter(None)
            images.set_fetcher(lambda u: png)

        # ⑦ 没有引用段 → 跟以前**完全一样**（还是纯文本、不冒新话）
        seen.clear()
        r_plain = agent.handle(mk("MMZ你好呀"))
        lp7 = (seen.get("payload") or {}).get("messages") or []
        _lp7_last = (lp7[-1] if lp7 else {})   # ⚠ 2026-11-01：数据目录人设不同时这一轮不发请求 → lp7 是空列表
        ok &= _ck(r_plain is not None
                  and isinstance((_lp7_last or {}).get("content"), str),
                  "没有引用、也没有图 → 最后一条还是**纯文本**（跟以前一模一样）",
                  ("没发请求" if not lp7
                   else str(type((_lp7_last or {}).get("content")).__name__)))
        bl_7 = json.dumps(seen.get("payload") or {}, ensure_ascii=False)
        ok &= _ck(not any(w in bl_7 for w in ("引用了", "被引用", "引用里")),
                  "没有引用段 → 一个字的新文本都没有")

        # 不该搭话的：不花一次模型调用
        seen.clear()
        r2 = agent.handle(mk("今天天气不错"))
        ok &= _ck(r2 is None and "payload" not in seen, "群里闲聊：不回，也不花模型调用")

        # 判活：固定一句、不经过模型
        # ⚠️ 那句台词是**配置值**（`agent.pingReply`），公开模板里留空 = 走兜底的「在呀。」。
        #    所以这里**自己钉一个值**再断言逐字相等 —— 不再依赖某台机器上的私有配置。
        seen.clear()
        _ping_keep = (base.cfg().get("agent") or {}).get("pingReply")
        try:
            base.cfg()["agent"]["pingReply"] = "自检用的那一句"
            r3 = agent.handle(mk("在吗", group=False))
            ok &= _ck(r3 == "自检用的那一句" and "payload" not in seen,
                      "判活：秒回固定那一句（配置里的 pingReply），不经过模型", repr(r3))
        finally:
            base.cfg()["agent"]["pingReply"] = _ping_keep

        # 唤醒到点：话也必须由模型组织（④ 老记录：system + 快照 + 到点那段，⛔ 不带当时对话）
        sent = []
        real_post = im._napcat_post
        im._napcat_post = lambda ep, payload, **kw: (sent.append((ep, payload)) or (True, ""))
        try:
            at2, _h = reminders.parse_when("1分钟后")
            rec2 = reminders.add(("g", 123456789), 123456789, 10001, "张三", "喝水", at2)
            ok &= _ck("hist" not in rec2 and "digest" not in rec2,
                      "④ 老账本记录：没有 hist / digest 两个键（老记录长这样）")
            remembered = memory.render(("g", 123456789))
            seen.clear()
            agent._on_due(rec2)
            body = sent[0][1] if sent else {}
            segs = body.get("message") or []
            ok &= _ck(bool(sent) and sent[0][0] == "send_group_msg", "唤醒到点：发在当初设的地方")
            ok &= _ck(not any(s.get("type") == "at" for s in segs),
                      "唤醒到点：⛔ 不 @ 任何人（用户批的）")
            said = "".join(s["data"].get("text", "") for s in segs if s.get("type") == "text")
            ok &= _ck("该喝水" in said, "唤醒到点那句话是模型给的（不是代码里的现成台词）", repr(said))
            wake = (seen.get("payload") or {}).get("messages") or []
            _wroles = [m.get("role") for m in wake]
            ok &= _ck(_wroles == ["system", "user", "user"],
                      "④ 老记录 → 到点那一轮只有 system + 快照 + 到点那段（不炸、不多一条）",
                      " ".join(_wroles))
            ok &= _ck(bool(wake) and wake[0].get("content") == persona.system_prompt(),
                      "唤醒轮的 system **逐字** = persona.system_prompt()")
            _wake_txt = wake[-1].get("content") if len(wake) > 2 else ""
            ok &= _ck(_wake_txt == ("<system-reminder>\n你被唤醒功能唤醒起来执行任务："
                                    "「喝水」（当前会话）\n</system-reminder>"),
                      "到点那段**逐字**（第 6 条）", repr(_wake_txt))
            _hist_txt = [m.get("content") for m in remembered
                         if isinstance(m.get("content"), str) and m.get("content")]
            ok &= _ck(not any(h in json.dumps(wake, ensure_ascii=False) for h in _hist_txt),
                      "④ 老记录 ⛔ 一条「当时的对话」都不带（当空处理）",
                      "%d 条历史一句都没进" % len(_hist_txt))
            _ = remembered
            # 她说"这一轮算了" = 空文本（`end_turn` 收尾也是这个形状）→ 这次就算了
            sent.clear()
            seen.clear()
            real_rt = llm.run_turn
            llm.run_turn = lambda msgs, ctx, **kw: ("", [], "")
            try:
                agent._on_due(rec2)
            finally:
                llm.run_turn = real_rt
            ok &= _ck(not sent, "唤醒收尾/空文本 → 一个字都不发（唤醒允许不说，不再逼）")

            # ═══ ①~⑥ 唤醒「当时」的现场：那场对话的下一轮（第 43 / 44 条）═══
            print()
            _CUR_SECT[0] = "4.x 唤醒「当时」的现场（第 43 / 44 条）"
            print("=== 4.x 唤醒「当时」的现场（第 43 / 44 条）===")
            _wk = ("g", 515151)
            memory.reset([_wk])
            _wkctx = {"key": _wk, "is_group": True, "group_id": 515151,
                      "user_id": 10001, "who": "张三", "text": "", "raw": "",
                      "images": [], "message_id": None}
            # 8 段（>6）：同一个人不连发，所以一段一条
            for _i in range(1, 5):
                memory.record(_wk, "user", "第%d句：早上好" % _i,
                              qq=10001, name="张三")
                memory.record(_wk, "assistant", "第%d句：早呀" % _i)
            _shot = [m.get("content") for m in memory.render(_wk)
                     if isinstance(m.get("content"), str) and m.get("content")][-6:]
            _r_now = toolkit.call("now", {}, _wkctx)
            _set_res = toolkit.call("wake", {"when": "20分钟后", "note": "睡前那杯水"}, _wkctx)
            _wkrec = [x for x in reminders.pending() if x.get("id") == _set_res.get("编号")]
            _wkrec = _wkrec[0] if _wkrec else {}
            _whist = _wkrec.get("hist") or []
            _wdg = str(_wkrec.get("digest") or "")
            ok &= _ck(_set_res.get("ok") is True and len(_whist) == 6,
                      "① 设唤醒 → 账本里 hist 是最近 6 段（这里本来有 8 段）",
                      "%d 段" % len(_whist))
            ok &= _ck(_whist == _shot,
                      "① hist 就是 memory.render 的最后 6 段（原样「名字: 内容」）",
                      json.dumps(_whist, ensure_ascii=False)[:90])
            ok &= _ck("now" in _wdg, "① digest 里有她这一轮调过的工具名", repr(_wdg)[:90])
            _dl = toolkit._wake_digest({"_tool_log": [
                ("say", {"text": "x"}, "发出去了 群 1"),
                ("wake", {"when": "x"}, "编号 1"),
                ("now", {}, "现在 10:00")]})
            ok &= _ck("say" not in _dl and "wake" not in _dl and "now" in _dl,
                      "① 摘要里 ⛔ 不含 wake / say（说话不算查东西）", _dl)
            # 总长 ≤1500：6 段里 3 段是 700+ 字的长句 → 从最新往回取，最早那段截断
            _wk4 = ("g", 515153)
            memory.reset([_wk4])
            for _i in range(3):
                memory.record(_wk4, "user", "长" * 700 + str(_i),
                              qq=10001, name="张三")
                memory.record(_wk4, "assistant", "短%d" % _i)
            _h4 = toolkit._wake_hist(_wk4)
            _h4tot = sum(len(x) for x in _h4)
            ok &= _ck(len(_h4) <= 6 and _h4tot <= 1500
                      and len(_h4) == 6 and len(_h4[0]) < 704,
                      "① hist 总长 ≤1500 字（从最新往回取，超了截断最早的）",
                      "%d 段 / %d 字 / 最早那段 %d 字" % (len(_h4), _h4tot,
                                                         len(_h4[0]) if _h4 else 0))
            # ⑤ 设完之后新聊的两句
            memory.record(_wk, "user", "设完之后新聊的：这句不许进冻结",
                          qq=10001, name="张三")
            memory.record(_wk, "assistant", "设完之后新聊的：她回的那句也不许进")
            _cap = []
            _real_rt_w = llm.run_turn
            _real_call_w = im._napcat_call
            llm.run_turn = lambda msgs, ctx, **kw: (_cap.append(msgs), ("", [], ""))[1]
            im._napcat_call = lambda ep, payload, **kw: (True, None)
            try:
                _exp_occ = agent._occasion(agent._wake_ctx(_wkrec), "唤醒")
                agent._on_due(_wkrec)
            finally:
                llm.run_turn = _real_rt_w
                im._napcat_call = _real_call_w
            _wm = _cap[0] if _cap else []
            _wr = [m.get("role") for m in _wm]
            _wc = [m.get("content") for m in _wm]
            _wj = json.dumps(_wm, ensure_ascii=False)
            ok &= _ck(len(_wm) > 1 and _wr[0] == "system"
                      and _wr[1] == "user" and _wc[1] == "以下是设这个唤醒之前的对话",
                      "② 第 1 条 system、第 2 条 = 「以下是设这个唤醒之前的对话」（逐字）",
                      "%s ｜ %r" % (" ".join(_wr[:2]), _wc[1] if len(_wc) > 1 else ""))
            ok &= _ck([m.get("content") for m in _wm[2:8]] == _shot and _wr[2:8]
                      == [agent._hist_role(x) for x in _shot],
                      "② 接下来 6 条就是冻结的那 6 段（原样；「名字: 」的是他说的）",
                      json.dumps(_wc[2:8], ensure_ascii=False)[:90])
            ok &= _ck(len(_wm) == 11 and _wr[8] == "user"
                      and _wc[8] == "你当时查到的数据：" + _wdg,
                      "② 第 9 条 = 「你当时查到的数据：…」**逐字**", repr(_wc[8] if len(_wc) > 8 else ""))
            ok &= _ck(len(_wm) == 11 and _wc[9] == _exp_occ
                      and _wc[10] == reminders.wake_note(_wkrec),
                      "② 最后两条 = 快照 + 到点那段（跟原来一个字都不差）",
                      "%d 条消息" % len(_wm))
            ok &= _ck("设完之后新聊的" not in json.dumps(_whist, ensure_ascii=False)
                      and "设完之后新聊的" not in _wj,
                      "⑤ 冻结的对话里**没有**「设完之后」的新消息")
            ok &= _ck(agent.WAKE_HIST_HEAD == "以下是设这个唤醒之前的对话"
                      and agent.WAKE_DIGEST_HEAD == "你当时查到的数据：%s",
                      "⑥ 这两句新文本**逐字**（第 43 / 44 条）")
            # ③ digest 为空（有 hist、这一轮没调工具）→ 那一条 user 消息不出现
            _wk3 = ("g", 515152)
            memory.reset([_wk3])
            memory.record(_wk3, "user", "下午好", qq=10001, name="张三")
            memory.record(_wk3, "assistant", "下午好呀")
            _wkctx3 = {"key": _wk3, "is_group": True, "group_id": 515152,
                       "user_id": 10001, "who": "张三", "text": "", "raw": "",
                       "images": [], "message_id": None}
            _set3 = toolkit.call("wake", {"when": "20分钟后", "note": "没查东西"}, _wkctx3)
            _wkrec3 = [x for x in reminders.pending() if x.get("id") == _set3.get("编号")]
            _wkrec3 = _wkrec3[0] if _wkrec3 else {}
            _cap3 = []
            _real_rt_w3 = llm.run_turn
            _real_call_w3 = im._napcat_call
            llm.run_turn = lambda msgs, ctx, **kw: (_cap3.append(msgs), ("", [], ""))[1]
            im._napcat_call = lambda ep, payload, **kw: (True, None)
            try:
                agent._on_due(_wkrec3)
            finally:
                llm.run_turn = _real_rt_w3
                im._napcat_call = _real_call_w3
            _wm3 = _cap3[0] if _cap3 else []
            _wj3 = json.dumps(_wm3, ensure_ascii=False)
            ok &= _ck("digest" not in _wkrec3 and len(_wkrec3.get("hist") or []) == 2,
                      "③ digest 为空、hist 有 2 段", "%d 段" % len(_wkrec3.get("hist") or []))
            ok &= _ck("你当时查到的数据" not in _wj3
                      and "以下是设这个唤醒之前的对话" in _wj3
                      and [m.get("role") for m in _wm3] == ["system", "user", "user",
                                                            "assistant", "user", "user"],
                      "③ digest 为空 → 那一条 user 消息**不出现**（别的照旧）",
                      " ".join(m.get("role") or "" for m in _wm3))

            # ── 主动插话（say）：发一句，然后接着干活；到顶了发不出去
            sent.clear()
            gctx = mk("MMZ看看这个", uid=10001)          # mk 默认就是群里的 ctx
            memory.record(gctx["key"], "user", gctx["text"], qq=10001, name="张三")
            r1 = toolkit.call("say", {"text": "等下，我查查"}, gctx)
            ok &= _ck(r1.get("ok") and sent and sent[-1][0] == "send_group_msg",
                      "say：能直接往群里插一句（不等这一轮结束）", str(r1.get("发出去了")))
            ok &= _ck("提示" in r1 and "接着办事" in str(r1.get("提示")),
                      "say：工具明说这不是收尾，她可以接着办（那个键叫「提示」）",
                      json.dumps(r1, ensure_ascii=False)[:80])
            ok &= _ck(any(m["role"] == "assistant" and m["content"] == "等下，我查查"
                          for m in memory.render(gctx["key"])),
                      "say：她说出去的话进对话线程（下一轮知道自己说过）")
            r2s = toolkit.call("say", {"text": "私聊你哈", "who": "张三"}, gctx)
            ok &= _ck(r2s.get("ok") and sent[-1][0] == "send_private_msg"
                      and sent[-1][1].get("user_id") == 10001,
                      "say：能指定私聊某个人（按她记得的名字查到 QQ）")
            ok &= _ck(not toolkit.call("say", {"text": "x", "who": "查无此人"}, gctx).get("ok"),
                      "say：查不到的人不乱发")
            for _i in range(20):
                toolkit.call("say", {"text": "第 %d 条" % _i}, gctx)
            over = toolkit.call("say", {"text": "再来一条"}, gctx)
            per_turn = int((base.cfg().get("agent") or {}).get("maxSendsPerTurn") or 10)
            ok &= _ck(not over.get("ok") and "上限" in str(over.get("error")),
                      "say：一轮发到 %d 条就发不出去了（她自己会收尾）" % per_turn,
                      str(over.get("error"))[:46])
            ok &= _ck(per_turn == 10,
                      "say：插话上限 = **10**（2026-10-30 从 15 降下来的，文案不变只改数字）",
                      str(per_turn))
            ok &= _ck("maxSendsPerHour" not in (base.cfg().get("agent") or {}),
                      "每小时那道闸已经按用户要求删掉了（只留每轮 10 条）")
            # say 的 to 填了**群号** → 必须发到那个群（踩过：走成私聊群号，NapCat 报"无法获取用户信息"）
            sent.clear()
            gid_say = int((base.cfg().get("bot") or {}).get("groups", [123456789])[0])
            ctx_g = mk("随便说说", uid=10001)
            ctx_g["group_id"] = gid_say
            r_say = toolkit.call("say", {"text": "在群里说一句", "who": str(gid_say)}, ctx_g)
            ok &= _ck(r_say.get("ok") and sent and sent[-1][0] == "send_group_msg"
                      and sent[-1][1].get("group_id") == gid_say,
                      "say：who 填群号 → 发到群里（不再当成私聊）", str(r_say)[:40])

            # 排查开关：手机上放个 dump-llm.on，就把发给模型的**完整请求**存一份
            open(store.path("dump-llm.on"), "w").close()
            llm.chat([{"role": "user", "content": "dump 测试"}], conn=llm.connection())
            dmp = store.read_json("llm-dump.json") or {}
            ok &= _ck(dmp.get("messages") and dmp["messages"][-1].get("content") == "dump 测试"
                      and dmp.get("model") and dmp.get("url"),
                      "排查开关：dump-llm.on 存在 → 完整请求落到 llm-dump.json")
            store.remove("dump-llm.on")
            store.remove("llm-dump.json")
            llm.chat([{"role": "user", "content": "再问一次"}], conn=llm.connection())
            ok &= _ck(store.read_json("llm-dump.json") is None,
                      "排查开关：文件删掉就不再落盘（不留常驻开销）")

            # ── 播报（电脑给事实 → 她组织那句话）—— 必须在假传输还在的时候测
            sent.clear()
            bcast = {"user_id": 10001,
                     "facts": {"人": "主人", "群": "123456789",
                               "数据": [{"站点": "B 站", "持续时长": "2 分 0 秒", "开始时间": "15:52"},
                                        {"站点": "B 站", "持续时长": "3 分 5 秒", "开始时间": "15:54"}]}}
            out_b = agent.on_api("announce", bcast)
            ok &= _ck(out_b and out_b.get("ok") and sent and sent[-1][0] == "send_private_msg",
                      "播报：电脑递事实 → 她发得出去", str((out_b or {}).get("message"))[:30])
            ok &= _ck("摸上了" in json.dumps(sent[-1][1], ensure_ascii=False),
                      "播报：发出去的是**她组织的话**，不是电脑那份模板")
            # 用户点名的：材料 = 抬头 + 一条记录一行（键名 = 站点/持续时长/开始时间），别的什么都不加
            pl2 = json.dumps(seen.get("payload") or {}, ensure_ascii=False)
            ok &= _ck(all(x in pl2 for x in ("站点", "持续时长", "开始时间", "B 站", "2 分 0 秒", "15:52"))
                      and "摸鱼时间" not in pl2,
                      "播报：材料是一行一条记录（键名 = 站点/持续时长/开始时间）",
                      pl2[pl2.find("下面是"):][:120] if "下面是" in pl2 else pl2[:60])
            # 只看**最后那条指令**（播报这一轮不带 end_turn，也不该有"不想说"的约定）。
            # 注意：这个桩里的 payload 是序列化过的报文（字符串），得先解回来。
            _p = seen.get("payload")
            if isinstance(_p, str):
                try:
                    _p = json.loads(_p)
                except Exception:
                    _p = {}
            _msgs = _p.get("messages") if isinstance(_p, dict) else _p
            last_u = ""
            for _m in reversed(_msgs or []):
                if (isinstance(_m, dict) and _m.get("role") == "user"
                        and isinstance(_m.get("content"), str)):
                    last_u = _m["content"]
                    break
            ok &= _ck("不想说" not in last_u and "end_turn" not in last_u,
                      "播报：指令里**没有**「不想说」/「end_turn」（用户点名的；"
                      "播报这一轮也不给收尾工具）",
                      last_u.split("\n")[-1][:60])
            ok &= _ck("电脑上的 PCStatus 刚拦到" not in pl2 and "不 @" not in pl2,
                      "播报：材料里没有我自己加的句子（只有抬头 + 记录）")
            ok &= _ck("用向其他人通报的方式" in pl2 and "高度概括" in pl2,
                      "播报：指令是用户写的那句（跟大家通报、高度概括）")
            # 2026-09-27 用户改的指令结尾：**两种称呼方式都允许**（他填了真名也想能叫"某人"）
            # ⚠️ 2026-10-04（第四批）：认不出身份时 `who` 保持空 → 走指令里**用户写的原文**
            #    里那个「某人」（载荷里的 `人` 从这一批起**不再被读**，见下面 ⑤）。
            ok &= _ck("你可以选择称呼这个人为某人" in pl2 and "也可以用 某人 这个名字" in pl2,
                      "播报：指令结尾是用户那版（可以叫某人，也可以用真名）")
            seen.clear()
            sent.clear()
            agent.on_api("announce", {"user_id": 10001,
                                      "facts": {"人": "某人", "群": "123456789",
                                                "数据": [{"站点": "B 站", "持续时长": "2 分 0 秒",
                                                          "开始时间": "15:52"}]}})
            pl_who = json.dumps(seen.get("payload") or {}, ensure_ascii=False)
            ok &= _ck("你可以选择称呼这个人为某人" in pl_who
                      and "也可以用 某人 这个名字" in pl_who,
                      "播报：名字就是「某人」时，这句照样在（不再有条件分支）")
            seen["announce_skip"] = True
            sent.clear()
            out_b2 = agent.on_api("announce", bcast)
            ok &= _ck(out_b2 and out_b2.get("ok") is True and not sent,
                      "播报：她不想说就**什么都不发**，而且回 ok:true（别让电脑拿模板补发）",
                      str((out_b2 or {}).get("message"))[:34])
            seen.pop("announce_skip", None)
            sent.clear()
            agent.on_api("announce", dict(bcast, group_id=123456789, mention=10001))
            msg = (sent[-1][1] or {}).get("message") if sent else None
            ok &= _ck(bool(sent) and not (isinstance(msg, dict) and msg.get("at")),
                      "播报：就算电脑传了 mention 也不 @ 人")

            # ⚠️ 2026-10-03（第三批）：电脑的播报载荷**顶层**多了一个 `UTC偏移`（`±HH:mm`、
            #    **不进 `facts`**，见 `规格-多电脑接入.md` §4.1 与 `答复-第三批.md` §6.1）。
            #    这里钉死"多这一个键**一个字都不进材料**"：同一份 facts 跑两遍（带 / 不带），
            #    把发给模型的**最后那条 user 指令**（= 抬头 + 记录 + 指令）抓出来逐字比。
            #    ⚠️ 只比那一条 —— 历史（memory.render）每一轮本来就会变，那不是材料。
            #    ⚠️ **必须待在上面那个 `_napcat_post` 假桩里**（出了这一节就是真发送，
            #       会往 QQ 里真发一条 —— 2026-10-03 踩过，别挪出去）。
            def _announce_last_user(req, ident=None):
                seen.pop("payload", None)
                agent.on_api("announce", req, ident)
                _p = seen.get("payload")
                if isinstance(_p, str):
                    try:
                        _p = json.loads(_p)
                    except Exception:
                        _p = {}
                _msgs = _p.get("messages") if isinstance(_p, dict) else _p
                for _m in reversed(_msgs or []):
                    if (isinstance(_m, dict) and _m.get("role") == "user"
                            and "摸鱼数据" in str(_m.get("content") or "")):
                        return str(_m.get("content") or "")
                return ""

            _mat_no_off = _announce_last_user(dict(bcast))
            _mat_with_off = _announce_last_user(dict(bcast, **{"UTC偏移": "+08:00"}))
            ok &= _ck(bool(sent), "播报：抓材料那两遍走的是**假发送桩**（没往真 QQ 发）")
            ok &= _ck(bool(_mat_no_off) and _mat_no_off == _mat_with_off
                      and "UTC偏移" not in _mat_with_off,
                      "播报：顶层多一个 `UTC偏移` → 给模型的材料**一个字都没变**（facts 是冻结契约）")

            # ── 2026-10-03（互联网改造那一批，契约 **B3 选 (a)**）：按 token 认人之后**覆盖**
            #    `group_id` 和 `facts.人` —— 认得出人就用他那条记录里的 `群` / `名字`（E2）。
            #    ⚠️ 必须待在这个 `_napcat_post` 假桩里（出了这一节就是真往 QQ 发，踩过一次）。
            _uo, _um, _urec = users.add("朋友甲", "10002", "20001", "自检用（稍后撤销）")
            _uident = users.ident_of(_urec)
            ok &= _ck(_uo, "播报覆盖：先发一条用户记录（自检用）", _um)
            sent.clear()
            agent.on_api("announce", dict(bcast, group_id=123456789), _uident)
            ok &= _ck(bool(sent) and sent[-1][0] == "send_group_msg"
                      and sent[-1][1].get("group_id") == 20001,
                      "播报覆盖：收件群按**表里的 `群`** 走（payload 里的 group_id 被忽略）",
                      json.dumps(sent[-1][1], ensure_ascii=False)[:60] if sent else "没发出去")
            _mat_u = _announce_last_user(dict(bcast, group_id=123456789), _uident)
            ok &= _ck("20001" in _mat_u and "朋友甲" in _mat_u,
                      "播报覆盖：材料里的群号与称呼也换成表里的（名字 = users.json 的 `名字`）")
            _mat_plain = _announce_last_user(dict(bcast, group_id=123456789))
            ok &= _ck("123456789" in _mat_plain,
                      "播报覆盖：**认不出人时一切照旧**（还是 payload 里那个群）")
            users.remove(_urec["id"])
            sent.clear()
            agent.on_api("announce", dict(bcast, group_id=123456789), _uident)
            ok &= _ck(bool(sent) and sent[-1][0] == "send_group_msg"
                      and sent[-1][1].get("group_id") == 123456789,
                      "播报覆盖：**撤销之后同一个身份立刻不算数**（回落到 payload 里那个群）",
                      json.dumps(sent[-1][1], ensure_ascii=False)[:60] if sent else "没发出去")

            # ── ⑤ 材料里"谁在摸鱼"那个**值**：走 `who.display_name`（备注 → 称呼 → 昵称 → QQ）──
            #    用户 2026-10-04 拍板：只换"值从哪来"，⛔ 模板/字段名一个字不动。
            #    ⚠️ 必须待在这个 `_napcat_post` 假桩里（出了这一节就是真往 QQ 发）。
            _o5, _m5, _r5 = users.add("", "10005", "", "⑤ 自检用")
            ok &= _ck(_o5, "⑤ 播报「谁」：先发一条**没备注**的记录（自检用）", _m5)
            memory.remember_name("10005", "小五")          # 只有称呼 → 材料里该显示"小五"
            _mat5 = _announce_last_user(dict(bcast, group_id=123456789), users.ident_of(_r5))
            ok &= _ck("小五" in _mat5 and "10005" not in _mat5,
                      "⑤ 播报材料里的「谁」= 解析出来的**显示名**（没备注 → 用她的称呼）")
            _mat5b = _announce_last_user(dict(bcast, group_id=123456789),
                                         {"id": "查无此id", "主人": False, "名字": "", "群": "",
                                          "主人QQ": ""})
            ok &= _ck("某人" in _mat5b and "主人" not in _mat5b,
                      "⑤ 认不出身份（理论上不该发生）→ 名字**保持空**，走指令里用户写的那句"
                      "原有兜底（载荷里的 `人` 已经不再被读；那条兜底分支 2026-10-04 删了）",
                      _mat5b.split("\n")[-1][:60])
            memory.forget_name("10005")
            users.remove(_r5["id"])
        finally:
            im._napcat_post = real_post

        ok &= _ck((agent.on_api("announce", {"facts": {"应用": "B 站"}}) or {}).get("ok") is False,
                  "播报：没给收件人会被拒（不乱发）")

        # ── 战况（pc_status）：**所有人（包括主人）一律走电脑发来的心跳缓存** ──
        #    用户 2026-10-05 拍板：「我的实时就不用了，真的做到所有人都一样」——
        #    于是「空 who = 主人那台 + 局域网直连（实时）」那整条路**没有任何入口**了。
        #    ⛔ 这一段全程离线，而且把直连那两个函数换成**一调就炸**的桩：
        #       任何一条 pc_status 路径只要还碰它们，自检当场就红（也顺便钉住"自检不联网"）。
        #    ⛔ 这里只钉"读谁的缓存"和"回哪一句"——desc / params / 材料一个字都不动。
        real_alive, real_fwd = im.pc_alive, im.forward_to_pc
        c2 = mk("状态", uid=10001)              # 后面几段也用它（说话人 = 10001）

        # ⭐ 2026-10-09「当天的战况永不过期」：正式路径判的是"缓存那条 `日期` == **他那台今天**"，
        #    所以自检里那些**打真 now** 的夹具（`statuscache.record(..., now=time.time()-N)`），
        #    `日期` 必须跟着**今天**走 —— 写死 "10-05" 到了别的日子就变成"跨天"，测的就不是原来那件事了。
        #    ⚠️ 这个 `_his_day()` 是**自检自己独立实现**的（⛔ 不调被测函数），口径照电脑侧
        #       `LogicalDay.Of`（本地时刻 < 日期切换点 → 算前一天）。
        from datetime import timedelta, timezone

        def _his_day(now=None, off=8.0, cut=(4, 0)):
            """他那边"今天"的 `MM-DD`：`off` = 他的 UTC 偏移（`None` = 走生产那条"退回本机本地时刻"）。"""
            _n = time.time() if now is None else float(now)
            if off is None:
                _t = datetime.fromtimestamp(_n)
            else:
                _t = (datetime.fromtimestamp(_n, timezone.utc)
                      + timedelta(hours=off)).replace(tzinfo=None)
            if _t.hour * 60 + _t.minute < cut[0] * 60 + cut[1]:
                _t = _t - timedelta(days=1)
            return _t.strftime("%m-%d")

        _TODAY = _his_day()                          # 夹具里那些"今天"的心跳全用它
        _YDAY = _his_day(time.time() - 86400)        # "昨天"（合并那几条里"不同天"的那一台）

        def _pc_boom(*a, **k):
            raise AssertionError("pc_status 碰了局域网直连 —— 那条路已经没有任何入口了")

        _pc_recs = []
        _PC_FRIEND_QQ, _PC_OWNER_QQ, _PC_STRANGER_QQ = 1700000009, 10001, 1099999999
        try:
            im.pc_alive = _pc_boom
            im.forward_to_pc = _pc_boom

            # ③ 直连那条路**一个调用点都没有**（源码级：AST 里没人调 `_pc_forward`）
            #    ⚠️ 2026-10-31：`pc_status` 搬进了**示例包**
            #       `examples/packages/pc-status/tool.py`（默认不装，自检开头从 zip 装），
            #       所以这里查的是**装上去之后**那个文件（它本人留着不删、一个调用点都没有）。
            import ast as _ast
            _pc_cap = capabilities.get("pc-status")
            ok &= _ck(_pc_cap is not None and not _pc_cap.builtin
                      and os.path.normcase(_pc_cap.dir).startswith(
                          os.path.normcase(capabilities.data_root())),
                      "战况③：`pc_status` 现在是**从 examples 装上去的示例包**"
                      "（默认的 capabilities/ 里没有它）",
                      _pc_cap.dir if _pc_cap else "没找到")
            with open(os.path.join(_pc_cap.dir, "tool.py"), encoding="utf-8") as _tkf:
                _tk_tree = _ast.parse(_tkf.read())
            _fwd_calls = [n for n in _ast.walk(_tk_tree) if isinstance(n, _ast.Call)
                          and getattr(getattr(n, "func", None), "id", "") == "_pc_forward"]
            ok &= _ck(not _fwd_calls,
                      "战况③：`_pc_forward()`（局域网直连）在全文件里**一个调用点都没有**"
                      "（它本人留着不删，但没有任何入口）", "调用点 %d 个" % len(_fwd_calls))

            # ⑦ desc / params 是用户逐字批过的两句 —— 冻在这儿，谁改谁红（机检）
            #    ⚠️ 搬进扩展包后形状从"元组"变成了标准 JSON Schema；**文字一个字没动**。
            _pc_tool = _pc_cap.tools[0]
            _pc_desc_want = "查电脑上今天干了多少活、现在在忙什么"
            _pc_who_want = "他的【消息前缀】；不填=当前说话的人"
            _pc_who = (_pc_tool["params"].get("properties") or {}).get("who") or {}
            ok &= _ck(_pc_tool["name"] == "pc_status" and _pc_tool["desc"] == _pc_desc_want
                      and _pc_who.get("description") == _pc_who_want
                      and _pc_who.get("type") == "string"
                      and (_pc_tool["params"].get("required") or []) == [],
                      "战况⑦：desc / params **逐字未变**（用户批过的那两句，"
                      "`who` 还是可选 string）", repr(_pc_who))

            # 先造两条记录：一个**非主人**（朋友甲）、一个**主人**
            _pc_ok_f, _pc_msg_f, _pc_fr = users.add("战况朋友甲", str(_PC_FRIEND_QQ), "",
                                                    "自检（稍后撤销）")
            _pc_ok_o, _pc_msg_o, _pc_own = users.add("战况主人", str(_PC_OWNER_QQ), "",
                                                     "自检（稍后撤销）", is_owner=True)
            _pc_recs += [_pc_fr, _pc_own]
            ok &= _ck(_pc_ok_f and _pc_ok_o,
                      "战况①：先造两条记录（一个非主人 + 一个主人，自检用）",
                      "%s / %s" % (_pc_msg_f, _pc_msg_o))
            _pc_win = {"工作日": [], "时段": ["00:00-24:00"], "日期切换点": "04:00"}
            _pc_hb = {"action": "status.push", "ok": True, "日期": _TODAY,
                      "摸鱼": "5 分", "现在": "在专注", "时段": _pc_win, "UTC偏移": "+08:00"}
            statuscache.record(dict(_pc_hb, **{"专注": "1 小时", "电脑名": "朋友机"}),
                               _pc_fr["id"], now=time.time() - 23)
            statuscache.record(dict(_pc_hb, **{"专注": "9 小时", "电脑名": "主人机"}),
                               _pc_own["id"], now=time.time() - 12)

            # ① 空 who + 说话人是**非主人** → 读**他自己**那条（不是主人的、也不是"全体最新"）
            _pc_ctx_f = mk("状态", uid=_PC_FRIEND_QQ)
            _pc_rf = toolkit.call("pc_status", {}, _pc_ctx_f)
            _pc_txt_f = json.dumps(_pc_rf, ensure_ascii=False)
            ok &= _ck(_pc_rf.get("ok") and _pc_rf.get("专注") == "1 小时"
                      and _pc_rf.get("数据时间") == "23 秒前",
                      "战况①：空 who + 说话人**不是主人** → 读**他自己**那条缓存"
                      "（`数据时间` 也按他那条算）", _pc_txt_f)
            ok &= _ck("9 小时" not in _pc_txt_f and "主人机" not in _pc_txt_f,
                      "战况①：⛔ 拿不到主人那条（从前空 who 就是答主人那台）", _pc_txt_f)

            # ② 空 who + 说话人**就是主人** → 也读**他自己**那条，**不再走直连**、带 `数据时间`
            _pc_ctx_o = mk("状态", uid=_PC_OWNER_QQ)
            _pc_ro = toolkit.call("pc_status", {}, _pc_ctx_o)
            ok &= _ck(_pc_ro.get("ok") and _pc_ro.get("专注") == "9 小时"
                      and _pc_ro.get("数据时间") == "12 秒前",
                      "战况②：空 who + 说话人是**主人** → 也是**他自己那条缓存**"
                      "（带 `数据时间`；直连那一次调用一次都没发生）",
                      json.dumps(_pc_ro, ensure_ascii=False))

            # ④ 「自己」= **当前说话的人**（和别处工具一个口径；不再指主人）
            ok &= _ck(toolkit.call("pc_status", {"who": "自己"}, _pc_ctx_f).get("专注")
                      == "1 小时",
                      "战况④：who=「自己」→ **说话的人**（朋友甲拿到的是自己那条）")
            ok &= _ck(toolkit.call("pc_status", {"who": "我自己"}, _pc_ctx_o).get("专注")
                      == "9 小时",
                      "战况④：「我自己」也是说话的人（主人问到自己那条）")

            # ⑤ 同一个人两台电脑 → 仍然并成一份（并的那一步在缓存这条路上）
            _pc_ok_f2, _pc_msg_f2, _pc_fr2 = users.add("战况朋友甲第二台", str(_PC_FRIEND_QQ),
                                                       "", "自检（稍后撤销）")
            _pc_recs.append(_pc_fr2)
            ok &= _ck(_pc_ok_f2, "战况⑤：同一个 QQ 再登记**第二台**（同一个人两台电脑）", _pc_msg_f2)
            if _pc_fr2:
                statuscache.record(dict(_pc_hb, **{"专注": "2 小时", "电脑名": "朋友机二"}),
                                   _pc_fr2["id"], now=time.time() - 5)
            _pc_rm = toolkit.call("pc_status", {}, _pc_ctx_f)
            _pc_txt_m = json.dumps(_pc_rm, ensure_ascii=False)
            ok &= _ck(_pc_rm.get("ok") and _pc_rm.get("专注") == "3 小时"
                      and str(_pc_rm.get("数据时间") or "").endswith("秒前"),
                      "战况⑤：那个人**两台电脑** → 还是并成一份"
                      "（1 小时 + 2 小时 = 3 小时），`数据时间` 取心跳最新那条", _pc_txt_m)
            ok &= _ck("朋友机" not in _pc_txt_m and "电脑名" not in _pc_txt_m,
                      "战况⑤：⛔ 材料里不出现电脑名（用户定的：不写哪台）", _pc_txt_m)

            # 认得出人、只是**没有心跳** → 原来那句（⛔ 不是新那句）
            statuscache.drop(_pc_own["id"])
            _pc_rn2 = toolkit.call("pc_status", {}, _pc_ctx_o)
            ok &= _ck(_pc_rn2.get("ok") is False and _pc_rn2.get("电脑不在线") is True
                      and _pc_rn2.get("error")
                      == "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据",
                      "战况：**有记录、没心跳** → 原来那句（用户 2026-10-03 定的）",
                      json.dumps(_pc_rn2, ensure_ascii=False))

            # 说话人**没登记过** → 用户 2026-10-05 逐字定稿的那一句（只有这一档用它）
            _pc_rg = toolkit.call("pc_status", {}, mk("状态", uid=_PC_STRANGER_QQ))
            ok &= _ck(_pc_rg.get("ok") is False
                      and _pc_rg.get("error") == "问话的这个人还没登记过电脑 —— 拿不到数据"
                      and "电脑不在线" not in _pc_rg,
                      "战况：说话人**没登记过** → 用户给的那句话（逐字；形状 = 只有 ok/error）",
                      json.dumps(_pc_rg, ensure_ascii=False))
            ok &= _ck(toolkit.call("pc_status", {"who": "自己"}, mk("状态", uid=_PC_STRANGER_QQ))
                      .get("error") == "问话的这个人还没登记过电脑 —— 拿不到数据",
                      "战况：「自己」也一样 —— 拿不到就是这句话")

            # `who=None`（模型偶尔这么填）→ 当没填 = 当前说话的人
            ok &= _ck(toolkit.call("pc_status", {"who": None}, _pc_ctx_f).get("专注") == "3 小时",
                      "战况：who 给 None（模型偶尔这么填）→ 当没填 = 当前说话的人")
            # `who` 认不出来 → **统一**那两句里的 `_NOBODY`（没编新话）
            _pc_unk = "宇宙无敌查无此人"
            _pc_ru = toolkit.call("pc_status", {"who": _pc_unk}, _pc_ctx_f)
            ok &= _ck(_pc_ru.get("ok") is False and _pc_ru.get("error")
                      == "没找到「%s」这个人 —— 让他起个称呼" % _pc_unk,
                      "战况：who 不认识 → 统一那句（和 _target/_NOBODY 一字不差）",
                      json.dumps(_pc_ru, ensure_ascii=False))
        finally:
            im.pc_alive, im.forward_to_pc = real_alive, real_fwd
            for _pc_r in _pc_recs:
                users.remove(str((_pc_r or {}).get("id") or ""))
            store.remove(statuscache.CACHE_NAME)

        # ── 第三批：电脑的心跳（`status.push`）→ status-cache.json → 战况的备用材料 ──
        #    契约 = PCStatus《给手机那边的规格-多电脑接入.md》§4.1「⭐ 出站心跳 status.push」。
        #    这里钉的是用户 2026-10-03 拍板的那几件：接住（**200、不是 501**）、
        #    落盘（含收到时间 + 上报时段 + 机器可读 时段）、
        #    直连优先、以及那几句**逐字不许动**的材料。
        #    ⭐ 2026-10-09：过期判定改成**只看日期**（`computer_day()`）—— 这一段跟着改。
        from fgbot import statuscache

        def _ts(y, mo, d, h, mi, off=8.0):
            """某个时刻的 epoch —— **按电脑那边的 UTC 偏移**算（默认 +08:00 = 北京）。"""
            return datetime(y, mo, d, h, mi,
                            tzinfo=timezone(timedelta(hours=off))).timestamp()

        _MON = _ts(2026, 9, 28, 10, 0)      # 2026-09-28 **星期一** 10:00（+08:00）
        _HB = {"action": "status.push", "ok": True, "日期": "09-28", "专注": "2 小时 5 分",
               "摸鱼": "25 分", "摸鱼来源": "B 站 20 分 / 小红书 5 分", "现在": "在摸鱼",
               "电脑名": "某台机器", "上报时段": "工作日 09:00-18:00",
               "时段": {"工作日": [1, 2, 3, 4, 5], "时段": ["09:00-18:00"],
                        "日期切换点": "04:00"},
               "UTC偏移": "+08:00"}
        store.remove(statuscache.CACHE_NAME)
        _rec, _why = statuscache.record(_HB, statuscache.cred_id("selftest-一把token"), now=_MON)
        _cache = store.read_json(statuscache.CACHE_NAME) or {}
        _users = _cache.get("用户") or {}
        _key = next(iter(_users), "")
        _blob = json.dumps(_cache, ensure_ascii=False)
        ok &= _ck(_rec and _key.startswith("t-") and _users.get(_key, {}).get("收到") == _MON,
                  "心跳：收到一跳 → 落盘（一人一条最新 + **收到时间**）", "%s ｜ 键 %s" % (_why, _key))
        ok &= _ck("上报时段" in _blob and "日期切换点" in _blob and "UTC偏移" in _blob,
                  "心跳：载荷按他们定稿的形状原样存（上报时段 + 机器可读 时段 + UTC偏移）")
        ok &= _ck("selftest-一把token" not in _blob,
                  "心跳：缓存里**没有 token 明文**（键只是它的指纹）")

        print("    他的上报时段（机器可读那三个子键）：%s"
              % json.dumps(_HB["时段"], ensure_ascii=False))
        _ent = statuscache.latest()
        ok &= _ck(statuscache.within_window(_ent, now=_MON + 3600) is True,
                  "时段：周一 11:00 落在 09:00-18:00 里 → 在时段内")
        ok &= _ck(statuscache.within_window(_ent, now=_ts(2026, 9, 28, 20, 0)) is False,
                  "时段：周一 20:00 → 不在时段里（他下班了）")
        ok &= _ck(statuscache.within_window(_ent, now=_ts(2026, 9, 27, 10, 0)) is False,
                  "时段：周日 10:00 → 不在工作日（1=周一 … 7=周日）")
        ok &= _ck(statuscache.within_window(_ent, now=_ts(2026, 9, 28, 18, 0)) is False,
                  "时段：18:00 整 **不含**（判定是 From <= t < To）")

        # ⭐ 2026-10-09「当天永不过期」：这一档现在只在**跨天**时才出现 ——
        #    缓存那条的 `日期` 是**昨天**（09-27），他那台已经翻到 09-28 了。
        _yent = {"收到": _MON, "载荷": dict(_HB, **{"日期": "09-27"})}
        _out = statuscache.material(_yent, now=_ts(2026, 9, 28, 20, 0))
        ok &= _ck(_out == {"ok": False,
                           "error": "他这会儿不在上报时段（工作日 09:00-18:00）"},
                  "战况（缓存）：**跨天** + 不在他的上报时段 → 那句原话（逐字）",
                  json.dumps(_out, ensure_ascii=False))
        _fr = statuscache.material(_ent, now=_MON + 23)
        ok &= _ck(_fr.get("ok") is True and _fr.get("日期") == "09-28"
                  and _fr.get("专注") == "2 小时 5 分" and _fr.get("摸鱼") == "25 分"
                  and _fr.get("摸鱼来源") == "B 站 20 分 / 小红书 5 分"
                  and _fr.get("现在") == "在摸鱼" and _fr.get("数据时间") == "23 秒前"
                  and len(_fr) == 7,
                  "战况（缓存）：当天 + 新鲜 → 那几个键 + **一个 `数据时间`**",
                  json.dumps(_fr, ensure_ascii=False))
        ok &= _ck(statuscache.material(_ent, now=_MON + 12 * 60).get("数据时间") == "12 分钟前",
                  "战况（缓存）：`数据时间` 的写法（12 分钟前）")
        # ⭐ 当天的数据**永不判过期**：91 分钟前那一跳照旧给数据（`数据时间` 说小时）
        _st = statuscache.material(_ent, now=_MON + 91 * 60)
        ok &= _ck(_st.get("ok") is True and _st.get("专注") == "2 小时 5 分"
                  and _st.get("数据时间") == "1 小时前",
                  "战况（缓存）：当天 + 超 90 分钟 → **照旧给数据**（⭐ 当天永不过期）",
                  json.dumps(_st, ensure_ascii=False))

        # 老的过期线（90 分钟）：`fresh()` **作为独立函数照旧**（用户点名"可以留着"），
        # 但正式路径（`material()`）**再也不走它** —— 正好 90:00 那一秒的行为一个样。
        ok &= _ck(statuscache.fresh(_ent, now=_MON + 5400)
                  and "数据时间" in statuscache.material(_ent, now=_MON + 5400),
                  "过期线（独立函数）：正好 90:00 → 仍算新鲜")
        ok &= _ck(not statuscache.fresh(_ent, now=_MON + 5401)
                  and statuscache.material(_ent, now=_MON + 5401).get("ok") is True,
                  "过期线（独立函数）：90:00 再过 1 秒 → 判过期；但**正式路径照旧给数据**"
                  "（当天永不过期，不再拿这条线当答案）")

        # 跨零点 / 日期切换点（逻辑日的星期几）/ To=24:00 / 空工作日 / 老版本没有 时段
        _e2 = {"收到": _MON, "载荷": dict(_HB, **{
            "时段": {"工作日": [1], "时段": ["22:00-06:00"], "日期切换点": "04:00"}})}
        ok &= _ck(statuscache.within_window(_e2, now=_ts(2026, 9, 29, 2, 0)) is True,
                  "时段：跨零点 22:00-06:00，周二 02:00 → 在时段内；而且 02:00 < 04:00 算**周一**那个逻辑日")
        ok &= _ck(statuscache.within_window(_e2, now=_ts(2026, 9, 29, 7, 0)) is False,
                  "时段：周二 07:00 → 过了 06:00，逻辑日也翻成周二（工作日只有周一）")
        _e3 = {"载荷": dict(_HB, **{"时段": {"工作日": [1, 2, 3, 4, 5],
                                            "时段": ["10:00-24:00"], "日期切换点": "04:00"}})}
        ok &= _ck(statuscache.within_window(_e3, now=_ts(2026, 9, 28, 23, 0)) is True,
                  "时段：To=24:00（他们归一过的写法）= 到当天结束，23:00 算在里面")
        _e4 = {"载荷": dict(_HB, **{"时段": {"工作日": [], "时段": ["00:00-24:00"],
                                            "日期切换点": "04:00"}})}
        ok &= _ck(statuscache.within_window(_e4, now=_MON) is None,
                  "时段：工作日=[]（这台电脑永远不发心跳）→ 判不了时段")
        _e5 = {"载荷": dict(_HB, **{"UTC偏移": "+02:00"})}
        ok &= _ck(statuscache.within_window(_e5, now=_ts(2026, 9, 28, 8, 30, off=2.0)) is False,
                  "时段：**按他电脑的 UTC偏移 换算**（西班牙 +02:00 的 08:30 = 北京 14:30 → 对他不在时段里）")
        ok &= _ck(statuscache.within_window(_e5, now=_ts(2026, 9, 28, 10, 0, off=2.0)) is True,
                  "时段：同一个偏移的正例（他那边 10:00 → 在时段里）")
        _e6 = {"收到": _MON, "载荷": {k: v for k, v in _HB.items() if k != "时段"}}
        ok &= _ck(statuscache.within_window(_e6, now=_MON) is None
                  and statuscache.material(_e6, now=_MON + 23).get("数据时间") == "23 秒前",
                  "时段：老版本电脑没有 `时段` 键 → 不瞎判时段；当天那条照旧给数据（`数据时间` 在）")

        store.remove(statuscache.CACHE_NAME)
        ok &= _ck(statuscache.latest() is None and statuscache.material() is None,
                  "战况（缓存）：一份缓存都没有 → 走原来那三句（不给新话）")

        # ── 战况：**只有心跳缓存这一条路**（当天给数据 / 跨天回那两句）──
        #    ⚠️ 这一段用的是"全天都在时段里"的那一份心跳（`_HB_ALL`）：这里要测的是
        #       **当天那条照旧给数据**，别让"跑自检的这一刻正好不在时段里"把断言带偏
        #       （"跨天 + 不在时段"那一档照旧由上面 `material(ent, now=…)` 直接钉）。
        #    ⚠️ 缓存键 = **说话人那条记录的 id**（不再是 `t-selftest` 那种随手起的键）——
        #       这正是 2026-10-05 改的那件事：空 who 不再等于"全体最新那条"。
        #    ⚠️ 2026-10-09：`日期` 跟着**今天**走（`_TODAY`）—— 打真 now 的夹具只能这样。
        _HB_ALL = dict(_HB, **{"日期": _TODAY, "上报时段": "每天 00:00-24:00",
                               "时段": {"工作日": [1, 2, 3, 4, 5, 6, 7],
                                        "时段": ["00:00-24:00"], "日期切换点": "04:00"}})
        _alive2, _fwd2 = im.pc_alive, im.forward_to_pc
        _cc_ok, _cc_msg, _cc_rec = users.add("战况缓存甲", "10001", "", "自检（稍后撤销）")
        _cc_id = str((_cc_rec or {}).get("id") or "")
        ok &= _ck(_cc_ok and _cc_id,
                  "战况（缓存）：给说话人（QQ 10001）先登记一条（自检用）", _cc_msg)

        def _cc_no_direct(*a, **k):
            raise AssertionError("pc_status 碰了局域网直连 —— 那条路已经没有任何入口了")

        try:
            im.pc_alive = _cc_no_direct
            im.forward_to_pc = _cc_no_direct

            # 一份缓存都没有 → 原来那句（一字未动）
            store.remove(statuscache.CACHE_NAME)
            ok &= _ck(toolkit.call("pc_status", {}, c2).get("error")
                      == "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据",
                      "战况：没有**他**的心跳缓存 → 原来那句（一字未动）")
            # 缓存里**只有别人的**那一跳 → 也得当"没有"（⛔ 绝不许拿"全体最新那条"顶上）
            statuscache.record(_HB_ALL, "t-别人家的键", now=time.time() - 5)
            ok &= _ck(toolkit.call("pc_status", {}, c2).get("error")
                      == "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据",
                      "战况：缓存里**只有别人的**一跳 → 不能拿「全体最新那条」顶上"
                      "（那会答成别人的数据）")
            store.remove(statuscache.CACHE_NAME)

            # 新鲜档：他自己那条
            statuscache.record(_HB_ALL, _cc_id, now=time.time() - 23)
            _cb = toolkit.call("pc_status", {}, c2)
            ok &= _ck(_cb.get("ok") and _cb.get("数据时间") == "23 秒前"
                      and _cb.get("专注") == "2 小时 5 分",
                      "战况：**他自己那条**新鲜 → 用缓存答 + 一个 `数据时间`",
                      json.dumps(_cb, ensure_ascii=False))

            # ⭐ 当天 + 超 90 分钟：**照旧给数据**（"当天的战况永不过期"，用户 2026-10-09 拍板）
            statuscache.record(_HB_ALL, _cc_id, now=time.time() - 91 * 60)
            _st2 = toolkit.call("pc_status", {}, c2)
            ok &= _ck(_st2.get("ok") is True and _st2.get("专注") == "2 小时 5 分"
                      and _st2.get("数据时间") == "1 小时前",
                      "战况：他那条缓存是**当天**的 + 超 90 分钟 → 照旧给数据"
                      "（`数据时间` 说小时；⛔ 那句 90 分钟的死文本不再走）",
                      json.dumps(_st2, ensure_ascii=False))
            # 同一个人的另一台是**昨天**的 → 把他顶下去？不：主那条按**心跳最新**挑，
            # 这里换个日子造一下"跨天"那一档（他那台已经翻篇、缓存还是昨天）
            statuscache.record(dict(_HB_ALL, **{"日期": _YDAY}), _cc_id, now=time.time() - 23)
            _st3 = toolkit.call("pc_status", {}, c2)
            ok &= _ck(_st3.get("ok") is False and _st3.get("电脑不在线") is True
                      and _st3.get("error")
                      == "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据",
                      "战况：缓存那条**跨天**了（他那台翻篇）→ 回现有那句"
                      "（全天时段 → 走「在时段」那一句），⛔ 一个字没改",
                      json.dumps(_st3, ensure_ascii=False))

            # ⛔ `material(who=None)`（"全体最新那条"那个兜底）正式路径上**没有人用**：
            #    抓一次现场，每一次递进来的 `who` 都必须非空。
            _mat_args, _real_material = [], statuscache.material

            def _spy_material(*a, **k):
                _mat_args.append(k.get("who") if "who" in k
                                 else (a[1] if len(a) > 1 else None))
                return _real_material(*a, **k)

            statuscache.material = _spy_material
            try:
                toolkit.call("pc_status", {}, c2)
                toolkit.call("pc_status", {"who": "战况缓存甲"}, c2)
                toolkit.call("pc_status", {}, mk("状态", uid=1099999999))
                toolkit.call("pc_status", {"who": "宇宙无敌查无此人"}, c2)
            finally:
                statuscache.material = _real_material
            ok &= _ck(_mat_args and all(str(x or "").strip() for x in _mat_args),
                      "战况：`statuscache.material()` 每次拿到都是**非空的 who**"
                      "（「全体最新那条」那条兜底，正式路径上一个调用方都没有）",
                      "递进来的 who：%s" % (_mat_args,))
            store.remove(statuscache.CACHE_NAME)
        finally:
            im.pc_alive, im.forward_to_pc = _alive2, _fwd2
            if _cc_rec:
                users.remove(_cc_id)
            store.remove(statuscache.CACHE_NAME)

        # ═══ 5.x ⭐ 2026-10-09「**当天的战况永不过期**」（用户逐条批过的那一件）═══
        #    判"当天"用**他们自己的逻辑日**：载荷里现成的 `日期` + `UTC偏移` +
        #    `时段.日期切换点`（口径 = 电脑侧 `LogicalDay.Of`，`LogicalDay.cs:45-51`）。
        #    缓存那条 `日期` == 他那台的今天 → **一律可用**（哪怕 8 小时前那一跳），
        #    照旧带 `数据时间`；**只有跨天**才回现有那两句（按他此刻在不在时段里选）。
        #    ⛔ 那句「最后心跳是 X 分钟前…」留在代码里当**死文本**（`statuscache.STALE_TEXT`），
        #       正式路径再也不走它；老那条 90 分钟的线（`STALE_SECONDS` / `fresh()`）照旧留着。
        #    全程离线打桩：只递条目进 `material()` / 只碰临时目录，不联网、不发消息。
        print()
        print("    ── ⭐ 当天的战况永不过期（用户 2026-10-09 拍板）──")
        ok &= _ck(statuscache.computer_day(_HB, now=_MON) == "09-28",
                  "当天①：「他那台今天」= 载荷里 `日期` 的写法（北京 +08:00 / 切换点 04:00）",
                  "算出来 = %s" % statuscache.computer_day(_HB, now=_MON))
        # ③ 跨时区：西班牙那台（+02:00）刚到 00:30（= 北京 06:30）→ 他那台还是**28 号**
        _sp_now = _ts(2026, 9, 29, 6, 30)                    # 北京 09-29 06:30 = 他那边 09-29 00:30
        _sp_day = statuscache.computer_day(dict(_HB, **{"UTC偏移": "+02:00"}), now=_sp_now)
        ok &= _ck(_sp_day == "09-28" and _sp_day != "09-29",
                  "当天③：**跨时区按他那台算** —— 他那边 00:30（北京 06:30）+ 切换点 04:00 "
                  "→ 他那个逻辑日是 **28 号**（⛔ 不是北京那个 29 号）", "算出来 = %s" % _sp_day)
        ok &= _ck(statuscache.same_logical_day({"载荷": dict(_HB, **{"日期": "09-28"})}, now=_MON)
                  and not statuscache.same_logical_day({"载荷": dict(_HB, **{"日期": "09-27"})},
                                                       now=_MON)
                  and not statuscache.same_logical_day({"载荷": dict(_HB, **{"日期": ""})}, now=_MON),
                  "当天：`same_logical_day()` 只认「== 他那台今天」（昨天那条 / 没日期那条都不算）")
        ok &= _ck(statuscache.computer_day({k: v for k, v in _HB.items() if k != "UTC偏移"},
                                           now=_MON) == _his_day(_MON, off=None),
                  "当天：老版本没有 `UTC偏移` → 照旧退回**本机本地时刻**（口径没变）")
        # ① 当天 + 6 小时前 → **仍然给数据**，`数据时间` 说 6 小时前
        _d1 = {"收到": _MON, "载荷": dict(_HB, **{"日期": "09-28"})}
        _o1 = statuscache.material(_d1, now=_MON + 6 * 3600)
        ok &= _ck(_o1.get("ok") is True and _o1.get("日期") == "09-28"
                  and _o1.get("专注") == "2 小时 5 分" and _o1.get("数据时间") == "6 小时前",
                  "当天①：**日期 = 他那台今天**、心跳是 6 小时前的 → 照旧给数据 + `数据时间`",
                  json.dumps(_o1, ensure_ascii=False))
        # ② 日期 = 昨天 → 回**现有那两句**（按他此刻在不在时段里选；逐字）
        _dy = {"收到": _MON, "载荷": dict(_HB, **{"日期": "09-27"})}
        ok &= _ck(statuscache.material(_dy, now=_ts(2026, 9, 28, 20, 0))
                  == {"ok": False, "error": "他这会儿不在上报时段（工作日 09:00-18:00）"},
                  "当天②：跨天 + 他这会儿**不在**时段 → 那句原话（逐字）")
        _o2 = statuscache.material(_dy, now=_ts(2026, 9, 28, 12, 0))
        ok &= _ck(_o2 == {"ok": False, "电脑不在线": True,
                          "error": "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据"},
                  "当天②：跨天 + 他这会儿**在**时段 → `电脑没开机（…）`那句原话（逐字）",
                  json.dumps(_o2, ensure_ascii=False))
        _o2b = statuscache.material(
            {"收到": _MON, "载荷": {k: v for k, v in _dy["载荷"].items() if k != "时段"}},
            now=_MON + 6 * 3600)
        ok &= _ck(_o2b.get("error") == "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据",
                  "当天②：跨天 + **判不出在不在时段**（老版本没有 `时段`）→ 还是那句"
                  "（⛔ 不编新话，也不说「他不在时段」）", json.dumps(_o2b, ensure_ascii=False))
        # ⑤ 90 分钟：**独立函数照旧**、那句死文本一个字没删，但正式路径再也不走到它
        _ages = [0, 23, 12 * 60, 90 * 60, 90 * 60 + 1, 6 * 3600, 8 * 3600, 47 * 3600]
        _dead = [a for a in _ages
                 if "最后心跳是" in json.dumps(
                     statuscache.material({"收到": _MON, "载荷": dict(_HB)}, now=_MON + a),
                     ensure_ascii=False)]
        ok &= _ck(not _dead,
                  "当天⑤：**正式路径再也不走到**那句 90 分钟的死文本"
                  "（0 秒 ~ 47 小时全扫一遍）", "走到的：%s" % (_dead or "一个都没有"))
        ok &= _ck(statuscache.fresh({"收到": _MON}, now=_MON + 5400)
                  and not statuscache.fresh({"收到": _MON}, now=_MON + 5401)
                  and statuscache.STALE_SECONDS == 5400,
                  "当天⑤：老那条 90 分钟的线**作为独立函数照旧**"
                  "（正好 90:00 新鲜、90:00 再过 1 秒过期）")
        ok &= _ck(statuscache.stale_text(91 * 60)
                  == "最后心跳是 91 分钟前，已经超过 90 分钟没动静了"
                  and statuscache.STALE_TEXT == "最后心跳是 %d 分钟前，已经超过 %d 分钟没动静了",
                  "当天⑤：那句死文本**一个字没删**（`STALE_TEXT` / `stale_text()` 原样留着）")
        with open(statuscache.__file__, encoding="utf-8") as _scf:
            _sc_src = _scf.read()
        _mat_node = [n for n in _ast.walk(_ast.parse(_sc_src))
                     if isinstance(n, _ast.FunctionDef) and n.name == "material"]
        # 机检口径：`material()` 的**代码里**不许出现那句死文本（常量名引用 / 那句字面量都不许）——
        # 注释和 docstring 里提到它没关系（那是给人看的）。
        _dead_refs = [n for n in _ast.walk(_mat_node[0])
                      if (isinstance(n, _ast.Name) and n.id in ("STALE_TEXT", "stale_text"))
                      or (isinstance(n, _ast.Constant) and isinstance(n.value, str)
                          and "最后心跳是" in n.value)] if _mat_node else ["没找到 material()"]
        ok &= _ck(not _dead_refs,
                  "当天⑤（机检）：`material()` 的**代码里**一个字都没提那句死文本"
                  "（⛔ 不是靠人眼看）", "%d 处引用" % len(_dead_refs))
        # ⑥ 材料 / 字段 / 失败话逐字未变（机检）
        #    ⚠️ 2026-10-31：`pc_status` 搬进了扩展包，那句失败话的引用点跟着搬过去
        #       （`examples/packages/pc-status/tool.py` 的 `_NO_HB`）—— 仍然是**同一个常量**。
        ok &= _ck(statuscache.NO_HEARTBEAT == capabilities.get("pc-status").mod._NO_HB
                  == "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据",
                  "当天⑥：`电脑没开机（…）`那句**逐字未变**，而且两处是**同一个常量**")
        ok &= _ck("他这会儿不在上报时段（%s）" in _sc_src
                  and "他这会儿不在上报时段\"" in _sc_src
                  and 'out["数据时间"] = ago_text(secs)' in _sc_src
                  and '"数据时间"' in _sc_src,
                  "当天⑥：`他这会儿不在上报时段（…）` / `数据时间` 那个键**原样还在**")
        # ④ 新鲜心跳（23 秒前）行为与改动前**逐字一致**（连键的顺序都在内）
        _o4 = statuscache.material({"收到": _MON, "载荷": dict(_HB, **{"日期": "09-28"})},
                                   now=_MON + 23)
        ok &= _ck(json.dumps(_o4, ensure_ascii=False) == json.dumps(
            {"ok": True, "日期": "09-28", "专注": "2 小时 5 分", "摸鱼": "25 分",
             "摸鱼来源": "B 站 20 分 / 小红书 5 分", "现在": "在摸鱼",
             "数据时间": "23 秒前"}, ensure_ascii=False),
                  "当天④：**新鲜心跳**（23 秒前）与改动前**逐字一致**（键序也在内）",
                  json.dumps(_o4, ensure_ascii=False))
        # ⑥ 那句 90 分钟的话**真的还在文件里**（只是没人调它）
        ok &= _ck("最后心跳是 %d 分钟前，已经超过 %d 分钟没动静了" in _sc_src,
                  "当天⑥：那句死文本**还在源文件里**（⛔ 用户点名不许删）")

        # ── A2：`pc_status` 的可选参数 `who`（**让她自己选哪台电脑**，2026-10-03）──
        #    用户定的形状：**不要程序按提问者路由** —— 像查记忆那样由 LLM 填 `who`。
        #    ⚠️ 2026-10-05 起所有人走的都是**心跳缓存**（局域网直连没有入口了）：
        #    · 不填 → 当前说话的人那台（**他自己那条缓存**）；
        #    · 填主人自己 → **也是他自己那条缓存**（不再"走直连"）；
        #    · 填朋友     → 只读**他的**心跳缓存（按 `users.json` 的 id 取，不是"最新那条"）；
        #    · 填不认识的人 → 用**既有**那句「没找到「X」这个人…」，不崩、不编新话。
        #    全部离线打桩：users.json / status-cache.json 都在临时目录里；
        #    直连那两个函数还是一调就炸的桩（顺便再钉一次"这条路没有入口"）。
        _A2_OWNER_QQ, _A2_FRIEND_QQ = 10001, 1700000009
        # ⚠️ 称呼得够短（`memory.clean_name` 那边"超过 8 字像句话"会被拒）—— 自检也一样
        _A2_OWNER_NAME, _A2_FRIEND_NAME = "甲同学", "乙朋友"
        _a2_ok_o, _a2_msg_o, _a2_own = users.add(_A2_OWNER_NAME, str(_A2_OWNER_QQ), "",
                                                 "自检（稍后撤销）", is_owner=True)
        _a2_ok_f, _a2_msg_f, _a2_fr = users.add(_A2_FRIEND_NAME, str(_A2_FRIEND_QQ), "",
                                                "自检（稍后撤销）")
        ok &= _ck(_a2_ok_o and _a2_ok_f, "A2：先发两条用户记录（主人那台 + 朋友那台，自检用）",
                  "%s / %s" % (_a2_msg_o, _a2_msg_f))
        try:
            # 朋友的缓存：键 = 他那个 id
            _a2_hb = dict(_HB_ALL, **{"专注": "朋友 3 小时",
                                      "摸鱼": "0", "现在": "在专注"})
            _a2_alive, _a2_fwd = im.pc_alive, im.forward_to_pc

            def _a2_boom(*a, **k):
                raise AssertionError("pc_status 碰了局域网直连 —— 那条路已经没有任何入口了")

            try:
                im.pc_alive = _a2_boom
                im.forward_to_pc = _a2_boom
                memory.remember_name(str(_A2_OWNER_QQ), _A2_OWNER_NAME)   # 称呼 → 认人那一路
                # 主人那台：**只读他自己那条缓存**（从前这里走的是局域网直连）
                statuscache.record(dict(_a2_hb, **{"专注": "主人 5 小时", "电脑名": "主人机"}),
                                   _a2_own["id"], now=time.time() - 40)
                _a2_own1 = toolkit.call("pc_status", {"who": _A2_OWNER_NAME}, c2)
                ok &= _ck(_a2_own1.get("ok") and _a2_own1.get("专注") == "主人 5 小时"
                          and _a2_own1.get("数据时间") == "40 秒前",
                          "A2：填主人自己那台 → 读**他自己那条缓存**"
                          "（不再走局域网直连；`数据时间` 也在）",
                          json.dumps(_a2_own1, ensure_ascii=False))
                ok &= _ck(toolkit.call("pc_status", {"who": str(_A2_OWNER_QQ)}, c2).get("专注")
                          == "主人 5 小时",
                          "A2：填主人那台的 QQ 号 → 也认（同一条缓存）")
                # 空 who + 说话人就是主人 → 还是**他自己那条**（用户拍板的"所有人都一样"）
                _a2_blank = toolkit.call("pc_status", {}, c2)
                ok &= _ck(_a2_blank.get("ok") and _a2_blank.get("专注") == "主人 5 小时"
                          and _a2_blank.get("数据时间") == "40 秒前",
                          "A2：**空 who** + 说话人是主人 → 他自己那条缓存"
                          "（带 `数据时间`；一次直连都不走）",
                          json.dumps(_a2_blank, ensure_ascii=False))

                # 朋友：新鲜档 + **直连一次都不许走**
                memory.remember_name(str(_A2_FRIEND_QQ), _A2_FRIEND_NAME)   # 称呼 → 认人那一路
                statuscache.record(dict(_a2_hb), _a2_fr["id"], now=time.time() - 23)
                _a2_f1 = toolkit.call("pc_status", {"who": _A2_FRIEND_NAME}, c2)
                ok &= _ck(_a2_f1.get("ok") and _a2_f1.get("专注") == "朋友 3 小时"
                          and _a2_f1.get("数据时间") == "23 秒前",
                          "A2：填朋友 → 读**他那条缓存**（新鲜档 + `数据时间`），一次直连都不走",
                          json.dumps(_a2_f1, ensure_ascii=False))
                ok &= _ck(toolkit.call("pc_status", {"who": str(_A2_FRIEND_QQ)}, c2).get("专注")
                          == "朋友 3 小时",
                          "A2：填朋友的 QQ 号 → 也认（她记不住称呼时给她这条退路）")

                # 跨天那一档（用"只有工作日 09:00-18:00"那份，缓存是**昨天**的、
                # 拿周一 20:00 去判 → 他那台翻篇了 + 这会儿不在时段）
                statuscache.record(dict(_HB, **{"日期": "09-27"}), _a2_fr["id"],
                                   now=_ts(2026, 9, 28, 12, 0))
                _a2_out = statuscache.material(statuscache.latest(_a2_fr["id"]),
                                               now=_ts(2026, 9, 28, 20, 0))
                ok &= _ck(_a2_out == {"ok": False,
                                      "error": "他这会儿不在上报时段（工作日 09:00-18:00）"},
                          "A2：带 who 时那几档照旧 —— **跨天** + 不在他的上报时段 → "
                          "那句原话（逐字）",
                          json.dumps(_a2_out, ensure_ascii=False))
                statuscache.record(dict(_a2_hb), _a2_fr["id"], now=time.time() - 91 * 60)
                _a2_st = toolkit.call("pc_status", {"who": _A2_FRIEND_NAME}, c2)
                ok &= _ck(_a2_st.get("ok") is True and _a2_st.get("专注") == "朋友 3 小时"
                          and _a2_st.get("数据时间") == "1 小时前",
                          "A2：带 who 时那几档照旧 —— **当天** + 超 90 分钟 → 照旧给数据"
                          "（⭐ 当天永不过期；⛔ 那句死文本不再走）",
                          json.dumps(_a2_st, ensure_ascii=False))

                # 他有登记、但一跳心跳都没发过 → 还是原来那句（不给新话）
                statuscache.drop(_a2_fr["id"])
                _a2_none = toolkit.call("pc_status", {"who": _A2_FRIEND_NAME}, c2)
                ok &= _ck(_a2_none.get("ok") is False and _a2_none.get("电脑不在线")
                          and _a2_none.get("error")
                          == "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据",
                          "A2：他有登记但没有任何心跳 → 还是原来那句（行为和现在一模一样）")

                # 不认识的 who：**统一**那句 `_NOBODY`（和 _target 一字不差），**绝不崩**
                _a2_unknown = "宇宙无敌查无此人"
                _a2_r = toolkit.call("pc_status", {"who": _a2_unknown}, c2)
                ok &= _ck(_a2_r.get("ok") is False and _a2_r.get("error")
                          == "没找到「%s」这个人 —— 让他起个称呼" % _a2_unknown,
                          "A2：who 不认识 → 统一那句（`_target()`/`_NOBODY` 同一句），没编新话",
                          json.dumps(_a2_r, ensure_ascii=False))
                # ⚠️ 纯数字的 `who` 走的是既有那条规矩：**当成 QQ 号直接用**（`_target` 里那句
                #    ">=5 位的数字就是 QQ 号"）—— 所以这里不断言具体措辞，只钉"不崩、能给她事实"。
                _a2_num = toolkit.call("pc_status", {"who": "10086"}, c2)
                ok &= _ck(isinstance(_a2_num, dict) and _a2_num.get("ok") is False
                          and "error" in _a2_num,
                          "A2：who 是个没登记过的 QQ 号 → 不崩（按既有规矩当 QQ 号用，回一句事实）",
                          json.dumps(_a2_num, ensure_ascii=False))
                # `who` 给 None（模型偶尔这么填）→ 当没填 = **当前说话的人**（这里正好是主人）
                _a2_wnone = toolkit.call("pc_status", {"who": None}, c2)
                ok &= _ck(_a2_wnone.get("ok") and _a2_wnone.get("专注") == "主人 5 小时",
                          "A2：who 给 None（模型偶尔这么填）→ 当没填 = **当前说话的人**"
                          "（他主人那条缓存；不再走直连）",
                          json.dumps(_a2_wnone, ensure_ascii=False))

                # 缓存按 **id** 分人存：朋友那次查询绝不会读到主人那条
                statuscache.record(dict(_HB_ALL, **{"专注": "主人 1 小时"}), _a2_own["id"],
                                   now=time.time())
                _a2_mix = toolkit.call("pc_status", {"who": _A2_FRIEND_NAME}, c2)
                ok &= _ck(_a2_mix.get("ok") is False or _a2_mix.get("专注") != "主人 1 小时",
                          "A2：两台电脑各存各的 —— 朋友的查询**绝不会**读到主人那条缓存",
                          json.dumps(_a2_mix, ensure_ascii=False))
            finally:
                im.pc_alive, im.forward_to_pc = _a2_alive, _a2_fwd
        finally:
            if _a2_own:
                users.remove(_a2_own["id"])
            if _a2_fr:
                users.remove(_a2_fr["id"])
        store.remove(statuscache.CACHE_NAME)

        # ═══ 6.x 身份 = QQ：称呼 / **本群**名片 / 昵称都只是别名 ════════════════════
        #    用户 2026-10-04 拍板「身份 = QQ」，2026-10-06 又定了两条：
        #      · **备注（面板备注 `名字` / 私有备注 `备注`）完全不参与认人**（只用于面板显示）；
        #      · **群名片按群存**（`memory.json[qq].cards[群号]`），认人只看**当前群**那张；
        #        老的单字段 `card` 从这天起只当**历史残留**（认人/显示都不许读）。
        #    认人 + 显示名的**唯一实现**在 `fgbot/who.py`。这一段把那份契约逐条钉住。
        #    ⚠️ 全程离线：`who` 里唯一会碰网络的那一步（现取昵称）在这里换成假桩。
        from fgbot import who as _who

        _WQ1, _WQ2, _WQ_LEGACY = "3100000011", "3200000022", "30002"
        _GP, _GB = "123456789", "20002"      # 两个群：本群名片各认各的
        _wo1, _wm1, _w1 = users.add("张三备注", _WQ1, "", "记事一")
        _wo2, _wm2, _w2 = users.add("", _WQ2, "")
        ok &= _ck(_wo1 and _wo2, "身份=QQ：QQ **必填**、备注（`名字`）**选填**（留空也发得出码）",
                  "%s ｜ %s" % (_wm1, _wm2))
        ok &= _ck(not users.add("没填QQ", "")[0], "身份=QQ：不给 QQ 号就发不出码（必填项）")
        _pr1 = [r for r in users.panel_rows() if r["id"] == _w2["id"]]
        ok &= _ck(bool(_pr1) and _pr1[0]["显示名"] == _WQ2 and "token" not in _pr1[0],
                  "身份=QQ：面板那份带上算好的 `显示名`（没备注 → 这里落到 QQ 号）")

        # ── ① 称呼 / 本群名片 / 昵称 / QQ 都认到**同一条**；备注那两档**不参与** ──
        memory.remember_name(_WQ1, "张三同志")
        memory.touch(_WQ1, nick="昵称王", card="主群名片", group_id=_GP)
        _hits = {"称呼": _who.resolve("张三同志", {"group_id": _GP}),
                 "本群名片": _who.resolve("主群名片", {"group_id": _GP}),
                 "昵称": _who.resolve("昵称王", {"group_id": _GP}),
                 "QQ": _who.resolve(_WQ1, {"group_id": _GP})}
        ok &= _ck(all((r or {}).get("id") == _w1["id"] for r in _hits.values()),
                  "① 称呼 / **本群**名片 / 昵称 / QQ 号都认到同一条",
                  "、".join("%s→%s" % (k, (v or {}).get("id")) for k, v in _hits.items()))
        _q1 = [_who.qq(w, {"group_id": _GP}) for w in ("张三同志", "主群名片", "昵称王", _WQ1)]
        ok &= _ck(all(q == _WQ1 and (r or {}).get("id") == _w1["id"] for q, r in _q1),
                  "① `who.qq()`（工具认人那条路）这几种写法也认，拿到的 QQ 号也对",
                  "、".join("%s→%s" % (q, (r or {}).get("id")) for q, r in _q1))
        # ⛔ 用户 2026-10-06 拍板：**面板备注 / 私有备注完全不参与匹配**（只用于面板显示）
        ok &= _ck(_who.resolve("张三备注") is None and _who.resolve("记事一") is None
                  and _who.qq("张三备注")[0] == "" and _who.qq("记事一")[0] == "",
                  "① 备注类（面板备注 `名字` / 私有备注 `备注`）**完全不参与认人**",
                  "%r ｜ %r" % (_who.resolve("张三备注"), _who.resolve("记事一")))
        # 没有电脑、只在她记忆里的那种人：**昵称 / 本群名片**也得认得出来
        memory.touch("10006", nick="只有昵称的人", card="只有名片的人", group_id=_GB)
        ok &= _ck(_who.qq("只有昵称的人")[0] == "10006"
                  and _who.qq("只有名片的人", {"group_id": _GB})[0] == "10006",
                  "① 只在她记忆里的人（没登记用户表）按**昵称 / 本群名片**也认得出",
                  "%s / %s" % (_who.qq("只有昵称的人")[0],
                               _who.qq("只有名片的人", {"group_id": _GB})[0]))
        ok &= _ck(_who.qq("只有名片的人")[0] == ""
                  and _who.qq("只有名片的人", {"group_id": _GP})[0] == "",
                  "① 那张名片在**私聊 / 别的群**里认不出（名片只认「本群」那张）",
                  "%s / %s" % (_who.qq("只有名片的人")[0],
                               _who.qq("只有名片的人", {"group_id": _GP})[0]))

        # ── ② 显示名优先级（`who.display_name`）：
        #    面板那一份 = 备注 > 称呼 > 本群名片(声明了群时) > 昵称 > QQ 号 ──
        ok &= _ck(_who.display_name(_w1) == "张三备注", "② 优先级 1/5：有**备注** → 用备注")
        users.update(_w1["id"], name="")
        ok &= _ck(_who.display_name(users.by_id(_w1["id"])) == "张三同志",
                  "② 优先级 2/5：备注清空 → 用她的**称呼**（这就是「留空就显示称呼」）")
        memory.forget_name(_WQ1)
        ok &= _ck(_who.display_name(users.by_id(_w1["id"])) == "昵称王",
                  "② 优先级 3/5：没备注、没称呼 → 用 **QQ 昵称**")
        # ③ 昵称也取不到 → 兜底 QQ 号本身（不许空、不许崩）
        memory.forget_person(_WQ1)
        _dn3 = _who.display_name(users.by_id(_w1["id"]))
        ok &= _ck(_dn3 == _WQ1, "③ 昵称取不到 → 兜底 **QQ 号本身**（不许空、不许崩）", repr(_dn3))
        ok &= _ck(_who.display_name(None) == "" and _who.display_name("") == ""
                  and _who.display_name("abc") == "abc",
                  "③ 边角输入不炸（None / 空串 / 不是数字的词）")
        # ⭐ 回归断言（2026-10-06 用户拍板）：显示名 = 「称呼 → 本群名片 → 昵称 → QQ 号」，
        #    ⛔ 以前那截 `[群名片:X]` / `[qq昵称:X]` **整条去掉了**。
        #    · **不声明群**（面板是跨群的）→ 名片那一档整档不可用（别群那张绝不出现）；
        #    · **声明了群 + 给了当下那张** → 名片就是那一档的取值（没称呼时直接顶上）；
        #    · 老单字段 `card`（历史残留）一个字节都不读。
        memory.touch(_WQ1, "昵称王", "别群的新名片", group_id=_GB)
        legacy_set(_WQ1, "别群的历史残留")
        _dnc = _who.display_name(users.by_id(_w1["id"]))
        ok &= _ck(_dnc == "昵称王" and "别群" not in _dnc,
                  "⭐ 回归：不声明群 → who 显示名**不出现**记忆里那张（别群的）群名片，"
                  "也不出现历史残留的 `card`",
                  "%r（cards=%r ｜ 历史残留 card=%r）"
                  % (_dnc, memory.record_of(_WQ1).get("cards"),
                     memory.record_of(_WQ1).get("card")))
        _dnc2 = _who.display_name(users.by_id(_w1["id"]), card_now="别群的新名片")
        ok &= _ck("别群的新名片" not in _dnc2,
                  "⭐ 回归：不声明 `is_group=True` 时，连显式传进来的名片也不用（面板是**跨群**的）",
                  repr(_dnc2))
        _dnc3 = _who.display_name(users.by_id(_w1["id"]), card_now="本群的名片", is_group=True)
        ok &= _ck(_dnc3 == "本群的名片",
                  "⭐ 回归：没称呼 + **声明了群** + 给了当下那张名片 → 名片顶上"
                  "（第二级降级，⛔ 不再拼 `[群名片:X]`）", repr(_dnc3))
        ok &= _ck("[" not in _dnc3 and "群名片" not in _dnc3,
                  "⭐ 回归：⛔ 方括号那截整条去掉了（前缀/材料两侧都不再有）", repr(_dnc3))
        ok &= _ck(_who.display_name(users.by_id(_w1["id"]), is_group=True,
                                    group_id=_GB) == "别群的新名片",
                  "⭐ 回归：没传 card_now → 退到记忆里**那个群**那张（`group_id=`）")
        ok &= _ck(_who.display_name(users.by_id(_w1["id"]), is_group=True,
                                    group_id=_GP) == "昵称王",
                  "⭐ 回归：**这个群**没名片 → 再退一级到昵称")
        ok &= _ck("别群的历史残留" not in (_dnc + _dnc2 + _dnc3),
                  "⭐ 回归：⛔ 历史残留的单字段 `card` 一个字节都不读")
        memory.remember_name(_WQ1, "张三同志")
        _dnc5 = _who.display_name(users.by_id(_w1["id"]), card_now="本群的名片", is_group=True)
        ok &= _ck(_dnc5 == "张三同志",
                  "⭐ 回归：**有称呼**时只出称呼（名片/昵称都不再拼在后面）", repr(_dnc5))
        memory.forget_person(_WQ1)

        # ── ③′ 现取昵称（面板那条路）：NapCat 那一步换成假桩，仍不联网 ──
        _who.forget_caches()
        _real_stranger = im.stranger_name
        try:
            im.stranger_name = lambda q: ("现取来的昵称" if str(q) == _WQ2 else "")
            ok &= _ck(_who.display_name(users.by_id(_w2["id"]), fetch=True) == "现取来的昵称",
                      "③′ 面板那条路（`fetch=True`）才会**现取一次** QQ 昵称")
            ok &= _ck(_who.display_name(users.by_id(_w2["id"])) == _WQ2,
                      "③′ 不现取的那些调用方（工具材料）拿到的还是 QQ 号 —— 绝不为一个名字等网络")
            im.stranger_name = lambda q: ""
            _who.forget_caches()
            ok &= _ck(_who.display_name(users.by_id(_w2["id"]), fetch=True) == _WQ2,
                      "③′ 昵称**取失败** → 照样兜底 QQ 号（不崩、不留空）")
        finally:
            im.stranger_name = _real_stranger
            _who.forget_caches()

        # ── ④ 同一个 QQ 两条记录（同一个人两台电脑）──
        #    ⚠️ 认人靠**称呼**（备注不再参与），所以这里先把称呼定回来。
        users.update(_w1["id"], name="张三")
        memory.remember_name(_WQ1, "张三同志")
        _wo3, _wm3, _w3 = users.add("张三", _WQ1, "", "第二台")
        ok &= _ck(_wo3, "④ 同一个 QQ **允许两条记录**（同一个人两台电脑）", _wm3)
        _HB  = {"action": "status.push", "ok": True, "日期": _TODAY, "专注": "1 小时",
                "时段": {"工作日": [], "时段": ["00:00-24:00"], "日期切换点": "04:00"},
                "UTC偏移": "+08:00"}
        statuscache.record(dict(_HB, **{"电脑名": "台式机"}), _w1["id"], now=time.time() - 600)
        statuscache.record(dict(_HB, **{"电脑名": "笔记本", "专注": "2 小时"}),
                           _w3["id"], now=time.time() - 10)
        ok &= _ck((_who.resolve("张三同志") or {}).get("id") == _w3["id"],
                  "④ 两条记录 → 取**心跳最新**那条（笔记本那条）")
        ok &= _ck(_who.identify("张三同志")[2] == "",
                  "④ 同一个 QQ 两条记录**不算重名**（原因空 = 认出来了）")
        # ⛔ 2026-10-06（用户拍板）：**电脑名再也不认人** —— 它只写日志。
        #    「张三同志台式机」里那个**称呼**照样命中（同一个 QQ → 还是挑心跳最新那条），
        #    但**光写电脑名**（「台式机」「笔记本」）谁都认不出来。
        ok &= _ck((_who.resolve("张三同志台式机") or {}).get("id") == _w3["id"],
                  "④ 词里带电脑名不影响挑记录（只按**心跳最新**那条）")
        ok &= _ck((_who.resolve("张三同志笔记本") or {}).get("id") == _w3["id"],
                  "④ 带另一个电脑名也一样（电脑名不参与挑）")
        ok &= _ck(_who.resolve("台式机") is None and _who.resolve("笔记本") is None,
                  "⭐ 回归：⛔ **电脑名当名字去认 → 认不出**（「台式机」/「笔记本」都不行）",
                  "%r ｜ %r" % (_who.resolve("台式机"), _who.resolve("笔记本")))
        ok &= _ck(_who.qq("台式机")[0] == "" and _who.identify("笔记本")[2] == "none",
                  "⭐ 回归：⛔ 电脑名不在任何一档里（`_ORDER` = %r，没有 `电脑名`）"
                  % (_who._ORDER,))
        ok &= _ck("电脑名" not in _who.aliases(users.by_id(_w1["id"])),
                  "⭐ 回归：⛔ `who.aliases()` 里也没有 `电脑名` 那一档",
                  json.dumps(_who.aliases(users.by_id(_w1["id"])), ensure_ascii=False))

        # ── ⑥ `who` 用一个**别名**也能查到人（pc_status 那条路；只读心跳缓存，不联网）──
        #    ⚠️ 2026-10-05（用户拍板 1(a)/2(a)/3(a)）：`_w1` 与 `_w3` 是**同一个 QQ 的两条记录**
        #       （同一个人两台电脑）→ 战报要**拼成一份**：专注相加（1 小时 + 2 小时 = 3 小时），
        #       `现在` / `数据时间` 取**心跳最新那条**（笔记本那条）。
        _w6a = toolkit.call("pc_status", {"who": "张三同志"}, c2)
        _w6b = toolkit.call("pc_status", {"who": "张三同志台式机"}, c2)
        ok &= _ck(_w6a.get("ok") and _w6a.get("专注") == "3 小时"
                  and _w6a.get("日期") == _TODAY
                  and str(_w6a.get("数据时间") or "").endswith("秒前"),
                  "⑥ who 填**别名**也能查到人；同一个人两台电脑 → `专注` **相加**"
                  "（1 小时 + 2 小时 = 3 小时），`数据时间` 按**心跳最新那条**算",
                  json.dumps(_w6a, ensure_ascii=False))
        ok &= _ck(_w6b.get("ok") and _w6b.get("专注") == "3 小时",
                  "⑥ 那个词里带**电脑名**也照样查到**这一个人**（同一个 QQ → 还是并成一份）",
                  json.dumps(_w6b, ensure_ascii=False))
        # ⛔ 电脑名单独当 who → 认不出人（pc_status 也一样）
        _w6c = toolkit.call("pc_status", {"who": "台式机"}, c2)
        ok &= _ck(_w6c.get("ok") is False
                  and _w6c.get("error") == "没找到「台式机」这个人 —— 让他起个称呼",
                  "⭐ 回归：`pc_status` 的 who **不再接受电脑名**（认不出 → 统一那句）",
                  json.dumps(_w6c, ensure_ascii=False))

        # ── ⑦ 认不出来 → **统一**那句（逐字，不许编新话）──
        _w7 = "宇宙无敌查无此人"
        _r7 = toolkit.call("pc_status", {"who": _w7}, c2)
        ok &= _ck(_r7.get("ok") is False
                  and _r7.get("error") == "没找到「%s」这个人 —— 让他起个称呼" % _w7,
                  "⑦ 认不出来 → 统一那句原文（逐字相等），没编新话",
                  json.dumps(_r7, ensure_ascii=False))

        # ── ⑧ 老数据兼容：手机上那条 `阿强` / `主人QQ 30002` 的形状 ──
        _wo8, _wm8, _w8 = users.add("阿强", _WQ_LEGACY, "", "")
        ok &= _ck(_wo8 and _who.display_name(users.by_id(_w8["id"])) == "阿强",
                  "⑧ 老数据（`名字` 里已经有值）照旧当**备注**显示：显示名 = 阿强",
                  "%s ｜ %s" % (_wm8, _who.display_name(_w8)))
        ok &= _ck(_who.resolve("阿强") is None,
                  "⑧ 但它**不再参与认人** —— 认不出来（用户 2026-10-06 拍板：备注只用于显示）")
        ok &= _ck(users.update(_w8["id"], name="")[0]
                  and _who.display_name(users.by_id(_w8["id"])) == _WQ_LEGACY,
                  "⑧ 备注**清空**也允许（老记录不会因为这个动作坏掉）")

        # 收尾：这一段自己造的记录都撤掉（不留给后面几节）。
        # ⚠️ **别整个删掉 memory.json / status-cache.json** —— 前面的小节写过东西，
        #    后面还有小节要用（踩过一次：`me_p` 那条因为这里把 memory.json 删了而失败）。
        memory.forget_person("10006")          # 上面那条"只有昵称/名片"的假人
        memory.forget_person(_WQ1)             # 上面临时定回来的那个称呼
        for _r in (_w1, _w2, _w3, _w8):
            users.remove(_r["id"])

        # ═══ 6.y 本群名片 / 重名不猜（用户 2026-10-06 拍板，只做"不进 LLM 文本"的那一半）═══
        #    ① A 群有名片、B 群没有 → 在 A 群按那张名片认得到、在 B 群认不到（**核心回归**）
        #    ② 私聊里**永远**不用任何群名片
        #    ③ 称呼 > 本群名片 > 昵称
        #    ④ 备注（面板备注 / 私有备注）**完全不参与匹配**
        #    ⑤ 同一个 QQ 两条记录（两台电脑）**照旧不算重名**（`pc_status` 也不变）
        #    ⑥ 两个不同 QQ 命中同一档 → **不猜**，回用户逐字定稿那句
        #    ⑦ 历史残留的单字段 `card`：**任何**显示/认人路径都不读
        #    ⑧ `say` 的弱路现在也认得**昵称 / 本群名片**
        #    ⑨ "九处 `who` 说明"里不再列举"这名字是哪一类"（用户 2026-10-06 改的话术）
        _YQ1, _YQ2, _YQ3, _YQ4 = "3300000033", "3400000044", "3500000055", "3600000066"
        _GA, _GB2 = "888000111", "888000222"     # 自检里造的两个群（不是真群号）
        _ya = _yb = _yc = _yd = None
        _AMBIG_DEF = "「%s」重名了，查不到 —— 让他起个称呼"
        try:
            _, _, _ya = users.add("", _YQ1, "")
            _, _, _yb = users.add("", _YQ2, "")
            _, _, _yc = users.add("", _YQ3, "")
            _, _, _yd = users.add("", _YQ4, "")
            _cA = {"group_id": _GA, "user_id": _YQ1, "key": ("g", _GA)}

            # ── ① 名片按群：A 群认得到、B 群 / 私聊认不到 ──
            memory.remember_name(_YQ1, "甲称呼")
            memory.touch(_YQ1, nick="甲昵称", card="甲名片", group_id=_GA)
            ok &= _ck((_who.resolve("甲名片", _cA) or {}).get("id") == _ya["id"],
                      "① 他在 A 群有名片 → **在 A 群**按那张名片认得到",
                      "%r" % ((_who.resolve("甲名片", _cA) or {}).get("id"),))
            ok &= _ck(_who.resolve("甲名片", {"group_id": _GB2}) is None
                      and _who.resolve("甲名片") is None,
                      "① **在 B 群 / 没群号**都认不到那张名片（核心回归：名片按群各一张）",
                      "%r / %r" % (_who.resolve("甲名片", {"group_id": _GB2}), _who.resolve("甲名片")))
            ok &= _ck((_who.resolve("甲称呼", {"group_id": _GB2}) or {}).get("id") == _ya["id"],
                      "① 称呼在**哪个群**都认得出（它不属于某个群）")

            # ── ② 私聊：名片档整档不可用 ──
            ok &= _ck(_who.qq("甲名片", {"is_group": False})[0] == ""
                      and _who.qq("甲名片")[0] == ""
                      and _who.qq("甲名片", {"group_id": ""})[0] == "",
                      "② 私聊里**永远不用**任何群名片（认不出来；名片档整档不可用）",
                      "%r / %r" % (_who.qq("甲名片", {"is_group": False})[0], _who.qq("甲名片")[0]))

            # ── ③ 档位顺序：称呼 > 本群名片 > 昵称 ──
            memory.touch(_YQ2, card="词甲", group_id=_GA)          # 乙：本群名片 = 词甲
            memory.remember_name(_YQ1, "词甲")                     # 甲：称呼   = 词甲
            ok &= _ck((_who.resolve("词甲", _cA) or {}).get("id") == _ya["id"],
                      "③ **称呼**优先于本群名片（同一个词两档都命中 → 认称呼那一档）",
                      "%r" % ((_who.resolve("词甲", _cA) or {}).get("id"),))
            memory.touch(_YQ3, nick="词乙")                        # 丙：昵称     = 词乙
            memory.touch(_YQ4, card="词乙", group_id=_GA)          # 丁：本群名片 = 词乙
            ok &= _ck((_who.resolve("词乙", _cA) or {}).get("id") == _yd["id"],
                      "③ **本群名片**优先于昵称（同一个词两档都命中 → 认名片那一档）",
                      "%r" % ((_who.resolve("词乙", _cA) or {}).get("id"),))

            # ── ④ 备注完全不参与匹配（用户给的那个例子：面板备注写了"张三"）──
            #    ⚠️ 自检里机主自己的称呼本来就叫「张三」→ 先摘掉，不然认到的是他（那是对的，
            #       但不是这条要测的：这条测的是"备注不算别名"）。
            _own_back = memory.name_of("10001")
            memory.forget_name("10001")
            _o9, _m9, _r9 = users.add("张三", "3700000077", "", "张三的台式机")
            try:
                _r9c = {"group_id": _GA, "user_id": _YQ1, "key": ("g", _GA)}
                ok &= _ck(_who.resolve("张三", _r9c) is None and _who.qq("张三", _r9c)[0] == ""
                          and _who.resolve("张三的台式机", _r9c) is None,
                          "④ 面板备注（`名字`=张三）/ 私有备注（`备注`=张三的台式机）"
                          "**完全不参与匹配** —— 认不出",
                          "%r / %r" % (_who.resolve("张三", _r9c), _who.qq("张三", _r9c)[0]))
            finally:
                if _own_back:
                    memory.remember_name("10001", _own_back)
                if _r9:
                    users.remove(_r9["id"])

            # ── ⑤ 同一个 QQ 两条记录 ≠ 重名（pc_status 行为不变）──
            _, _, _y5 = users.add("", _YQ1, "", "第二台")
            _HB2 = {"action": "status.push", "ok": True, "日期": _TODAY, "专注": "1 小时",
                    "时段": {"工作日": [], "时段": ["00:00-24:00"], "日期切换点": "04:00"},
                    "UTC偏移": "+08:00"}
            statuscache.record(dict(_HB2, **{"电脑名": "Y台机"}), _ya["id"], now=time.time() - 600)
            statuscache.record(dict(_HB2, **{"电脑名": "Y本本", "专注": "2 小时"}),
                               _y5["id"], now=time.time() - 10)
            _i5 = _who.identify("词甲", _cA)
            ok &= _ck(_i5[0] == _YQ1 and _i5[1] is not None and _i5[2] == "",
                      "⑤ 同一个 QQ 两条记录（两台电脑）**不算重名** → 照旧 `_pick` 挑一条",
                      "%r" % ((_i5[0], (_i5[1] or {}).get("id"), _i5[2]),))
            _p5 = toolkit.call("pc_status", {"who": "词甲"}, _cA)
            ok &= _ck(_p5.get("ok") and _p5.get("专注") == "3 小时"
                      and str(_p5.get("数据时间") or "").endswith("秒前"),
                      "⑤ `pc_status` 的多台电脑行为不变（专注相加、`数据时间` 取心跳最新那条）",
                      json.dumps(_p5, ensure_ascii=False))

            # ── ⑥ 两个不同 QQ 命中同一档 → 不猜，回**用户逐字定稿**那句 ──
            memory.remember_name(_YQ2, "重名词")
            memory.remember_name(_YQ3, "重名词")
            _i6 = _who.identify("重名词", _cA)
            ok &= _ck((_i6[0], _i6[1], _i6[2]) == ("", None, "ambiguous"),
                      "⑥ 两个不同 QQ 同一称呼 → `ambiguous`（**绝不跨人静默挑**）",
                      "%r" % ((_i6[0], _i6[1], _i6[2]),))
            ok &= _ck(_who.resolve("重名词", _cA) is None and _who.qq("重名词", _cA) == ("", None),
                      "⑥ 老接口 `resolve` / `qq` 也不猜（给 None / 空）")
            ok &= _ck(toolkit._AMBIGUOUS == _AMBIG_DEF,
                      "⑥ 重名那句常量 = 用户定稿的原文（逐字）", repr(toolkit._AMBIGUOUS))
            _want6 = _AMBIG_DEF % "重名词"
            _r6a = toolkit.call("memory", {"text": "不该写进去", "who": "重名词"}, _cA)
            _r6b = toolkit.call("pc_status", {"who": "重名词"}, _cA)
            _r6c = toolkit.call("memory", {"who": "重名词"}, _cA)
            ok &= _ck(_r6a.get("error") == _want6 and _r6b.get("error") == _want6
                      and _r6c.get("error") == _want6,
                      "⑥ 重名 → 三个工具（memory 记 / pc_status / memory 查）都回那一句（逐字相等）",
                      "%r ｜ %r ｜ %r" % (_r6a.get("error"), _r6b.get("error"), _r6c.get("error")))
            ok &= _ck("不该写进去" not in json.dumps(memory.all_people(), ensure_ascii=False),
                      "⑥ 重名时**一个字都没写**（不瞎记到谁名下）",
                      json.dumps(memory.facts_of(_YQ2), ensure_ascii=False)[:40])
            memory.forget_name(_YQ2)
            memory.forget_name(_YQ3)

            # ── ⑦ 历史残留的单字段 `card`：显示/认人都不读 ──
            legacy_set(_YQ1, "★旧字段名片★")
            ok &= _ck(_who.resolve("★旧字段名片★", _cA) is None
                      and _who.qq("★旧字段名片★", _cA)[0] == "",
                      "⑦ 历史残留的 `card` **不再当别名**（认不出来）",
                      "%r" % (_who.resolve("★旧字段名片★", _cA),))
            _dump7 = json.dumps(agent._people(), ensure_ascii=False)
            _row7 = [p for p in memory.all_people() if p["qq"] == _YQ1]
            ok &= _ck("★旧字段名片★" not in _dump7 and "甲名片" in _dump7
                      and _row7 and _row7[0]["card"] == "甲名片（群 %s）" % _GA,
                      "⑦ 面板/App 那份 `card` 只由**按群那张表**拼出来（历史残留一个字都不读）",
                      "%r" % (_row7[0]["card"] if _row7 else None,))
            ok &= _ck("★旧字段名片★" not in _who.display_name(users.by_id(_ya["id"]))
                      and "★旧字段名片★" not in memory.display_name(_YQ1, True, card_now="")
                      and "★旧字段名片★" not in memory.display_name(_YQ1, False)
                      and "★旧字段名片★" not in str(_who.aliases(users.by_id(_ya["id"]), _GA)),
                      "⑦ 显示名（who / 消息前缀）与别名字典都不读它",
                      "%r" % (_who.display_name(users.by_id(_ya["id"])),))

            # ── ⑧ `say` 的弱路也认得昵称 / 本群名片 ──
            _sent_p = []
            _real_send_p = im.send_private
            im.send_private = lambda uid, text, **kw: (_sent_p.append((uid, text)) or True)
            try:
                _s8a = toolkit.call("say", {"text": "自检", "who": "甲昵称"}, _cA)
                ok &= _ck(_s8a.get("ok") and _sent_p and _sent_p[-1][0] == int(_YQ1),
                          "⑧ `say` 的弱路认得**昵称**（以前只认称呼/记忆内容）",
                          "%r ｜ %r" % (_s8a, _sent_p[-1:]))
                _sent_p[:] = []
                _s8b = toolkit.call("say", {"text": "自检", "who": "甲名片"}, _cA)
                ok &= _ck(_s8b.get("ok") and _sent_p and _sent_p[-1][0] == int(_YQ1),
                          "⑧ `say` 的弱路认得**本群名片**", "%r ｜ %r" % (_s8b, _sent_p[-1:]))
                _sent_p[:] = []
                _cB2 = {"group_id": _GB2, "user_id": _YQ1, "key": ("g", _GB2)}
                _s8c = toolkit.call("say", {"text": "自检", "who": "甲名片"}, _cB2)
                ok &= _ck(_s8c.get("ok") is False and not _sent_p
                          and _s8c.get("error") == "没找到「甲名片」这个人 —— 让他起个称呼",
                          "⑧ 别的群里那张名片不认 → **一个字都不发**，失败话=统一那句 `_NOBODY`",
                          "%r" % (_s8c.get("error"),))
            finally:
                im.send_private = _real_send_p

            # ── ⑨ 各工具的 `who` 说明：不再列举"这名字是哪一类" ──
            #    ⚠️ A3 合并之后带 who 的工具是这 7 个（memory / user_info / callname /
            #       history / pc_status / send_private / say；`wake` 那个参数叫 where）。
            #       `memory` / `history` 现在写【消息前缀】（第 1 / 9 条批的新字）。
            #    ⚠️ 2026-10-31：`pc_status` 搬进了示例包（`examples/packages/pc-status`），
            #       它的 `who` 说明照样算在这七处里（文字一个字没动）。
            _who_descs = [t["params"]["who"][1] for t in toolkit.TOOLS
                          if "who" in (t.get("params") or {})]
            _who_descs += [((t["params"].get("properties") or {}).get("who") or {}).get("description")
                           for t in capabilities.get("pc-status").tools]
            ok &= _ck(len(_who_descs) == 7
                      and not any(k in d for d in _who_descs for k in ("群名片", "昵称", "QQ 号")),
                      "⑨ 七处 `who` 参数说明里不再列举类别（只留【称呼】/【消息前缀】；⛔ 别的一句没动）",
                      " ｜ ".join(_who_descs))
        finally:
            for _q in (_YQ1, _YQ2, _YQ3, _YQ4):
                memory.forget_person(_q)
            for _r in (_ya, _yb, _yc, _yd):
                if _r:
                    users.remove(_r["id"])

        # ═══ 6.y2 2026-10-06 用户批准的那一批 ═══════════════════════════════════
        #    A 的七条文本（逐字）/ 新工具 `user_info`（四种返回 + fields 各种写法）/
        #    显示四级降级（前缀 / 历史行 / 被引用那条 / 播报材料）/ `strip_echo` 新格式 /
        #    `say` 用统一那两句 / **电脑名整条链路清干净**。
        #    ⚠️ 全程离线：唯一会碰网络的现取昵称那一步，这里记忆里都已经有昵称了。
        print()
        _CUR_SECT[0] = "6.y2 本轮批准的那批（改名 / user_info / 显示规则 / 电脑名清理）"
        print("=== 6.y2 本轮批准的那批（改名 / user_info / 显示规则 / 电脑名清理）===")
        import inspect

        _win_all = {"工作日": [], "时段": ["00:00-24:00"], "日期切换点": "04:00"}
        _tmap = {t["name"]: t for t in toolkit.TOOLS}

        # ── A① 两个常量 + 改名（逐字）──
        ok &= _ck(toolkit._NOBODY == "没找到「%s」这个人 —— 让他起个称呼",
                  "A1 `_NOBODY` **逐字**（用户定稿）", repr(toolkit._NOBODY))
        ok &= _ck(toolkit._AMBIGUOUS == "「%s」重名了，查不到 —— 让他起个称呼",
                  "A2 `_AMBIGUOUS` **一字未动**（逐字）", repr(toolkit._AMBIGUOUS))
        ok &= _ck("recall" not in _tmap and "memory" in _tmap,
                  "A4 工具改名：`recall` → `memory`（旧名没了）", "、".join(sorted(_tmap)))
        ok &= _ck(list(_tmap["memory"]["params"].keys()) == ["who", "ask", "text"],
                  "A4/B5 参数：`who` / `ask` / `text`（⛔ 没有 action、没有 old/new）",
                  str(list(_tmap["memory"]["params"].keys())))
        ok &= _ck(_tmap["memory"]["desc"] == "查或记某个人的记忆（住哪、性别、生日、口味、身份、喜好等）",
                  "B5 `memory` 的说明**逐字**（新字清单第 1 条）",
                  _tmap["memory"]["desc"])
        ok &= _ck(_tmap["memory"]["params"]["who"][1] == "【消息前缀】或「自己」；留空=当前说话的人",
                  "B5 `who` 的说明**逐字**", _tmap["memory"]["params"]["who"][1])
        ok &= _ck(_tmap["memory"]["params"]["ask"][1]
                  == "查什么；留空=全部",
                  "B5 `ask` 的说明**逐字**", _tmap["memory"]["params"]["ask"][1])
        ok &= _ck(_tmap["memory"]["params"]["text"][1]
                  == "要记或要改的一条事实",
                  "B5 `text` 的说明**逐字**", _tmap["memory"]["params"]["text"][1])
        ok &= _ck(_tmap["weather"]["desc"] == "查某个城市的天气。",
                  "A5 天气说明**逐字**", _tmap["weather"]["desc"])

        # ── A③ / B⑧ 新工具 `user_info`：说明 + 两个参数（逐字）──
        ok &= _ck(_tmap["user_info"]["desc"] == "查用户的资料：QQ 号、称呼、QQ 昵称、本群名片。",
                  "A3 `user_info` 说明**逐字**")
        ok &= _ck(_tmap["user_info"]["params"]["who"][1] == "【消息前缀】；留空=当前说话的人"
                  and _tmap["user_info"]["params"]["fields"][1] == "想知道的项，留空=全给",
                  "A3 `user_info` 两个参数说明**逐字**",
                  "%r ｜ %r" % (_tmap["user_info"]["params"]["who"][1],
                                _tmap["user_info"]["params"]["fields"][1]))
        ok &= _ck(set(_tmap) == {"now", "memory", "user_info", "callname", "wake", "plan",
                                 "history", "weather", "search", "read_url",
                                 "send_private", "say", "skill"},
                  "B5 工具表 = 合并后的 13 个定义（remember / fix_memory / call_me / "
                  "forget_call_name / remind / reminders 都没了；`pc_status` 搬去了扩展包、"
                  "多了 `skill`）", "、".join(sorted(_tmap)))
        # ⚠️ 2026-10-31：`end_turn` 是**条件出现**的；`pc_status` 搬成了扩展包
        #    （解锁之后才会出现在请求里）。常态目录 = `TOOLS`（11 个内置 + `skill`）。
        ok &= _ck(set(toolkit.names()) == set(_tmap)
                  and len(toolkit.names()) == 13,
                  "B5 常态工具目录 = 13 个（12 个内置 + skill；pc_status 要先读技能才解锁）",
                  "、".join(toolkit.names()))
        # ── B5 新 / 合并工具的说明（逐字，新字清单第 4/5/9/10 条）──
        ok &= _ck(_tmap["callname"]["desc"]
                  == "给某个人定【称呼】",
                  "B5 `callname` 说明**逐字**", _tmap["callname"]["desc"][:30])
        ok &= _ck(_tmap["callname"]["params"]["who"][1] == "【消息前缀】；留空=当前说话的人"
                  and _tmap["callname"]["params"]["name"][1]
                  == "他要你怎么叫他（新的【称呼】）；留空=取消，回到他的群名片/昵称",
                  "B5 `callname` 两个参数**逐字**")
        ok &= _ck(list(_tmap["wake"]["params"].keys())
                  == ["action", "when", "note", "where", "id"],
                  "B5 `wake` 参数 = action / when / note / where / id",
                  str(list(_tmap["wake"]["params"].keys())))
        ok &= _ck(_tmap["wake"]["desc"] == "给自己设一个唤醒：到点你会被叫醒执行任务",
                  "B5 `wake` 说明**逐字**", _tmap["wake"]["desc"])
        ok &= _ck(_tmap["wake"]["params"]["action"][1]
                  == "留空=定新的；列=看现有的；取消=撤一条"
                  and _tmap["wake"]["params"]["note"][1]
                  == "醒来时给自己看的说明：为什么醒、做什么"
                  and _tmap["wake"]["params"]["where"][1]
                  == "醒来在哪儿说话：留空=当前会话；填某人的【消息前缀】=私聊他"
                  and _tmap["wake"]["params"]["id"][1] == "要撤的那一条：编号或关键词",
                  "B5 `wake` 的 action/note/where/id 说明**逐字**")
        ok &= _ck(_tmap["history"]["desc"] == "回看你上下文里没有的更早发言",
                  "B5 `history` 说明**逐字**", _tmap["history"]["desc"])
        ok &= _ck(list(_tmap["history"]["params"].keys())
                  == ["count", "who", "q", "after", "before"],
                  "B5 `history` 参数 = count / who / q / after / before")
        ok &= _ck(_tmap["plan"]["desc"]
                  == "多步任务先建一份计划（目标 + 步骤表）；一步能办完的不用。",
                  "B5 `plan` 说明**逐字**（2026-10-30 修订）", _tmap["plan"]["desc"])
        ok &= _ck(_tmap["plan"]["params"]["objective"][1] == "这次要办成什么，一句话（可选）"
                  and _tmap["plan"]["params"]["steps"][1]
                  == "每步一条带状态（未开始/进行中/已完成）；整张替换，最多一个进行中",
                  "B5 `plan` 两个参数**逐字**")
        _psteps = toolkit.schemas()
        _ps = [x for x in _psteps if x["function"]["name"] == "plan"][0]["function"]["parameters"]
        ok &= _ck(_ps["properties"]["steps"].get("items", {}).get("type") == "object"
                  and "进行中" in json.dumps(_ps, ensure_ascii=False),
                  "B5 `plan.steps` 的 schema 带 items / 三个状态（不然模型写不对形状）")

        # ── 6.y2.9 术语统一（2026-10-30 定稿）：13 条最终文本逐字都在 ──
        #    只核对「最终文本」在不在；改了哪几个字由上面的逐条断言分别钉。
        #    ⚠️ 2026-10-31：②③ 那两条是 `pc_status` 的文本 —— 它搬进扩展包了，
        #       所以从扩展包的工具定义里取（字**一个字没动**）。
        from fgbot import keeper as _k13
        _pc13 = capabilities.get("pc-status").tools[0]
        _term13 = (
            ("① user_info.who", _tmap["user_info"]["params"]["who"][1]
             == "【消息前缀】；留空=当前说话的人"),
            ("② pc_status.who",
             (_pc13["params"].get("properties") or {}).get("who", {}).get("description")
             == "他的【消息前缀】；不填=当前说话的人"),
            ("③ pc_status.desc",
             _pc13["desc"] == "查电脑上今天干了多少活、现在在忙什么"),
            ("④ send_private.who", _tmap["send_private"]["params"]["who"][1]
             == "发给谁：【消息前缀】；留空=当前说话的人"),
            ("⑤ say.who", _tmap["say"]["params"]["who"][1]
             == "发给谁：【消息前缀】就是私聊他；留空=发在当前会话里"),
            ("⑥ callname.who", _tmap["callname"]["params"]["who"][1]
             == "【消息前缀】；留空=当前说话的人"),
            ("⑦ memory.desc", _tmap["memory"]["desc"]
             == "查或记某个人的记忆（住哪、性别、生日、口味、身份、喜好等）"),
            ("⑧ memory.text",
             _tmap["memory"]["params"]["text"][1] == "要记或要改的一条事实"),
            ("⑨ guards 记忆", any("他的记忆里什么都没写" in _c[3] for _c in guards._CLAIMS)),
            ("⑩ keeper 正文①",
             _k13.KEEPER_BODY.startswith("这是一个人的记忆，一行一条，行首的数字是编号：\n\n")),
            ("⑪ keeper 正文②", "就把那几条的编号写进「删」" in _k13.KEEPER_BODY),
            ("⑫ plan.desc", _tmap["plan"]["desc"]
             == "多步任务先建一份计划（目标 + 步骤表）；一步能办完的不用。"),
            ("⑬ guards 唤醒",
             any("你像在答应唤醒，但这一轮没调 wake。" in _c[3]
                 for _c in guards._CLAIMS)),
        )
        _term_bad = [n for n, hit in _term13 if not hit]
        ok &= _ck(not _term_bad,
                  "术语统一（2026-10-30 定稿）：13 条最终文本**逐字**都在",
                  ("不对：%s" % "、".join(_term_bad)) if _term_bad else "13/13")

        # ── A⑥ 天气取不到城市时的失败话（逐字）──
        _wr = toolkit.call("weather", {}, mk("MMZ"))
        ok &= _ck(_wr == {"ok": False,
                          "error": "没说哪个城市。要是他以前说过自己住哪，先查一下他的记忆。"},
                  "A6 天气没给城市 → 失败话**逐字**", json.dumps(_wr, ensure_ascii=False))

        # ── A⑦ `say` 自己那句删掉了（源码里一个字都不该剩）──
        _say_src = inspect.getsource(toolkit.t_say)
        ok &= _ck("不知道「" not in _say_src and "先 recall 一下" not in _say_src
                  and "to 留空" not in _say_src,
                  "A7 `say` 那句「不知道「%s」的 QQ 号 —— …（to 留空就行）」**整句删掉了**")

        # ── B⑧ `user_info` 四种返回（逐字）+ `fields` 各种写法 ──
        _UQQ, _UQQ2, _UG = "30001", "30002", "20002"
        memory.remember_name(_UQQ, "李四")
        memory.touch(_UQQ, nick="華仙", card="阿猫", group_id=_UG)
        memory.remember_name(_UQQ2, "王五")
        memory.touch(_UQQ2, nick="是阿强呀")
        _cg = {"group_id": _UG, "user_id": int(_UQQ), "is_group": True, "key": ("g", _UG)}
        _cp = {"user_id": int(_UQQ), "key": ("p", int(_UQQ))}
        ok &= _ck(toolkit.call("user_info", {}, _cg)
                  == {"ok": True, "QQ": _UQQ, "称呼": "李四",
                      "QQ昵称": "華仙", "本群名片": "阿猫"},
                  "B8 ① 群里·fields 留空 —— **逐字**",
                  json.dumps(toolkit.call("user_info", {}, _cg), ensure_ascii=False))
        ok &= _ck(toolkit.call("user_info", {"fields": "昵称"}, _cg)
                  == {"ok": True, "QQ": _UQQ, "QQ昵称": "華仙"},
                  "B8 ② 群里·fields=「昵称」 —— **逐字**",
                  json.dumps(toolkit.call("user_info", {"fields": "昵称"}, _cg),
                             ensure_ascii=False))
        ok &= _ck(toolkit.call("user_info", {}, _cp)
                  == {"ok": True, "QQ": _UQQ, "称呼": "李四", "QQ昵称": "華仙"},
                  "B8 ③ 私聊·留空 —— **逐字**（⛔ 永远没有 `本群名片`）",
                  json.dumps(toolkit.call("user_info", {}, _cp), ensure_ascii=False))
        ok &= _ck(toolkit.call("user_info", {"who": "王五"}, _cp)
                  == {"ok": True, "QQ": _UQQ2, "称呼": "王五", "QQ昵称": "是阿强呀"},
                  "B8 ④ 私聊查别人 —— **逐字**",
                  json.dumps(toolkit.call("user_info", {"who": "王五"}, _cp), ensure_ascii=False))
        # fields 宽松认"包含"；认不出的项忽略；填了就只给那几项 + `QQ`
        for _f, _want in (("称呼", {"ok": True, "QQ": _UQQ, "称呼": "李四"}),
                          ("QQ", {"ok": True, "QQ": _UQQ}),
                          ("号", {"ok": True, "QQ": _UQQ}),
                          ("QQ号", {"ok": True, "QQ": _UQQ}),
                          ("昵称", {"ok": True, "QQ": _UQQ, "QQ昵称": "華仙"}),
                          ("名片", {"ok": True, "QQ": _UQQ, "本群名片": "阿猫"}),
                          ("群名片", {"ok": True, "QQ": _UQQ, "本群名片": "阿猫"}),
                          ("称呼 昵称", {"ok": True, "QQ": _UQQ, "称呼": "李四",
                                         "QQ昵称": "華仙"}),
                          ("瞎写的项", {"ok": True, "QQ": _UQQ})):
            _got = toolkit.call("user_info", {"fields": _f}, _cg)
            ok &= _ck(_got == _want, "B8 `fields`=%r → 只给那几项 + `QQ`" % _f,
                      json.dumps(_got, ensure_ascii=False))
        # 认人撞名 / 没找到 → 统一那两句
        ok &= _ck(toolkit.call("user_info", {"who": "查无此人甲乙"}, _cg).get("error")
                  == "没找到「查无此人甲乙」这个人 —— 让他起个称呼",
                  "B8 `user_info` 认不出 → `_NOBODY`")
        # ⛔ 没有"设备/电脑"这一项
        ok &= _ck(all(k not in json.dumps(toolkit.call("user_info", {}, _cg), ensure_ascii=False)
                      for k in ("电脑名", "设备")),
                  "B8 ⛔ `user_info` 里**没有**「设备/电脑」这一项")
        # 徽：私聊里 `fields` 要名片也给不出来（本来就没有）
        ok &= _ck(toolkit.call("user_info", {"fields": "名片"}, _cp)
                  == {"ok": True, "QQ": _UQQ},
                  "B8 私聊里就算 `fields`=「名片」也给不出来（私聊没有本群）")

        # ── B⑩ 显示四级降级：前缀 / 历史行 / 被引用那条 / 播报材料 ──
        #    群聊：称呼 → 本群名片 → 昵称 → QQ 号；私聊：称呼 → 昵称 → QQ 号
        memory.forget_name(_UQQ)
        ok &= _ck(memory.display_name(_UQQ, True, card_now="新增名片", group_id=_UG) == "新增名片",
                  "B10 群聊第 2 级：没称呼 → **本群名片**")
        _hk = ("g", _UG)
        memory.reset([_hk])
        memory.record(_hk, "user", "在吗", qq=_UQQ, name="")
        _hl = memory.render(_hk)
        ok &= _ck(bool(_hl) and _hl[0]["content"].startswith("阿猫: "),
                  "B10 **历史行**也按所在群的名片（前缀 = `名字: `）",
                  json.dumps(_hl, ensure_ascii=False)[:120])
        ok &= _ck("[" not in _hl[0]["content"] and "群名片" not in _hl[0]["content"],
                  "B10 历史行里⛔ 方括号那截没了")
        memory.remember_name(_UQQ, "李四")
        _hl2 = memory.render(_hk)
        ok &= _ck(_hl2[0]["content"].startswith("李四: "),
                  "B10 历史行：有称呼就用称呼", _hl2[0]["content"][:40])
        ok &= _ck(memory.display_name(_UQQ, True, group_id=_UG) == "李四",
                  "B10 群聊第 1 级：称呼压过名片/昵称")
        memory.forget_name(_UQQ)
        ok &= _ck(memory.display_name(_UQQ, True) == "華仙",
                  "B10 群聊第 3 级：没称呼、没本群名片（没给群号）→ **昵称**")
        memory.forget_person(_UQQ)
        ok &= _ck(memory.display_name(_UQQ, True) == _UQQ
                  and memory.display_name(_UQQ, False) == _UQQ,
                  "B10 第 4 级：只剩 **QQ 号**（不许空）")
        # 私聊链路：称呼 → 昵称 → QQ 号（⛔ 没有名片那一档）
        memory.touch(_UQQ, nick="華仙", card="阿猫", group_id=_UG)
        ok &= _ck(memory.display_name(_UQQ, False) == "華仙"
                  and memory.display_name(_UQQ, False, card_now="阿猫") == "華仙",
                  "B10 私聊：名片**永远不出现**（哪怕显式传进来）")
        memory.remember_name(_UQQ, "李四")
        # 被引用那条：跟前缀同一套
        _qm = {"sender": {"user_id": _UQQ, "card": "被引用的名片", "nickname": "被引用的昵称"}}
        ok &= _ck(images._who_of_msg(_qm, _cg) == "李四",
                  "B10 被引用那条：**跟前缀同一套**（有称呼 → 称呼）",
                  images._who_of_msg(_qm, _cg))
        ok &= _ck("[" not in images._who_of_msg(_qm, _cg),
                  "B10 被引用那条里⛔ 方括号那截没了")
        # 播报材料：按"所在群"的名片（把称呼撤掉，看第 2 级）
        _ub_ok, _ub_msg, _ub_rec = users.add("", _UQQ, "", "自检（稍后撤销）")
        ok &= _ck(_ub_ok, "B10 播报：给这个人造一条用户记录", _ub_msg)
        _real_rt2, _real_sg2, _real_sp2 = llm.run_turn, im.send_group, im.send_private
        _cap2 = {}

        def _rt2(msgs, ctx):
            _cap2["last"] = str((msgs or [{}])[-1].get("content") or "")
            return ("播报自检", [], None)

        try:
            llm.run_turn = _rt2
            im.send_group = lambda gid, text, **kw: True
            im.send_private = lambda uid, text, **kw: True
            memory.forget_name(_UQQ)
            agent.on_api("announce", {"group_id": int(_UG),
                                      "facts": {"数据": [{"站点": "B 站"}]}},
                         users.ident_of(_ub_rec) if _ub_rec else None)
            ok &= _ck("阿猫" in _cap2.get("last", "") and "[" not in _cap2.get("last", ""),
                      "B10 **播报材料**也按所在群的名片（没称呼 → 本群名片；⛔ 无方括号）",
                      _cap2.get("last", "")[-70:])
            memory.remember_name(_UQQ, "李四")
            _cap2.pop("last", None)
            agent.on_api("announce", {"group_id": int(_UG),
                                      "facts": {"数据": [{"站点": "B 站"}]}},
                         users.ident_of(_ub_rec) if _ub_rec else None)
            ok &= _ck("李四" in _cap2.get("last", ""),
                      "B10 播报材料：有称呼就用称呼", _cap2.get("last", "")[-50:])
        finally:
            llm.run_turn, im.send_group, im.send_private = _real_rt2, _real_sg2, _real_sp2
            if _ub_rec:
                users.remove(_ub_rec["id"])

        # ── B⑪ `guards.strip_echo`：认新格式（名字 + 冒号）+ 名片/昵称也算她的名字 ──
        ok &= _ck(guards.strip_echo("李四: 好累啊", names=("李四",)) == "好累啊",
                  "B11 `strip_echo` 认**新格式**（名字 + 冒号）")
        ok &= _ck(guards.strip_echo("李四: 你也在啊") == "你也在啊",
                  "B11 走**真名单**也削得掉（新格式）")
        _sp = guards.speaker_names()
        ok &= _ck("李四" in _sp and "華仙" in _sp and "阿猫" in _sp,
                  "B11 `speaker_names()` 把 **称呼 / 昵称 / 本群名片** 都收进来了",
                  "、".join(_sp))
        ok &= _ck(guards.strip_echo("華仙: 我在呢") == "我在呢"
                  and guards.strip_echo("阿猫: 我在呢") == "我在呢",
                  "B11 **昵称 / 本群名片**开头的误抄也削得掉（以前靠方括号那截）")
        ok &= _ck(guards.strip_echo("张三[群名片:已放弃思考20s]: 好累啊", names=("张三",))
                  == "好累啊",
                  "B11 老的 `名字[群名片:X]: …` 那种写法**照样认**（向后兼容）")
        ok &= _ck(guards.strip_echo("建议: 多喝水") == "建议: 多喝水",
                  "B11 正常句子（「建议: …」）不被误伤")

        # ── B⑦ `say` 失败话 = 统一那两句 ──
        _sent_say = []
        _real_sp3 = im.send_private
        try:
            im.send_private = lambda uid, text, **kw: (_sent_say.append(uid) or True)
            _s1 = toolkit.call("say", {"text": "自检", "who": "查无此人甲乙"}, _cp)
            ok &= _ck(_s1.get("ok") is False and not _sent_say
                      and _s1.get("error") == "没找到「查无此人甲乙」这个人 —— 让他起个称呼",
                      "B7 `say` 认不出人 → 统一那句 `_NOBODY`（逐字）",
                      "%r" % (_s1.get("error"),))
            memory.remember_name("7000000001", "撞名甲乙")
            memory.remember_name("7000000002", "撞名甲乙")
            _s2 = toolkit.call("say", {"text": "自检", "who": "撞名甲乙"}, _cp)
            ok &= _ck(_s2.get("ok") is False and not _sent_say
                      and _s2.get("error") == "「撞名甲乙」重名了，查不到 —— 让他起个称呼",
                      "B7 `say` 撞名 → 统一那句 `_AMBIGUOUS`（逐字）",
                      "%r" % (_s2.get("error"),))
            memory.forget_name("7000000001")
            memory.forget_name("7000000002")
        finally:
            im.send_private = _real_sp3
            memory.forget_person("7000000001")
            memory.forget_person("7000000002")

        # ── B⑨ 电脑名整条链路：认人 / 别名 / 材料 都不许出现 ──
        ok &= _ck(_who._ORDER == ("称呼", "群名片", "昵称"),
                  "B9 认人档位 = 称呼 → 本群名片 → 昵称（⛔ `电脑名` 整档没了）",
                  str(_who._ORDER))
        ok &= _ck(not hasattr(_who, "_pc_name") and not hasattr(_who, "pc_name"),
                  "B9 `who` 里连那个读电脑名的函数都没了（整条链路清干净）")
        # 心跳里的电脑名：**只写日志** —— 不进任何材料（缓存 + 合并两个材料路径都看一遍）
        _hbcn_ok, _hbcn_msg, _hbcn_rec = users.add("", "3655555555", "", "自检（稍后撤销）")
        ok &= _ck(_hbcn_ok, "B9 造一台带电脑名的心跳", _hbcn_msg)
        if _hbcn_rec:
            memory.remember_name("3655555555", "电脑名甲")
            statuscache.record({"action": "status.push", "ok": True, "日期": _TODAY,
                                "专注": "1 小时", "摸鱼": "0", "现在": "在忙",
                                "电脑名": "★电脑名不该出现★", "时段": _win_all,
                                "UTC偏移": "+08:00"},
                               _hbcn_rec["id"], now=time.time() - 10)
            _hbcn_out = json.dumps(toolkit.call("pc_status", {"who": "电脑名甲"}, c2),
                                   ensure_ascii=False)
            ok &= _ck("★电脑名不该出现★" not in _hbcn_out,
                      "B9 ⛔ 电脑名不进战况材料（只写日志）", _hbcn_out)
            ok &= _ck("★电脑名不该出现★" not in _who.display_name(_hbcn_rec)
                      and "★电脑名不该出现★" not in str(_who.aliases(_hbcn_rec)),
                      "B9 ⛔ 电脑名不进显示名、也不进别名字典")
            users.remove(_hbcn_rec["id"])
            memory.forget_person("3655555555")
        # 收尾：这一节自己造的东西都撤掉
        memory.reset([_hk, _cp["key"]])
        memory.forget_person(_UQQ)
        memory.forget_person(_UQQ2)

        # ═══ 6.z 同一个人多台电脑 → 战报**拼成一份**（用户 2026-10-05 拍板 1(a)+2(a)+3(a)）═══
        #    规则（只看"今天有数据"、相加、来源按名相加降序、`现在`/`数据时间` 取心跳最新那条）
        #    与解析/格式化都在 `fgbot/merge.py`（**纯函数**）；"去哪几条缓存里找那个人另外几台"
        #    在 `statuscache.merge_person`。全程**离线打桩**：users.json / status-cache.json
        #    都在临时目录里，不联网、不发消息。
        #    ⚠️ 单台那两条（⑥ / ⑥′）钉的是"输出与改动前**逐字相同**"：拿 json 字符串逐字比，
        #       连**键的顺序**都在内（⑥′ 走的是 2026-10-05 之后的**空 who = 说话人**那条路，
        #       所以那份"逐字相同"是**缓存这条路上**的逐字相同 —— 现在它会带一个 `数据时间`）。
        #    ⚠️ 这个 section 里直连那两个函数同样换成**一调就炸**的桩（再钉一次"没有入口"）。
        _win_all = {"工作日": [], "时段": ["00:00-24:00"], "日期切换点": "04:00"}

        # ── ①②③ 纯函数那几条（不碰用户表、不碰缓存）──
        _rt = ["1 小时 12 分", "20 分 26 秒", "18 分", "45 秒",
               "1 小时", "1 分 49 秒", "0"]
        _rt_bad = [t for t in _rt if merge.fmt_secs(merge.parse_secs(t)) != t]
        ok &= _ck(not _rt_bad and merge.parse_secs("") == 0 and merge.parse_secs(None) == 0
                  and merge.parse_secs("   ") == 0 and merge.fmt_secs(0) == "0"
                  and merge.parse_secs("18") is None and merge.parse_secs("瞎写") is None,
                  "合并①：时长**解析 ⇄ 格式化往返**逐字不变（用户列的那几种写法全在内，"
                  "含 \"0\" 与空；认不出来的给 None —— ⛔ 不当成 0）",
                  "往返不上的：%s" % (_rt_bad or "无"))
        _drop = [("1 小时 12 分 26 秒", "1 小时 12 分"), ("12 小时 5 分 3 秒", "12 小时 5 分"),
                 ("1 小时 30 秒", "1 小时"), ("2 小时 0 分 0 秒", "2 小时")]
        _drop_bad = ["%s→%s（要 %s）" % (t, merge.fmt_secs(merge.parse_secs(t)), w)
                     for t, w in _drop if merge.fmt_secs(merge.parse_secs(t)) != w]
        ok &= _ck(not _drop_bad and merge.fmt_secs(3600) == "1 小时"
                  and merge.fmt_secs(3660) == "1 小时 1 分"
                  and merge.fmt_secs(3599) == "59 分 59 秒",
                  "合并①：**≥1 小时那一档丢掉秒**、余 0 分只写\"N 小时\""
                  "—— 与电脑侧 `Durations.Status`（`Durations.cs:37`）**逐字一致**",
                  "不对的：%s" % (_drop_bad or "无"))
        ok &= _ck(merge.parse_secs("1 小时 12 分") == 4320
                  and merge.parse_secs("20 分 26 秒") == 1226
                  and merge.parse_secs("1 分 49 秒") == 109
                  and merge.parse_secs("45 秒") == 45,
                  "合并①：解析出来的**秒数**对（1 小时 12 分 = 4320 / 20 分 26 秒 = 1226）")
        _m_two = merge.merge_data([{"日期": "10-05", "专注": "1 小时 12 分",
                                    "摸鱼": "20 分 26 秒", "现在": "在摸鱼"},
                                   {"日期": "10-05", "专注": "20 分 26 秒",
                                    "摸鱼": "1 分 49 秒", "现在": "在忙"}])
        ok &= _ck(_m_two.get("专注") == "1 小时 32 分" and _m_two.get("摸鱼") == "22 分 15 秒"
                  and _m_two.get("日期") == "10-05" and _m_two.get("现在") == "在摸鱼",
                  "合并②：两台**相加**（\"1 小时 12 分\" + \"20 分 26 秒\" = \"1 小时 32 分\"，"
                  "≥1 小时那一档照电脑侧**不写秒**）；"
                  "`现在` 只取主那条", json.dumps(_m_two, ensure_ascii=False))
        _m_src = merge.merge_data([{"日期": "10-05", "摸鱼来源": "B 站 20 分 / 小红书 5 分"},
                                   {"日期": "10-05", "摸鱼来源": "知乎 40 分 / B 站 26 分"}])
        ok &= _ck(_m_src.get("摸鱼来源") == "B 站 46 分 / 知乎 40 分 / 小红书 5 分",
                  "合并③：`摸鱼来源` 按**来源名**相加（两台都有的 B 站并成一条）、按**总时长降序**；"
                  "⛔ 里面一个字都不是电脑名", json.dumps(_m_src, ensure_ascii=False))
        ok &= _ck(merge.sum_sources(["B 站 20 分 26 秒", "小红书 5 分"])
                  == "B 站 20 分 26 秒 / 小红书 5 分",
                  "合并③：来源里那个时长照旧是**格式化字符串**（\"20 分 26 秒\" 那种也拆得开）")

        # ── ②③④⑤⑥ 真取数那一路 ──
        _m_recs = []
        _m_alive, _m_fwd = im.pc_alive, im.forward_to_pc

        def _m_no_direct(*a, **k):
            raise AssertionError("pc_status 碰了局域网直连 —— 那条路已经没有任何入口了")

        try:
            im.pc_alive = _m_no_direct
            im.forward_to_pc = _m_no_direct
            _MQQ = "3511111111"
            for _m_nm in ("合并甲", "合并乙", "合并丙"):
                _m_ok, _m_msg, _m_rec = users.add(_m_nm, _MQQ, "", "自检（稍后撤销）")
                ok &= _ck(_m_ok, "合并④⑤：造同一个 QQ（%s）的记录：%s" % (_MQQ, _m_nm), _m_msg)
                if _m_rec:
                    _m_recs.append(_m_rec)
            _m_a, _m_b, _m_c = _m_recs[0], _m_recs[1], _m_recs[2]
            # ⚠️ 2026-10-06：认人**不再看备注**（面板备注 `名字` 只用于显示）——
            #    "合并乙" 这个名字得是她的**称呼**才认得出来（同一个 QQ 三条记录不算重名）。
            memory.remember_name(_MQQ, "合并乙")
            statuscache.record({"action": "status.push", "ok": True, "日期": _TODAY,
                                "专注": "1 小时 12 分", "摸鱼": "20 分 26 秒",
                                "摸鱼来源": "B 站 20 分", "现在": "在摸鱼",
                                "电脑名": "台式机", "时段": _win_all, "UTC偏移": "+08:00"},
                               _m_a["id"], now=time.time() - 600)
            statuscache.record({"action": "status.push", "ok": True, "日期": _TODAY,
                                "专注": "20 分 26 秒", "摸鱼": "1 分 49 秒",
                                "摸鱼来源": "知乎 40 分 / B 站 26 分", "现在": "在忙",
                                "电脑名": "笔记本", "时段": _win_all, "UTC偏移": "+08:00"},
                               _m_b["id"], now=time.time() - 30)
            statuscache.record({"action": "status.push", "ok": True, "日期": _YDAY,
                                "专注": "5 小时", "摸鱼": "0", "现在": "在忙",
                                "电脑名": "昨天那台", "时段": _win_all, "UTC偏移": "+08:00"},
                               _m_c["id"], now=time.time() - 900)
            # ⚠️ 2026-10-06（用户拍板）：称呼是**按 QQ** 的（一个人的三台电脑共用它）→
            #    挑哪台当"主那条"由 `_pick` 定 = **心跳最新**那条（⛔ 电脑名不再参与）。
            #    这里要看的是"同一天的两台相加、昨天那台不混进来"，
            #    所以让**乙那条心跳最新**（30 秒前）：主那条 = 乙，甲同一天 → 并进来，
            #    丙（昨天、心跳更旧）既不冒头也不混进来。
            _m_out = toolkit.call("pc_status", {"who": "合并乙笔记本"}, c2)
            _m_txt = json.dumps(_m_out, ensure_ascii=False)
            ok &= _ck(_m_out.get("ok") and _m_out.get("专注") == "1 小时 32 分"
                      and _m_out.get("摸鱼") == "22 分 15 秒" and _m_out.get("日期") == _TODAY,
                      "合并②：缓存那条路上两台真的**相加**了"
                      "（专注 1 小时 32 分 / 摸鱼 22 分 15 秒）", _m_txt)
            ok &= _ck(_m_out.get("摸鱼来源") == "B 站 46 分 / 知乎 40 分"
                      and "台式机" not in _m_txt and "笔记本" not in _m_txt,
                      "合并③：来源按名相加 + **总时长降序**（B 站 46 分 / 知乎 40 分）；"
                      "⛔ 材料里没有电脑名（台式机 / 笔记本一个都没出现）", _m_txt)
            ok &= _ck(_m_out.get("现在") == "在忙"
                      and str(_m_out.get("数据时间") or "").endswith("秒前"),
                      "合并④：`现在` 与 `数据时间` 都取**心跳最新那条**（乙那条，30 秒前那条）",
                      _m_txt)
            ok &= _ck("5 小时" not in _m_txt and _YDAY not in _m_txt,
                      "合并⑤：**不同 `日期`** 的那台（丙：昨天那 5 小时）没被混进来", _m_txt)
            # ⑥ 只有一台 → 逐字相同（键、值、顺序、`数据时间` 一个都没动）
            _m_ok6, _m_msg6, _m_r6 = users.add("单台丙", "3622222222", "", "自检（稍后撤销）")
            ok &= _ck(_m_ok6, "合并⑥：再造一台**单独的**（那个人只有一条记录）", _m_msg6)
            memory.remember_name("3622222222", "单台丙")     # 认人看**称呼**，不看备注
            if _m_r6:
                _m_recs.append(_m_r6)
                statuscache.record({"action": "status.push", "ok": True, "日期": _TODAY,
                                    "专注": "1 小时 25 分", "摸鱼": "25 分",
                                    "摸鱼来源": "B 站 20 分", "现在": "在摸鱼",
                                    "电脑名": "独苗机", "时段": _win_all, "UTC偏移": "+08:00"},
                                   _m_r6["id"], now=time.time() - 23)
            _m_one = json.dumps(toolkit.call("pc_status", {"who": "单台丙"}, c2),
                                ensure_ascii=False)
            _m_one_want = ('{"ok": true, "日期": "%s", "专注": "1 小时 25 分", '
                           '"摸鱼": "25 分", "摸鱼来源": "B 站 20 分", "现在": "在摸鱼", '
                           '"数据时间": "23 秒前"}' % _TODAY)
            ok &= _ck(_m_one == _m_one_want,
                      "合并⑥：**只有一台**电脑 → 输出与改动前**逐字相同**"
                      "（连键的顺序、`数据时间` 都没动）", _m_one)

            # ── ⑥′⑦′ 空 who（= **当前说话的人**那台）：走缓存，也会把"同一个人的另一台"并进来 ──
            #    ⚠️ 这里说话人是 c2（QQ 10001），所以**得给他本人登记记录** ——
            #       从前那两条"直连主人"记录（空 who 时靠**主人那条**认人）已经没有意义了。
            _m_okA, _m_msgA, _m_rA = users.add("缓存第一台", "10001", "", "自检（稍后撤销）")
            ok &= _ck(_m_okA, "合并⑥′：给说话人（QQ 10001）登记第一台", _m_msgA)
            if _m_rA:
                _m_recs.append(_m_rA)
                statuscache.record({"action": "status.push", "ok": True, "日期": _TODAY,
                                    "专注": "1 小时 25 分", "摸鱼": "25 分",
                                    "摸鱼来源": "B 站 20 分", "现在": "在摸鱼",
                                    "电脑名": "缓存一台", "时段": _win_all, "UTC偏移": "+08:00"},
                                   _m_rA["id"], now=time.time() - 50)
            _m_live1 = json.dumps(toolkit.call("pc_status", {}, c2), ensure_ascii=False)
            _m_live1_want = ('{"ok": true, "日期": "%s", "专注": "1 小时 25 分", '
                             '"摸鱼": "25 分", "摸鱼来源": "B 站 20 分", "现在": "在摸鱼", '
                             '"数据时间": "50 秒前"}' % _TODAY)
            ok &= _ck(_m_live1 == _m_live1_want,
                      "合并⑥′：空 who + 说话人**只有一台** → 读他自己那条缓存"
                      "（键序、`数据时间` 都照旧；一次直连都没走）", _m_live1)
            _m_okB, _m_msgB, _m_rB = users.add("缓存第二台", "10001", "", "自检（稍后撤销）")
            ok &= _ck(_m_okB, "合并⑦′：同一个 QQ 再登记**第二台**（同一个人两台电脑）", _m_msgB)
            if _m_rB:
                _m_recs.append(_m_rB)
                statuscache.record({"action": "status.push", "ok": True, "日期": _TODAY,
                                    "专注": "2 小时", "摸鱼": "30 分",
                                    "摸鱼来源": "联调标记 30 分", "现在": "在忙",
                                    "电脑名": "缓存二台", "时段": _win_all, "UTC偏移": "+08:00"},
                                   _m_rB["id"], now=time.time() - 60)
            _m_live2 = toolkit.call("pc_status", {}, c2)
            _m_live2_txt = json.dumps(_m_live2, ensure_ascii=False)
            ok &= _ck(_m_live2.get("ok") and _m_live2.get("专注") == "3 小时 25 分"
                      and _m_live2.get("摸鱼") == "55 分"
                      and _m_live2.get("摸鱼来源") == "联调标记 30 分 / B 站 20 分"
                      and _m_live2.get("现在") == "在摸鱼"
                      and _m_live2.get("数据时间") == "50 秒前"
                      and "缓存一" not in _m_live2_txt and "缓存二" not in _m_live2_txt,
                      "合并⑦′：空 who + 同一个人的**两台电脑**（同一天）→ 相加"
                      "（1 小时 25 分 + 2 小时 = 3 小时 25 分）；主那条**自己那条被跳过**"
                      "（不是 4 小时 50 分）；⛔ 材料里没有电脑名", _m_live2_txt)

            # ── ⑧ 缓存这条路上的失败文案：改完照旧（一个字都没动）──
            store.remove(statuscache.CACHE_NAME)   # 先清干净，免得多出来的缓存把这一档吃掉
            _m_f1 = toolkit.call("pc_status", {}, c2)
            ok &= _ck(_m_f1.get("ok") is False and _m_f1.get("电脑不在线") is True
                      and _m_f1.get("error")
                      == "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据",
                      "合并⑧：**没有他的心跳** → 那句原话逐字未变（「电脑没开机（…）」）",
                      json.dumps(_m_f1, ensure_ascii=False))
            # ⚠️ 直连那条路上的**两句**文案（"…没接住…" / "电脑返回的格式不对"）在这条路上
            #    永远不会有；`t_pc_status` 里那句删掉了，`_pc_forward` 里那几个原因码**原样留着**。
            with open(toolkit.__file__, encoding="utf-8") as _tkf2:
                _tk_txt = _tkf2.read()
            ok &= _ck("请求发过去了，但电脑没接住（它那个程序可能没在跑）" not in _tk_txt
                      and "_pc_forward" in _tk_txt,
                      "合并⑧：直连那条路上的「…但电脑没接住（…）」**随分支一起删掉了**"
                      "（`_pc_forward()` 本人还在、原因码也原样 —— 只是没有任何入口）")
        finally:
            im.pc_alive, im.forward_to_pc = _m_alive, _m_fwd
            for _m_r in _m_recs:
                users.remove(str((_m_r or {}).get("id") or ""))
            for _m_q in ("3511111111", "3622222222"):
                memory.forget_person(_m_q)          # 上面为认人临时定的称呼
            store.remove(statuscache.CACHE_NAME)


        # ── **501 那条路必须消失**：真的起一个本地 HTTP 服务，按契约打一条 status.push
        #    契约：POST /api + action=status.push + 她那套鉴权 → **200 / 204 = 收到**。
        #    回 501 的话电脑会一直以为"她还不认识这个动作"（用户点名最要紧的一条）。
        # ⚠️ 2026-10-04（第四批）：推送那两条**只认 `users.json` 里「每人一把」那把令牌** ——
        #    这一节从前用的是共享令牌（`bot.token`），现在会被 **403**（见 6.55 的 ⑫ 那一节）。
        #    所以这里先借一条用户记录，用完立刻撤掉。
        import urllib.request as _urq
        store.remove(statuscache.CACHE_NAME)
        _hb_ok, _hb_msg, _hb_rec = users.add("心跳自检", "10007", "", "自检用（稍后撤销）")
        _hb_tok = str((_hb_rec or {}).get("token") or "")
        _srv2 = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=_srv2.serve_forever, daemon=True).start()
        _api_url = "http://127.0.0.1:%d/api" % _srv2.server_address[1]

        def _api_post(obj):
            _b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            _rq = _urq.Request(_api_url, data=_b,
                               headers={"Content-Type": "application/json"})
            _tk = _hb_tok
            if _tk:
                _rq.add_header("Authorization", "Bearer " + _tk)
            try:
                with _urq.urlopen(_rq, timeout=10) as _resp:
                    return _resp.status, _resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as _e:
                return _e.code, _e.read().decode("utf-8", "replace")

        try:
            ok &= _ck(_hb_ok and bool(_hb_tok),
                      "心跳：先借一条用户记录（推送只认「每人一把」那把令牌）", _hb_msg)
            _code, _body = _api_post(_HB)
            ok &= _ck(_code == 200, "心跳：POST /api status.push → **200**（501 那条路没了）",
                      "HTTP %s ｜ %s" % (_code, _body[:50]))
            ok &= _ck(bool((store.read_json(statuscache.CACHE_NAME) or {}).get("用户")),
                      "心跳：走真 HTTP 那一趟也真的落盘了")
            _code2, _ = _api_post({"action": "没有这个动作"})
            ok &= _ck(_code2 == 501, "别的没实现的 action 照旧 501（只有 status.push 被接住）",
                      "HTTP %s" % _code2)
            _code3, _ = _api_post({"action": "status.push", "ok": True})
            ok &= _ck(_code3 == 200,
                      "心跳：缺战况键也回 200（心跳那一跳不看正文；回 4xx 会让它按别的档去重试）")
        finally:
            _srv2.shutdown()
            _srv2.server_close()
            if _hb_rec:
                users.remove(_hb_rec["id"])
        ok &= _ck("心跳：收到 status.push" in _read_log(),
                  "心跳：日志里留了一行（排查用）")

        # ══════════════════════════════════════════════════════════════
        # 6.55 互联网改造那一批（2026-10-03）
        #      新签名 / 重放保护 / 用户表（发码·撤销）/ 门禁 / 429 限流 / 面板不带 token
        #
        # 契约：`规格-多电脑接入.md` §3/§5/§6 + `给PCStatus的答复.md` B1~B6・C1~C5・D2
        #       + `PCStatus\给手机那边的答复-第三批.md` §11/§12。
        # 全部**离线打桩、不联网**：真的起一个 127.0.0.1 的 HTTP 服务，但只打它自己；
        # `users.json` 与 `local-config.json` 都指到临时目录（正式目录一个字节都不动）。
        # ══════════════════════════════════════════════════════════════
        real_local = base.LOCAL_CFG_PATH
        base.LOCAL_CFG_PATH = os.path.join(tmp, "local-config.json")
        store.remove(users.FILE)
        ratelimit.reset()
        _srv3 = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=_srv3.serve_forever, daemon=True).start()
        _root3 = "http://127.0.0.1:%d" % _srv3.server_address[1]

        def _hit(path, body=b"", headers=None, method="POST"):
            _b = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            _rq = _urq.Request(_root3 + path, data=(_b if method == "POST" else None),
                               headers=headers or {}, method=method)
            try:
                with _urq.urlopen(_rq, timeout=10) as r:
                    return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8", "replace"), dict(e.headers or {})

        def _newhdr(tok, body, ts=None, nonce=None):
            s = fgsig.sign_sha256(tok, body, ts=ts, nonce=nonce)
            return {fgsig.HEAD_SIG: s["sig"], fgsig.HEAD_TS: str(s["ts"]),
                    fgsig.HEAD_NONCE: s["nonce"], "Content-Type": "application/json"}

        try:
            # ── ① 用户表：token 形状 / 发码 / 邀请码 / 撤销 ──
            t0 = users.new_token()
            ok &= _ck(len(t0) == 20 and all(c in users.ALPHABET for c in t0)
                      and not (set(t0) & set("ILOU")) and t0 == t0.upper(),
                      "用户表：新 token = 20 位 Crockford base32 大写（无 I L O U）")
            o1, m1, rec1 = users.add("张三", "10002", "123456789", "自检")
            o2, m2, rec2 = users.add("小李", "10003", "", "自检")
            ok &= _ck(o1 and o2 and rec1 and rec2, "用户表：能发两把码（每人一把）", "%s / %s" % (m1, m2))
            ok &= _ck(len(str(rec1["id"])) == 4 and rec1["主人QQ"] == 10002
                      and rec1["群"] == 123456789 and rec1["主人"] is False
                      and rec1["建立时间"] and rec2["群"] == "",
                      "用户表：字段齐（id 4 位 / 名字 / 群 int 或空 / 主人QQ / 主人 / 建立时间 / 备注）")
            ok &= _ck(users.find_by_token(str(rec1["token"]).lower()) is not None
                      and users.find_by_token("不存在的token") is None,
                      "用户表：按 token 认人（大小写不敏感；不认识的认不出来）")
            # ⚠️ 2026-10-04 用户拍板改了这条规矩：**同一个 QQ 允许两条记录**（同一个人两台电脑）。
            #    以前是"一个 QQ 只许登记一条"，现在按 `who._pick()` 挑（带电脑名就用它、
            #    否则心跳最新那条）。这里造一条再立刻撤掉，免得影响下面"面板就 2 个人"。
            _dup_ok, _dup_m, _dup_rec = users.add("张三第二台", "10002")
            ok &= _ck(_dup_ok, "用户表：同一个 QQ **可以**登记两条（同一个人两台电脑）", _dup_m)
            if _dup_rec:
                users.remove(_dup_rec["id"])
            ok &= _ck(users.find_by_token(rec1["token"])["id"] == rec1["id"],
                      "用户表：认出来的是**那条记录**（id = 日志/缓存键）")

            code1, err1 = users.invite_code(rec1, "1.2.3.4:45678")
            ok &= _ck(code1 == "FG2-1|1.2.3.4:45678|%s" % rec1["token"],
                      "邀请码：`FG2-1|<公网host:port>|<token>`（第三段就是他那把）")
            ok &= _ck(users.invite_code(rec1, "http://1.2.3.4:45678")[0] is None
                      and users.invite_code(rec1, "1.2.3.4:45678/")[0] is None
                      and users.invite_code(rec1, "1.2.3.4")[0] is None
                      and users.invite_code(rec1, "")[0] is None
                      and err1 == "",
                      "邀请码：地址形状不对就生成不出来（带 http:// / 带斜杠 / 没端口 / 空）")
            ok &= _ck(users.valid_public_url("xxx.ddns.net:45678") == ("xxx.ddns.net", 45678)
                      and users.valid_public_url("1.2.3.4:0") is None
                      and users.valid_public_url("1.2.3.4:65536") is None
                      and users.valid_public_url("我的名字:80") is None,
                      "邀请码：地址校验照电脑侧的规矩（域名行 / 端口 1~65535 / host 只许字母数字点减号）")
            _rows = users.panel_rows("1.2.3.4:45678")
            ok &= _ck(len(_rows) == 2 and all(r["邀请码"].startswith("FG2-1|1.2.3.4:45678|") for r in _rows)
                      and all("token" not in r for r in _rows),
                      "用户表：面板那份带邀请码、但**不带 token 字段**（只有前缀指纹）",
                      json.dumps(_rows[0], ensure_ascii=False)[:70])

            # 心跳缓存按 **id** 存；撤销时一并删掉（B2.3 的附带要求）
            statuscache.record({"action": "status.push", "ok": True, "日期": "10-03",
                                "时段": {"工作日": [], "时段": ["00:00-24:00"],
                                         "日期切换点": "04:00"}}, rec1["id"])
            ok &= _ck(statuscache.last_seen(rec1["id"]) is not None,
                      "用户表：心跳缓存按用户 id 存（面板能看到「最后心跳」）")
            okr, mkr = users.remove(rec1["id"])
            ok &= _ck(okr and users.find_by_token(rec1["token"]) is None
                      and users.find_by_token(rec2["token"]) is not None,
                      "撤销：**立刻生效、只影响他一个**（小李那把照旧能用）", mkr)
            ok &= _ck(statuscache.last_seen(rec1["id"]) is None,
                      "撤销：他那条心跳缓存也一起删了（不留他的数据）")

            # ── ② 新签名 / 重放 / 老签名 ──
            b1 = json.dumps({"action": "status.push", "ok": True, "日期": "10-03",
                             "时段": {"工作日": [], "时段": ["00:00-24:00"],
                                      "日期切换点": "04:00"}}, ensure_ascii=False).encode("utf-8")
            c, _t, _h = _hit("/api", b1, _newhdr(rec2["token"], b1))
            ok &= _ck(c == 200, "新签名：签对了 → 200（她收下了）", "HTTP %s" % c)
            _bad = _newhdr(rec2["token"], b1)
            _bad[fgsig.HEAD_SIG] = "sha256=" + "0" * 64
            c, t, _h = _hit("/api", b1, _bad)
            ok &= _ck(c == 403 and t == "",
                      "新签名：签错了 → 403 + **空正文**（契约 C4：不回显任何东西）",
                      "HTTP %s ｜ 正文 %r" % (c, t[:20]))
            c, _t, _h = _hit("/api", b1, _newhdr(rec2["token"], b1, ts=int(time.time()) - 600))
            ok &= _ck(c == 403, "新签名：时间戳超 ±120 秒窗口 → 403", "HTTP %s" % c)
            _rp = _newhdr(rec2["token"], b1)
            c1r, _t, _h = _hit("/api", b1, _rp)
            c2r, _t, _h = _hit("/api", b1, _rp)
            ok &= _ck(c1r == 200 and c2r == 403,
                      "重放：**同一份头原样再发** → 第一次 200、第二次 403（nonce 去重）",
                      "HTTP %s → %s" % (c1r, c2r))
            _old = {"X-Signature": "sha1=" + fgsig.sign_sha1(rec2["token"], b1),
                    "Content-Type": "application/json"}
            c, _t, _h = _hit("/api", b1, _old)
            ok &= _ck(c == 200, "老契约：`X-Signature: sha1=` 照旧能用（老头一个字节没动）",
                      "HTTP %s" % c)
            _sh = base.napcat_token()
            _old2 = {"X-Signature": "sha1=" + fgsig.sign_sha1(_sh, b1),
                     "Content-Type": "application/json"}
            c, t, _h = _hit("/api", b1, _old2)
            ok &= _ck(c == 403 and t == "",
                      "推送：**共享那把 token 的老签名推 status.push → 403 + 空正文**"
                      "（2026-10-04 起推送只认「每人一把」那把；老契约的**签名**照旧认，"
                      "但推送这条动作不认这把令牌）",
                      "HTTP %s ｜ 正文 %r" % (c, t[:20]))
            c, _t, _h = _hit("/api", b1, {"Authorization": "Bearer " + rec2["token"],
                                          "Content-Type": "application/json"})
            ok &= _ck(c == 200, "Bearer：本机来源能用（手机上的 App / 面板这条路）", "HTTP %s" % c)
            c, _t, _h = _hit("/api", b1, {"Authorization": "Bearer nope-not-a-token",
                                          "Content-Type": "application/json"})
            ok &= _ck(c == 403, "Bearer：不认识的 token → 403", "HTTP %s" % c)

            # ── ③ 用户管理：只有主人能调（B6）──
            _ul = json.dumps({"action": "user.list"}, ensure_ascii=False).encode("utf-8")
            c, t, _h = _hit("/api", _ul, _newhdr(rec2["token"], _ul))
            ok &= _ck(c == 403 and t == "",
                      "用户管理：**朋友的 token 调不了**（403 空正文，B6）", "HTTP %s" % c)
            c, t, _h = _hit("/api", _ul, _newhdr(_sh, _ul))
            ok &= _ck(c == 200 and "小李" in t,
                      "用户管理：主人那把能调，能看到用户表", "HTTP %s ｜ %s" % (c, t[:60]))
            c, t, _h = _hit("/api", _ul, {"Authorization": "Bearer " + _sh,
                                          "Content-Type": "application/json"})
            ok &= _ck(c == 200, "用户管理：本机 Bearer（主人）也能调", "HTTP %s" % c)

            # ── ③′ **控制面那些动作也只有主人能调**（2026-10-05 用户拍板"需要只有我能调"）──
            #    从前：本机 / 局域网**任何一把有用户令牌的人**都能调（公网那条路早就被挡）。
            #    这里**逐个动作**用真 HTTP + 真令牌打一遍（`_sh` = 共享那把 = 主人身份）：
            #      · 朋友那把（`rec2`，非主人）→ **403 + 空正文**；
            #      · 共享那把（本机 Bearer = 主人，**面板走的就是它**）→ **200 + 照旧的结果**。
            #    ⚠️ 只加闸：动作名 / 参数 / 返回结构一个字没动 —— 所以主人那半条只钉
            #       "没被挡住、`ok` 照旧在"（各动作自己的业务断言在控制面那一节，带主人身份）。
            #    ⚠️ `restart` 会往 `base.RESTART_PATH` 写请求文件 —— 这里临时指到 tmp 里
            #       **另一个名字**（别用 `restart.txt`：后面「公网」那一节要断言
            #       "公网调 restart 没留下 restart.txt"，用同一个路径会互相干扰），
            #       验完删掉、路径还原（⛔ 绝不往正式目录里丢 restart.txt）。
            _ctrl_restart_bak = base.RESTART_PATH
            base.RESTART_PATH = os.path.join(tmp, "restart-控制面闸.txt")
            _CTRL_CASES = [
                ("reset", {}),
                ("add", {"name": "自检控制面那家", "baseUrl": "http://127.0.0.1:1/v1",
                         "model": "自检模型", "key": "自检假key"}),
                ("use", {"name": "自检控制面那家"}),
                ("del", {"name": "自检控制面那家"}),
                ("test", {}),
                ("effort", {"value": "high"}),
                ("reasoning", {"value": "high"}),
                ("思考强度", {"value": "high"}),
                ("triggers", {}),                      # 不给 words = 只读
                ("触发词", {}),
                ("关键词", {}),
                ("memory", {}),
                ("记忆", {}),
                ("mem_add", {"qq": "10003", "text": "自检控制面放的这条"}),
                ("mem_fix", {"qq": "10003", "old": "自检控制面放的这条",
                             "new": "自检控制面改的这条"}),
                ("mem_del", {"qq": "10003", "old": "自检控制面改的这条"}),
                ("mem_name", {"qq": "10003", "name": "小李改的"}),
                ("mem_person_add", {"qq": "10003", "name": "李"}),
                ("mem_person_del", {"qq": "10003"}),
                ("mode", {}),
                ("restart", {}),
                ("重启", {}),
                # 提供商 / 模型目录 / 后台模型（2026-10-30 新增的那批，同一道主人闸）
                ("providers.utility", {"inherit": True}),
                ("providers.save", {"id": "selftest-prov", "name": "自检提供商",
                                    "baseUrl": "http://127.0.0.1:1/v1"}),
                ("providers.addmodels", {"provider": "selftest-prov",
                                         "models": [{"id": "sm-1", "name": "自检模型"}]}),
                ("providers.activate", {"provider": "selftest-prov", "model": "sm-1"}),
                ("providers.delmodel", {"provider": "selftest-prov", "model": "sm-1"}),
                ("providers.delete", {"provider": "selftest-prov"}),
            ]
            _apis_had = os.path.exists(store.path(llm.APIS_FILE))
            _ctrl_bad = []
            try:
                for _a, _kw in _CTRL_CASES:
                    _b = json.dumps(dict({"action": _a}, **_kw),
                                    ensure_ascii=False).encode("utf-8")
                    try:
                        os.remove(base.RESTART_PATH)
                    except Exception:
                        pass
                    _c1, _t1, _h1 = _hit("/api", _b,
                                         {"Authorization": "Bearer " + rec2["token"],
                                          "Content-Type": "application/json"})
                    _wrote1 = os.path.exists(base.RESTART_PATH)
                    _c2, _t2, _h2 = _hit("/api", _b,
                                         {"Authorization": "Bearer " + _sh,
                                          "Content-Type": "application/json"})
                    try:
                        _ok2 = "ok" in (json.loads(_t2) or {})
                    except Exception:
                        _ok2 = False
                    if not (_c1 == 403 and _t1 == "" and not _wrote1):
                        _ctrl_bad.append("%s：非主人 → HTTP %s %r（restart 文件 %s）"
                                         % (_a, _c1, _t1[:20], _wrote1))
                    if not (_c2 == 200 and _ok2):
                        _ctrl_bad.append("%s：主人 → HTTP %s %r" % (_a, _c2, _t2[:40]))
            finally:
                base.RESTART_PATH = _ctrl_restart_bak
                # ⚠️ `重启`（中文别名）走的是 `agent.on_api` 那一条 —— 它写的是
                #    `store.path("restart.txt")`（= tmp/restart.txt）；而后面「公网」那一节
                #    要断言"公网调 restart **没留下** restart.txt"。两个都擦掉。
                for _rf in (os.path.join(tmp, "restart-控制面闸.txt"),
                            store.path("restart.txt")):
                    try:
                        os.remove(_rf)
                    except Exception:
                        pass
                # ⚠️ 这一节造的那两家（老的 add 和新的 providers.save）会留在
                #    tmp 的 llm-apis.txt 里（`del` 现在**不许删当前启用的**，所以没删掉）。
                #    后面几节还要用 config.json 里那家，这里按名字清干净、把 active 复位；
                #    原来没有这个文件的话，连文件一起删掉。
                try:
                    _pd = llm.apis_doc()
                    _gone = {"自检控制面那家", "自检提供商"}
                    _keep = [p for p in _pd["providers"] if p["name"] not in _gone]
                    _keep_ids = {p["id"] for p in _keep}
                    _pd["providers"] = _keep
                    if _pd["active"].get("provider") not in _keep_ids:
                        _pd["active"]["provider"] = ""
                        _pd["active"]["model"] = ""
                    if _pd["utility"].get("provider") not in _keep_ids:
                        _pd["utility"]["provider"] = ""
                    if _apis_had:
                        store.write_json(llm.APIS_FILE, _pd)
                    else:
                        store.remove(llm.APIS_FILE)
                except Exception:
                    pass
            ok &= _ck(not _ctrl_bad,
                      "控制面闸：%d 个动作（含中文别名）→ 非主人**全部 403 空正文**、"
                      "主人（共享令牌 = 面板那条路）**全部照旧 200**" % len(_CTRL_CASES),
                      "不对的：%s" % "；".join(_ctrl_bad))

            # **两把不许互换**（契约 A3 点名要钉的）：NapCat 那条路（`POST /`）只认共享那把 ——
            # 拿用户 token 去签它，一样被丢掉。⚠️ 载荷用 `meta_event`（她本来就不处理），
            # 所以**万一**鉴权真放行了也不会叫她开口、不会发任何消息（自检不许有副作用）。
            _n0 = _read_log()
            _body_nap = b'{"post_type":"meta_event","meta_event_type":"heartbeat"}'
            _c, _t, _h = _hit("/", _body_nap,
                              {"X-Signature": "sha1=" + fgsig.sign_sha1(rec2["token"], _body_nap),
                               "Content-Type": "application/json"})
            _tail = _read_log()[len(_n0):]
            ok &= _ck(_c == 204 and "鉴权失败" in _tail and "没处理的上报" not in _tail,
                      "两把不许互换：用户 token 签的 `POST /` 照样被丢（只有共享那把进得来）",
                      "HTTP %s" % _c)

            # ── ④ 公网那条路：`bot.control.allowPublic`（2026-10-03 加的开关）──
            #
            # 用户拍板的规矩：
            #   · **关**（默认）= 和从前**逐字一样**：公网来源一律 403 空正文；
            #   · **开** = **只有 `POST /api`** 放到"鉴权那一步"：必须带有效凭据
            #     （新签名 `X-FG-Signature` / 老签名 `X-Signature: sha1=`，每人一把那把
            #     token）；没凭据 / 签错 → **403 空正文 + 计一次失败**（照 429 那套）；
            #     共享那把 `napcatToken` 公网不认，`Bearer` 也不给公网；
            #     就算凭据对，公网也**只许调 `status.push` / `announce`**；
            #   · `/panel`、`/status`、`POST /`（NapCat 上报）**这颗键管不着**：公网一律 403；
            #   · 关掉 → **立刻**回到"公网一律 403"；本机/局域网一个字都不变。
            #
            # ⚠️ 打桩：真机上 127.0.0.1 **永远**算本机，所以 `is_local` 与
            #    `client_allowed` **两个都要打**才算"这条从公网来"（只打后者的话，
            #    共享那把 token 在模拟里照样被当成主人 —— 那个桩就白打了）。
            _real_local, _real_allow = server.is_local, server.client_allowed
            _real_ap, _real_restart = server.allow_public, base.RESTART_PATH
            _nb = b'{"post_type":"meta_event","meta_event_type":"heartbeat"}'
            try:
                server.is_local = lambda ip: False
                server.client_allowed = lambda ip: False
                base.RESTART_PATH = os.path.join(tmp, "restart.txt")

                # ── ① 开关**关**：和现在逐字一致（公网一律 403，连计数都不动）──
                server.allow_public = lambda: False
                ratelimit.reset()
                c, t, _h = _hit("/api", b1, _newhdr(rec2["token"], b1))
                ok &= _ck(c == 403 and t == "",
                          "公网·开关关：**签名对也 403 + 空正文**（= 现在的行为，逐字不变）",
                          "HTTP %s ｜ %r" % (c, t[:20]))
                ok &= _ck(ratelimit.state("127.0.0.1") == "窗口内失败 0 次",
                          "公网·开关关：门禁挡下的那条**不算鉴权失败**（计数没动）",
                          ratelimit.state("127.0.0.1"))
                c, _t, _h = _hit("/panel", b"", {}, method="GET")
                ok &= _ck(c == 403, "公网·开关关：/panel → 403（不告诉对方这里有个面板）",
                          "HTTP %s" % c)
                c, _t, _h = _hit("/status", b"", {}, method="GET")
                ok &= _ck(c == 403, "公网·开关关：/status → 403", "HTTP %s" % c)
                c, _t, _h = _hit("/", _nb, {"X-Signature": "sha1=" + fgsig.sign_sha1(_sh, _nb),
                                            "Content-Type": "application/json"})
                ok &= _ck(c == 403, "公网·开关关：POST /（NapCat 上报）→ 403", "HTTP %s" % c)

                # ── ② 开关**开** ──
                server.allow_public = lambda: True
                ratelimit.reset()
                _n0 = _read_log()
                c, _t, _h = _hit("/api", b1, _newhdr(rec2["token"], b1))
                ok &= _ck(c == 200, "公网·开关开：**有效新签名 → 200**（朋友那把 token）",
                          "HTTP %s" % c)
                _pub = [l for l in _read_log().splitlines() if "公网来源" in l]
                ok &= _ck(bool(_pub) and "127.0.0.1" in _pub[-1] and "日期" not in _pub[-1],
                          "公网·开关开：进来时**写一行日志**（含来源 IP、**不记内容**）",
                          _pub[-1][:90] if _pub else "（没写）")
                c, _t, _h = _hit("/api", b1,
                                 {"X-Signature": "sha1=" + fgsig.sign_sha1(rec2["token"], b1),
                                  "Content-Type": "application/json"})
                ok &= _ck(c == 200, "公网·开关开：**老契约 `X-Signature: sha1=` 也放行**"
                                    "（朋友那台不用改）", "HTTP %s" % c)

                ratelimit.reset()
                c, t, _h = _hit("/api", b1, {"Content-Type": "application/json"})
                ok &= _ck(c == 403 and t == ""
                          and ratelimit.state("127.0.0.1") == "窗口内失败 1 次",
                          "公网·开关开：**没凭据 → 403 空正文 + 计一次失败**",
                          "HTTP %s ｜ %s" % (c, ratelimit.state("127.0.0.1")))
                _bad = _newhdr(rec2["token"], b1)
                _bad[fgsig.HEAD_SIG] = "sha256=" + "0" * 64
                c, t, _h = _hit("/api", b1, _bad)
                ok &= _ck(c == 403 and t == "",
                          "公网·开关开：**签错 → 403 空正文**（不是「谁来都行」）",
                          "HTTP %s ｜ %r" % (c, t[:20]))
                c, _t, _h = _hit("/api", b1, _newhdr(_sh, b1))
                ok &= _ck(c == 403, "公网·开关开：**共享那把 token（napcatToken）公网不认**"
                                    "（朋友走 users.json 里自己那把）", "HTTP %s" % c)
                c, _t, _h = _hit("/api", b1, {"Authorization": "Bearer " + rec2["token"],
                                              "Content-Type": "application/json"})
                ok &= _ck(c == 403, "公网·开关开：**Bearer 不给公网**（那条明文凭据只给本机/局域网）",
                          "HTTP %s" % c)

                # 公网来源**照常吃 429**（本机/局域网永不封那条一个字没改）
                ratelimit.reset()
                _codes, _hd = [], {}
                for _i in range(10):
                    _c, _t, _hd = _hit("/api", b1, {"Content-Type": "application/json"})
                    _codes.append(_c)
                ok &= _ck(_codes[-1] == 429 and str(_hd.get("Retry-After") or "").isdigit(),
                          "公网·开关开：**失败照样计数 → 第 10 次起 429 + `Retry-After`**",
                          "前 10 次：%s" % _codes)
                _c, _t, _hd = _hit("/api", b1, _newhdr(rec2["token"], b1))
                ok &= _ck(_c == 429 and _t == "",
                          "公网·开关开：封禁期间**连合法签名也回 429 + 空正文**（口径不变）",
                          "HTTP %s ｜ %r" % (_c, _t[:20]))
                ratelimit.reset()

                # 凭据对也不许调控制面那些动作（重启她 / 清记忆 / 删模型 API…）
                _rb = json.dumps({"action": "restart"}, ensure_ascii=False).encode("utf-8")
                _st0 = ratelimit.state("127.0.0.1")
                c, t, _h = _hit("/api", _rb, _newhdr(rec2["token"], _rb))
                ok &= _ck(c == 403 and t == ""
                          and not os.path.exists(base.RESTART_PATH)
                          and ratelimit.state("127.0.0.1") == _st0,
                          "公网·开关开：别的动作（restart 这类控制面）**一律 403 空正文**"
                          "（也没留下 restart.txt、也不计失败）",
                          "HTTP %s ｜ %s" % (c, t[:20]))
                ok &= _ck(("status.push" in server.PUBLIC_ACTIONS)
                          and ("announce" in server.PUBLIC_ACTIONS),
                          "公网·开关开：白名单里就是那两条（心跳 + 播报）",
                          "、".join(server.PUBLIC_ACTIONS))

                # 开关管不着的那三条：公网照样 403
                c, _t, _h = _hit("/panel", b"", {}, method="GET")
                ok &= _ck(c == 403, "公网·开关开：/panel **还是 403**（这颗键管不着面板）",
                          "HTTP %s" % c)
                c, _t, _h = _hit("/status", b"", {}, method="GET")
                ok &= _ck(c == 403, "公网·开关开：/status **还是 403**", "HTTP %s" % c)
                # 2026-10-04：**根路径**也是信息类入口，一起收进局域网 ——
                # 公网来源不回那行字，回 **404 + 空正文**（比 403 更"这里什么都没有"）。
                c, t, _h = _hit("/", b"", {}, method="GET")
                ok &= _ck(c == 404 and t == "",
                          "公网·开关开：GET /（根路径）→ **404 + 空正文**"
                          "（外面什么都不该看到）",
                          "HTTP %s ｜ %r" % (c, t[:20]))
                c, _t, _h = _hit("/favicon.ico", b"", {}, method="GET")
                ok &= _ck(c == 403, "公网·开关开：GET /favicon.ico → 403（照旧，什么都不给）",
                          "HTTP %s" % c)
                c, _t, _h = _hit("/", _nb, {"X-Signature": "sha1=" + fgsig.sign_sha1(_sh, _nb),
                                            "Content-Type": "application/json"})
                ok &= _ck(c == 403, "公网·开关开：POST /（NapCat 上报）**一律 403**"
                                    "（NapCat 就在同一台手机上，绝不对外）", "HTTP %s" % c)

                # ── ③ 关掉 → 立刻收回 ──
                server.allow_public = lambda: False
                c, _t, _h = _hit("/api", b1, _newhdr(rec2["token"], b1))
                ok &= _ck(c == 403, "公网·**关掉开关立刻回到 403**（他要能一键收回）",
                          "HTTP %s" % c)
            finally:
                server.is_local, server.client_allowed = _real_local, _real_allow
                server.allow_public, base.RESTART_PATH = _real_ap, _real_restart
                ratelimit.reset()

            # ── ④.5 开关这颗键本身：默认关、就是配置里那个值 ──
            _ctl = base._cfg.setdefault("bot", {}).setdefault("control", {})
            _keep_ap = _ctl.get("allowPublic", None)
            try:
                _ctl.pop("allowPublic", None)
                ok &= _ck(server.allow_public() is False,
                          "开关：**配置里没有 `allowPublic` = 默认关**（= 从前的行为）")
                _ctl["allowPublic"] = True
                ok &= _ck(server.allow_public() is True,
                          "开关：填 true → 开（`config.json` / `local-config.json` 都走这条）")
                _ctl["allowPublic"] = "no"
                ok &= _ck(server.allow_public() is False,
                          "开关：填个不是布尔的假值 → 当关（宁可挡住，不放进来）")
            finally:
                if _keep_ap is None:
                    _ctl.pop("allowPublic", None)
                else:
                    _ctl["allowPublic"] = _keep_ap
            # （只报数、不断言：用户**有权**把这颗键关掉，关掉=默认行为，自检不该报错）
            print("  · 这台机器现在：bot.control.allowPublic = %r → 公网%s"
                  % ((base.bot_cfg().get("control") or {}).get("allowPublic"),
                     "能调 /api（必须带签名凭据）" if server.allow_public()
                     else "一律 403（默认）"))

            # ── ④.6 本机 / 局域网：一个字都不变（开关开着也全通）──
            c, _t, _h = _hit("/api", b1, _newhdr(rec2["token"], b1))
            ok &= _ck(c == 200, "本机/局域网：开关开着照旧 200（新签名）", "HTTP %s" % c)
            c, _t, _h = _hit("/api", b1, {"Authorization": "Bearer " + rec2["token"],
                                          "Content-Type": "application/json"})
            ok &= _ck(c == 200, "本机/局域网：**Bearer 照旧能用**（App / 面板那条老路）",
                      "HTTP %s" % c)
            # ⚠️ 2026-10-04（第四批）：共享那把**推不了** `status.push`（推送只认每人一把那把，
            #    见 ⑫）—— 但它**照旧认主人**：那份身份现在只管控制面 / 面板动作。
            #    `role: owner` 的语义一个字没动（下面用控制面动作 `user.list` 验它）。
            _ul6 = json.dumps({"action": "user.list"}, ensure_ascii=False).encode("utf-8")
            c, _t, _h = _hit("/api", _ul6, _newhdr(_sh, _ul6))
            ok &= _ck(c == 200, "本机/局域网：**共享那把 token 照旧认主人**"
                                "（控制面 / 面板动作，`role: owner` 语义没动）", "HTTP %s" % c)
            _ul6o = {"X-Signature": "sha1=" + fgsig.sign_sha1(_sh, _ul6),
                     "Content-Type": "application/json"}
            c, _t, _h = _hit("/api", _ul6, _ul6o)
            ok &= _ck(c == 200, "本机/局域网：共享那把 + **老 sha1 签名**调控制面照旧能用"
                                "（老契约一个字节没动）", "HTTP %s" % c)
            c, _t, _h = _hit("/", _nb, {"X-Signature": "sha1=" + fgsig.sign_sha1(_sh, _nb),
                                        "Content-Type": "application/json"})
            ok &= _ck(c == 204, "本机/局域网：POST /（NapCat 上报）照旧 204（本机不受影响）",
                      "HTTP %s" % c)
            c, _htm, _h = _hit("/panel", b"", {}, method="GET")
            ok &= _ck(c == 200, "面板：局域网/本机能打开（宽松版策略）", "HTTP %s" % c)
            # ── ④.7 根路径：本机 / 局域网**照旧**（公网那条钉在上面 ④ 里了）──
            c, t, _h = _hit("/", b"", {}, method="GET")
            ok &= _ck(c == 200 and "机魂小悦在跑" in t,
                      "根路径：本机 / 局域网**照旧**看得见那行字（电脑上打开不受影响）",
                      "HTTP %s ｜ %r" % (c, t[:24]))
            ok &= _ck(not _h.get("Server"),
                      "响应头：**不发 Server 头**（不给「这是 Python http.server」的指纹；"
                      "Date 照旧在）",
                      "Server=%r ｜ Date=%r" % (_h.get("Server"), bool(_h.get("Date"))))

            # ── ⑤ 没配 token → 拒绝服务 ──
            _real_nap, _real_toks = base.napcat_token, users.tokens
            try:
                base.napcat_token = lambda: ""
                users.tokens = lambda: []
                c, _t, _h = _hit("/api", b1, _newhdr(rec2["token"], b1))
                ok &= _ck(c == 403, "空 token：/api **拒绝服务**（不再「空就放行」）", "HTTP %s" % c)
                c, _t, _h = _hit("/", b'{"post_type":"message"}', {})
                ok &= _ck(c == 403, "空 token：NapCat 那条路也拒绝（不再放行伪造上报）",
                          "HTTP %s" % c)
            finally:
                base.napcat_token, users.tokens = _real_nap, _real_toks

            # ── ⑥ 413：请求体超上限（D2）──
            try:
                _sk = socket.create_connection(("127.0.0.1", _srv3.server_address[1]), timeout=5)
                _sk.sendall(b"POST /api HTTP/1.1\r\nHost: x\r\nContent-Length: 2000000\r\n\r\n")
                _resp = _sk.recv(200).decode("utf-8", "replace")
                _sk.close()
                ok &= _ck(" 413 " in _resp, "413：请求体超 1 MB → 413 + 空正文（D2）",
                          _resp.splitlines()[0] if _resp else "（没回话）")
            except Exception as _e:
                ok &= _ck(False, "413：请求体超上限那条路", repr(_e))

            # ── ⑦ 429 限流：5 分钟 10 次失败 → 封 15 分钟（本机/局域网永不封）──
            ok &= _ck(ratelimit.state("127.0.0.1") == "窗口内失败 0 次",
                      "限流：**正常请求一个字节都不计数**", ratelimit.state("127.0.0.1"))
            _badh = {"X-FG-Signature": "sha256=" + "0" * 64,
                     fgsig.HEAD_TS: str(int(time.time())),
                     fgsig.HEAD_NONCE: fgsig.new_nonce()}
            c, _t, _h = _hit("/api", b1, _badh)
            ok &= _ck(c == 403, "限流：本机写错 token → 403（**不封**，本机/局域网永不封）",
                      "HTTP %s" % c)
            _real_lan, _real_allow2 = server.is_lan, server.client_allowed
            try:
                # 假装这条是"公网来的"：门禁放它过（好走到鉴权那一步），但它不算自己人
                server.client_allowed = lambda ip: True
                server.is_lan = lambda ip: False
                codes = []
                for _i in range(11):
                    _h2 = {"X-FG-Signature": "sha256=" + "0" * 64,
                           fgsig.HEAD_TS: str(int(time.time())),
                           fgsig.HEAD_NONCE: fgsig.new_nonce()}
                    _c, _t, _hd = _hit("/api", b1, _h2)
                    codes.append(_c)
                ok &= _ck(codes[9] == 429 or codes[10] == 429,
                          "限流：第 10 次失败开始封 → 429", "前 11 次：%s" % codes)
                _c, _t, _hd = _hit("/api", b1, _newhdr(rec2["token"], b1))
                _ra = _hd.get("Retry-After") or ""
                ok &= _ck(_c == 429 and str(_ra).isdigit() and 1 <= int(_ra) <= 900,
                          "限流：封禁期间连**合法请求**也回 429 + `Retry-After`（秒，1~900）",
                          "HTTP %s ｜ Retry-After %s" % (_c, _ra))
                _c, _t, _hd = _hit("/api", b1, _newhdr(rec2["token"], b1))
                ok &= _ck(_t == "", "限流：429 那条也是**空正文**", repr(_t[:20]))
            finally:
                server.is_lan, server.client_allowed = _real_lan, _real_allow2
                ratelimit.reset()
            ok &= _ck(ratelimit.retry_after("127.0.0.1") == 0, "限流：重置之后就解封了")

            # ── ⑧ napcatToken 缺失 → 回退用旧的 bot.token（⛔ 不许让她变聋）──
            _bcfg = base._cfg.get("bot") or {}
            _keep = _bcfg.get("napcatToken")
            try:
                base._cfg["bot"]["napcatToken"] = ""
                ok &= _ck(base.napcat_token() == (_bcfg.get("token") or "").strip()
                          and base.napcat_token() != "",
                          "兼容：没有 bot.napcatToken（或它是空的）→ 回退用旧的 bot.token")
                base._cfg["bot"]["napcatToken"] = "拆出来的那把"
                ok &= _ck(base.napcat_token() == "拆出来的那把",
                          "兼容：配了 bot.napcatToken 就用它（两把互不干扰）")
            finally:
                base._cfg["bot"]["napcatToken"] = _keep

            # ── ⑨ 隐藏键 role: owner（主人模式）与本地配置覆盖层 ──
            # ⚠️ 自己搭夹具：`_shared_token_ok()` 还要求 `bot.control.lanEnabled` 开着、
            #    而且来源命中 `allowIps`。公开模板里 allowIps 是空的（= 只认本机），
            #    照旧写死"192.168.1.101 能用"就会红 —— 这里临时给它一个网段。
            _real_role = base._cfg.get("role")
            _real_ctrl = dict(base._cfg.get("bot", {}).get("control") or {})
            try:
                base._cfg["bot"]["control"] = dict(_real_ctrl, lanEnabled=True,
                                                   allowIps=["192.168.1.0/24"])
                base._cfg["role"] = "owner"
                ok &= _ck(base.owner_mode() and server._shared_token_ok("192.168.1.101"),
                          "主人模式：role=owner → 局域网来源能用共享那把 token（免邀请码）")
                base._cfg["role"] = "friend"
                ok &= _ck((not base.owner_mode())
                          and (not server._shared_token_ok("192.168.1.101"))
                          and server._shared_token_ok("127.0.0.1"),
                          "主人模式：填成别的值 = 不认；那时只有**本机**能用那把 token")
            finally:
                base._cfg["role"] = _real_role
                base._cfg["bot"]["control"] = _real_ctrl
            ok &= _ck(base.save_local({"bot": {"publicUrl": "1.2.3.4:45678"}})
                      and base.public_url() == "1.2.3.4:45678",
                      "本地配置：面板填的公网地址写进 local-config.json（deploy 不覆盖它）")
            ok &= _ck(bool(base.bot_cfg().get("token")) and bool(base.bot_cfg().get("groups")),
                      "本地配置：叠上去时是**逐层合**，没把 token / groups 顶掉")
            ok &= _ck(base.save_local({"role": "owner"}) and base.owner_mode(),
                      "本地配置：隐藏键 role 也能写在本地那份里")
            store.remove("local-config.json")

            # ── ⑩ 面板：不带 token、要手输（localStorage）、有用户管理 ──
            _html3 = panel.render("TOKEN-XYZ")
            ok &= _ck("TOKEN-XYZ" not in _html3 and "__TOKEN__" not in _html3,
                      "面板：**页面里不再内嵌任何 token**（A5 堵掉的那个洞）")
            ok &= _ck("localStorage" in _html3 and "fgPanelToken" in _html3,
                      "面板：token 由用户手输一次、存 localStorage（浏览器自己记着）")
            ok &= _ck(("user.list" in _html3) and ("user.invite" in _html3)
                      and ("user.add" in _html3) and ("user.del" in _html3)
                      and ("user.set" in _html3) and ("user.publicurl" in _html3),
                      "面板：有「用户管理」（列人 / 发码 / 邀请码 / 撤销 / 改 / 公网地址）")
            # ── ⑨ 加人表单：**QQ 必填 + 备注（选填）**；填完 QQ 立刻把昵称取出来给他核 ──
            ok &= _ck('label:"QQ 号", numeric:true, required:true' in _html3
                      and 'label:"备注", required:false' in _html3
                      and 'label:"名字", required:true' not in _html3,
                      "⑨ 加人表单：**QQ 号必填**、**备注（选填，留空就显示称呼）**；"
                      "老那个「名字必填」的说法没了")
            ok &= _ck(("user.nick" in _html3) and ("bindQQLookup" in _html3)
                      and ("这个号的昵称：" in _html3),
                      "⑨ 填完 QQ **立刻取昵称显示出来给他核**（走控制面 user.nick，页面里只有动作名）")
            ok &= _ck("显示名" in _html3 and 'u["称呼"]' in _html3 and 'u["昵称"]' in _html3,
                      "⑨ 用户列表按显示名排，且把**备注 / 称呼 / 昵称 / QQ** 四种都摆出来")
            ok &= _ck("Retry-After" in _html3 and "429" in _html3,
                      "面板：429 会告诉用户等多久（Retry-After）")
            ok &= _ck(("user.export" in _html3) and ("user.import" in _html3),
                      "面板：有「导出用户表 / 导入用户表」（两个动作名都在页面里）")
            ok &= _ck("别外传" in _html3 and "含密钥" in _html3,
                      "面板：导出那份**页面上写清「含密钥、别外传」**（导出内容里确实有 token）")
            ok &= _ck("users.json.bak" in _html3,
                      "面板：导入前告诉用户「整张表覆盖」、旧的那张另存成 users.json.bak")
            # ── ⑩.1 文案口径：给用户看的字叫「令牌」（2026-10-03 用户点名改的）──
            #    为什么改：用户原话「把那些地方的描述给改成**令牌**」——
            #    "token" 那个词和大模型的"词元"容易混。⚠️ **只改给人看的说法**：
            #    `localStorage` 键名 / 请求头 / 后端字段一个字都没动（下面那条钉住它）。
            _sh3 = base.napcat_token()
            ok &= _ck("输入面板令牌" in _html3 and 'placeholder="令牌"' in _html3,
                      "面板（⑤）：门禁标题和输入框占位都写成「令牌」")
            ok &= _ck("fgPanelToken" in _html3 and "localStorage" in _html3
                      and "Bearer" in _html3,
                      "面板（⑤）：**机制没动**（localStorage 键名 fgPanelToken / Bearer 请求头照旧）")
            ok &= _ck(("看共享令牌" in _html3) and ("token.show" in _html3),
                      "面板：登录后有一个「🔑 看共享令牌」的入口（走已鉴权的 token.show）")
            ok &= _ck("共享令牌" in _html3 and "主人可查看" in _html3
                      and "查看共享令牌" in _html3,
                      "面板：「共享令牌」那张卡写着「别发给朋友、别发群里」；"
                      "门禁写着令牌 = 手机 config.json 里的 bot.token")
            ok &= _ck(bool(_sh3) and _sh3 not in _html3,
                      "面板（⑤）：**HTML 里依旧不含那把令牌**（A5 那条不许退化；不打印真值）",
                      "令牌长度 %d" % len(_sh3))

            # ── ⑩.2 地址栏里那截 ?token=：用它登录 + **立刻抹掉**（2026-10-05 用户发现的问题）──
            #    用户原话：「网页面板的网址明晃晃的写着 http://…:17383/panel?token=… ——
            #    我如果直播的话会暴露的吧」。于是：链接里带 token 时**先拿它当一次登录**，
            #    然后**马上**用 `history.replaceState` 把那一截从地址栏删掉；
            #    ⛔ **不管这把令牌认不认都抹**（认不认是下一步 /status / /api 的事，地址栏不能等它）。
            #    ⚠️ 这一节只查页面源码里那套机制在不在、顺序对不对 ——
            #       "真在浏览器里打开一遍、看着地址栏被抹"是**人那一步**（浏览器不在自检范围里，
            #       自检也不许联网 / 拉起浏览器）。
            ok &= _ck("URLSearchParams" in _html3 and "replaceState" in _html3,
                      "面板：链接里那截 ?token= 会被 URLSearchParams 读出来 + replaceState 抹掉")
            _i_clean = _html3.find('history.replaceState(null, "", location.pathname')
            _i_main = _html3.find('var TOKEN = ""')
            ok &= _ck(0 <= _i_clean < _i_main,
                      "面板：抹地址栏那一步在 <head>（第一帧之前）就跑完，比主脚本读 localStorage 还早")
            ok &= _ck('_q["delete"]("token")' in _html3,
                      "面板：只删 token 这**一个**参数（别的参数和 #hash 都留着）")
            ok &= _ck(("window.URLTOKEN" in _html3) and ("deepTrim(window.URLTOKEN)" in _html3)
                      and ('localStorage.setItem("fgPanelToken", TOKEN)' in _html3),
                      "面板：链接里那把走**和手输完全一样的那条路**（清洗 → 存 localStorage）")
            ok &= _ck("TOKEN_FROM_URL" in _html3 and "deepTrim(window.URLTOKEN)" in _html3,
                      "面板：链接里那把照旧清洗后存起来（门禁上不再写任何说明文字）")
            # ⚠️ 那条提示**不许**在 needToken 里清标记：起来那几条请求是并发出门的，
            #    令牌不认时每条都会调一次 needToken —— 清了的话提示只在第一条上闪一下，
            #    后面几条一盖就没了（真机用错令牌打开时踩到过，门禁上只剩"403 重新粘一次"）。
            _nt = _html3[_html3.find("function needToken("):]
            _nt = _nt[:_nt.find("\n}\n")]
            ok &= _ck(_nt and ("TOKEN_FROM_URL = false" not in _nt),
                      "面板：needToken 里**不清**那个标记（并发 403 不会把「从链接里来的」盖掉）")
            ok &= _ck(("这个页面本身不带任何凭据" not in _html3)
                      and ("地址栏里的令牌已自动清除" not in _html3)
                      and ("personality.md" not in _html3)
                      and ("令牌 = 手机" not in _html3)
                      and ("钥匙本身" not in _html3),
                      "面板：说明类长句一律不出现（门禁 / 页脚都只留字段名和错误）")

            # ── ⑪ 看共享令牌（`token.show`，2026-10-03 加）──
            #
            # 用户的原话是「我上哪去获取这个令牌？」→ 面板上点一下就能看到。
            # 四条纪律（用户点名要的）：
            #   · **只有主人**能调（别人 403 空正文，和 user.* 同口径）；
            #   · 值只从**已鉴权的 /api** 走（⛔ 绝不嵌进 HTML）；响应带 `Cache-Control: no-store`；
            #   · 日志里**只写"谁看了令牌"**，一个字节的值都不落；
            #   · 断言里**不打印真值**（长度 / 前后缀 / 全等比较）。
            _sh2 = base.napcat_token()
            _tk = json.dumps({"action": "token.show"}, ensure_ascii=False).encode("utf-8")

            # ① 改文案之后登录流程照旧：输对进得来、输错进不去
            c, _t, _h = _hit("/api", _tk, {"Authorization": "Bearer " + _sh2,
                                           "Content-Type": "application/json"})
            ok &= _ck(c == 200, "登录照旧：输对那把共享令牌 → 进得来（200）", "HTTP %s" % c)
            c, t, _h = _hit("/api", _tk, {"Authorization": "Bearer not-a-real-token",
                                          "Content-Type": "application/json"})
            ok &= _ck(c in (401, 403) and t == "",
                      "登录照旧：令牌输错 → 401/403 + 空正文（进不去面板）",
                      "HTTP %s ｜ 正文 %r" % (c, t[:20]))

            # ② 未鉴权 → 403 空正文（照现有口径）
            c, t, _h = _hit("/api", _tk, {"Content-Type": "application/json"})
            ok &= _ck(c == 403 and t == "",
                      "令牌：**一个凭据都不带**调 token.show → 403 + 空正文",
                      "HTTP %s ｜ 正文 %r" % (c, t[:20]))

            # ③ 朋友的令牌也不行（只有主人能看）
            c, t, _h = _hit("/api", _tk, _newhdr(rec2["token"], _tk))
            ok &= _ck(c == 403 and t == "",
                      "令牌：朋友的令牌调 token.show → 403 + 空正文（**只有主人**）",
                      "HTTP %s ｜ 正文 %r" % (c, t[:20]))

            # ④ 主人（已鉴权）→ 200，**返回的就是 config 里那把**（不打印真值）
            _log_before = _read_log()
            c, t, _h = _hit("/api", _tk, {"Authorization": "Bearer " + _sh2,
                                          "Content-Type": "application/json"})
            try:
                _got = str((json.loads(t) or {}).get("token") or "")
            except Exception:
                _got = ""
            ok &= _ck(c == 200 and bool(_got) and _got == _sh2
                      and len(_got) == len(_sh2)
                      and _got[:4] == _sh2[:4] and _got[-2:] == _sh2[-2:],
                      "令牌：鉴权后能看，**值和 config 里那把一致**"
                      "（全等 + 长度 + 前 4 位 + 后 2 位；断言里不打印真值）",
                      "HTTP %s ｜ 长度 %d、前 4 位 %s…" % (c, len(_got), _got[:4]))
            _hh = {str(k).lower(): v for k, v in (_h or {}).items()}
            ok &= _ck("no-store" in str(_hh.get("cache-control") or ""),
                      "令牌：那条响应带 `Cache-Control: no-store`（凭据明文不许被缓存）",
                      "Cache-Control: %s" % _hh.get("cache-control"))
            _tk_tail = _read_log()[len(_log_before):]
            ok &= _ck("查看了共享令牌" in _tk_tail,
                      "令牌：日志里留一行「某来源查看了令牌」（事件留痕）",
                      _tk_tail.strip().splitlines()[-1][:70] if _tk_tail.strip() else "（没写日志）")
            ok &= _ck(_sh2 not in _read_log(),
                      "令牌：**整份日志里搜不到那个值**（一个字节都没落）")

            # ── ⑫ 推送只认「每人一把」的用户令牌（2026-10-04 第四批）──
            #
            # 用户拍板：**推送数据只认「每人一把」的用户令牌，不再认共享令牌** ——
            #   · `announce`（含别名「播报」/「broadcast」）与 `status.push` 的凭据必须是
            #     `users.json` 里某一条记录那把 token（身份 = 那条记录的 id）；
            #   · **共享那把**（`bot.token` / `napcatToken`，身份 `own`）来推 →
            #     **403 空正文** + 照 D2 **计一次失败**（本机 / 局域网照旧永不封）；
            #   · ⛔ 别的动作一个字没动：`POST /`（NapCat 上报）照旧只认共享那把；
            #     控制面 / 面板动作（`user.*` … `token.show`）共享那把照旧认（见上面 ④.6）。
            # ⚠️ 打桩：`announce` 会走到模型那一层 —— 自检**绝不联网**，只换最底下两层
            #    （`llm.run_turn` 与 `im.send_*`），别的一律走真路径（含 server 那道门禁）。
            _real_rt, _real_sp, _real_sg = llm.run_turn, im.send_private, im.send_group
            _push_sent, _push_msgs = [], []
            _ann_req = {"action": "announce", "user_id": 10001,
                        "facts": {"人": "载荷里那个人", "数据": [
                            {"站点": "B 站", "持续时长": "2 分 0 秒", "开始时间": "15:52"}]}}

            def _rt_stub(msgs, ctx):
                _push_msgs.append(msgs)
                return ("摸鱼了哈", [], None)

            def _last_instr():
                """发给模型的**最后那条 user 指令**（= 材料 + 指令，就是"谁在摸鱼"那句）。"""
                for _m in reversed((_push_msgs[-1] if _push_msgs else []) or []):
                    if isinstance(_m, dict) and _m.get("role") == "user":
                        return str(_m.get("content") or "")
                return ""

            try:
                llm.run_turn = _rt_stub
                im.send_private = lambda uid, text, **kw: (
                    _push_sent.append(("p", uid, text)) or True)
                im.send_group = lambda gid, text, **kw: (
                    _push_sent.append(("g", gid, text)) or True)

                # ① 用户令牌推 announce → 200；⑦ 「谁在摸鱼」= 那条记录的显示名
                _ab = json.dumps(_ann_req, ensure_ascii=False).encode("utf-8")
                c, t, _h = _hit("/api", _ab, _newhdr(rec2["token"], _ab))
                _instr = _last_instr()
                ok &= _ck(c == 200 and bool(_push_sent) and "小李" in _instr,
                          "推送①⑦：**用户令牌**推 announce → 200；材料里「谁在摸鱼」="
                          "那条记录的**显示名**（小李）",
                          "HTTP %s ｜ 发出 %d 条 ｜ %s" % (c, len(_push_sent), _instr[-44:]))
                ok &= _ck("载荷里那个人" not in _instr,
                          "推送⑦：载荷里的 `人` **不再被读**（那条兜底分支已删；"
                          "名字只从记录来）",
                          _instr[-44:])

                # ② 用户令牌推 status.push → 200，并且按**那条记录的 id** 落盘
                _hb2 = json.dumps({"action": "status.push", "ok": True, "日期": "10-04",
                                   "时段": {"工作日": [], "时段": ["00:00-24:00"],
                                            "日期切换点": "04:00"}},
                                  ensure_ascii=False).encode("utf-8")
                c, _t, _h = _hit("/api", _hb2, _newhdr(rec2["token"], _hb2))
                ok &= _ck(c == 200 and statuscache.last_seen(rec2["id"]) is not None,
                          "推送②：**用户令牌**推 status.push → 200，心跳按那条记录的 id 落盘",
                          "HTTP %s ｜ 最后心跳 %s" % (c, statuscache.last_seen(rec2["id"])))

                # ③ 共享那把推两条（含中文别名）→ **403 + 空正文**
                for _act in ("status.push", "announce", "播报", "broadcast"):
                    _rb2 = json.dumps(dict(_ann_req, action=_act),
                                      ensure_ascii=False).encode("utf-8")
                    c, t, _h = _hit("/api", _rb2, _newhdr(_sh, _rb2))
                    ok &= _ck(c == 403 and t == "",
                              "推送③：**共享令牌推 %r → 403 + 空正文**" % _act,
                              "HTTP %s ｜ 正文 %r" % (c, t[:20]))
                ok &= _ck(not _push_sent or len(_push_sent) == 1,
                          "推送③：被拒的那几条**没有真的发出去**（announce 没走到发送那一步）",
                          "发送记录 %d 条" % len(_push_sent))

                # ③′ 「照现有规则计一次失败」：本机/局域网永不封，所以装成公网来源验计数
                _rl0, _ca0 = server.is_lan, server.client_allowed
                try:
                    server.client_allowed = lambda ip: True
                    server.is_lan = lambda ip: False
                    ratelimit.reset()
                    _rb3 = json.dumps(_ann_req, ensure_ascii=False).encode("utf-8")
                    c, t, _h = _hit("/api", _rb3, _newhdr(_sh, _rb3))
                    ok &= _ck(c == 403 and t == ""
                              and ratelimit.state("127.0.0.1") == "窗口内失败 1 次",
                              "推送③：共享令牌来推 → **照现有规则计一次失败**"
                              "（本机 / 局域网那份永不封的规矩没动）",
                              "HTTP %s ｜ %s" % (c, ratelimit.state("127.0.0.1")))
                finally:
                    server.is_lan, server.client_allowed = _rl0, _ca0
                    ratelimit.reset()

                # ⑥ 乱写的令牌推 announce → 403 + 空正文
                c, t, _h = _hit("/api", _ab, {"Authorization": "Bearer nope-not-a-user-token",
                                              "Content-Type": "application/json"})
                ok &= _ck(c == 403 and t == "",
                          "推送⑥：乱写的令牌 → 403 + 空正文", "HTTP %s ｜ %r" % (c, t[:20]))

                # 日志里要能一眼看出"推送不认共享令牌"（用户点名要的那行）
                _log_tail = _read_log()
                ok &= _ck("不认共享令牌" in _log_tail,
                          "推送③：日志里留下「不认共享令牌」那行（真机排查要看它）",
                          [l for l in _log_tail.splitlines() if "不认共享令牌" in l][-1:][0][-60:]
                          if "不认共享令牌" in _log_tail else "（没写）")
                ok &= _ck(base.napcat_token() not in _log_tail,
                          "推送：日志里**不出现共享那把令牌的明文**（E3 那条纪律没退）")
            finally:
                llm.run_turn, im.send_private, im.send_group = _real_rt, _real_sp, _real_sg

            # ══════════════════════════════════════════════════════════════
            # 6.55b 远程面板登录 + 反向代理（2026-10-31，差距表第 6 项）
            #
            # 用户定的验收口径（requirements §2）：
            #   · 局域网照旧免登录；公网 / 反代后面**必须登录**；
            #   · 登录页四态：无凭据 / 错凭据 / 对凭据 / 退出后；
            #   · 错口令一句人话 + 冷却（挡爆破），日志不落输入；
            #   · 伪造 X-Forwarded-For **不能**提权；只信 `panel.trustedProxies` 里的反代；
            #   · `panel.allowRemote` 关着时远程 403、本机 / 局域网一个字不变。
            #
            # ⚠️ 全部离线：只打 127.0.0.1 上自己起的 `_srv3`。模拟"公网来的"靠
            #    `X-Forwarded-For`（默认信任回环 = 同机反代，和真部署一个形状）。
            # ══════════════════════════════════════════════════════════════
            import urllib.parse as _up
            from fgbot import loginpage as _lp
            from fgbot import proxy as _px
            from fgbot import websession as _ws

            class _NoRedir(_urq.HTTPRedirectHandler):
                """别跟着 303 走 —— 要亲眼看到 Set-Cookie 和那一跳。"""

                def redirect_request(self, *a, **kw):
                    return None

            _nr = _urq.build_opener(_NoRedir)

            def _hit_nr(path, body=b"", headers=None, method="POST"):
                _rq = _urq.Request(_root3 + path,
                                   data=(body if method == "POST" else None),
                                   headers=headers or {}, method=method)
                try:
                    with _nr.open(_rq, timeout=10) as r:
                        return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
                except urllib.error.HTTPError as e:
                    return e.code, e.read().decode("utf-8", "replace"), dict(e.headers or {})

            def _hget(h, name):
                for k, v in (h or {}).items():
                    if str(k).lower() == str(name).lower():
                        return v
                return ""

            def _login(ip, pw, extra=None):
                h = {"X-Forwarded-For": ip,
                     "Content-Type": "application/x-www-form-urlencoded"}
                h.update(extra or {})
                return _hit_nr("/login", _up.urlencode({"password": pw}).encode("utf-8"),
                               h, method="POST")

            _RIP = "203.0.113.9"
            _R = {"X-Forwarded-For": _RIP}
            _pn = base.cfg().setdefault("panel", {})
            _pn_save = dict(_pn)
            _ws.reset()
            ratelimit.reset()
            try:
                _pn["allowRemote"] = True
                _pn["trustedProxies"] = ["127.0.0.1/32", "::1/128"]

                # ── ① 反代来源判定（纯函数：不经过 HTTP 也能把规则钉死）──
                _nets = _px.parse_trusted(_pn["trustedProxies"])
                ok &= _ck(_px.is_trusted("127.0.0.1", _nets)
                          and not _px.is_trusted("203.0.113.9", _nets),
                          "反代①：默认名单只信本机（127.0.0.1 是、公网不是）")
                ok &= _ck(_px.resolve("127.0.0.1",
                                      {"X-Forwarded-For": "203.0.113.9"}, _nets)
                          == "203.0.113.9",
                          "反代①：可信对端 + XFF → 真来源（不是把公网当 127.0.0.1）")
                ok &= _ck(_px.resolve("203.0.113.7",
                                      {"X-Forwarded-For": "127.0.0.1"}, _nets)
                          == "203.0.113.7",
                          "反代①：**不可信的对端声称 127.0.0.1 → 不认**（伪造头提不了权）")
                ok &= _ck(_px.resolve("127.0.0.1",
                                      {"X-Forwarded-For": "127.0.0.1, 203.0.113.9"}, _nets)
                          == "203.0.113.9",
                          "反代①：XFF 里客户端自己塞的 127.0.0.1 不算数"
                          "（**从右往左**取最靠近她的真实地址）")
                _nets2 = _px.parse_trusted(["10.0.0.0/8", "127.0.0.1/32", "写错的", ""])
                ok &= _ck(_px.resolve("127.0.0.1",
                                      {"X-Forwarded-For": "203.0.113.9, 10.1.2.3"}, _nets2)
                          == "203.0.113.9"
                          and not _px.is_trusted("203.0.113.9", _nets2),
                          "反代①：多层反代（10/8 也是自己人）→ 跳过可信代理、停在第一个"
                          "不可信地址；名单里写错的项被跳过（**不会**变成“全信”）")
                ok &= _ck(_px.resolve("127.0.0.1", {"X-Real-IP": "198.51.100.5"}, _nets)
                          == "198.51.100.5",
                          "反代①：只传 X-Real-IP 也认（nginx / Caddy 那一行）")
                ok &= _ck(_px.resolve("::ffff:127.0.0.1",
                                      {"X-Forwarded-For": "203.0.113.9"}, _nets)
                          == "203.0.113.9",
                          "反代①：IPv4-mapped 的 `::ffff:127.0.0.1` 也算本机（双栈常见坑）")
                ok &= _ck(_px.is_https("127.0.0.1", {"X-Forwarded-Proto": "https"}, _nets)
                          and not _px.is_https("203.0.113.7",
                                               {"X-Forwarded-Proto": "https"}, _nets),
                          "反代①：只信**可信代理**的 X-Forwarded-Proto（cookie 的 Secure 靠它）")

                # ── ② 无凭据：远程打开 /panel → 登录页（不是 403 白屏、不是直接进）──
                _c, _b, _h = _hit("/panel", b"", dict(_R), method="GET")
                ok &= _ck(_c == 200 and 'action="/login"' in _b and "口令" in _b
                          and "fgPanelToken" not in _b
                          and str(_sh) not in _b
                          and _hget(_h, "Cache-Control") == "no-store",
                          "登录页①：远程没登录打开 /panel → **登录页**（200、no-store；"
                          "不是 403 白屏、不是直接进面板），页面里没有令牌")
                _c, _b, _h = _hit("/panel", b"",
                                  {"X-Forwarded-For": "127.0.0.1, 203.0.113.9"},
                                  method="GET")
                ok &= _ck(_c == 200 and 'action="/login"' in _b
                          and "fgPanelToken" not in _b,
                          "登录页①：**伪造 X-Forwarded-For（塞个 127.0.0.1）也绕不过** —— "
                          "从右往左取，看到的还是登录页")
                _c, _b, _h = _hit("/status", b"", dict(_R), method="GET")
                ok &= _ck(_c == 403 and _b == "",
                          "登录页①：远程没登录 → /status **403 空正文**")
                _c, _b, _h = _hit("/login", b"", dict(_R), method="GET")
                ok &= _ck(_c == 200 and 'action="/login"' in _b,
                          "登录页：远程直接开 /login 也是登录页（200）")
                _c, _b, _h = _hit_nr("/login", b"", {}, method="GET")
                ok &= _ck(_c == 302 and _hget(_h, "Location") == "/panel",
                          "登录页：本机 / 局域网开 /login → 直接回面板（不需要登录）")

                # ── ③ 错凭据：一句人话 + 不泄露细节 + 日志不落输入 ──
                ratelimit.reset()
                _c, _b, _h = _login(_RIP, "WRONG-MARKER-XYZ")
                ok &= _ck(_c == 401 and "口令不对" in _b
                          and "WRONG-MARKER-XYZ" not in _b and str(_sh) not in _b,
                          "登录页②：错口令 → 401 + 一句人话（不回显输入、不透露"
                          "“口令对不对”的细节）")
                ok &= _ck("WRONG-MARKER-XYZ" not in _read_log(),
                          "登录页②：**输入的口令一个字节都没进日志**")

                # ── ④ 对凭据：发会话 cookie；之后面板 + 数据 + /api 都能用（主人身份）──
                _c, _b, _h = _login(_RIP, _sh)
                _sc = _hget(_h, "Set-Cookie")
                _rawck = _ws.raw_from_cookie(_sc)
                ok &= _ck(_c == 303 and bool(_rawck)
                          and "HttpOnly" in _sc and "SameSite=Lax" in _sc
                          and "Path=/" in _sc and "Secure" not in _sc,
                          "登录页③：对凭据 → 303 + `Set-Cookie`（HttpOnly / SameSite=Lax；"
                          "明文 HTTP 下**不加** Secure，否则浏览器会整条丢掉）",
                          "HTTP %s" % _c)
                ok &= _ck(_rawck not in _b and _rawck not in _read_log(),
                          "会话：cookie 原值不在响应正文 / 日志里（只在 Set-Cookie 头）")
                _CK = {"Cookie": "fgPanelSession=" + _rawck, "X-Forwarded-For": _RIP}
                _c, _b, _h = _hit("/panel", b"", dict(_CK), method="GET")
                ok &= _ck(_c == 200 and "fgPanelToken" in _b and str(_sh) not in _b
                          and _hget(_h, "Cache-Control") == "no-store",
                          "登录页③：带会话 → **面板 200**（页面里仍然没有令牌）")
                _c, _b, _h = _hit("/status", b"", dict(_CK), method="GET")
                ok &= _ck(_c == 200 and '"ok": true' in _b,
                          "登录页③：带会话 → /status 200", "HTTP %s" % _c)
                _c, _b, _h = _hit("/settings", b"", dict(_CK), method="GET")
                _c2, _b2, _h2 = _hit("/providers", b"", dict(_CK), method="GET")
                _c3, _b3, _h3 = _hit("/onboard", b"", dict(_CK), method="GET")
                ok &= _ck(_c == 200 and _c2 == 200 and _c3 == 200
                          and str(_sh) not in _b3,
                          "登录页③：带会话 → /settings /providers /onboard 全 200"
                          "（/onboard 是主人页，token 只有 ****）",
                          "HTTP %s / %s / %s" % (_c, _c2, _c3))
                _ub = json.dumps({"action": "user.list"},
                                 ensure_ascii=False).encode("utf-8")
                _c, _b, _h = _hit("/api", _ub,
                                  dict(_CK, **{"X-FG-Panel": "1",
                                               "Content-Type": "application/json"}))
                ok &= _ck(_c == 200 and '"ok": true' in _b,
                          "登录页③：带会话 + `X-FG-Panel` → **POST /api 200（主人身份）** —— "
                          "远程控制面通了", "HTTP %s" % _c)
                _c, _b, _h = _hit("/api", _ub,
                                  dict(_CK, **{"Content-Type": "application/json"}))
                ok &= _ck(_c == 403 and _b == "",
                          "会话：**不带 `X-FG-Panel` 的写请求 → 403**（防 CSRF；跨站表单"
                          "设不了自定义头）", "HTTP %s" % _c)
                _pb = json.dumps({"action": "status.push", "ok": True},
                                 ensure_ascii=False).encode("utf-8")
                _c, _b, _h = _hit("/api", _pb,
                                  dict(_CK, **{"X-FG-Panel": "1",
                                               "Content-Type": "application/json"}))
                ok &= _ck(_c == 403,
                          "会话：推送（status.push）**照旧不认共享令牌换来的会话** → 403"
                          "（推送只认用户表里那把）", "HTTP %s" % _c)
                ratelimit.reset()
                _c, _b, _h = _hit("/", b'{"post_type":"meta_event"}', dict(_CK))
                ok &= _ck(_c == 403,
                          "会话：`POST /`（NapCat 上报）**不认会话**（只许本机 / 局域网）",
                          "HTTP %s" % _c)

                # 会话寿命 / 撤销（单元级，时间注入，不真等 12 小时）
                _ident_t = {"id": "selftest", "主人": True}
                _t0 = time.time()
                _raw2 = _ws.new(_ident_t, now=_t0)
                ok &= _ck(_ws.lookup(_raw2, now=_t0 + 1) is not None
                          and _ws.lookup(_raw2,
                                         now=_t0 + _ws.session_seconds() + 1) is None,
                          "会话：绝对寿命到点就失效（`panel.sessionHours`）")
                _raw3 = _ws.new(_ident_t, now=_t0)
                ok &= _ck(_ws.lookup(_raw3, now=_t0 + _ws.idle_seconds() + 1) is None,
                          "会话：闲置超时也失效（`panel.sessionIdleMinutes`）")
                _raw4 = _ws.new(_ident_t, now=_t0)
                ok &= _ck(_ws.revoke(_raw4) and _ws.lookup(_raw4, now=_t0 + 1) is None,
                          "会话：revoke 之后立刻查不到（退出那条路的底层）")

                # HTTPS 反代后面：cookie 带 Secure
                _c, _b, _h = _login("203.0.113.11", _sh,
                                    {"X-Forwarded-Proto": "https"})
                ok &= _ck(_c == 303 and "Secure" in (_hget(_h, "Set-Cookie") or ""),
                          "会话：HTTPS 反代后面（`X-Forwarded-Proto: https`）→ cookie 带 "
                          "`Secure`", "HTTP %s" % _c)

                # ── ⑤ 退出后：旧 cookie 立刻失效 ──
                _c, _b, _h = _hit_nr("/logout", b"", dict(_CK), method="POST")
                ok &= _ck(_c == 303 and "Max-Age=0" in (_hget(_h, "Set-Cookie") or ""),
                          "登录页④：退出 → 303 + 下发过期 cookie", "HTTP %s" % _c)
                _c, _b, _h = _hit("/status", b"", dict(_CK), method="GET")
                ok &= _ck(_c == 403 and _b == "",
                          "登录页④：**退出后旧 cookie 立刻失效**（/status 403，不是等它过期）",
                          "HTTP %s" % _c)
                _c, _b, _h = _hit("/panel", b"", dict(_CK), method="GET")
                ok &= _ck(_c == 200 and 'action="/login"' in _b
                          and "fgPanelToken" not in _b,
                          "登录页④：退出后旧 cookie 打开 /panel → 回到登录页")

                # ── ⑥ 冷却（先单元级把时间钉死，再真 HTTP 打一遍）──
                _ws.reset()
                _tt = time.time()
                _blocked = False
                for _i in range(_ws.max_fails()):
                    _blocked, _secs = _ws.login_fail("198.51.100.99", now=_tt)
                ok &= _ck(_blocked
                          and _ws.login_blocked("198.51.100.99", now=_tt + 1) > 0
                          and _ws.login_blocked("198.51.100.99",
                                                now=_tt + _ws.cooldown_seconds() + 1) == 0,
                          "冷却：窗口内错满 → 冷却；到点自己解开（%d 次 / %d 秒）"
                          % (_ws.max_fails(), _ws.cooldown_seconds()))
                _ws.reset()
                ratelimit.reset()
                _codes = []
                for _i in range(_ws.max_fails()):
                    _codes.append(_login("198.51.100.7", "bad-%d" % _i)[0])
                ok &= _ck(_codes[-1] == 429,
                          "冷却：真 HTTP —— 同一个 IP 错满 → 第 %d 次起 429"
                          % _ws.max_fails(), "前 %d 次：%s" % (len(_codes), _codes))
                _c, _b, _h = _login("198.51.100.7", _sh)
                ok &= _ck(_c == 429
                          and str(_hget(_h, "Retry-After") or "").isdigit() and _b != "",
                          "冷却：冷却期里**正确口令也不收**（429 + Retry-After + 一句人话）",
                          "HTTP %s" % _c)
                _c, _b, _h = _login("198.51.100.8", _sh)
                ok &= _ck(_c == 303,
                          "冷却：**按 IP 分开** —— 另一个地址照常能登录", "HTTP %s" % _c)
                _ws.reset()

                # ── ⑦ 代理白名单：名单外的对端，XFF 当空气 ──
                _pn["trustedProxies"] = ["192.0.2.1/32"]     # 故意不含回环
                _c, _b, _h = _hit("/panel", b"", dict(_R), method="GET")
                ok &= _ck(_c == 200 and "fgPanelToken" in _b,
                          "反代白名单：对端**不在**名单里 → XFF 不认（这里对端是本机，"
                          "走回本机老路；公网真对端同样会只按自己的地址算）")
                _pn["trustedProxies"] = ["127.0.0.1/32", "::1/128"]
                _c, _b, _h = _hit("/panel", b"", dict(_R), method="GET")
                ok &= _ck(_c == 200 and 'action="/login"' in _b,
                          "反代白名单：对端**在**名单里 → 按 XFF 判成公网（登录页）")

                # ── ⑧ allowRemote 关掉：远程 403、本机 / 局域网一个字不变 ──
                _pn["allowRemote"] = False
                ratelimit.reset()
                _c, _b, _h = _hit("/panel", b"", dict(_R), method="GET")
                ok &= _ck(_c == 403 and _b == "",
                          "远程关闭：公网 /panel → **403 空正文**（不是登录页）")
                _c, _b, _h = _hit("/login", b"", dict(_R), method="GET")
                ok &= _ck(_c == 403, "远程关闭：公网 /login → 403")
                _c, _b, _h = _hit("/panel", b"", {}, method="GET")
                ok &= _ck(_c == 200 and "fgPanelToken" in _b,
                          "远程关闭：本机 /panel **一个字不变**（照旧面板）")
                _c, _b, _h = _hit("/status", b"", {"Authorization": "Bearer " + _sh},
                                  method="GET")
                ok &= _ck(_c == 200, "远程关闭：本机 Bearer /status 照旧 200")
                _pn["allowRemote"] = True

                # ── ⑨ 开关只认真正的布尔 / 登录页自身不吐东西 ──
                for _v, _want in (("true", False), (1, False), (True, True)):
                    _pn["allowRemote"] = _v
                    ok &= _ck(server.panel_remote() is _want,
                              "远程开关：只认真正的布尔（%r → %s）" % (_v, _want))
                _pn["allowRemote"] = True
                _bad_html = _lp.render(error="<script>x</script>")
                ok &= _ck("&lt;script&gt;" in _bad_html and "<script>x" not in _bad_html
                          and "fgPanelToken" not in _bad_html,
                          "登录页：文案会被转义、页面里没有任何凭据 / 面板 JS")
            finally:
                _pn.clear()
                _pn.update(_pn_save)
                _ws.reset()
                ratelimit.reset()
        finally:
            _srv3.shutdown()
            _srv3.server_close()
            store.remove(users.FILE)
            store.remove("local-config.json")
            base.LOCAL_CFG_PATH = real_local
            base.load()                     # 把内存里那份配置也还原（别把 publicUrl 带出去）
            ratelimit.reset()
            fgsig.reset_nonces()

        # ══════════════════════════════════════════════════════════════
        # 6.56 并发闸（2026-10-03 加）：`ThreadingHTTPServer` 原来**每请求一条线程、
        #      没有上限** —— 端口一映射到公网就能被撑死。现在超上限直接
        #      **503 + 空正文 + Retry-After**（和电脑侧讲好的那套一致）。
        #
        # 这段自检要证明三件事（用户点名）：
        #   ① 正常请求不受影响（没满就照旧 200）；
        #   ② 超限回 503（+ Retry-After + 空正文）；
        #   ③ **不泄漏名额/线程** —— 用"第二轮风暴照样只有 2 条 200"来证，
        #      再用 in-flight 归零 + 线程数回基线兜一道。
        # ⚠️ 离线打桩：只打 127.0.0.1 上自己起的那个服务，正式目录一个字节不动。
        # ══════════════════════════════════════════════════════════════
        class _SlowHandler(server.Handler):
            """把每条请求拖住 0.7 秒 —— 好让"同时打进来"这件事真的发生。"""

            def do_GET(self):
                time.sleep(0.7)
                self._text("ok")

        _gate = server.GatedServer(("127.0.0.1", 0), _SlowHandler, max_concurrent=2)
        threading.Thread(target=_gate.serve_forever, daemon=True).start()
        _gurl = "http://127.0.0.1:%d/anything" % _gate.server_address[1]
        _threads_before = threading.active_count()

        def _storm(n):
            """n 条**同时**发出去（Barrier 保证"同时"）；返回 `[(码, 头, 正文), …]`。"""
            out, lk = [], threading.Lock()
            start = threading.Barrier(n)

            def one():
                try:
                    start.wait(timeout=10)
                except Exception:
                    pass
                try:
                    with _urq.urlopen(_gurl, timeout=15) as r:
                        c, h, b = r.status, dict(r.headers), r.read()
                except urllib.error.HTTPError as e:
                    c, h, b = e.code, dict(e.headers or {}), e.read()
                except Exception as e:
                    c, h, b = -1, {}, repr(e).encode()
                with lk:
                    out.append((c, h, b))

            ts = [threading.Thread(target=one) for _ in range(n)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=25)
            return out

        def _plain():
            try:
                with _urq.urlopen(_gurl, timeout=15) as r:
                    return r.status, r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8", "replace")

        try:
            ok &= _ck(_gate.max_concurrent == 2 and _gate.rejected() == 0,
                      "并发闸：上限是按参数配的（自检用 2；正式那份读 config 的 maxConcurrent）")
            # 先把一条正常请求打过去 —— 没满的时候**一点没受影响**
            _c1, _b1 = _plain()
            ok &= _ck(_c1 == 200 and _b1.strip() == "ok",
                      "并发闸：没满的时候正常请求照旧 200（用户点名要的「正常请求不受影响」）",
                      "HTTP %s ｜ %r" % (_c1, _b1[:20]))

            _r1 = _storm(6)
            _codes1 = sorted(c for c, _h, _b in _r1)
            # ⚠️ Windows 回环上偶尔有一条压根没连上（码 = -1）：那也是"没放进来" ✓
            #    这条断言要的是"**最多** 2 条进得来"，-1 不算违规 ✗
            ok &= _ck(_codes1.count(200) == 2
                      and all(c in (503, -1) for c in _codes1 if c != 200),
                      "并发闸：上限 2、同时来 6 条 → 最多 2 条 200，其余 503（或被拒）",
                      "码 = %s" % _codes1)
            _rej = [(h, b) for c, h, b in _r1 if c == 503]
            ok &= _ck(bool(_rej) and all(b == b"" for _h, b in _rej),
                      "并发闸：503 一律**空正文**（不给她/对方塞任何一句话）")
            ok &= _ck(all(str(h.get("Retry-After") or "") == "1" for h, _b in _rej),
                      "并发闸：503 带 `Retry-After: 1`（叫对方退避，别原地重试）",
                      "Retry-After = %s" % [h.get("Retry-After") for h, _b in _rej])
            ok &= _ck(_gate.rejected() == 4,
                      "并发闸：挡住的那 4 条都记了数（日志里 10 秒最多一行，别写爆）",
                      "rejected=%d" % _gate.rejected())

            # 等上一轮的连接真的收干净（不然第二轮会因为"上一轮还没放槽"而误判）
            for _ in range(80):
                if _gate.inflight() == 0:
                    break
                time.sleep(0.05)
            ok &= _ck(_gate.inflight() == 0,
                      "并发闸：**in-flight 归零**（线程干完就还名额，不泄漏）",
                      "inflight=%d" % _gate.inflight())

            # 第二轮：如果名额泄漏了，这一轮就不可能再出"2 条 200"
            _r2 = _storm(3)
            _codes2 = sorted(c for c, _h, _b in _r2)
            ok &= _ck(_codes2.count(200) == 2 and _codes2.count(503) == 1,
                      "并发闸：第二轮暴雨仍是 **2 条 200 + 1 条 503** = 名额一条没漏",
                      "码 = %s" % _codes2)
            time.sleep(0.6)
            ok &= _ck(_gate.inflight() == 0,
                      "并发闸：第二轮跑完 in-flight 照样归零",
                      "inflight=%d" % _gate.inflight())
            ok &= _ck(threading.active_count() <= _threads_before + 1,
                      "并发闸：**线程数回到基线**（没有留下一堆僵尸线程）",
                      "线程 %d → %d" % (_threads_before, threading.active_count()))
            _c2, _b2 = _plain()
            ok &= _ck(_c2 == 200 and _b2.strip() == "ok",
                      "并发闸：风头过去以后正常请求照样 200（闸门不会把服务卡死）",
                      "HTTP %s ｜ %r" % (_c2, _b2[:20]))
        finally:
            _gate.shutdown()
            _gate.server_close()
        ok &= _ck("并发满了" in _read_log(),
                  "并发闸：日志里留了一行（排查用）")

        # ── 她误把"日志前缀"一起说出来（2026-09-26 用户点名的 bug）
        ok &= _ck(guards.strip_echo("主人（QQ 10001）: 哎，你来啦！我是MMZ～",
                                    names=("主人",)) == "哎，你来啦！我是MMZ～",
                  "日志前缀：`谁（QQ …）: 话` 只削前缀、她的话一个字不动")
        ok &= _ck(guards.strip_echo("张三[群名片:已放弃思考20s]: 好累啊", names=("张三",)) == "好累啊",
                  "日志前缀：`谁（群名片 …）: 话` 一样削")
        ok &= _ck(guards.strip_echo("你好呀，今天几号？") == "你好呀，今天几号？",
                  "日志前缀：正常回答一个字不动")
        ok &= _ck(guards.strip_echo("建议: 多喝水") == "建议: 多喝水",
                  "日志前缀：不认识的`词: `不误伤（只有她认识的称呼/数字/带 QQ 的括号才削）")
        ok &= _ck(guards.strip_echo("10001: 你好", names=()) == "你好",
                  "日志前缀：纯数字开头也算（那明显是日志，不是她的话）")
        # 她自己把名字当前缀写出来（用户点名要兜的）
        ok &= _ck(guards.strip_echo("MMZ: 你好呀") == "你好呀",
                  "日志前缀：她自己写「MMZ: …」也削掉")
        ok &= _ck(guards.strip_echo("MMZBOT：在的呀") == "在的呀",
                  "日志前缀：大名「MMZBOT：…」（全角冒号）一样削")
        ok &= _ck(guards.strip_echo("MMZ（QQ 10000）: 在的") == "在的",
                  "日志前缀：她的名字 + 自己的 QQ 号也削")

        # ── 运行层提示词：用户 2026-09-26 改的（删包装句和标题行、性格只留一段散文）
        sysp = persona.system_prompt()
        ok &= _ck("用户写给你的性格" not in sysp and "这个文件是给你改的" not in sysp,
                  "提示词：不再带「下面这段是用户写给你的性格」和文件标题行",
                  sysp.splitlines()[0][:30])
        ok &= _ck(("你的名字是%s" % persona.name()) in sysp,
                  "提示词：性格正文就是他写的那段散文")
        ok &= _ck(persona.name() == "MMZ" and "MMZBOT" in persona.call_names(),
                  "提示词：散文写法也能认出名字/大名（群里叫她的词）",
                  "%s / %s" % (persona.name(), "、".join(persona.call_names())))
        ok &= _ck("常识（数学" not in sysp and "改不了自己的代码" not in sysp,
                  "提示词：按用户要求删掉了那两句（常识直接答 / 改不了自己的文件）")

        # ── 触发词（用户 2026-09-27 要的独立一栏；存 runtime.json，deploy 不覆盖）
        #    · 别名只在**开头**算叫她；触发词**出现在哪儿都算**
        #    · 触发词只管把话递给她，回什么全由模型组织（没有现成回复）
        #    · **不放性格文件**（用户点名的：那是"她是谁"，会整段进提示词）
        import fgbot.llm as _llm
        _old = _llm.runtime_get("triggerWords")
        # ⚠️ 2026-10-05（用户拍板"需要只有我能调"）：`triggers` / `memory` / `mem_*` /
        #    `reset` / `effort` / `mode` / `restart` 这些**控制面动作只有主人能调**了。
        #    下面这一整段测的是"**动作本身**还能不能干活"，所以统一递一个**主人身份**进去；
        #    闸本身（非主人 → 403 空正文 / 主人 → 照旧）在 6.55 的 ③′ 那一节逐动作钉。
        _OWN_IDENT = {"id": "selftest-主人", "主人": True, "名字": "主人"}
        try:
            ok &= _ck(_llm.runtime_set("triggerWords", ["摸鱼", "好累"]),
                      "触发词：面板/App 能存进去（runtime.json）")
            ok &= _ck(persona.trigger_words() == ["摸鱼", "好累"],
                      "触发词：读得出来（config 默认 + runtime 覆盖）",
                      "、".join(persona.trigger_words()))
            ok &= _ck(agent._addressed(mk("今天又摸鱼了", group=True)),
                      "触发词：出现在**句中**也算在叫她（别名不这样）")
            ok &= _ck(not agent._addressed({"is_group": True, "text": "你好呀MMZBOT", "raw": ""}),
                      "触发词：别名出现在**句中**不算叫她（只有触发词才句中生效）")
            r_tr = agent.on_api("triggers", {"words": "摸鱼、好累、难受"}, _OWN_IDENT)
            ok &= _ck(r_tr.get("ok") and persona.trigger_words() == ["摸鱼", "好累", "难受"],
                      "触发词：控制面能改（逗号/顿号都当分隔）", str(r_tr.get("message"))[:30])
            agent.on_api("triggers", {"words": []}, _OWN_IDENT)
            ok &= _ck(persona.trigger_words() == []
                      and not agent._addressed(mk("今天又摸鱼了", group=True)),
                      "触发词：清空之后句中的词就不叫她了（空 = 一个都没有）")
            ok &= _ck(isinstance(agent.info().get("触发词"), list),
                      "触发词：/status 里带着它（面板/App 读得到）")
            # ── 触发词限流（30 秒）+ 她自己说的话不能触发她（用户点名的两条）
            _llm.runtime_set("triggerWords", ["摸鱼"])
            agent._TRIG_AT.clear()
            seen.clear()
            c_tr = mk("今天又摸鱼了", group=True)
            c_tr["key"] = ("g", 123456789)
            r1 = agent.handle(c_tr)                       # 第一次：接（会走模型，桩答一句）
            n1 = len([1 for k in seen if k == "payload"]) if seen else 0
            seen.clear()
            r2 = agent.handle(dict(c_tr))                 # 第二次：30 秒内 → 不接
            ok &= _ck(r2 is None and not [k for k in seen if k == "payload"],
                      "触发词：30 秒内连着撞同一个词，第二次不接（也不烧模型）")
            ok &= _ck(bool(agent._TRIG_AT), "触发词：接话时记下了时刻（限流用得着）")
            # 被 @ / 叫名字 / 私聊 走的是另一条路，不受这个限流
            seen.clear()
            r3 = agent.handle(mk("又摸鱼了", group=True, at=True))
            ok &= _ck(r3 is not None, "触发词限流**不**影响被 @（点名照答）")
            # 她自己发的消息（发信人 = 她自己）一律扔掉 → 她的话里带触发词也勾不动她
            seen.clear()
            me = mk("我今天在摸鱼", group=True, uid=base.self_id())
            ok &= _ck(agent.handle(me) is None and not [k for k in seen if k == "payload"],
                      "她自己说的话里有关键词 → 不触发（防自问自答打转）")
            agent._TRIG_AT.clear()
        finally:
            _llm.runtime_set("triggerWords", _old if isinstance(_old, list) else [])

        # ── B5：指定人的参数 who（2026-09-27 用户拍板加的）+ A3/A6：工具合并（2026-10-30）
        qq_me, qq_other = "10001", "30003"
        ctx_b5 = mk("随便说点什么", uid=int(qq_me))
        # 1) memory 带 text + who → 记到**那个人**名下，且不顺手记到说话人名下
        toolkit.call("memory", {"text": "他喜欢喝美式", "who": qq_other}, ctx_b5)
        _f_other = json.dumps(memory.facts_of(qq_other), ensure_ascii=False)
        _f_me = json.dumps(memory.facts_of(qq_me), ensure_ascii=False)
        ok &= _ck("美式" in _f_other and "美式" not in _f_me,
                  "B5：memory(text=…) 带 who → 记在那个人名下（当前说话人名下没有）")
        # 2) 不带 who → 老行为：记在当前说话人名下
        toolkit.call("memory", {"text": "他喜欢喝拿铁"}, ctx_b5)
        ok &= _ck("拿铁" in json.dumps(memory.facts_of(qq_me), ensure_ascii=False),
                  "B5：不带 who → 还是记在当前说话人名下（老行为不变）")
        # 3) who 是个查不到的名字 → 给人话，什么都不写
        _r = toolkit.call("memory", {"text": "别写进去", "who": "查无此人张三"}, ctx_b5)
        ok &= _ck(_r.get("ok") is False and "没找到" in str(_r.get("error"))
                  and "别写进去" not in json.dumps(memory.all_people(), ensure_ascii=False),
                  "B5：who 查不到 → 人话报错、一个字都不写", str(_r.get("error"))[:26])
        # 3b) text 留空 = 查（同一个工具两用）；返回形状还是老那三种
        _rq = toolkit.call("memory", {"who": qq_other}, ctx_b5)
        ok &= _ck(_rq.get("ok") is True and _rq.get("一共") == len(memory.facts_of(qq_other)),
                  "B5：memory(text 留空) → 查（形状还是「一共 / 记着他这些」）", str(_rq)[:60])
        # 4) callname 带 who：填 name = 定称呼，留空 = 取消
        toolkit.call("callname", {"name": "张三", "who": qq_other}, ctx_b5)
        ok &= _ck(memory.display_name(qq_other, False) == "张三",
                  "B5：callname 带 who → 给那个人定称呼")
        ok &= _ck(memory.display_name(qq_me, False) != "张三",
                  "B5：callname 带 who 时不会把称呼按到说话人头上")
        _cn = toolkit.call("callname", {"who": qq_other}, ctx_b5)
        ok &= _ck(_cn.get("ok") and memory.display_name(qq_other, False) != "张三",
                  "B5：callname 的 name 留空 = 取消那个人的称呼")
        # 5) 唤醒：设 / 列 / 取消（A3：remind + reminders 合成一个 wake）
        _r = toolkit.call("wake", {"when": "20分钟后", "note": "喝水"}, ctx_b5)
        ok &= _ck(_r.get("ok") is True and _r.get("在哪说") == "当前会话"
                  and set(_r) == {"ok", "编号", "时刻", "醒来做什么", "还有", "在哪说"},
                  "B5：wake 留空 action = 定一个新的（返回键 = 第 7 条那五个）", str(_r))
        _rid = _r.get("编号")
        _list = toolkit.call("wake", {"action": "列"}, ctx_b5)
        ok &= _ck(any(i["编号"] == _rid for i in (_list.get("还没响的") or [])),
                  "B5：wake(action=列) → 列表里有它（键名「醒来做什么 / 在哪说」）")
        ok &= _ck(all(set(i) == {"编号", "时刻", "醒来做什么", "还有", "在哪说"}
                      for i in (_list.get("还没响的") or [])),
                  "B5：列表每一行的键名 = 第 7 条那五个")
        _c = toolkit.call("wake", {"action": "取消", "id": str(_rid)}, ctx_b5)
        ok &= _ck(_c.get("ok") and _c.get("取消了"),
                  "B5：wake(action=取消, id=…) → 撤掉那一条")
        _after = toolkit.call("wake", {"action": "列"}, ctx_b5)
        ok &= _ck(not any(i["编号"] == _rid for i in (_after.get("还没响的") or [])),
                  "B5：取消之后，那一条就不在列表里了（别的唤醒不受影响）")
        # 6) wake 的 where：填人 = 醒来私聊他；note 留空 = 那句「没说醒来要干什么」
        memory.remember_name(qq_other, "张三")      # 上一段刚取消过称呼（显示名要有名字）
        _r2 = toolkit.call("wake", {"when": "20分钟后", "note": "看看他", "where": qq_other},
                           ctx_b5)
        ok &= _ck(_r2.get("ok") and _r2.get("在哪说") == "私聊 张三",
                  "B5：wake 的 where 填人 → 醒来私聊他", str(_r2.get("在哪说")))
        toolkit.call("wake", {"action": "取消", "id": str(_r2.get("编号"))}, ctx_b5)
        _r3 = toolkit.call("wake", {"when": "20分钟后"}, ctx_b5)
        ok &= _ck(_r3.get("ok") is False and _r3.get("error") == "没说醒来要干什么 ",
                  "B5：note 留空 → 逐字回第 7 条那句（结尾那个空格也照原样）",
                  repr(_r3.get("error")))
        ok &= _ck(all(n not in [t["name"] for t in toolkit.TOOLS]
                      for n in ("remind", "reminders", "call_me", "forget_call_name",
                                "remember", "fix_memory", "cancel_reminder")),
                  "B5：旧工具名一个都不在了（remind / reminders / call_me / "
                  "forget_call_name / remember / fix_memory / cancel_reminder）")

        # ── 控制面：记忆的读和写（网页面板 / 手机 App 上编辑用）
        #    ⚠️ 从这一行起统一带 `_OWN_IDENT`（2026-10-05 起这些动作只有主人能调）
        r_mem = agent.on_api("memory", {}, _OWN_IDENT)
        ok &= _ck(r_mem and r_mem.get("ok") and isinstance(r_mem.get("memory"), list),
                  "记忆接口：能列出整份库（带 QQ / 称呼 / 每一条 / 时间）")
        ok &= _ck(agent.on_api("mem_add", {"qq": "10001", "text": "面板加的测试条"},
                               _OWN_IDENT)["ok"],
                  "记忆接口：能加一条")
        ok &= _ck(agent.on_api("mem_fix", {"qq": "10001", "old": "面板加的测试条",
                                           "new": "面板改过的测试条"}, _OWN_IDENT)["ok"],
                  "记忆接口：能改一条")
        ok &= _ck(agent.on_api("mem_del", {"qq": "10001", "old": "面板改过的测试条"},
                               _OWN_IDENT)["ok"],
                  "记忆接口：能删一条")
        # 整条原文改：只许动那一条（不然「住在苏州」会把「现在住在苏州」一起改掉）
        memory.add_fact("10001", "住在苏州")
        memory.add_fact("10001", "现在住在苏州")
        agent.on_api("mem_fix", {"qq": "10001", "old": "住在苏州", "new": "住苏州"},
                     _OWN_IDENT)
        left = memory.facts_of("10001")
        ok &= _ck("住苏州" in left and "现在住在苏州" in left,
                  "记忆接口：给的是一条的原文时，只动那一条（不误伤长得像的）")
        for f in ("住苏州", "现在住在苏州"):
            memory.fix_fact("10001", f)
        # 加人 / 删人 / 昵称落库（面板上的气泡就靠这几个）
        ok &= _ck(agent.on_api("mem_person_add", {"qq": "2222222222", "name": "临时人"},
                               _OWN_IDENT)["ok"],
                  "记忆接口：能加一个人（面板的「＋ 加人」）")
        ok &= _ck(any(p["qq"] == "2222222222" and p["name"] == "临时人"
                      for p in agent.on_api("memory", {}, _OWN_IDENT)["memory"]),
                  "加完在列表里看得到")
        ok &= _ck(agent.on_api("mem_person_del", {"qq": "2222222222"}, _OWN_IDENT)["ok"],
                  "记忆接口：能整块删掉一个人")
        ok &= _ck(not any(p["qq"] == "2222222222"
                          for p in agent.on_api("memory", {}, _OWN_IDENT)["memory"]),
                  "删完就不在列表里了")
        memory.touch("3333333333", "小昵称", "小名片", "777000111")
        rec3 = [p for p in agent.on_api("memory", {}, _OWN_IDENT)["memory"]
                if p["qq"] == "3333333333"]
        ok &= _ck(rec3 and rec3[0]["nick"] == "小昵称"
                  and rec3[0]["cards"] == {"777000111": "小名片"}
                  and rec3[0]["card"] == "小名片（群 777000111）",
                  "昵称：消息进来时会把 QQ 昵称/**那个群的**群名片落库"
                  "（名片按群存；气泡那份由它拼出来）",
                  json.dumps(rec3[0] if rec3 else {}, ensure_ascii=False)[:120])
        ok &= _ck(memory.touch("3333333333", "小昵称", "小名片", "777000111") is False,
                  "昵称没变就不重复写盘（每条消息都会调它）")
        me_p = [p for p in agent.on_api("memory", {}, _OWN_IDENT)["memory"]
                if p["qq"] == str(base.self_id())]
        ok &= _ck(me_p and (me_p[0]["nick"] or me_p[0]["name"]),
                  "她自己那块有名字（气泡上不会是一串光秃秃的 QQ 号）")
        after = [f for p in agent.on_api("memory", {}, _OWN_IDENT)["memory"] for f in p["facts"]]
        ok &= _ck(not any("面板" in f for f in after), "记忆接口：删完库里真的没有了")
        ok &= _ck(agent.on_api("mem_name", {"qq": "1111111111", "name": "临时称呼"},
                               _OWN_IDENT)["ok"],
                  "记忆接口：能改称呼")
        ok &= _ck(agent.on_api("mem_name", {"qq": "1111111111", "name": ""},
                               _OWN_IDENT)["ok"],
                  "记忆接口：称呼留空 = 清掉")
        r_res = agent.on_api("restart", {}, _OWN_IDENT)
        ok &= _ck(r_res and r_res.get("ok") and os.path.isfile(store.path("restart.txt")),
                  "控制面：面板的「重启她」= 留 restart.txt（让看门狗办，她不自杀）")
        html = panel.render("TOKEN-XYZ")
        ok &= _ck("TOKEN-XYZ" not in html and "__TOKEN__" not in html,
                  "面板：渲染时**不再往里塞 token**（A5；token 由用户在浏览器里粘一次）")
        ok &= _ck(("记忆" in html) and ("mem_add" in html) and ("mem_name" in html),
                  "面板：带记忆编辑（加/改/删/称呼）")
        # 注意别用 "mode" 当关键词 —— "model" 里就有它（这条断言第一版就踩了）
        ok &= _ck(not any(w in html for w in ("人格", "灵珠", "魔丸")),
                  "面板：没有切换人格那套残留")
        ok &= _ck(html.count("<script") == html.count("</script>") and
                  html.count("<style") == html.count("</style>"), "面板：HTML 结构闭合")
        # 面板按这些字段渲染气泡和详情，少一个都会显示成空白
        need = {"qq", "name", "nick", "card", "facts", "at"}
        ok &= _ck(all(need <= set(p) for p in agent.on_api("memory", {}, _OWN_IDENT)["memory"]),
                  "记忆接口：每个人带着面板要用的字段（qq/称呼/昵称/群名片/记忆/时间）")

        # ── 「记忆」页那一列的显示口径（用户 2026-10-05 定的）────────────────
        #    左列**三级降级**：称呼 → 昵称 → QQ 号；右侧固定 QQ 号；详情头部齐全。
        #    ⚠️ 这段逻辑跑在**浏览器**里，手机侧没有 node 能执行它 —— 所以这里把
        #       发出去的那段 JS 抠出来**逐字核**（谁改了那几行，这条断言就红）。
        import re as _re                              # 别用 `re`：本函数后面还有一个
                                                      # `import re`，同作用域会更早 UnboundLocal

        def _js(fn):
            """从面板 HTML 里抠出 `function fn(...){…}` 的正文（按大括号配对）。"""
            i = html.index("function %s(" % fn)
            j = html.index("{", i)
            depth, k = 0, j
            while k < len(html):
                if html[k] == "{":
                    depth += 1
                elif html[k] == "}":
                    depth -= 1
                    if depth == 0:
                        return html[j + 1:k]
                k += 1
            return ""

        def _code(s):
            """去掉注释和空白只留代码 —— 断言别被注释里的字带偏。"""
            return _re.sub(r"\s+", " ", _re.sub(r"/\*.*?\*/", "", s, flags=_re.S)).strip()

        _lab = _code(_js("labelOf"))
        ok &= _ck(_lab == "return p.name || p.nick || p.qq;",
                  "面板·记忆页：左列**三级降级**（称呼 → 昵称 → QQ 号）", _lab)
        ok &= _ck("var sub = p.qq;" in _code(_js("renderPeople")),
                  "面板·记忆页：右侧固定显示 **QQ 号**（昵称不再占右边那格）")
        _mt = _code(_js("matchP"))
        ok &= _ck(all(("p.%s" % f) in _mt for f in ("name", "nick", "card", "qq"))
                  and "p.facts" in _mt,
                  "面板·记忆页：搜索覆盖 称呼/昵称/群名片/QQ 号/记忆内容 五种写法")
        _dt = _code(_js("drawDetail"))
        ok &= _ck(all(('meta.push("%s：' % w) in _dt
                       for w in ("称呼", "昵称", "群名片", "QQ", "更新")),
                  "面板·记忆页：详情头部 称呼/昵称/群名片/QQ/更新 齐全（缺的那项不显示）")
        ok &= _ck('placeholder="搜索称呼、昵称、群名片、QQ 或记忆"' in html,
                  "面板·记忆页：搜索框占位写了五种")
        # `显示名` 那颗雷（2026-10-05 修）：记忆那块数据的形状是 `{"qq","name"…}`，
        # 直接喂给 `who.display_name()` 会**解析不出 QQ 号**（它读的是 `主人QQ`），
        # 四级兜底全落空 → `显示名` 永远等于那串裸 QQ 号（面板左列就只剩一串数字）。
        memory.ensure_person("4444444444")
        memory.remember_name("4444444444", "三十三")
        _row = [p for p in agent.on_api("memory", {}, _OWN_IDENT)["memory"]
                if p["qq"] == "4444444444"]
        ok &= _ck(bool(_row) and _row[0]["显示名"] == "三十三",
                  "记忆接口：`显示名` 先按 QQ 号回查用户表再算（有称呼就给称呼，不再是裸 QQ 号）",
                  (_row or [{}])[0].get("显示名"))
        memory.forget_person("4444444444")

        # ── 控制面（⚠️ 这些动作 2026-10-05 起**只有主人能调** → 这里统一递主人身份）
        out = agent.on_api("reset", {}, _OWN_IDENT)
        ok &= _ck(out and out.get("ok") and not memory.threads(), "控制面 reset：对话记忆清空")
        ok &= _ck(agent.on_api("不存在的动作", {}, _OWN_IDENT) is None,
                  "不认识的 action 返回 None（server 回 501）")
        # 思考强度：手机改的存 runtime.json（deploy 不覆盖）
        e1 = agent.on_api("effort", {"value": "max"}, _OWN_IDENT)
        ok &= _ck(e1 and e1.get("ok") and llm.connection()["effort"] == "max",
                  "控制面 effort：能改思考强度", str(e1.get("message"))[:34])
        ok &= _ck(llm.connection()["effort_from"] == "手机改的",
                  "改完记在 runtime.json 里（不是 config.json，deploy 顶不掉）")
        ok &= _ck(not agent.on_api("effort", {"value": "超高"}, _OWN_IDENT)["ok"],
                  "effort：乱填的强度会被拒")
        agent.on_api("effort", {"value": "high"}, _OWN_IDENT)
        ok &= _ck(llm.connection()["effort"] == "high", "effort：改回 high")
        m = agent.on_api("mode", {}, _OWN_IDENT)
        ok &= _ck(m is not None and m.get("ok") is False and "人格" in (m.get("message") or ""),
                  "控制面 mode：明确回「v2 没有人格切换」（老 App 发了也不会一头雾水）")
        inf = agent.info()
        ok &= _ck(inf.get("ready") is True and "apis" in inf, "info() 给面板的状态齐")
        blob = json.dumps(inf, ensure_ascii=False)
        key_now = llm.connection()["key"]
        ok &= _ck(not key_now or key_now not in blob, "info() 里**没有**明文 key")

        # ══════════════════════════════════════════════════════════════
        # 6.6 语义召回（`memory` 那个工具的 `ask`）
        #
        # ⚠️ 这一节**不许联网、不许加载真模型**：
        #    · 曲线 / tiebreak / 三种形状 / 自愈 —— 全部用**假 embedder** 跑真代码路径
        #    · 真模型那一条**只测「能不能加载 + 出不出 512 维单位向量」**，而且
        #      模型不在（或装不上）时**跳过**，不算失败
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.6 语义召回"
        print("=== 6.6 语义召回 ===")
        import re
        from fgbot import embed, semantic, vecstore, recall as recall_mod

        # ── 系数：必须和 POC 调好的那套一致（instruct+A 形态的解）
        ok &= _ck((semantic.THETA, semantic.P, semantic.C, semantic.N_MAX,
                   semantic.S_MIN_SEND) == (0.30, 2.0, 0.08, 10, 0.42),
                  "条数曲线的系数是 POC 定的那套",
                  "θ=%s p=%s c=%s n_max=%s s_min=%s" % (semantic.THETA, semantic.P,
                                                        semantic.C, semantic.N_MAX,
                                                        semantic.S_MIN_SEND))
        # 查询要加 BGE 指令前缀（加前缀后排名更好、无关查询天花板更低）
        ok &= _ck(embed.QUERY_INSTRUCTION == "为这个句子生成表示以用于检索相关文章：",
                  "查询带 BGE 指令前缀")
        ok &= _ck(semantic.TIE_WINDOW == 0.05, "tiebreak 窗口是 0.05")

        # ── 曲线：POC 的四个锚点（instruct+A 实测工作点 mid/high/vhigh）
        for ss, want, note in (([0.05, 0.11], 0, "全都非常低 → 0 条"),
                               ([0.44], 1, "一条中等 → 1 条"),
                               ([0.53] * 5, 3, "五条都高 → 3 条"),
                               ([0.60] * 10, 10, "十条非常高 → 10 条"),
                               ([0.60] * 20, 10, "二十条非常高 → 封顶 10 条")):
            got = semantic.how_many(ss)
            ok &= _ck(got == want, "曲线：%s" % note, "want %d got %d" % (want, got))
        ok &= _ck(semantic.how_many([0.43]) == 1, "兜底门槛：算出 0 但最高分 ≥0.42 → 回 1 条")
        ok &= _ck(semantic.how_many([0.41]) == 0, "最高分 <0.42 → 0 条（回「没找到相关的」）")

        # ── tiebreak：旧事实 vs 新事实（向量治不了这个）
        tf = ["住在杭州", "住在青岛"]
        got = semantic.select(tf, [0.72, 0.69], [1000.0, 2000.0])
        ok &= _ck(got and got[0][0] == "住在青岛",
                  "tiebreak：分数差 0.03（<0.05）→ **新的**「住在青岛」排前面",
                  str([x[0] for x in got]))
        got = semantic.select(tf, [0.90, 0.60], [1000.0, 2000.0])
        ok &= _ck(got and got[0][0] == "住在杭州", "tiebreak：分数差 0.30（>0.05）→ 还是分数说话")
        got = semantic.select(tf, [0.72, 0.69], None)
        ok &= _ck(got and got[0][0] == "住在青岛",
                  "tiebreak：老数据没有时间戳 → 不是报错，退回写入顺序（后写的在前）")
        got = semantic.select(tf, [0.72, 0.69], [0, 0])
        ok &= _ck(got and got[0][0] == "住在青岛", "tiebreak：时间是 0 也一样，不报错")
        # ⚠️ 这条是**回归测试**：时间戳一样时必须靠写入顺序（下标大的更新）。
        #    老记忆第一次补算向量时，一次补算里的几条拿到的是同一个时间戳 ——
        #    第一版就是栽在这里（靠"稳定排序保序"，结果保成了旧的在前）。
        t_same = [1790557564.0] * 2
        got = semantic.select(tf, [0.70, 0.668], t_same)
        ok &= _ck(got and got[0][0] == "住在青岛",
                  "tiebreak：**时间戳一样**时后写的（下标大）排前面",
                  str([x[0] for x in got]))
        got = semantic.select(tf, [0.70, 0.668], t_same, seq=[1, 0])
        ok &= _ck(got and got[0][0] == "住在杭州",
                  "tiebreak：seq 显式给的时候按 seq 走")

        # ── 旁挂文件：向量和时间戳，绝不进 memory.json
        fake = embed.FakeEmbedder()
        vq = "10001"
        vfacts = ["住在杭州", "住在青岛", "喜欢喝美式咖啡"]
        vecs = fake.encode_facts(vfacts)
        vecstore.put(vq, vfacts, vecs)
        v_now, t_now = vecstore.load_for(vq, vfacts)
        ok &= _ck(all(v_now) and all(t_now) and len(v_now[0]) == 512,
                  "向量旁挂：写进去能读回来（512 维 + 时间戳）")
        # 面板/App 直接改 memory.json 的一条 → 只有那一条该失效
        v_fix, t_fix = vecstore.load_for(vq, ["住在苏州", "住在青岛", "喜欢喝美式咖啡"])
        ok &= _ck(v_fix[0] is None and all(v_fix[1:]),
                  "旁挂自愈：改过的那条向量自动作废，没动过的不重算")
        ok &= _ck(all(k not in json.dumps(memory.record_of(vq), ensure_ascii=False)
                      for k in ("向量", "指纹")),
                  "向量**没有**塞进 memory.json（面板/App 在读它）")
        ok &= _ck(isinstance((memory.record_of(vq) or {}).get("facts"), list)
                  and all(isinstance(x, str) for x in memory.record_of(vq)["facts"]),
                  "memory.json 的 facts 仍然是**字符串数组**（形状没动）")

        # ── 模型指纹 + 配方版本：换了模型/改了配方，旧向量必须作废
        #    为什么要有这一级：不然旧向量会被继续用，**分数悄悄变坏而且不报错**。
        # 先测**真的** `fingerprint()`：造个假模型目录，改一个文件的大小 → 指纹必须变
        mfd = os.path.join(tmp, "models", "bge-small-zh-v1.5-onnx")
        os.makedirs(os.path.join(mfd, "onnx"), exist_ok=True)
        for rel, n in ((embed.ONNX_REL, 100), (embed.DATA_REL, 200),
                       (embed.TOKENIZER_REL, 300)):
            with open(os.path.join(mfd, rel), "wb") as fh:
                fh.write(b"x" * n)
        embed.set_model_dir(mfd)
        fp1 = embed.fingerprint()
        ok &= _ck(fp1 == ("model_quantized.onnx:100|model_quantized.onnx_data:200"
                          "|tokenizer.json:300"),
                  "模型指纹 = 三个文件的名字+大小拼成的", str(fp1))
        ok &= _ck(embed.stamp() == (fp1, embed.VEC_VERSION),
                  "stamp = (模型指纹, 配方版本)", str(embed.stamp()))
        with open(os.path.join(mfd, embed.DATA_REL), "wb") as fh:
            fh.write(b"x" * 201)                     # 相当于换了个模型
        embed.reset()                                 # 清掉按进程缓存的那个指纹
        ok &= _ck(embed.fingerprint() != fp1, "换了模型文件 → 指纹跟着变")
        embed.set_model_dir(os.path.join(tmp, "这里没有模型"))
        ok &= _ck(embed.stamp() is None,
                  "拿不到指纹（模型不在）→ stamp 给 None，调用方必须维持现状")
        embed.set_model_dir(None)                     # 恢复真目录，后面要测真模型

        # 戳不一致 → **整份**作废（连别人的一起清，不然下次 put 会把旧向量认证成新的）
        s_a = ("指纹A", embed.VEC_VERSION)
        s_b = ("指纹B", embed.VEC_VERSION)
        s_c = ("指纹B", embed.VEC_VERSION + 1)
        va = fake.encode_facts(["住在北京"])
        vecstore.put("2222222222", ["住在北京"], va, stamp=s_a)
        vecstore.put(vq, vfacts, vecs, stamp=s_a)
        ok &= _ck(all(vecstore.load_for(vq, vfacts, s_a)[0]),
                  "指纹一致 → 复用（不重算）")
        vecstore.load_for(vq, vfacts, s_b)            # 触发整份作废
        ok &= _ck(not any(vecstore.load_for(vq, vfacts, s_b)[0]),
                  "模型指纹不一致 → 这个人的向量作废")
        ok &= _ck(not any(vecstore.load_for("2222222222", ["住在北京"], s_b)[0]),
                  "整份作废：**别人名下的**向量也一起清了")
        vecstore.put(vq, vfacts, vecs, stamp=s_b)
        ok &= _ck(all(vecstore.load_for(vq, vfacts, s_b)[0]), "换完指纹重新算过 → 又能复用")
        vecstore.load_for(vq, vfacts, s_c)            # 配方版本变了
        ok &= _ck(not any(vecstore.load_for(vq, vfacts, s_c)[0]),
                  "**配方版本**不一致 → 同样作废重算")
        vecstore.put(vq, vfacts, vecs, stamp=s_c)
        ok &= _ck(all(vecstore.load_for(vq, vfacts, None)[0]),
                  "模型不可用（stamp=None）→ **不清空**，向量还在")
        ok &= _ck(vecstore.current_stamp() == s_c,
                  "stamp=None 也不会把戳改掉", str(vecstore.current_stamp()))

        # ── 真代码路径 + 假 embedder：曲线/tiebreak/三种形状都走一遍
        real_get = embed.get_embedder
        real_stamp = embed.stamp
        try:
            embed.get_embedder = lambda: fake
            store.set_dir(tmp)
            memory.forget_person(vq)
            memory.add_fact(vq, "住在杭州")
            memory.add_fact(vq, "住在青岛")
            memory.add_fact(vq, "喜欢喝美式咖啡")
            cx = mk("MMZ", uid=int(vq))

            r = toolkit.call("memory", {}, cx)
            ok &= _ck(r == {"ok": True, "一共": 3,
                            "记着他这些": ["住在杭州", "住在青岛", "喜欢喝美式咖啡"]},
                      "形状③ 没填 `ask` → 全部（逐字对）", str(r))
            r = toolkit.call("memory", {"ask": "量子纠缠退相干"}, cx)
            ok &= _ck(r == {"ok": True, "一共": 3, "没找到相关的": True},
                      "形状② 完全无关 → 「没找到相关的」（逐字对）", str(r))
            hit = None
            for q in ("喜欢喝美式咖啡", "住在青岛", "住在杭州"):
                rr = toolkit.call("memory", {"ask": q}, cx)
                if rr.get("这几条"):
                    hit = rr
                    break
            ok &= _ck(hit is not None and hit.get("ok") is True and hit.get("一共") == 3
                      and all(isinstance(x, str) for x in hit.get("这几条") or []),
                      "形状① 对上了 → 只回这几条", str(hit))
            ok &= _ck(all("这几条" not in toolkit.call("memory", {}, cx) for _ in (0,)),
                      "形状③ 里没有「这几条」这个键")
            # 绝不给她相似度数字
            blob2 = json.dumps([toolkit.call("memory", {}, cx),
                                toolkit.call("memory", {"ask": "量子纠缠退相干"}, cx),
                                hit], ensure_ascii=False)
            ok &= _ck(not re.search(r"\d\.\d{2,}", blob2),
                      "三种形状里**一个相似度数字都没有**")

            # 降级：模型用不了 → 退回「全部给她」，而且不报错
            embed.get_embedder = lambda: None
            r = toolkit.call("memory", {"ask": "他喜欢喝什么"}, cx)
            ok &= _ck(r == {"ok": True, "一共": 3,
                            "记着他这些": ["住在杭州", "住在青岛", "喜欢喝美式咖啡"]},
                      "降级：模型用不了 → 退回「把这个人的全部记忆给她」，不报错", str(r))
            # 降级：工具不抛异常（pick 返回 (None, True)）
            ok &= _ck(recall_mod.pick(vq, ["住在杭州"], "他住哪") == (None, True),
                      "降级：recall.pick 明确回 (None, True)")

            # ── 换了模型 / 改了配方：**走真代码路径**，自动作废重算、结果照常
            embed.get_embedder = lambda: fake
            embed.stamp = lambda: ("指纹A", embed.VEC_VERSION)
            q_hit = "喜欢喝美式咖啡"
            base_r = toolkit.call("memory", {"ask": q_hit}, cx)
            ok &= _ck(base_r.get("这几条")
                      and vecstore.current_stamp() == ("指纹A", embed.VEC_VERSION),
                      "第一次 memory 查询把「模型指纹+配方」写进了向量文件", str(base_r))
            n0 = fake.fact_batches
            ok &= _ck(toolkit.call("memory", {"ask": q_hit}, cx) == base_r
                      and fake.fact_batches == n0,
                      "指纹没变 → **复用**，一条都不重算")

            embed.stamp = lambda: ("指纹B", embed.VEC_VERSION)   # 换模型
            n1 = fake.fact_batches
            ok &= _ck(toolkit.call("memory", {"ask": q_hit}, cx) == base_r,
                      "换了模型指纹 → 结果照常返回（没报错、没降级）")
            ok &= _ck(fake.fact_batches > n1,
                      "换了模型指纹 → **真的重算了**（不是拿旧向量接着用）")
            ok &= _ck(vecstore.current_stamp() == ("指纹B", embed.VEC_VERSION),
                      "戳跟着更新成新的", str(vecstore.current_stamp()))

            embed.stamp = lambda: ("指纹B", embed.VEC_VERSION + 1)   # 改配方
            n2 = fake.fact_batches
            ok &= _ck(toolkit.call("memory", {"ask": q_hit}, cx) == base_r
                      and fake.fact_batches > n2,
                      "改了配方版本 → 同样自动作废重算，结果照常")

            # 模型不可用：拿不到指纹 → **维持现状**，不清空、也不重算
            n3, rows3 = fake.fact_batches, vecstore.stats()["条"]
            embed.stamp = lambda: None
            ok &= _ck(toolkit.call("memory", {"ask": q_hit}, cx) == base_r,
                      "拿不到指纹（stamp=None）→ 照常返回")
            ok &= _ck(fake.fact_batches == n3 and vecstore.stats()["条"] == rows3,
                      "拿不到指纹 → 向量**没被清空、也没被重算**（维持现状）")
        finally:
            embed.get_embedder = real_get
            embed.stamp = real_stamp

        # ── 真模型：**只测能不能加载 + 出不出 512 维单位向量**（模型不在就跳过）
        ok &= _ck(embed.QUERY_INSTRUCTION.startswith("为这个句子"),
                  "查询前缀没被自检改掉")
        mdir = embed.model_dir()
        if os.path.isfile(os.path.join(mdir, embed.ONNX_REL)):
            embed.reset()
            emb = embed.get_embedder()
            ok &= _ck(emb is not None,
                      "真模型：加载得上（拿不到就说明手机上的 onnxruntime/模型有问题）",
                      embed.why_not())
            if emb is not None:
                v = emb.encode_query("他住在哪个城市")
                n = sum(float(x) * float(x) for x in v) ** 0.5
                ok &= _ck(len(v) == 512, "真模型：输出 512 维", str(len(v)))
                ok &= _ck(abs(n - 1.0) < 1e-3, "真模型：输出是单位向量", "norm=%.6f" % n)
                # 查询逐条编码（动态量化对这个敏感，批里混长句整批都会变）
                a = emb.encode_query("他住在哪个城市")
                b = emb.encode_query("他住在哪个城市")
                ok &= _ck(all(float(x) == float(y) for x, y in zip(a, b)),
                          "真模型：同一条查询编两次逐位相同")
            embed.reset()
        else:
            print("  ⚠️ 跳过真模型那条（%s 里没有模型文件）—— 手机上会测到" % mdir)
        # ── ① 等超时 ≠ 丢掉：迟到的回复也要发出去（2026-10-02 用户点名的 bug）────
        #    现场：handle() 等 maxWaitSeconds 一到就 return None → server.py 静默不发，
        #    而后台 job 后来算出来的话**永久丢了**（bot.log 3254-3258 那条 45 分钟的）。
        #    修法：前台超时先走（回 LATE_PENDING，什么都不发），后台算完**自己补发**。
        #    这里全程打桩、离线：假传输层 + 假发送回调。
        #
        #    ⚠️ 这一段从前是**时序型**断言（2026-10-03 修）：它靠"后台那条恰好在 1 秒
        #       上下算完"来分岔 —— 本机实测 20 次里 11 次判成"前台等到了"（`fg=None`），
        #       而 deploy 第②步是"自检非 0 就中止" → **部署随机中止**、要人重跑。
        #       现在后台那条**卡在门闸（threading.Event）上**：测试不放闸它一个字都算不
        #       出来，于是"前台等不到"是**确定**发生的，不是赌那 1 秒里谁快谁慢；
        #       所有"等一等再看"的地方一律等**事件**（后台那条路走完的同步点），
        #       不睡固定秒数 —— 睡固定秒数的断言换台机器/换次负载就可能翻脸。
        print()
        _CUR_SECT[0] = "6c. 超时之后迟到的回复（打桩、离线）"
        print("=== 6c. 超时之后迟到的回复（打桩、离线）===")
        print("  先验一件更要紧的事：自检里发生的「收到一条消息」**绝不会真的发出去**")
        _sent = []
        _real_send_g, _real_send_p = im.send_group, im.send_private
        im.send_group = lambda *a, **kw: (_sent.append(("群", a, kw)), True)[1]
        im.send_private = lambda *a, **kw: (_sent.append(("私聊", a, kw)), True)[1]
        _stub_reply = {"text": "收到了，我在。"}
        # 后台那条要卡住的门闸：None = 不卡（照常立刻回）。测试自己 `set()` 放行 ——
        # 「前台先走 / 后台后算完」这个**次序由测试摆死**，不靠睡多久去撞。
        _hold = {"ev": None}
        # 后台那条迟到路径的**同步点**：`_late_reply` 整条（含补发）走完才记这一笔。
        # 等它就是"等事件"，不是"睡 1.4 秒看看"。
        _late_done = []
        _real_late = agent._late_reply

        def _late_probe(ctx, item, reply, send):
            try:
                return _real_late(ctx, item, reply, send)
            finally:
                _late_done.append(item)

        def _stub_llm(url, payload, headers, timeout):
            ev = _hold["ev"]
            if ev is not None:
                ev.wait(30)          # 事件同步：不放闸就不往下走（原来这里是 sleep(1.2)）
            if _stub_reply["text"] == "慢":
                c = "收到了，我在。"
            else:
                c = _stub_reply["text"]
            return {"model": "stub", "choices": [{"index": 0, "finish_reason": "stop",
                                                  "message": {"role": "assistant", "content": c}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        def _settle_late(what):
            """等后台那条迟到路径**走完**（补发认领完）。返回 (等到没, 说明)。

            为什么必须有这个同步点：没有它就只能"睡一会儿再看" —— 那就又是时序型
            断言，换台机器/换次负载就可能翻脸（正是这次要治的病）。
            """
            got = wait_until(lambda: bool(_late_done), 15)
            return got, "%s：走完 %d 条" % (what, len(_late_done))

        agent._late_reply = _late_probe
        llm.set_transport(_stub_llm)
        try:
            e = {"post_type": "message", "message_type": "group", "group_id": 123456789,
                 "user_id": 10001, "self_id": base.self_id(), "message_id": 3101,
                 "raw_message": "MMZ迟到了吗",
                 "sender": {"user_id": 10001, "card": "已深度思考20秒", "nickname": "x"}}
            c_late = server.build_ctx(e, b"{}")
            _sent[:] = []
            server._on_message(e, b"{}")
            wait_until(lambda: len(_sent) >= 1, 10)      # 等"发出去了"这件事，不睡固定 0.4 秒
            ok &= _ck(len(_sent) == 1 and _sent[0][0] == "群" and _sent[0][1][1] == "收到了，我在。",
                      "正常打桩（server._on_message）→ 走真的发送路径，**恰好一条**",
                      "%d 条：%s" % (len(_sent), [x[1][1] for x in _sent]))

            # 合成两条：各自一个 key（互不排队），一个快、一个慢。
            e_fast = dict(e, message_id=3102, raw_message="MMZ快答")
            e_late = dict(e, message_id=3103, raw_message="MMZ慢答")
            ctx_f, ctx_l = server.build_ctx(e_fast, b"{}"), server.build_ctx(e_late, b"{}")
            got = {}

            def run_fg(ctx, box):
                box["reply"] = agent.handle(ctx, late=lambda it, rp: late_calls.append(rp))

            late_calls = []
            _late_done[:] = []
            _stub_reply["text"] = "收到了，我在。"
            _hold["ev"] = None                       # ①a 不卡：后台立刻算完
            th = threading.Thread(target=run_fg, args=(ctx_f, got), daemon=True)
            th.start()
            th.join(10)
            ok &= _ck(got.get("reply") == "收到了，我在。",
                      "①a 算得快：句子的发送权归**前台**（handle 把话交出来）",
                      repr(got.get("reply")))
            ok &= _ck(not late_calls, "①a 没人打扰后台（迟到那条路一次都没被叫）")

            # 慢条：把 maxWaitSeconds 临时压到 1 秒，同时**把后台那条卡在门闸上** ——
            # 前台那 1 秒一定等不到（LATE_PENDING 是摆出来的，不是撞出来的）。
            ag_cfg = base.cfg().get("agent") or {}
            old_wait = ag_cfg.get("maxWaitSeconds")
            ag_cfg["maxWaitSeconds"] = 1
            late_calls = []
            _late_done[:] = []
            _stub_reply["text"] = "慢"
            gate1 = threading.Event()
            _hold["ev"] = gate1
            box = {}
            t0 = time.time()
            fg = agent.handle(ctx_l, late=lambda it, rp: late_calls.append(rp))
            dt = time.time() - t0
            ok &= _ck(fg is agent.LATE_PENDING,
                      "①b 等超时了 → handle 回 LATE_PENDING（**不是 None**："
                      "「她不想说」和「还没算完」绝不许混）", repr(fg))
            ok &= _ck(dt < 1.6, "①b 前台 1 秒就放了手（不陪等）", "%.2f 秒" % dt)
            ok &= _ck(not late_calls, "①b 那会儿后台还没算完（还没人补发）")
            ok &= _ck(not _late_done and not gate1.is_set(),
                      "①b 前台走的时候后台**确实**还卡着（上面三条因此是确定发生的，"
                      "不是「这次运气好慢了一点」）")
            gate1.set()                              # 放闸：后台这才算出来 → 自己补发
            _settled, _settle_why = _settle_late("①c")
            ok &= _ck(_settled, "①c 后台那条路**真的走完了**（等事件，不睡固定秒数）",
                      _settle_why)
            ok &= _ck(late_calls == ["收到了，我在。"],
                      "①c 后台算完**自己补发了一次**（迟到的也没丢）", str(late_calls))
            ok &= _ck("这条迟到" in _read_log() and "补发了" in _read_log(),
                      "①c 补发这件事写进了日志（纯日志，不进模型）",
                      " ｜ ".join(l for l in _read_log().splitlines() if "迟到" in l)[:90])
            # 「恰好一次」是**确定性**验的：发送权认领过了，把这条路再整走一遍也发不出
            # 第二句（原来靠"多睡 0.6 秒看会不会冒头"—— 那是时序，不是证据）。
            if _late_done:
                _real_late(ctx_l, _late_done[-1], "收到了，我在。",
                           lambda cc, tt: late_calls.append(tt))
            ok &= _ck(late_calls == ["收到了，我在。"],
                      "①c 补发**恰好一次**（认领过再走一遍也发不出第二句）", str(late_calls))

            # 空文本：她本来就没打算说话 → 后台也不许硬发一句
            # （`end_turn` 收尾时 `run_turn` 返回的也是空串，同一条路）
            late_calls = []
            _late_done[:] = []
            _stub_reply["text"] = ""
            gate2 = threading.Event()
            _hold["ev"] = gate2
            fg2 = agent.handle(server.build_ctx(dict(e, message_id=3104, raw_message="MMZ空答"), b"{}"),
                               late=lambda it, rp: late_calls.append(rp))
            ok &= _ck(fg2 is agent.LATE_PENDING,
                      "①d 超时 + 后台算出来是**空的**：前台先回 LATE_PENDING（**不是 None**）",
                      repr(fg2))
            gate2.set()                              # 放闸：后台这才算出"空的"，然后认领掉
            _settled, _settle_why = _settle_late("①d")
            ok &= _ck(_settled, "①d 后台那条路**真的走完了**（等事件，不睡固定秒数）",
                      _settle_why)
            ok &= _ck(not late_calls,
                      "①d 超时 + 后台算出来是空的 → 一条都不发（模型主动留空 = 不说话）",
                      "late=%s" % late_calls)

            ag_cfg["maxWaitSeconds"] = old_wait
            _stub_reply["text"] = "收到了，我在。"
        finally:
            _hold["ev"] = None                 # 门闸一定放掉，别把后台线程挂在那儿
            agent._late_reply = _real_late
            im.send_group, im.send_private = _real_send_g, _real_send_p

        # ── 太长就自动拆成几条依次发（2026-10-04 用户拍板：「干脆别截断。自动切自动发」）──
        #
        #    以前是**硬截断**，真机上真丢过话 —— bot.log 里那行
        #    「18:18:18 群里这条太长了（1020 字），截到 800」，**220 个字直接没了**。
        #    现在拆分的实现只有一处（`fgbot/chunker.py`），出口也只有一处
        #    （`im.send_long`）：她的话 / 提醒 / 播报 / 主动插话全从那儿出去。
        #
        #    ⚠️ 打桩只换**最底下那一层**（`im._napcat_post` = 真正打 NapCat 的函数）：
        #       拆条、间隔、失败就停、日志**全是真的**，而且一条都不会真的发进 QQ。
        #    ⚠️ 除了"节奏"那一条，其余各段把间隔临时设成 0 —— 免得自检白等好几秒。
        print()
        _CUR_SECT[0] = "6e. 太长就自动拆成几条依次发（打桩、离线）"
        print("=== 6e. 太长就自动拆成几条依次发（打桩、离线）===")
        from fgbot import chunker as _chk
        _real_post_e = im._napcat_post
        _eposts = []
        _efail = {"at": 0}

        def _epost(endpoint, payload, timeout=20, retry=True):
            """假的 NapCat 发送层：只记下"发了什么"，一条都不出网。"""
            _eposts.append((endpoint, payload))
            if _efail["at"] and len(_eposts) == _efail["at"]:
                return False, "retcode"          # 造"第 N 条发失败"
            return True, ""

        def _etext():
            return ["".join(s["data"].get("text") or ""
                            for s in p["message"] if s["type"] == "text")
                    for _e, p in _eposts]

        def _etypes():
            return [[s["type"] for s in p["message"]] for _e, p in _eposts]

        im._napcat_post = _epost
        _ag_e = base.cfg().get("agent") or {}
        _bak_e = tuple(_ag_e.get(k) for k in ("maxGroupReplyChars", "maxPrivateReplyChars",
                                              "replySplitGapSeconds", "replySplitMaxParts"))
        _stub_back_e = _stub_reply["text"]
        # 一段**没有冒号/括号/空行**的长话：guards 那两道削（内心独白 / 日志前缀）不会动它，
        # 于是"拼起来 == 原文"才能逐字比。
        _unit = "今天下午我在群里看到大家在讨论那个新出的游戏，说得挺热闹的。"
        _long, _i = "", 0
        while len(_long) < 2000:
            _i += 1
            _long += "%s第%d句。" % (_unit, _i)
        try:
            _cap_g = int(_ag_e.get("maxGroupReplyChars") or 1200)

            # ── ① 短回复 → 恰好一条，内容逐字不变 ─────────────────────────
            _eposts[:] = []
            _short = "在呀，今天怎么样？"
            _r1 = im.send_group(123456789, _short, at=10001, reply_to="1692039722")
            ok &= _ck(_r1 and len(_eposts) == 1 and _eposts[0][0] == "send_group_msg",
                      "① 短回复 → **恰好一条**（不多拆）", "%d 条" % len(_eposts))
            ok &= _ck(_etext() == ["\n" + _short],
                      "① 短回复的内容**逐字不变**（一个字没多、一个字没少）", repr(_etext()))
            ok &= _ck(_etypes() == [["reply", "at", "text"]],
                      "① 短回复的发送形状照旧：引用 + @ + 正文", str(_etypes()))

            # ── ② 2000 字 → N 条：每条 ≤ 上限、顺序对、**拼起来一字不差** ──
            ok &= _ck(len(_long) >= 2000, "② 造出来的那条长回复 ≥ 2000 字", "%d 字" % len(_long))
            _eposts[:] = []
            _r2 = im.send_group(123456789, _long)
            _segs = _etext()
            ok &= _ck(_r2 and len(_segs) >= 2, "② 2000 字 → 拆成 N 条（N > 1）",
                      "%d 条" % len(_segs))
            ok &= _ck(all(len(s) <= _cap_g for s in _segs),
                      "② 每一条都 ≤ 上限 %d" % _cap_g, str([len(s) for s in _segs]))
            ok &= _ck("".join(_segs) == _long,
                      "② ⭐ 把所有段拼起来 == 原文（**一个字都不能少**）",
                      "实际拼出 %d 字，原文 %d 字" % (len("".join(_segs)), len(_long)))
            ok &= _ck(len(_eposts) == len(_segs)
                      and all(e == "send_group_msg" and p.get("group_id") == 123456789
                              for e, p in _eposts),
                      "⑤ 发送桩记到了 N 次调用，每次都是 send_group_msg、群号都对",
                      "%d 次" % len(_eposts))

            # ── ③ 拆点落在句子边界；没有标点也不崩 ─────────────────────────
            _stops = "。！？；!?;\n…"
            ok &= _ck(all((s[-1] in _stops) or (s[-1] in " \t") for s in _segs[:-1]),
                      "③ 前几条都切在**句子边界**上（句末标点 / 换行 / 空格）",
                      str([s[-1] for s in _segs[:-1]]))
            _eposts[:] = []
            _r3 = im.send_group(123456789, "啊" * 2500)
            _ns = _etext()
            ok &= _ck(_r3 and len(_ns) >= 2 and "".join(_ns) == "啊" * 2500
                      and all(len(x) <= _cap_g for x in _ns),
                      "③b 一长串**没有任何标点**：不崩、照样拆、一字不差、每条 ≤ 上限",
                      "%d 条 %s" % (len(_ns), [len(x) for x in _ns]))
            _eposts[:] = []
            _en = "hello there this is a fairly long english sentence. " * 40
            im.send_group(123456789, _en)
            _es = _etext()
            ok &= _ck("".join(_es) == _en and all(len(x) <= _cap_g for x in _es),
                      "③c 英文长文：拼回去一字不差、每条 ≤ 上限")
            ok &= _ck(all(not (x[-1].isascii() and x[-1].isalnum()
                              and _es[k + 1][0].isascii() and _es[k + 1][0].isalnum())
                          for k, x in enumerate(_es[:-1])),
                      "③c 英文**单词没被劈成两半**（切点不在字母/数字中间）",
                      str([x[-6:] + "|" + _es[k + 1][:6] for k, x in enumerate(_es[:-1])])[:110])

            # ── ④ 引用/@ 只挂第一段（CQ 码那两条路都不许重复带）────────────
            _eposts[:] = []
            im.send_group(123456789, _long, at=10001, reply_to="1692039722")
            _ts = _etypes()
            ok &= _ck(_ts[0][:2] == ["reply", "at"],
                      "④ 第一段带着引用（reply）+ @（at）—— 照现在一样", str(_ts[0]))
            ok &= _ck(_eposts[0][1]["message"][0]["data"].get("id") == "1692039722"
                      and _eposts[0][1]["message"][1]["data"].get("qq") == "10001",
                      "④ 第一段那两个 CQ 段的参数**就是原来那条**（id / qq 没串）")
            ok &= _ck(all("reply" not in t and "at" not in t for t in _ts[1:]),
                      "④ 后续段**不重复带** reply / at（第二段再回一次那条消息很怪）",
                      str(_ts[1:]))

            # ── ④b 节奏：两条之间真的停了（配置里那 0.5 秒）────────────────
            _eposts[:] = []
            _ag_e["replySplitGapSeconds"] = 0.5
            _t0 = time.time()
            im.send_group(123456789, _long)      # 2 条 → 中间该停 0.5 秒
            _dt = time.time() - _t0
            ok &= _ck(_dt >= 0.45, "④b 两条之间**真的停了**（0.5 秒那颗键生效）",
                      "%.2f 秒" % _dt)
            _ag_e["replySplitGapSeconds"] = 0    # 后面的段不用白等

            # ── ⑥ 中间有一条发失败 → 后面的不发了 + 一行日志 ────────────────
            _eposts[:] = []
            _efail["at"] = 2
            _n0 = len(_read_log())
            _rf = im.send_group(123456789, _long)
            _efail["at"] = 0
            _ftxt = _etext()
            _tail = _read_log()[_n0:]
            ok &= _ck(_rf is False and len(_eposts) == 2,
                      "⑥ 第 2 条发送失败 → **只发到第 2 条就停**（后面的不硬发）",
                      "%d 次调用" % len(_eposts))
            ok &= _ck("后面的" in _tail and "不发了" in _tail,
                      "⑥ 这件事写进了日志（写明发到第几条、剩几条没发）",
                      " ｜ ".join(l for l in _tail.splitlines() if "不发了" in l)[:110])
            ok &= _ck(_long.startswith("".join(_ftxt)),
                      "⑥ 已经发出去的那两段就是原文开头（顺序对、没串）")
            _eposts[:] = []
            _efail["at"] = 1
            _n0 = len(_read_log())
            im.send_private(10001, _long)
            _efail["at"] = 0
            ok &= _ck(len(_eposts) == 1 and "不发了" in _read_log()[_n0:],
                      "⑥ 第 **1** 条就失败 → 一条都不往下发（连第 2 条都不试）",
                      "%d 次调用" % len(_eposts))

            # ── ⑦ 播报那条路同样会拆 ────────────────────────────────────
            _eposts[:] = []
            _stub_reply["text"] = _long
            _ea = guards.strip_echo(guards.strip_monologue(_long)[0])
            _out_a = agent.on_api("announce", {
                "group_id": 123456789,
                "facts": {"人": "某人", "群": "123456789",
                          "数据": [{"站点": "B 站", "持续时长": "2 分 0 秒"}]}})
            _as = _etext()
            ok &= _ck(bool(_out_a) and _out_a.get("ok") and len(_as) >= 2
                      and "".join(_as) == _ea,
                      "⑦ 播报（电脑递事实那条路）**同样会拆**，而且一字不差",
                      "%d 条 %s" % (len(_as), [len(x) for x in _as]))
            _eposts[:] = []
            _out_p = agent.on_api("announce", {
                "user_id": 10001,
                "facts": {"人": "某人", "数据": [{"站点": "B 站", "持续时长": "2 分 0 秒"}]}})
            _ps = _etext()
            ok &= _ck(bool(_out_p) and _out_p.get("ok") and len(_ps) >= 2
                      and "".join(_ps) == _ea and all(e == "send_private_msg" for e, _ in _eposts),
                      "⑦ 私聊播报也走同一条路（拆开、发的是 private_msg）",
                      "%d 条" % len(_ps))

            # ── ⑦b 两个出口上限不同（群里 1200 / 私聊 1500）────────────────
            _cap_p = int(_ag_e.get("maxPrivateReplyChars") or 1500)
            _mid = ""
            while len(_mid) < 1300:
                _mid += _unit
            _eposts[:] = []
            im.send_group(123456789, _mid)
            _g_n = len(_etext())
            _eposts[:] = []
            im.send_private(10001, _mid)
            _p_n = len(_etext())
            ok &= _ck(_g_n >= 2 and _p_n == 1 and _cap_g < len(_mid) <= _cap_p,
                      "⑦b 两个出口上限不同：同一条 %d 字 → 群里 %d 条、私聊 %d 条"
                      "（群上限 %d / 私聊上限 %d）" % (len(_mid), _g_n, _p_n, _cap_g, _cap_p),
                      "群 %d 条 ｜ 私聊 %d 条" % (_g_n, _p_n))

            # ── ⑧ 上限是配置化的（改小 → 拆得更多）────────────────────────
            _ag_e["maxGroupReplyChars"] = 300
            _eposts[:] = []
            im.send_group(123456789, _long)
            _n300 = len(_etext())
            _ag_e["maxGroupReplyChars"] = _cap_g
            ok &= _ck(_n300 > len(_segs),
                      "⑧ 上限**配置化**：群上限 1200 → %d 条，改成 300 → %d 条"
                      % (len(_segs), _n300))

            # ── ⑨ 兜底条数：并进最后一条（不丢字）+ 日志写明 ────────────────
            #    ⚠️ 必须同时把**上限**压小（不然 2021 字在 1200 的上限下本来就只有 2 条，
            #       压根撞不上兜底，"并进最后一条"那条路一步都不会走）。
            _ag_e["replySplitMaxParts"] = 2
            _ag_e["maxGroupReplyChars"] = 300
            _eposts[:] = []
            _n0 = len(_read_log())
            im.send_group(123456789, _long)
            _tail = _read_log()[_n0:]
            _mt = _etext()
            ok &= _ck(len(_eposts) == 2 and len(_mt) == 2 and "".join(_mt) == _long
                      and len(_mt[0]) <= 300 and len(_mt[1]) > 300,
                      "⑨ 撞上兜底条数（上限压到 300、兜底压到 2 条来试）→ 只发 2 条，"
                      "**剩下的一字不丢**、全并进最后一条",
                      "第 1 条 %d 字 ｜ 第 2 条 %d 字 ｜ 共 %d 字"
                      % (len(_mt[0]), len(_mt[1]), len(_long)))
            ok &= _ck("并进最后一条" in _tail and "一个字都没丢" in _tail,
                      "⑨ 并进这件事写进了日志（写明并进来多少字，不是静默丢弃）",
                      " ｜ ".join(l for l in _tail.splitlines() if "并进" in l)[:110])
            _ag_e["maxGroupReplyChars"] = _cap_g
            _ag_e["replySplitMaxParts"] = _bak_e[3] if _bak_e[3] is not None else 8

            # ── ⑩ chunker 本身的两条硬性质（不发消息，直接验）─────────────
            _p8, _m8 = _chk.chunk("句子。" * 2000, 100, 8)
            ok &= _ck(len(_p8) == 8 and "".join(_p8) == "句子。" * 2000 and _m8 > 0,
                      "⑩ 兜底条数 8 真撞上时：正好 8 条、拼回去一字不差",
                      "最后一条 %d 字（并进来 %d 字）" % (len(_p8[-1]), _m8))
            _cq = "前面的话" * 10 + "[CQ:at,qq=10001]" + "后面的话" * 10
            _pc = _chk.split(_cq, 50)
            ok &= _ck(any("[CQ:at,qq=10001]" in x for x in _pc)
                      and "".join(_pc) == _cq,
                      "⑩ 正文里的 CQ 码**绝不被劈开**（整个留在某一段里，拼回去一字不差）",
                      str([len(x) for x in _pc]))
            _pr, _mr = _chk.chunk("短", 1200, 8)
            ok &= _ck(_pr == ["短"] and _mr == 0, "⑩ 短文本原样一段（split 不添油加醋）")

            # ── ⑪ 这台机器的 config.json 里那几个值 ────────────────────────
            try:
                with open(base.CFG_PATH, encoding="utf-8") as _cf:
                    _cfgfile_e = json.load(_cf)
                _ce = _cfgfile_e.get("agent") or {}
            except Exception as _e:
                _ce = {}
                print("    ⚠️ 读不出 config.json：%r" % (_e,))
            ok &= _ck(_ce.get("maxGroupReplyChars") == 1200
                      and _ce.get("maxPrivateReplyChars") == 1500
                      and float(_ce.get("replySplitGapSeconds") or 0) == 0.5
                      and int(_ce.get("replySplitMaxParts") or 0) == 8,
                      "⑪ 这台机器的 config.json：群 1200 / 私聊 1500 / 间隔 0.5 秒 / 兜底 8 条",
                      str({k: _ce.get(k) for k in ("maxGroupReplyChars", "maxPrivateReplyChars",
                                                   "replySplitGapSeconds", "replySplitMaxParts")}))

            # ── ⑫ 代码里**再没有**硬截断（防以后又有人把它加回来）──────────
            def _live(src):
                """只留"活代码"行（注释行去掉 —— 注释里引着老日志原文是有意的）。"""
                return "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))

            _srcs = {}
            for _n in ("fgbot/agent.py", "fgbot/toolkit.py", "fgbot/im.py"):
                try:
                    with open(os.path.join(base.DIR, _n), encoding="utf-8") as _f:
                        _srcs[_n] = _f.read()
                except Exception as _e:
                    _srcs[_n] = ""
                    print("    ⚠️ 读不出 %s：%r" % (_n, _e))
            ok &= _ck(bool(_srcs["fgbot/agent.py"])
                      and "群里这条太长了" not in _live(_srcs["fgbot/agent.py"])
                      and "截到 %d" not in _live(_srcs["fgbot/agent.py"]),
                      "⑫ agent.py 里**再没有**那处硬截断（「群里这条太长了…截到 %d」）")
            ok &= _ck(bool(_srcs["fgbot/im.py"])
                      and "maxGroupReplyChars" in _live(_srcs["fgbot/im.py"])
                      and "maxGroupReplyChars" not in _live(_srcs["fgbot/agent.py"]),
                      "⑫ 上限只在**一处**读（im.py 的 `_split_cfg`）—— "
                      "agent.py 那边一个字都不碰（以前是它自己截的）")
            ok &= _ck(_srcs["fgbot/toolkit.py"]
                      and "太长，截断了" not in _live(_srcs["fgbot/toolkit.py"])
                      and "text[:3000]" not in _live(_srcs["fgbot/toolkit.py"]),
                      "⑫ toolkit.py 里**再没有** 3000 字硬截断（那两句删掉了）")
            ok &= _ck(_srcs["fgbot/im.py"]
                      and "chunker.chunk" in _live(_srcs["fgbot/im.py"]),
                      "⑫ 所有出口都汇到 `im.send_long` → `chunker.chunk`（一处实现）")
        finally:
            for _k, _v in zip(("maxGroupReplyChars", "maxPrivateReplyChars",
                               "replySplitGapSeconds", "replySplitMaxParts"), _bak_e):
                if _v is None:
                    _ag_e.pop(_k, None)
                else:
                    _ag_e[_k] = _v
            _stub_reply["text"] = _stub_back_e
            im._napcat_post = _real_post_e

        # ── ④ 120 秒超时为什么一次都没触发 + ③ 测试当前这家 ──────────────────
        #    现场：那三条请求各挂了 901 秒，而 timeoutSeconds=120；348KB 日志里
        #    超时记录 **0 条**。查实：urlopen(timeout=…) 是**每次 recv** 的上限，
        #    不是总时长 —— 对端只要偶尔吐一个字节（"滴血"），120 秒就被一次次重置。
        #    这里用一个**只发半截、慢慢滴**的本地假模型端口把这事复现出来，
        #    再验新加的**总时长（wall-clock）看门狗**掐得断。
        print()
        _CUR_SECT[0] = "6d. 总时长看门狗 + 空响应证据 + 测试当前这家（打桩、离线）"
        print("=== 6d. 总时长看门狗 + 空响应证据 + 测试当前这家（打桩、离线）===")
        import socket as _socket
        import http.client as _httpc
        from fgbot import persona as _persona

        _drip = {"n": 0}

        class _DripSrv(ThreadingHTTPServer):
            daemon_threads = True

        class _DripH(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)               # 把请求体读完，不然对端还在发
                _drip["n"] += 1
                # 只回半截：头说 10000 字节，之后每 0.6 秒滴一个字节 ——
                # 正好把"每次 recv 120 秒"那条超时无限重置（滴血）。
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "10000")
                self.end_headers()
                try:
                    for _ in range(400):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.6)
                except Exception:
                    pass

        _srv = _DripSrv(("127.0.0.1", 0), _DripH)
        _port = _srv.server_address[1]
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
        llm.set_transport(None)                  # 这一段**走真网络**：只是对端是本机假端口
        _log_mark = len(_read_log())
        _conn = {"url": "http://127.0.0.1:%d/v1/chat/completions" % _port, "key": "selftest",
                 "timeout": 120, "wallSeconds": 2, "headers": {}}
        _pl = {"model": "假模型", "messages": [{"role": "user", "content": "x"}], "stream": False}
        _t0 = time.time()
        _err = None
        try:
            # ⚠️ 走 `_post`（不是 _one_request）：重试那一层在 _post 里，
            #    要验的正是"被总时长掐断之后**会重试**"。
            llm._post(_pl, _conn)
            _err = "居然回来了"
        except llm.LlmError as _e:
            _err = "%s：%s" % (_e.code, _e)
        _dt = time.time() - _t0
        try:
            _srv.shutdown()
        except Exception:
            pass
        ok &= _ck(_err.startswith("WALL_TIMEOUT") and _dt < 7,
                  "④ 滴血连接（每 0.6 秒来一个字节）被**总时长**掐断 —— 不再是 901 秒",
                  "%.1f 秒 / %s" % (_dt, _err))
        _txt = _read_log()[_log_mark:]
        _tries = _drip["n"]
        ok &= _ck("被总时长掐断" in _txt and "第 1 次重试" in _txt,
                  "④ 日志里看得出「这次是被总时长掐的」，而且**重试了**（诊断不再靠猜）",
                  " ｜ ".join(l for l in _txt.splitlines() if "总时长" in l)[:110])
        ok &= _ck(_tries >= 2,
                  "④ 总时长掐断之后**真的又发了一次**（现有重试机制，不是白白放弃）",
                  "假端口一共收到 %d 次请求" % _tries)

        # ── ② 空响应要留证据：finish_reason + 原始返回体 + 状态码 + 耗时
        #    现场：EMPTY_RESPONSE 只写了一句"重试一次"，45 分钟里收到什么一个字节没留。
        _log_mark = len(_read_log())

        def _empty_llm(url, payload, headers, timeout):
            return {"model": "假模型", "choices": [{"index": 0, "finish_reason": "length",
                                                   "message": {"role": "assistant", "content": ""}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 300,
                              "completion_tokens_details": {"reasoning_tokens": 300}}}

        llm.set_transport(_empty_llm)
        _d = llm.chat([{"role": "user", "content": "x"}], tools=None)
        _txt = _read_log()[_log_mark:]
        ok &= _ck(("finish_reason='length'" in _txt or 'finish_reason="length"' in _txt)
                  and "返回体" in _txt and "HTTP 200" in _txt,
                  "② 空响应的证据行：finish_reason + 原始返回体 + HTTP 状态 + 耗时",
                  " ｜ ".join(l for l in _txt.splitlines() if "EMPTY_RESPONSE" in l)[:100])
        ok &= _ck(("reasoning_tokens" in _txt) and "秒 ｜第" in _txt,
                  "② 证据行里带着原始 body 和这次耗时（查得回来）")
        # ⛔ 只写日志：EMPTY_RESPONSE 那句**给模型看的文本**一个字都不许动
        ok &= _ck("EMPTY_RESPONSE" not in json.dumps(_d),
                  "② 证据只进日志 —— 给模型看的东西里没有它")

        # ── ③ 「测试当前这家」的假绿灯：思考把 max_tokens 吃光 → content 空，却报"能用"
        _probe = {}

        def _probe_llm(url, payload, headers, timeout):
            _probe.update(payload)
            _probe["_timeout"] = timeout
            if payload.get("max_tokens", 0) < 1000:
                return {"model": "deepseek-flash",
                        "choices": [{"index": 0, "finish_reason": "length",
                                     "message": {"role": "assistant", "content": "",
                                                 "reasoning_content": "想…" * 100}}]}
            return {"model": "deepseek-flash",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": "好"}}]}

        llm.set_transport(_probe_llm)
        _ok1, _msg1 = llm.test_provider()
        ok &= _ck(_ok1 is True and "好" in _msg1,
                  "③ 模型正常 → 「测试当前这家」如实说能用", _msg1)
        ok &= _ck((_probe.get("max_tokens") or 0) >= 1000,
                  "③ 这次的 token 预算够思考 + 一个字（不再是 20 个，思考一吃就光）",
                  "max_tokens=%s" % _probe.get("max_tokens"))

        def _empty_probe(url, payload, headers, timeout):
            return {"model": "deepseek-flash",
                    "choices": [{"index": 0, "finish_reason": "length",
                                 "message": {"role": "assistant", "content": ""}}]}

        llm.set_transport(_empty_probe)
        _ok2, _msg2 = llm.test_provider()
        ok &= _ck(_ok2 is False and "空" in _msg2,
                  "③ 回了空 content → **判成不能用**（原来是「能用：(空)」的假绿灯）", _msg2)
        # ⛔ 那句提示词是 LLM 文本，一个字都不许动（要改得先给用户看）
        ok &= _ck(_probe.get("messages") == [{"role": "user", "content": "回一个字：好"}],
                  "③ 测试用的那句提示词**逐字未变**（LLM 文本，不许顺手改）",
                  repr(_probe.get("messages")))

        # ── dump-llm.on：完整请求/响应照现有机制存，**不含 key**
        store.remove("llm-dump.json")
        open(store.path("dump-llm.on"), "w").close()
        _key_mark = (llm.connection().get("key") or "")[:6]
        llm.set_transport(_probe_llm)
        llm.chat([{"role": "user", "content": "x"}], tools=None)
        store.remove("dump-llm.on")
        _dump_txt = json.dumps(store.read_json("llm-dump.json") or {}, ensure_ascii=False)
        if _key_mark:
            _dump_ok = _key_mark not in _dump_txt
            _dump_why = "dump %d 字 / key 前 6 位 %r" % (len(_dump_txt), _key_mark)
        else:
            # ⚠️ 暂存目录里**没有 llm-key.txt**（它在 deploy 的 NEVER 名单里），config 的 apiKey 也空
            #    → 这一趟没有 key 可查。那就只钉"dump 真的写出来了"。
            #    为什么必须这么改：deploy 第 ② 步是在**暂存目录**里跑自检的，从前那条老 deploy
            #    靠"有告警就不看退出码"糊过去；现在退出码是硬的（用户点名要修），
            #    这条不放过，任何一次 deploy 都推不上去。手机上（有 key）那半条查照旧跑。
            _dump_ok = "messages" in _dump_txt
            _dump_why = "dump %d 字（这趟没配 key，跳过「不含 key」那半条）" % len(_dump_txt)
        ok &= _ck(_dump_ok, "② dump-llm.on 存在 → 完整请求/响应照旧存一份，**不含 key**", _dump_why)

        # ══════════════════════════════════════════════════════════════
        # ⑨ 群管理（2026-10-04 用户点名要的那一块）
        #    「我希望能管理可以说话和接收的消息的群」——
        #    名单存手机本地的 groups.json（deploy 的 NEVER），读的时候
        #    **并上** config.json 的 bot.groups（升级/首次部署时她那两个群不能丢）。
        # ⛔ 这一节**一个网络请求都不许发**：NapCat 那道缝照样打桩。
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.9 群管理（namesake：groups.json ∪ config.json ∪ 用户表）"
        print("=== 6.9 群管理（namesake：groups.json ∪ config.json ∪ 用户表）===")
        from fgbot import groups as _g

        # ⚠️ 公开版自检**不许写死某台机器的群号**（那正是这次要修的那 12 条之一）：
        #    群号从仓库那份 `config.json` 的 `bot.groups` 读；它是空的也照样能跑
        #    （下面跟 config 有关的那几条会变成"没有配置群"的形态）。
        _cfg_gids = [str(g) for g in ((base.bot_cfg().get("groups") or []))]
        _GA = int(_cfg_gids[0]) if _cfg_gids else None
        _GB = int(_cfg_gids[1]) if len(_cfg_gids) > 1 else None
        _GFAKE = 555000111                     # 面板上加的假群（和 config / 用户表都不撞）
        _GSEEN = 555000222                     # 她收到过消息、但不在名单里的群

        def _gclean():
            """把三个清单文件清干净（都在临时目录里，不碰正式那份）。"""
            for _n in (_g.WHITELIST_FILE, _g.SEEN_FILE, "group-names.json"):
                store.remove(_n)
            _g._invalidate()

        #    ⚠️ `group-names.json` 和 im 那两级进程内缓存（`_GROUP_NAMES` / `_GROUP_TRIED`）
        #       也一起清掉：第 5 节那条"群名"用例问过 123456789（还故意让它失败过一次），
        #       留着的话这一节就变成"吃上一节的缓存"，测不到"按需去问一次"。
        try:
            im._GROUP_NAMES.clear()
            im._GROUP_TRIED.clear()
        except Exception:
            pass
        _gclean()
        _gbase = _g.known()
        if _cfg_gids:
            ok &= _ck(set(_cfg_gids).issubset(set(_gbase)),
                      "① 并集：config.json 的 bot.groups 都在名单里（升级/首部署时它们不会丢）",
                      "、".join(_gbase))
            ok &= _ck(all(agent._in_scope(mk("MMZ", gid=int(_x))) for _x in _cfg_gids),
                      "① 这些群里她是理人的")
        else:
            print("    ⚠️ 仓库 config.json 的 bot.groups 是空的（公开模板允许）—— "
                  "「config 群并进来」那两条按空名单的形态检查")
            ok &= _ck(_gbase == [], "① config 群为空时名单也是空的（没有凭空多出群）",
                      "、".join(_gbase) or "（空）")
        ok &= _ck(not agent._in_scope(mk("MMZ", gid=_GFAKE)),
                  "① 不在名单里的群 → 不理（老行为没变）")
        ok &= _ck(str(_GFAKE) not in _gbase and str(_GSEEN) not in _gbase,
                  "① 这时候 groups.json 是空的，名单就是「config + 用户表」那一份")

        # ── 加：写进 groups.json，**立刻生效**（热重载，不重启）
        _okA, _msgA = _g.add(_GFAKE, name="假群测试")
        ok &= _ck(_okA and str(_GFAKE) in _g.known(),
                  "② 加一个群（手填群号）→ 并集里立刻有它", _msgA)
        ok &= _ck(store.read_json(_g.WHITELIST_FILE).get("群")[0].get("名字") == "假群测试",
                  "② 名字 / 备注 / 加入时间 都落进 groups.json 了",
                  str(store.read_json(_g.WHITELIST_FILE))[:120])
        ok &= _ck(_g.source_of(_GFAKE) == "local"
                  and (not _GA or _g.source_of(_GA) == "config"),
                  "② 每条能看出「从哪来」（面板上得标出来）")
        ok &= _ck(agent._in_scope(mk("MMZ", gid=_GFAKE)) is True,
                  "② 加进来之后 → **同一群人她开始理了**")

        # ── 不在名单的群消息：**记一条**（⛔ 不记消息内容，⛔ 一个网络请求都不发）
        _real_gcall = im._napcat_call
        _real_names, _real_tried = dict(im._GROUP_NAMES), set(im._GROUP_TRIED)
        _ncalls = []

        def _fake_gcall(ep, payload, **kw):
            _ncalls.append((ep, payload.get("group_id")))
            return True, {"group_name": "秘密基地"}

        try:
            im._napcat_call = _fake_gcall
            _secret = "这句话一个字都不许落进文件里"
            _ctx_seen = mk("MMZ", gid=_GSEEN)
            _ctx_seen["who"] = "某个群友"
            ok &= _ck(not agent._in_scope(_ctx_seen), "③ 这个群不在名单里（前提）")
            _n0 = len(_ncalls)
            _rec, _why = _g.see(_GSEEN, "某个群友")
            ok &= _ck(_rec, "③ 不在名单的群来了消息 → 记下一条", _why)
            ok &= _ck(len(_ncalls) == _n0,
                      "③ `see()`（跑在收消息那条路上）**一个网络请求都不发** —— "
                      "它只翻缓存，群名交给面板按需补", "打了 %d 次" % (len(_ncalls) - _n0))
            _raw = open(store.path(_g.SEEN_FILE), encoding="utf-8").read()
            ok &= _ck(str(_GSEEN) in _raw and "某个群友" in _raw,
                      "③ 「最近见过的群」里有 群号 + 谁在说话（群名这时还空着）",
                      _raw.replace("\n", " ")[:150])
            ok &= _ck(_secret not in _raw,
                      "③ ⛔ 记录里**没有消息内容**（只记事实）")
            # 面板打开时才去补群名：按需、每组一次、顺手回填进文件
            _seen = _g.fill_seen_names()
            ok &= _ck("秘密基地" in open(store.path(_g.SEEN_FILE), encoding="utf-8").read()
                      and _seen and _seen[0]["名字"] == "秘密基地",
                      "③ 面板打开时按需补群名（补到了就回填，下次不用再问）", str(_seen))
            ok &= _ck(len([c for c in _ncalls if c[1] == _GSEEN]) == 1,
                      "③ 群名只问了**一次**（`group_name` 自带进程内 + 落盘缓存）",
                      str(_ncalls))
            _seen_rows = _g.seen_rows()
            ok &= _ck(len(_seen_rows) == 1 and _seen_rows[0]["id"] == _GSEEN
                      and str(_GFAKE) not in [str(x["id"]) for x in _seen_rows],
                      "③ 面板那份只列**不在名单里**的群（刚加进去的假群不出现）",
                      str(_seen_rows))
        finally:
            im._napcat_call = _real_gcall
            im._GROUP_NAMES.clear()
            im._GROUP_NAMES.update(_real_names)
            im._GROUP_TRIED.clear()
            im._GROUP_TRIED.update(_real_tried)

        # ── 面板那三个动作（主人身份；走 agent.on_api → server 层的口令）
        _OWN = {"id": "own", "主人": True, "名字": "", "群": ""}
        _OUT = {"id": "x1", "主人": False, "名字": "朋友", "群": ""}
        try:
            # ⚠️ 自检**绝不联网**：这几条会按需查群名，所以 NapCat 那道缝照样打桩。
            im._napcat_call = _fake_gcall
            ok &= _ck(agent.on_api("group.list", {}, _OUT) is agent.FORBIDDEN,
                      "④ 不是主人调 group.* → FORBIDDEN（server 回 403 空正文，和 user.* 同口径）")
            _r = agent.on_api("group.list", {}, _OWN)
            _rows_by_id = {str(x["id"]): x for x in (_r or {}).get("groups", [])}
            ok &= _ck(_r and _r.get("ok") and _GFAKE in [x["id"] for x in _r["groups"]]
                      and all(x["生效"] for x in _r["groups"]),
                      "④ group.list 列出名单，每条都带「现在生效」",
                      str([(x["id"], x["生效"], x["来源"]) for x in _r["groups"]]))
            ok &= _ck(all(str(_GSEEN) != str(x["id"]) for x in _r["groups"]),
                      "④ group.list 的名单里没有「不在名单里」那个群（它只在 seen 里）")
            if _GA:
                ok &= _ck(_rows_by_id.get(str(_GA), {}).get("名字") == "秘密基地",
                          "④ 面板上那行 config 群也带得出群名（先翻缓存、没有再问一次 NapCat，"
                          "结果落进 group-names.json）",
                          str(_rows_by_id.get(str(_GA))))
            _r = agent.on_api("group.add", {"id": "111222333", "note": "面板加的"}, _OWN)
            ok &= _ck(_r and _r.get("ok") and "111222333" in _g.known(),
                      "④ group.add 立刻生效", (_r or {}).get("message", ""))
            _r = agent.on_api("group.note", {"id": "111222333", "note": "张三的群"}, _OWN)
            _rows_by_id = {str(x["id"]): x
                           for x in (agent.on_api("group.list", {}, _OWN) or {}).get("groups", [])}
            ok &= _ck(_r and _r.get("ok") and _rows_by_id["111222333"]["备注"] == "张三的群",
                      "④ group.note 改备注", str(_rows_by_id.get("111222333")))
            _r = agent.on_api("group.del", {"id": "111222333"}, _OWN)
            ok &= _ck(_r and _r.get("ok") and "111222333" not in _g.known()
                      and not agent._in_scope(mk("MMZ", gid=111222333)),
                      "④ group.del 移除 → 立刻不理它了", (_r or {}).get("message", ""))
            if _GA:
                _r = agent.on_api("group.del", {"id": str(_GA)}, _OWN)
                ok &= _ck(_r and not _r.get("ok"),
                          "④ config.json 里那条**删不掉**（如实说，不假装删成功）",
                          (_r or {}).get("message", ""))
                ok &= _ck(agent._in_scope(mk("MMZ", gid=_GA)),
                          "④ 删不掉之后它**照旧生效**（并集的兜底意义就在这）")
        finally:
            im._napcat_call = _real_gcall
            im._GROUP_NAMES.clear()
            im._GROUP_NAMES.update(_real_names)
            im._GROUP_TRIED.clear()
            im._GROUP_TRIED.update(_real_tried)

        # ── 在名单里 / 不在名单里：同一条消息，处理 vs 丢掉
        #    ⚠️ 走的是**真路径**：`server._on_message`（打那行「收到 群 …」的日志）
        #       → `agent.handle` → `_in_scope` 判断。把 `_think`（真"想"那一步，
        #       在 memory 的 worker 线程里）打个桩，就能看出"到底递没递给她"。
        real_think = agent._think
        real_llm_run = llm.run_turn
        _think_hits = []

        def _stub_think(ctx, addressed):
            _think_hits.append(ctx.get("group_id"))
            return None

        try:
            agent._think = _stub_think
            llm.run_turn = lambda msgs, ctx: ("", [], None)
            _evt = {"post_type": "message", "message_type": "group",
                    "group_id": _GFAKE, "user_id": 10001,
                    "self_id": base.self_id(), "message_id": 7,
                    "raw_message": "MMZ你好",
                    "sender": {"user_id": 10001, "card": "群友", "nickname": "x"}}
            _log_at = len(_read_log())
            server._on_message(_evt, b"{}")
            _got = wait_until(lambda: _think_hits == [_GFAKE], timeout=3.0)
            ok &= _ck(_got,
                      "⑤ 在名单里 → server 收到这条、并且**真的递给了她**（_think 被叫到）",
                      "think=%s" % _think_hits)
            ok &= _ck("收到 群 %d" % _GFAKE in _read_log()[_log_at:],
                      "⑤ bot.log 里有那行「收到 群 %s」" % _GFAKE)
            # 移出名单 → **同一条消息**又被丢掉
            _rm_ok, _rm_msg = _g.remove(_GFAKE)
            ok &= _ck(_rm_ok, "⑤ 移除那个假群（`groups.remove`）", _rm_msg)
            _think_hits[:] = []
            _log_at = len(_read_log())
            server._on_message(_evt, b"{}")
            ok &= _ck(not agent._in_scope(server.build_ctx(_evt, b"{}")),
                      "⑤ 移除之后 `_in_scope` = False（她立刻不再理这个群）")
            ok &= _ck(not wait_until(lambda: bool(_think_hits), timeout=1.5),
                      "⑤ 移出名单之后 → **同一条消息**不再递给她（被丢掉）")
            ok &= _ck("收到 群 %d" % _GFAKE in _read_log()[_log_at:],
                      "⑤ 丢掉的那条**照样留痕**（bot.log 里还是那行「收到 群 …」—— "
                      "不然用户查不出到底收没收到）")
        finally:
            agent._think = real_think
            llm.run_turn = real_llm_run

        # ── deploy.py 的 NEVER 名单里要有这两个文件（推代码不许覆盖手机上的名单）
        #    ⚠️ **不 import deploy**：自检在手机上跑的是暂存目录，那儿没有 deploy.py。
        #       所以直接读仓库里那份的源文件，把 NEVER = {…} 那一段抠出来看字面量。
        #       本地自检时它在 phone-bot/ 里（base.DIR 就是它所在的目录）；
        #       万一挪过位置，也只是少查这一条（下面那行会说明）。
        _dep = ""
        for _cand in (os.path.join(base.DIR, "deploy.py"),
                      os.path.join(os.path.dirname(base.DIR), "deploy.py")):
            try:
                with open(_cand, encoding="utf-8") as _df:
                    _dep = _df.read()
                break
            except Exception:
                continue
        if _dep:
            _never = _dep.split("NEVER = {", 1)[-1].split("}", 1)[0]
            for _f in (_g.WHITELIST_FILE, _g.SEEN_FILE):
                ok &= _ck('"%s"' % _f in _never,
                          "⑥ deploy.py 的 NEVER 里有 %s（推代码不会覆盖手机上的群名单）" % _f)
        else:
            print("    ⚠️ 读不到 deploy.py（手机上跑的是暂存目录）—— NEVER 那两条在本地自检里查")

        # ── ⛔ 面板 HTML 里不许有令牌（A5 那条铁律，加了新卡片之后照样成立）
        _html = panel.render()
        _tok = str(base.napcat_token() or "")
        ok &= _ck(bool(_tok) and _tok not in _html,
                  "⑦ 面板 HTML 里没有令牌（⚠️ 新加的「群管理」卡也没带任何凭据）")
        ok &= _ck("目标群" in _html and "最近会话群" in _html and "group.list" in _html,
                  "⑦ 面板上确实有「群管理」那一块（目标群 / 最近会话群 + 动作名）")
        ok &= _ck("加进来 = 她能收到这个群的消息" in _html and "不会退群" in _html,
                  "⑦ 「加进来 = 她能收到那个群的消息、也可能说话」和「不会退群」都还在"
                  "（在这两个动作的二次确认弹窗 / 按钮 tooltip 里）",
                  "加进来那句在 = %s" % ("加进来 = 她能收到这个群的消息" in _html))
        # ── ⛔ 日志里也不许有那一截（`?token=…`）：`do_GET` 出异常时那条日志以前打的是
        #    **整条 `self.path`**（含查询串）—— 老书签 / 面板链接一出异常就会整条落进 bot.log，
        #    日志会被 tail、会被发出去。现在只留路径。这里**直接读 server.py 的源码**查这一条
        #    （行为级的那条路要真发一个坏请求，自检里没这条缝）。
        _srvsrc = ""
        try:
            with open(server.__file__, encoding="utf-8") as _sf:
                _srvsrc = _sf.read()
        except Exception:
            pass
        if _srvsrc:
            ok &= _ck('log_exc("GET %s" % self.path)' not in _srvsrc,
                      "⑧ 日志：GET 异常那条**不再打整条 self.path**（?token= 进不了 bot.log）")
        # 收尾：假群在 ⑤ 里已经移掉了，这里只把「见过的群」也清掉（临时目录整份会删）
        _g.forget_seen(_GSEEN)
        _gclean()

        # ══════════════════════════════════════════════════════════════
        # 6.95 「申请」队列：好友申请 + 群邀请（2026-10-04 第二批，用户点名）
        #
        #   用户原话：「可以运行加群的话，可以允许通过好友申请吗？不过不要自动通过，
        #   而是把申请放到网页面板上，我决定拒绝还是通过还是忽略。然后加群也改成那样。」
        #   —— 于是：群邀请**不再自动同意**（`bot.autoAcceptGroupInvite` 改成 false，
        #   键留着）；好友申请也不再只写一行日志。**两样都进 `requests.json` 排队**，
        #   等用户在这面板上裁决（`request.approve / reject / ignore`）。
        #
        # ⛔ 这一节**一个真网络请求都不发**：NapCat 那道缝（`_napcat_post` /
        #    `_napcat_call`）全打桩，状态文件都在临时目录里；事件照样从**真入口**
        #    （`POST /`）打进去，钉住 `server.py` 那条分支真的接到 `agent.on_request`。
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.95 申请队列：好友申请 + 群邀请（打桩、离线）"
        print("=== 6.95 申请队列：好友申请 + 群邀请（打桩、离线）===")

        from fgbot import reqs as _rq

        _RF, _RF2 = 444555666, 444555667          # 两个好友申请人
        _RG, _RINV = 555666777, 111222333         # 群邀请：群号 / 邀请人
        _RCANARY = "这句话一个字都不许落进文件"     # 事件里的**别的字段**（⛔ 不记）
        _RCMT = "我是张三，拉我一下"                # 验证消息（**该**进 requests.json）

        def _rclean():
            """把群那三个清单 + requests.json 清干净（都在临时目录里，不碰正式那份）。"""
            _gclean()
            store.remove(_rq.FILE)

        def _rcaches():
            """把 im 那几级进程内缓存清掉（名字要重新查一次才算数）。"""
            try:
                im._GROUP_NAMES.clear()
                im._GROUP_TRIED.clear()
                im._STRANGER_NAMES.clear()
                im._STRANGER_TRIED.clear()
            except Exception:
                pass

        def _state_text():
            """四个状态文件的全文 —— 查"有没有落进来 / 有没有多落"。"""
            out = []
            for _n in (_g.WHITELIST_FILE, _g.SEEN_FILE, "group-names.json", _rq.FILE):
                try:
                    with open(store.path(_n), encoding="utf-8") as _f:
                        out.append(_f.read())
                except Exception:
                    pass
            return "\n".join(out)

        def _friend_evt(**extra):
            """一条**好友申请**事件（形状照 OneBot 11 / NapCat 的 request 上报）。"""
            e = {"post_type": "request", "request_type": "friend", "sub_type": "",
                 "user_id": _RF, "self_id": base.self_id(), "flag": "FLAG-R-好友1",
                 "comment": _RCMT, "sender": {"nickname": _RCANARY, "card": _RCANARY}}
            e.update(extra)
            return e

        def _invite_evt(**extra):
            """一条**群邀请**事件。"""
            e = {"post_type": "request", "request_type": "group", "sub_type": "invite",
                 "group_id": _RG, "user_id": _RINV, "self_id": base.self_id(),
                 "flag": "FLAG-R-群邀请1", "comment": _RCMT,
                 "sender": {"nickname": _RCANARY, "card": _RCANARY}}
            e.update(extra)
            return e

        _real_post, _real_call = im._napcat_post, im._napcat_call
        _posts, _calls = [], []

        def _fake_post(ep, payload, **kw):
            """NapCat 出站打桩：**记下调用参数**，不真发。"""
            _posts.append((ep, dict(payload)))
            return True, ""

        def _fake_call(ep, payload, **kw):
            """查询那套也打桩（顺手取名字走它）。"""
            _calls.append((ep, dict(payload)))
            if ep == "get_group_info":
                return True, {"group_name": "被拉进去的新群"}
            if ep == "get_stranger_info":
                return True, {"nickname": "张三"}
            return True, {}

        # 真的起一个本地 HTTP 服务，把事件**从 NapCat 上报那条路**（`POST /`）打进去 ——
        # 目的是钉住 `server.py` 那个入口真的会把它交给 `agent.on_request`
        #（只测 agent 层的话，"新加的那条分支有没有接上"就没人管）。
        _srvI = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=_srvI.serve_forever, daemon=True).start()
        _rootI = "http://127.0.0.1:%d" % _srvI.server_address[1]
        _tokI = base.napcat_token() or ""

        def _report(evt):
            """按 NapCat 的形态打一条上报（老 sha1 签名，本机来源）。"""
            _b = json.dumps(evt, ensure_ascii=False).encode("utf-8")
            _rqq = urllib.request.Request(
                _rootI + "/", data=_b,
                headers={"Content-Type": "application/json",
                         "X-Signature": "sha1=" + fgsig.sign_sha1(_tokI, _b)})
            try:
                with urllib.request.urlopen(_rqq, timeout=10) as r:
                    return r.status, r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8", "replace")

        _OWN = {"id": "selftest-主人", "主人": True, "名字": "主人"}
        _FRIEND_IDENT = {"id": "selftest-朋友", "主人": False, "名字": "朋友甲"}

        def _api(action, **kw):
            body = {"action": action}
            body.update(kw)
            return agent.on_api(action, body, _OWN)

        _sw_backup = base.cfg().get("bot", {}).get("autoAcceptGroupInvite", None)
        try:
            im._napcat_post = _fake_post
            im._napcat_call = _fake_call
            _rcaches()
            # ── ① 好友申请：从真入口进来 → **只入库**（以前只写一行日志、零动作）──
            base.cfg().setdefault("bot", {})["autoAcceptGroupInvite"] = False
            _rclean()
            _posts[:] = []
            _calls[:] = []
            _l0 = len(_read_log())
            _code, _body = _report(_friend_evt())
            _fhit = wait_until(lambda: len(_rq.pending()) == 1, timeout=5.0)
            _frec = _rq.pending()[0] if _fhit else {}
            ok &= _ck(_code == 204 and _body == "",
                      "① 好友申请从 NapCat 上报那条路进来 → 照旧 204 空正文（契约没变）",
                      "HTTP %s %r" % (_code, _body))
            ok &= _ck(_fhit and _frec.get("类型") == _rq.FRIEND
                      and _frec.get("qq") == str(_RF) and _frec.get("状态") == _rq.PENDING,
                      "① 好友申请**入库排队**了（以前是「只写一行日志、零动作」）",
                      str(_frec))
            ok &= _ck(_frec.get("flag") == "FLAG-R-好友1" and _frec.get("验证消息") == _RCMT,
                      "① `flag` 和**验证消息**都存下来了（面板上要显示申请人写的那句话）")
            ok &= _ck(_frec.get("名字") == "张三",
                      "① 顺手问了 `get_stranger_info` 把名字查到（失败留空、每人只问一次）",
                      "查询：%s" % _calls)
            ok &= _ck(not _posts,
                      "① 收到申请**一个出站动作都没发**（不自动通过、不自动加好友）",
                      str(_posts))
            # ⚠️ 这一行要等：入库（写文件）和写日志是**两步**，日志在后 ——
            #    只看文件到位就读日志会偶发读不到（容器里第一次跑就栽在这儿）。
            ok &= _ck(wait_until(lambda: "申请队列：收下一条好友申请" in _read_log()[_l0:],
                                 timeout=5.0),
                      "① 日志里一行「申请队列：收下一条好友申请…」（一眼看出它进了队列）")
            # ── ② 群邀请：入库 + 照旧记进「最近见过的群」+ ⛔ **没有再自动同意** ──
            _rclean()
            _rcaches()
            _posts[:] = []
            _calls[:] = []
            _l1 = len(_read_log())
            _code, _body = _report(_invite_evt())
            _ghit = wait_until(lambda: len(_rq.pending()) == 1, timeout=5.0)
            _grec = _rq.pending()[0] if _ghit else {}
            ok &= _ck(_ghit and _grec.get("类型") == _rq.GROUP
                      and _grec.get("群") == str(_RG) and _grec.get("qq") == str(_RINV)
                      and _grec.get("名字") == "被拉进去的新群",
                      "② 群邀请**入库排队**了（群号 / 邀请人 / 群名都在）", str(_grec))
            ok &= _ck(not any(p[0] == "set_group_add_request" for p in _posts),
                      "② ⛔ **没有再自动同意**：一个 `set_group_add_request` 都没调（这条钉死）",
                      "出站：%s" % (_posts,))
            _seen = _g.seen_records().get(str(_RG)) or {}
            ok &= _ck(_seen.get("邀请人") == str(_RINV),
                      "② 那个群**照旧记进了「最近见过的群」**（邀请人也在 —— 面板上他点一下就能加）",
                      str(_seen))
            ok &= _ck(str(_RG) not in _g.known() and not _g.is_local(_RG),
                      "② 但**没有**顺手加进白名单（加不加是用户自己在面板上的动作）",
                      "known=%s" % (_g.known(),))
            ok &= _ck(wait_until(lambda: "申请队列：收下一条群邀请" in _read_log()[_l1:], timeout=5.0)
                      and "同意把机器人拉进群" not in _read_log()[_l1:],
                      "② 日志写的是「收下一条群邀请…等面板裁决」，不是以前那句「同意把机器人拉进群」")

            # ── ③ 去重：同一个 flag 再打一遍 → 还是 1 条；已裁决的不许被打回待处理 ──
            _report(_invite_evt())
            _dup = wait_until(lambda: "已经收过了" in _read_log()[_l1:], timeout=5.0)
            ok &= _ck(_dup and len(_rq.records()) == 1,
                      "③ 同一条上报重发（flag 一样）→ **不重复入库**（还是 1 条）",
                      "records=%d ｜ %s" % (len(_rq.records()), _rq.records()))
            ok &= _ck(len([c for c in _calls if c[0] == "get_group_info"]) == 1,
                      "③ 群名**只问了一次**（进程内缓存挡掉了第二次）", str(_calls))

            # ── ④ 裁决之「通过」：主人调 request.approve → 真调 NapCat（approve=True）──
            _own = _api("request.list")
            ok &= _ck(isinstance(_own, dict) and _own.get("ok")
                      and len(_own.get("requests") or []) == 1,
                      "④ 主人调 `request.list` → 拿到待处理那一条（面板上就是这一行）",
                      str(_own.get("pendingCount")))
            _rows = (_own.get("requests") or [])[0]
            ok &= _ck("flag" not in _rows and "FLAG-R-" not in json.dumps(_own, ensure_ascii=False),
                      "④ ⛔ 列表响应里**没有 flag**（一次性凭据不上面板 / 不进接口）")
            _gid1 = _rows.get("id")
            _posts[:] = []
            _r = _api("request.approve", id=_gid1)
            ok &= _ck(_r and _r.get("ok") and len(_posts) == 1
                      and _posts[0][0] == "set_group_add_request"
                      and _posts[0][1].get("approve") is True
                      and _posts[0][1].get("sub_type") == "invite",
                      "④ 点「通过」→ 调 `set_group_add_request(approve=True, sub_type=invite)`",
                      str(_posts))
            ok &= _ck(not _rq.pending() and _rq.find(_gid1)["状态"] == _rq.APPROVED
                      and len(_r.get("history") or []) == 1,
                      "④ 通过之后**立刻从待处理列表里消失**（状态=已通过、进「处理过」那一列）",
                      "状态=%s" % (_rq.find(_gid1)["状态"],))

            # ── ⑤ 拒绝：好友 `approve=False`（⚠️ 好友接口**不带 reason**）；群邀请带原因 ──
            _rclean()
            _rcaches()
            _posts[:] = []
            _calls[:] = []
            _report(_friend_evt(flag="FLAG-R-好友2", user_id=_RF2))
            wait_until(lambda: len(_rq.pending()) == 1, timeout=5.0)
            _fid2 = (_rq.pending()[0]["id"] if _rq.pending() else "")
            _r2 = _api("request.reject", id=_fid2, reason="不认识")
            ok &= _ck(_r2 and _r2.get("ok") and len(_posts) == 1
                      and _posts[0][0] == "set_friend_add_request"
                      and _posts[0][1].get("approve") is False
                      and "reason" not in _posts[0][1],
                      "⑤ 拒绝好友 → `set_friend_add_request(approve=False)`，"
                      "而且**不带 reason**（好友这条接口没这个参数）", str(_posts))
            ok &= _ck(_rq.find(_fid2)["状态"] == _rq.REJECTED,
                      "⑤ 状态记成「已拒绝」")
            _rclean()
            _rcaches()
            _posts[:] = []
            _calls[:] = []
            _report(_invite_evt(flag="FLAG-R-群邀请2"))
            wait_until(lambda: len(_rq.pending()) == 1, timeout=5.0)
            _gid2 = (_rq.pending()[0]["id"] if _rq.pending() else "")
            _r3 = _api("request.reject", id=_gid2, reason="暂时不加群")
            ok &= _ck(_r3 and _r3.get("ok") and len(_posts) == 1
                      and _posts[0][0] == "set_group_add_request"
                      and _posts[0][1].get("approve") is False
                      and _posts[0][1].get("reason") == "暂时不加群",
                      "⑤ 拒绝群邀请 → `approve=False` 且**把你填的原因发给对方**", str(_posts))

            # ── ⑥ 「忽略」= **零 API 调用**，只是从待处理收起来（可恢复）──
            _rclean()
            _rcaches()
            _posts[:] = []
            _calls[:] = []
            _report(_friend_evt(flag="FLAG-R-忽略"))
            wait_until(lambda: len(_rq.pending()) == 1, timeout=5.0)
            _ig = (_rq.pending()[0]["id"] if _rq.pending() else "")
            # ⚠️ 这两行要在**收事件之后**清：收事件本身会问一次名字（那是查询，会进 _calls）。
            #    要钉的是"忽略这一个动作**零调用**"，不是"整个过程零调用"。
            _posts[:] = []
            _calls[:] = []
            _r4 = _api("request.ignore", id=_ig)
            ok &= _ck(_r4 and _r4.get("ok") and not _posts and not _calls,
                      "⑥ 点「忽略」→ **零 API 调用**（QQ 那边那条申请还挂着）", str(_posts))
            ok &= _ck(_rq.find(_ig)["状态"] == _rq.IGNORED and not _rq.pending(),
                      "⑥ 状态记成「已忽略」，从待处理列表消失")
            _r5 = _api("request.restore", id=_ig)
            ok &= _ck(_r5 and _r5.get("ok") and _rq.find(_ig)["状态"] == _rq.PENDING
                      and len(_rq.pending()) == 1,
                      "⑥ 「已忽略」还能**放回待处理**再决定（也不调任何 API）",
                      "状态=%s" % (_rq.find(_ig)["状态"],))

            # ── ⑦ 过期：挂超过 7 天的「待处理」→ 标成「已过期」（**不删**）──
            _rclean()
            _okE, _msgE, _recE = _rq.add(_rq.FRIEND, qq="10086", name="老申请", comment=_RCMT,
                                        flag="FLAG-R-老", at=time.time() - 8 * 86400)
            ok &= _ck(_okE and _recE and _recE["状态"] == _rq.PENDING,
                      "⑦ 造一条 8 天前的「待处理」（`add(at=…)`）", str(_recE))
            _n_exp = _rq.expire()
            _old = _rq.find(_recE["id"])
            ok &= _ck(_n_exp == 1 and _old and _old["状态"] == _rq.EXPIRED,
                      "⑦ 超过 %d 天的待处理 → 标成「已过期」" % _rq.TTL_DAYS)
            ok &= _ck(len(_rq.records()) == 1,
                      "⑦ **没有静默删掉**（记录还在，用户在面板的「处理过的申请」里看得见）")
            ok &= _ck(len(_rq.rows()) == 0 and len(_rq.rows(only_pending=False)) == 1,
                      "⑦ 默认列表**只显示「待处理」**（过期的进「已处理」那一列）")
            _r6 = _api("request.restore", id=_recE["id"])
            ok &= _ck(_r6 and _r6.get("ok") and _rq.find(_recE["id"])["状态"] == _rq.PENDING,
                      "⑦ 「已过期」也能放回待处理")
            ok &= _ck(_rq.expire() == 0 and _rq.find(_recE["id"])["状态"] == _rq.PENDING,
                      "⑦ 放回来之后**不会再被自动过期**（用户亲手捞回来的那条一直留着等他决定）")

            # ── ⑧ 只有主人能调：非主人 / 认不出身份 → FORBIDDEN（server 回 403 空正文）──
            _outs = []
            for _a in ("request.list", "request.approve", "request.reject",
                       "request.ignore", "request.restore"):
                _outs.append((_a, agent.on_api(_a, {"id": "XXXXXX"}, _FRIEND_IDENT)))
            ok &= _ck(all(o is agent.FORBIDDEN for _a, o in _outs),
                      "⑧ 非主人调 request.*（五个动作）→ 全部 FORBIDDEN"
                      "（`server.py` 看到它就回 **403 空正文**，和 user.* / group.* 同口径）",
                      str([(a, o is agent.FORBIDDEN) for a, o in _outs]))
            ok &= _ck(agent.on_api("request.list", {}, None) is agent.FORBIDDEN,
                      "⑧ 认不出身份（ident=None）也一律 FORBIDDEN —— 不许「没身份就当主人」")

            # ── ⑨ 事件里的别的字段 ⛔ 一个字都不落盘；验证消息**该**落盘 ──
            ok &= _ck(_RCANARY not in _state_text(),
                      "⑨ 事件里**别的**字段（`sender` 的昵称 / 名片）一个字都没进任何状态文件")
            ok &= _ck(_RCMT in (open(store.path(_rq.FILE), encoding="utf-8").read()
                                if os.path.exists(store.path(_rq.FILE)) else ""),
                      "⑨ **验证消息**确实进了 `requests.json`（这是面板要显示的那句话）")

            # ── ⑩ 老开关还留着：只有**真正的 true** 才自动同意（默认 false）──
            _rclean()
            _rcaches()
            _posts[:] = []
            _calls[:] = []
            base.cfg().setdefault("bot", {})["autoAcceptGroupInvite"] = True
            _report(_invite_evt(flag="FLAG-R-自动"))
            _auto = wait_until(lambda: any(p[0] == "set_group_add_request" for p in _posts),
                               timeout=5.0)
            _arec = [r for r in _rq.records() if r["flag"] == "FLAG-R-自动"]
            ok &= _ck(_auto and _posts[0][1].get("approve") is True,
                      "⑩ `autoAcceptGroupInvite=true` → **才**自动同意（这颗键留着，以后想自动还能开）",
                      str(_posts))
            ok &= _ck(_arec and _arec[0]["状态"] == _rq.APPROVED,
                      "⑩ 自动同意的那条**也入了库**、状态直接记「已通过」（面板上看得到）",
                      str(_arec))
            _rclean()
            _rcaches()
            _posts[:] = []
            _calls[:] = []
            base.cfg().get("bot", {}).pop("autoAcceptGroupInvite", None)
            _report(_invite_evt(flag="FLAG-R-默认"))
            _dft = wait_until(lambda: len(_rq.pending()) == 1, timeout=5.0)
            ok &= _ck(_dft and not _posts,
                      "⑩ 键**不在**（默认）→ 照样**不自动**（错的那一头必须是「等用户点」）",
                      "出站：%s" % (_posts,))

            # ── ⑪ 她那一层炸了也只写日志，绝不往外抛（不许影响别的消息处理）──
            #    ⚠️ 这里把 `base.log_exc` 也打桩：真让它写就会往 stdout 打一段 Traceback，
            #       而 deploy 会把带 "Traceback" 的行当成「自检里有告警」打出来。
            _real_add, _real_logexc = _rq.add, base.log_exc
            _raised, _excs = "", []

            def _boom(*a, **k):
                raise RuntimeError("桩故意炸")

            _rq.add = _boom
            base.log_exc = lambda where: _excs.append(where)
            try:
                agent.on_request(_friend_evt(flag="FLAG-R-炸"))
            except Exception as e:
                _raised = repr(e)
            finally:
                _rq.add = _real_add
                base.log_exc = _real_logexc
            ok &= _ck(_raised == "" and _excs == ["on_request"],
                      "⑪ 中间出任何异常 → 只写一行日志（`log_exc('on_request')`），**绝不往外抛**",
                      "抛了：%s ｜ 写日志：%s" % (_raised or "（没抛 ✓）", _excs))

            # ── ⑫ deploy.py 的 NEVER 里要有 requests.json；面板那一块要在、且不带令牌 ──
            if _dep:
                ok &= _ck('"requests.json"' in _never,
                          "⑫ deploy.py 的 NEVER 里有 requests.json"
                          "（推代码不会覆盖手机上还没裁决的申请）")
            else:
                print("    ⚠️ 读不到 deploy.py（手机上跑的是暂存目录）—— NEVER 那条在本地自检里查")
            _html = panel.render()
            _tokH = str(base.napcat_token() or "")
            ok &= _ck(bool(_tokH) and _tokH not in _html,
                      "⑫ 面板 HTML 里没有令牌（加了「申请」那一页之后照样成立）")
            ok &= _ck('<h3 id="reqHead">待处理</h3>' in _html and "已处理" in _html
                      and "request.approve" in _html
                      and "request.reject" in _html and "request.ignore" in _html,
                      "⑫ 面板上确实有「待处理 / 已处理」那两张卡（三个动作名也都在）")
            ok &= _ck("没有待处理的申请" in _html and "request.restore" in _html,
                      "⑫ 0 条时的说法（「没有待处理的申请」）和「放回待处理」都写在面板上")
            ok &= _ck("忽略" in _html and "放回待处理" in _html and "已过期" in _html,
                      "⑫ 面板上「忽略」的 tooltip（只是这里不看了）、「放回待处理」按钮、"
                      "「已过期」那档状态都还在")
            ok &= _ck("通过" in _html and "真的同意" in _html,
                      "⑫ 「通过」按钮的 tooltip 和二次确认弹窗里写着：通过 = 真的同意"
                      "（好友会加上 / 她会进群）")

            # ── ⑬ 开关的默认值 / 现在用户 config 里是什么 ──
            try:
                with open(base.CFG_PATH, encoding="utf-8") as _cf:
                    _cfgfile = json.load(_cf)
                _sw_now = ("bot" in _cfgfile) and _cfgfile["bot"].get(
                    "autoAcceptGroupInvite", "（没有这颗键）")
            except Exception as _e:
                _sw_now = "读不出来：%r" % (_e,)
            ok &= _ck(_sw_now is False,
                      "⑬ 这台机器的 `config.json`：`bot.autoAcceptGroupInvite` = **false**"
                      "（不再自动同意；键留着，以后想自动还能开）",
                      "现在用户 config 里是 %r" % (_sw_now,))
        finally:
            im._napcat_post, im._napcat_call = _real_post, _real_call
            if _sw_backup is None:
                base.cfg().get("bot", {}).pop("autoAcceptGroupInvite", None)
            else:
                base.cfg().setdefault("bot", {})["autoAcceptGroupInvite"] = _sw_backup
            try:
                _srvI.shutdown()
                _srvI.server_close()
            except Exception:
                pass
            _rcaches()
            _rclean()

        # ══════════════════════════════════════════════════════════════
        # 6.10 消息装配（2026-10-09 那一批的两件事，用户逐条点的）
        #
        #   ① 「问战况」那一回合：她第 1 次自己调 `pc_status` → **第 2 次请求**
        #      只留「system + 当前那句 + 她自己的 tool_calls + tool 结果」，
        #      ⛔ 更早的对话历史一条都不带；而**第 1 次请求一个字不动**（历史照旧在）。
        #   ② 别的工具（`memory` / `search` / …）第 2 次**照旧带历史**
        #      （回归：⛔ 不许跟着 `pc_status` 一起砍 —— 用户点名只砍那一个）。
        #   ③ 播报（`announce`）：**一条对话历史都不带**，形状 = [system] + [材料/指令]。
        #
        #   ⚠️ 走的是**真入口**（`agent._think`，跟 `handle()` 里那个 worker 同一条路），
        #      只把模型那层换成假传输层；断言比的是**请求里那串 messages**（wire 形状）。
        #   ⛔ 这一节不联网、不发消息：模型 = 假传输层，NapCat 那道缝（`_napcat_call`）
        #      打桩（不查群名），两个发送口也打桩；状态文件都在临时目录里。
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.10 消息装配：战况第 2 次不带历史 / 播报不带历史（打桩、离线）"
        print("=== 6.10 消息装配：战况第 2 次不带历史 / 播报不带历史（打桩、离线）===")

        _MS_GID, _MS_QQ = 888777666, 10001
        _MS_HIST = ["（自检历史甲）", "（自检历史乙）", "（自检历史丙）"]
        _ms_shots = []          # 每次请求的 messages（按 wire 形状存一份）
        _ms_inputs = []         # `run_turn` 每次进来时那份 messages（= 拼装器给的）
        _ms_sent = []
        # ⚠️ 「这一节正在跑」的开关：提醒到点那种**后台**回合也可能在同一时刻进来
        #    （它走 `llm.run_turn`）。不挡住的话，它会吃脚本、污染 `_ms_shots`，
        #    这一节就变成**偶发红**（部署时随机中止）。挡住之后：后台那条照旧能跑，
        #    只是不算进这一节的账。
        _ms_busy = {"on": False}
        _ms_real_call, _ms_real_sg = im._napcat_call, im.send_group
        _ms_real_sp, _ms_real_run = im.send_private, llm.run_turn

        def _ms_copy(x):
            """按 wire 形状复制一份（跟真发出去的那串 JSON 逐字对应）。"""
            return json.loads(json.dumps(x, ensure_ascii=False))

        def _ms_seq(ms):
            """角色 + 长度（⛔ 不打原文）。"""
            out = []
            for m in ms:
                c = m.get("content")
                n = len(c) if isinstance(c, str) else sum(
                    len(p.get("text") or "") for p in (c or []) if isinstance(p, dict))
                tag = str(m.get("role"))
                if m.get("tool_calls"):
                    tag += "+tool_calls(%s)" % ",".join(
                        (tc.get("function") or {}).get("name") or "?"
                        for tc in m["tool_calls"])
                out.append("%s(%d)" % (tag, n))
            return " ".join(out)

        def _ms_stub(script):
            """假模型：按脚本回（`("tool", 名字, 参数)` / `("text", 内容)`）。"""
            _it = iter(script)

            def _fn(url, payload, headers, timeout):
                if not _ms_busy["on"]:
                    # 不是这一节的回合（后台提醒那种）—— 给个中性回复，⛔ 不记进这一节的账
                    return {"model": "stub-模型",
                            "choices": [{"index": 0, "finish_reason": "stop",
                                         "message": {"role": "assistant",
                                                     "content": "（自检：后台那条）"}}],
                            "usage": {}}
                _ms_shots.append(_ms_copy(payload.get("messages")))
                _k = next(_it)
                if _k[0] == "tool":
                    return {"model": "stub-模型",
                            "choices": [{"index": 0, "finish_reason": "tool_calls",
                                         "message": {"role": "assistant", "content": "",
                                                     "tool_calls": [
                                                         {"id": "call_p%d" % len(_ms_shots),
                                                          "type": "function",
                                                          "function": {
                                                              "name": _k[1],
                                                              "arguments": json.dumps(
                                                                  _k[2], ensure_ascii=False)}}]}}],
                            "usage": {}}
                return {"model": "stub-模型",
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": _k[1]}}],
                        "usage": {}}
            return _fn

        def _ms_ctx(text):
            return {"key": ("g", _MS_GID), "is_group": True, "group_id": _MS_GID,
                    "user_id": _MS_QQ, "who": "自检", "text": text, "raw": text,
                    "images": [], "reply_to": None, "message_id": 1,
                    "at": time.time(), "evt": {}}

        def _ms_seed():
            """造一段**自检自己写的**历史（跟真群聊无关）：砍没砍掉就看她还看不看得见它。"""
            key = ("g", _MS_GID)
            memory.reset([key])
            memory.record(key, "user", _MS_HIST[0], qq=100000011, name="甲")
            memory.record(key, "assistant", _MS_HIST[1])
            memory.record(key, "user", _MS_HIST[2], qq=100000012, name="丙")
            return key

        def _ms_run(msgs, ctx):
            if not _ms_busy["on"]:
                return _ms_real_run(msgs, ctx)          # 后台那条：原样走，不算进这一节
            _ms_inputs.append(_ms_copy(msgs))
            return _ms_real_run(msgs, ctx)

        def _ms_turn(tool_name, args, label, want_history):
            """一个「她第 1 次就调了 `tool_name`」的回合。"""
            nonlocal ok
            _ms_shots[:] = []
            _ms_inputs[:] = []
            key = _ms_seed()
            ctx = _ms_ctx("问战况")
            memory.record(key, "user", "问战况", qq=_MS_QQ, name="自检")
            llm.run_turn = _ms_run
            llm.set_transport(_ms_stub([("tool", tool_name, args),
                                        ("text", "（自检：她的话）")]))
            _ms_busy["on"] = True
            try:
                agent._think(ctx, "触发词")
            finally:
                _ms_busy["on"] = False
                llm.set_transport(None)
                llm.run_turn = _ms_real_run
            shots = list(_ms_shots)
            print("  %s" % label)
            for _i, _ms in enumerate(shots, 1):
                print("    请求#%d：%s" % (_i, _ms_seq(_ms)))
            ok &= _ck(len(shots) == 2, "%s：这一回合正好**两次**请求" % label,
                      "%d 次" % len(shots))
            if len(shots) != 2:
                return
            _cut = ctx.get("_hist_range") or (0, 0)
            _j1 = json.dumps(shots[0], ensure_ascii=False)
            _j2 = json.dumps(shots[1], ensure_ascii=False)
            _has1 = all(h in _j1 for h in _MS_HIST)
            _has2 = any(h in _j2 for h in _MS_HIST)
            # ① 第 1 次请求 = 拼装器给的那份，**逐字**（历史一条不少）
            #    ⚠️ B1 之后历史段从第 2 条开始（第 1 条是「你看到的是这个群最近 N 条消息」）；
            #    ⚠️ 2026-10-31 起最前面多一条**技能目录**（system 之后、历史之前），
            #       所以历史段整体后移一位（`_cut` 由拼装器现算，这里跟着它走）。
            _cat_at = 1 if capabilities.catalog_text() else 0
            ok &= _ck(shots[0] == _ms_inputs[0]
                      and _cut == (2 + _cat_at, 2 + _cat_at + len(_MS_HIST)) and _has1,
                      "%s：① 第 1 次请求**逐字** = 拼装的那份、历史照旧在"
                      "（历史段 = %r，system 在最前）" % (label, _cut), _ms_seq(shots[0]))
            # ② 第 2 次请求的开头**逐字** = 「system + 快照 + 当前那句」
            #    （C-3：按 `_hist_range` 这段**本轮边界**切，不是按最后一条 system）
            _keep = list(_ms_inputs[0][:_cut[0]]) + list(_ms_inputs[0][_cut[1]:])
            _roles2 = [m.get("role") for m in shots[1]]
            if not want_history:
                ok &= _ck(shots[1][:len(_keep)] == _keep,
                          "%s：② 第 2 次请求开头**逐字** =「system + 快照 + 当前那句」（%d 条）"
                          % (label, len(_keep)))
            # ②' 历史该在的在、该不在的不在
            ok &= _ck(_has2 == want_history,
                      "%s：② 第 2 次请求%s更早的对话历史（期望：%s）"
                      % (label, "**还带着**" if _has2 else "**不带**",
                         "带着" if want_history else "不带"), _ms_seq(shots[1]))
            # ③ 序列合法性（tool 必须紧跟它的 tool_calls）
            ok &= _ck(llm._pairing_ok(shots[0]) and llm._pairing_ok(shots[1]),
                      "%s：③ 两次请求都是合法序列（每条 tool 紧跟它的 tool_calls）" % label)
            if want_history:
                ok &= _ck(shots[1][:len(_ms_inputs[0])] == _ms_inputs[0],
                          "%s：第 2 次 = 原样那份 + 她的 tool 往返（历史一个字节没动）" % label)
            else:
                # 2026-10-31 起开头多一条技能目录（system 之后、历史之前）——
                # 期望形状 = system + 技能目录 + 最近N条 + 快照 + 当前那句 + 她的 tool 往返
                _want_roles = (["system"] + (["user"] if _cat_at else [])
                               + ["user", "user", "user", "assistant", "tool"])
                ok &= _ck(_roles2 == _want_roles,
                          "%s：② 第 2 次请求的序列 = system +（技能目录）+ 最近N条 + 快照"
                          " + 当前那句 + assistant(tool_call) + tool" % label,
                          " ".join(_roles2))

        def _ms_announce():
            """③ 播报：一条对话历史都不带（材料 / 指令一个字不改）。"""
            nonlocal ok
            _ms_shots[:] = []
            _ms_seed()                       # 先塞一段历史：播报那条路要是还带，这里就露馅
            _row = {"站点": "自检站", "持续时长": "2分0秒", "开始时间": "15:52"}
            llm.set_transport(_ms_stub([("text", "（自检：播报）")]))
            _ms_busy["on"] = True
            try:
                agent._announce({"action": "announce", "facts": {"人": "自检", "数据": [_row]},
                                 "group_id": _MS_GID}, None)
            finally:
                _ms_busy["on"] = False
                llm.set_transport(None)
            ann = list(_ms_shots)
            print("  ③ 播报（announce）：")
            for _i, _ms in enumerate(ann, 1):
                print("    请求#%d：%s" % (_i, _ms_seq(_ms)))
            _a0 = ann[0] if ann else []          # 那一次请求的 messages
            _aroles = [m.get("role") for m in _a0]
            ok &= _ck(_aroles == ["system", "user"],
                      "③ 播报请求的形状就是 [system] + [材料/指令]（⛔ 一条历史都没有）",
                      " ".join(_aroles))
            ok &= _ck(bool(_a0) and _a0[0].get("content") == persona.system_prompt(),
                      "③ 播报的系统提示词**逐字** = persona.system_prompt()（人设一个字没动）")
            _acont = ((_a0[1].get("content") if len(_a0) > 1 else "") or "")
            _arow = json.dumps(_row, ensure_ascii=False, separators=(",", ":"))
            ok &= _ck(_arow in _acont and "<system-reminder>" in _acont
                      and str(_MS_GID) in _acont,
                      "③ 材料（那一行记录逐字）+ 指令（`<system-reminder>` / 收件群）都在")
            ok &= _ck(not any(h in _acont for h in _MS_HIST),
                      "③ ⛔ 那段对话历史一个字都没进播报请求")

        def _ms_repeat():
            """A4：同工具 + 同参数第 3 次出现 → 塞一条 <system-reminder>（只提醒不禁止）。"""
            nonlocal ok
            _ms_shots[:] = []
            _ms_inputs[:] = []
            key = _ms_seed()
            ctx = _ms_ctx("再问一次")
            memory.record(key, "user", "再问一次", qq=_MS_QQ, name="自检")
            llm.run_turn = _ms_run
            llm.set_transport(_ms_stub([("tool", "now", {}), ("tool", "now", {}),
                                        ("tool", "now", {}), ("text", "（自检：重复调用）")]))
            _ms_busy["on"] = True
            try:
                agent._think(ctx, "触发词")
            finally:
                _ms_busy["on"] = False
                llm.set_transport(None)
                llm.run_turn = _ms_real_run
            _rep = list(_ms_shots)
            print("  ④ A4 重复调用（同一工具 + 同一组参数）：")
            for _i, _ms in enumerate(_rep, 1):
                print("    请求#%d：%s" % (_i, _ms_seq(_ms)))
            _want = ("<system-reminder>\n同一个工具（now）、同一组参数，这一轮你已经调了 3 次了，"
                     "结果不会变。换个参数，或者就用现在手里的东西把话说出来\n</system-reminder>")
            _has3 = bool(_rep) and any(m.get("role") == "user" and m.get("content") == _want
                                       for m in _rep[3]) if len(_rep) > 3 else False
            _has2 = any("同一个工具（now）" in str(m.get("content"))
                        for m in _rep[2]) if len(_rep) > 2 else False
            _has1 = bool(_rep) and any("同一个工具（now）" in str(m.get("content"))
                                       for m in _rep[0]) if _rep else False
            ok &= _ck(len(_rep) == 4 and not _has1 and not _has2 and _has3,
                      "A4 第 3 次同工具同参数才塞提醒（第 1、2 次不塞；形态逐字）",
                      "%d 次请求 / 前两次含=%s,%s 第3次含=%s" % (len(_rep), _has1, _has2, _has3))
            ok &= _ck(bool(_rep) and llm._pairing_ok(_rep[-1]),
                      "A4 提醒插在**这一批 tool 消息之后**（tool_calls ↔ tool 配对没坏）")

        try:
            im._napcat_call = lambda ep, payload, **kw: (True, {"group_name": "自检专用群"})
            im.send_group = lambda *a, **kw: (_ms_sent.append(a), True)[1]
            im.send_private = lambda *a, **kw: (_ms_sent.append(a), True)[1]
            _ms_turn("pc_status", {"who": ""},
                     "① 战况（pc_status）：第 2 次**不带**历史", want_history=False)
            _ms_turn("memory", {"who": ""},
                     "② 别的工具（memory）：第 2 次**照旧带**历史", want_history=True)
            _ms_repeat()
            _ms_announce()
            ok &= _ck(bool(_ms_sent), "（这一节真的调到了发送那一步 —— 打桩，一条都没发出去）")
        finally:
            llm.set_transport(None)
            llm.run_turn = _ms_real_run
            im._napcat_call, im.send_group = _ms_real_call, _ms_real_sg
            im.send_private = _ms_real_sp

        # ══════════════════════════════════════════════════════════════
        # 6.11 max_tokens 续写（2026-10-30，用户拍板：照 DSH 的做法）
        #
        #   DSH：`finish=max-tokens` **不覆盖结束状态** → 接着问，让她把话说完。
        #   这里钉四件事：
        #   ① 半截文本 + 后面的正文**连续**拼接（中间不插空格、不插换行）；
        #   ② 半截的 tool_calls 照旧**一个都不执行**（老行为不许变）；
        #   ③ 续写**不占工具轮次**；续写后她给 tool_calls 就照常执行，文本保留；
        #   ④ 安全阀：连续 3 次续写之后第 4 次撞 length 就不再请求（共 4 次）。
        #
        #   ⚠️ 只把模型那层换成假传输层，别的全走真入口（`llm.run_turn`）。
        #   ⛔ 不联网、不发消息。
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.11 max_tokens 续写（撞 length 不结束；打桩、离线）"
        print("=== 6.11 max_tokens 续写（撞 length 不结束；打桩、离线）===")

        _CW_MARK = "（自检：max_tokens 续写）"
        _cw = {"n": 0, "shots": []}

        def _cw_stub(script):
            """按脚本回：`("length", 文本)` / `("tool", 名字, 参数)` / `("text", 内容)`。

            ⚠️ 只服务这一节自己的请求（靠 `_CW_MARK` 认人）：后台提醒那种回合
               撞进来也不许吃脚本、不许记进这一节的账。
            """
            _it = iter(script)

            def _fn(url, payload, headers, timeout):
                _msgs = payload.get("messages") or []
                _mine = any(m.get("role") == "user" and m.get("content") == _CW_MARK
                            for m in _msgs)
                if not _mine:
                    return {"model": "stub-模型",
                            "choices": [{"index": 0, "finish_reason": "stop",
                                         "message": {"role": "assistant",
                                                     "content": "（自检：别的回合）"}}],
                            "usage": {}}
                _cw["n"] += 1
                _cw["shots"].append(json.loads(json.dumps(_msgs, ensure_ascii=False)))
                try:
                    _k = next(_it)
                except StopIteration:
                    _k = ("text", "（自检脚本用完了）")
                if _k[0] == "length":
                    return {"model": "stub-模型",
                            "choices": [{"index": 0, "finish_reason": "length",
                                         "message": {"role": "assistant",
                                                     "content": _k[1]}}],
                            "usage": {}}
                if _k[0] == "tool":
                    return {"model": "stub-模型",
                            "choices": [{"index": 0, "finish_reason": "tool_calls",
                                         "message": {"role": "assistant", "content": "",
                                                     "tool_calls": [
                                                         {"id": "call_cw%d" % _cw["n"],
                                                          "type": "function",
                                                          "function": {
                                                              "name": _k[1],
                                                              "arguments": json.dumps(
                                                                  _k[2], ensure_ascii=False)}}]}}],
                            "usage": {}}
                return {"model": "stub-模型",
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": _k[1]}}],
                        "usage": {}}
            return _fn

        def _cw_turn(script, max_rounds=None):
            """真跑一轮 `run_turn`，返回 (文本, 工具, 错误, 每次请求的 messages)。"""
            _cw["n"] = 0
            _cw["shots"] = []
            llm.set_transport(_cw_stub(script))
            msgs = [{"role": "system", "content": "（自检）"},
                    {"role": "user", "content": _CW_MARK}]
            try:
                _t, _c, _e = llm.run_turn(msgs, {}, max_rounds=max_rounds)
                return _t, _c, _e, list(_cw["shots"])
            finally:
                llm.set_transport(None)

        # ── ① 撞一次 length → 接着问；两段文本连续拼接 ──
        _log0 = len(_read_log())
        _t1, _c1, _e1, _s1 = _cw_turn([("length", "我在想"), ("text", "好了。")])
        print("  ① length 一次 → %r（请求 %d 次）" % (_t1, _cw["n"]))
        ok &= _ck(_t1 == "我在想好了。" and _cw["n"] == 2 and not _e1 and not _c1,
                  "① 撞到 max_tokens → **不结束**，接着问；两段文本连续拼接",
                  "%r ／ 请求 %d 次" % (_t1, _cw["n"]))
        _hist1 = list(_cw["shots"][1]) if len(_cw["shots"]) > 1 else []
        _asst1 = [m for m in _hist1 if m.get("role") == "assistant"]
        ok &= _ck(len(_hist1) == 3 and len(_asst1) == 1
                  and _asst1[0].get("content") == "我在想"
                  and not _asst1[0].get("tool_calls"),
                  "① 半截的 assistant 消息（逐字）追加进了 messages；半截 tool_calls 一个没留",
                  "%d 条 / %s" % (len(_hist1), llm._digest({"messages": _hist1})))
        _log1 = _read_log()[_log0:]
        ok &= _ck("第 1 次续写" in _log1 and "这次撞到了 max_tokens 上限" in _log1,
                  "① 续写时两行日志都在（老那行保留 + 「第 N 次续写」）",
                  " ｜ ".join(l for l in _log1.splitlines()
                             if "续写" in l or "max_tokens" in l)[:120])

        # ── ② 安全阀：连续撞 length 最多续写 3 次，第 4 次收手 ──
        _log0 = len(_read_log())
        _t2, _c2, _e2, _s2 = _cw_turn([("length", "第一段"), ("length", "第二段"),
                                       ("length", "第三段"), ("length", "第四段")])
        _log2 = _read_log()[_log0:]
        print("  ② 连续 length → %r（请求 %d 次）" % (_t2, _cw["n"]))
        ok &= _ck(_cw["n"] == 4 and _t2 == "第一段第二段第三段第四段",
                  "② 安全阀：连撞 3 次后第 4 次**不再请求**（共 4 次），已写出的全拼回来",
                  "%d 次请求 ／ %r" % (_cw["n"], _t2))
        ok &= _ck("不再续写" in _log2,
                  "② 安全阀踩下时**记了一条日志**",
                  " ｜ ".join(l for l in _log2.splitlines()
                             if "不再续写" in l)[:120])
        ok &= _ck("第 3 次续写" in _log2 and "第 4 次续写" not in _log2,
                  "② 每次继续都记「第 N 次续写」；第 4 次没继续，不记")

        # ── ③ 续写之后给 tool_calls → 工具照常执行，拼接文本保留（正常正文返回）──
        _log0 = len(_read_log())
        _t3, _c3, _e3, _s3 = _cw_turn([("length", "我在想"), ("tool", "now", {}),
                                       ("text", "好了。")])
        print("  ③ length → tool_calls → 正文：%r（工具 %r，请求 %d 次）"
              % (_t3, _c3, _cw["n"]))
        ok &= _ck(_cw["n"] == 3 and _c3 == ["now"] and _t3 == "我在想好了。",
                  "③ 续写之后给 tool_calls → 工具照常执行、拼接文本保留",
                  "%r ／ 工具 %r ／ 请求 %d 次" % (_t3, _c3, _cw["n"]))
        _last3 = _s3[-1] if _s3 else []
        _seq3 = [m.get("role") for m in _last3]
        ok &= _ck(bool(_last3) and llm._pairing_ok(_last3),
                  "③ 续写 + 工具往返之后序列合法（每条 tool 紧跟它的 tool_calls）",
                  " ".join(_seq3))
        _log3 = _read_log()[_log0:]
        ok &= _ck("第 1 次续写" in _log3 and "撞到了 max_tokens 上限" in _log3,
                  "③ 续写攒文本这一路只记了「第 1 次续写」一次（后面是完整回复，计数已清零）")

        # ── ④ 续写**不吃工具轮次**（连着两个工具 + max_rounds=2）──
        #    ⚠️ 要是"续写"偷偷占掉一个工具轮次，第二个工具就不会执行
        #       （`tool_rounds` 提前到 2，工具目录被摘），这条立刻变红。
        _t4, _c4, _e4, _s4 = _cw_turn([("length", "我在想"), ("tool", "now", {}),
                                       ("tool", "now", {}), ("text", "好了。")],
                                      max_rounds=2)
        print("  ④ length → 两个工具（max_rounds=2）：%r（工具 %r，请求 %d 次）"
              % (_t4, _c4, _cw["n"]))
        ok &= _ck(_cw["n"] == 4 and _c4 == ["now", "now"] and _t4 == "我在想好了。",
                  "④ 续写**没吃掉工具轮次**（max_rounds=2，两个工具都执行了；"
                  "轮次用完那一步也没丢攒下的文本）",
                  "%r ／ 工具 %r ／ 请求 %d 次" % (_t4, _c4, _cw["n"]))
        _last4 = _s4[-1] if _s4 else []
        ok &= _ck(bool(_last4) and llm._pairing_ok(_last4),
                  "④ 轮次用完后的最后一次请求序列合法（tool_calls ↔ tool 都配得上）",
                  " ".join(m.get("role") for m in _last4))

        # ── ⑤ 轮次快用完 / 用完：两句事实（2026-10-30 用户定）──
        _t5, _c5, _e5, _s5 = _cw_turn([("tool", "now", {}), ("tool", "now", {}),
                                       ("text", "好了。")], max_rounds=2)
        _blob5 = " ".join(str(m.get("content") or "") for _s in _s5 for m in _s)
        ok &= _ck("工具次数快用完了" in _blob5 and "工具次数用完了" in _blob5,
                  "⑤ 轮次快用完时提醒一次、用完时再塞一句事实",
                  "%r" % [c for c in _blob5.split() if "工具次数" in c][:2])

        # ═══ 6.10b 战况连调两次（2026-10-30 修的既有 bug）═════════════════════
        #   ① 第 1 次剪掉历史 ✓ ② 剪完要把 `_hist_range` 收窄成空区间 ✓
        #   ③ 同一轮第 2 次调 pc_status 时**不许再剪** —— 旧代码用旧下标，
        #      下标已移位，会把「快照 + 当前那句」也删掉（配对仍合法、不报错、静默变傻）。
        print()
        _CUR_SECT[0] = "6.10b 连续两次 pc_status 的剪枝（离线）"
        print("=== 6.10b 连续两次 pc_status 的剪枝（离线）===")
        _tb = [{"role": "system", "content": "S"},
               {"role": "user", "content": "历史甲"},
               {"role": "assistant", "content": "历史乙"},
               {"role": "user", "content": "快照"},
               {"role": "user", "content": "当前这句"}]
        _tb_ctx = {"_hist_range": (1, 3)}
        _tb1 = llm._trim_history_after_tool(_tb, ["pc_status"], _tb_ctx)
        _tb.append({"role": "assistant", "content": None,
                    "tool_calls": [{"id": "t1", "type": "function",
                                    "function": {"name": "pc_status", "arguments": "{}"}}]})
        _tb.append({"role": "tool", "tool_call_id": "t1", "content": "{}"})
        _tb2 = llm._trim_history_after_tool(_tb, ["pc_status"], _tb_ctx)
        _tb_keep = [m.get("content") for m in _tb]
        print("  ① 剪 %d 条 → ② 再剪 %d 条；剩下 %r" % (_tb1, _tb2, _tb_keep))
        ok &= _ck(_tb1 == 2 and _tb2 == 0,
                  "连续两次 pc_status：第二次不再剪（本轮已剪过，只认标记）",
                  "剪 %d / %d 条" % (_tb1, _tb2))
        ok &= _ck("快照" in _tb_keep and "当前这句" in _tb_keep,
                  "连续两次 pc_status：快照和当前那句都还在（旧 bug：会被一起删掉）",
                  "%r" % (_tb_keep,))

        # ═══ 6.z 2026-10-30「agent 升级」第 5~13 步 ═══════════════════════════
        #    合并工具（memory / callname / wake）/ 唤醒到点那一轮 / history /
        #    plan / memory-keeper / B1 私聊字数窗口 / B2 截断明说 / B3 自动压缩。
        print()
        _CUR_SECT[0] = "6.z agent 升级（第 5~13 步）"
        print("=== 6.z agent 升级（第 5~13 步）===")
        from fgbot import history as _hist
        from fgbot import keeper as _keeper
        from fgbot import plan as _plan

        # ── ① 过去的说法（history 要用；⛔ 将来那套一个字都不许变）──
        _pn = datetime(2026, 9, 25, 22, 0)
        _pn_ts = clock.stamp(_pn)
        ok &= _ck(abs(reminders.parse_when("3天前", now=_pn, past=True)[0]
                      - (_pn_ts - 3 * 86400)) < 3,
                  "过去模式：「3天前」= 正好三天前",
                  reminders.parse_when("3天前", now=_pn, past=True)[1])
        ok &= _ck(abs(reminders.parse_when("20分钟前", now=_pn, past=True)[0]
                      - (_pn_ts - 1200)) < 3,
                  "过去模式：「20分钟前」= 正好二十分钟前")
        ok &= _ck(abs(reminders.parse_when("昨天晚上", now=_pn, past=True)[0]
                      - (_pn_ts - 26 * 3600)) < 3,
                  "过去模式：「昨天晚上」= 昨天 20:00",
                  reminders.parse_when("昨天晚上", now=_pn, past=True)[1])
        _pm_future = True
        try:
            reminders.parse_when("明天早上7点", past=True)
        except ValueError:
            _pm_future = False
        ok &= _ck(not _pm_future, "过去模式：⛔ 不接受将来的说法（不然 history 会查反）")
        ok &= _ck(abs(reminders.parse_when("20分钟后", now=_pn)[0] - (_pn_ts + 1200)) < 3
                  and reminders.parse_when("九点半", now=_pn)[0] > _pn_ts + 3600
                  and abs(reminders.parse_when("9点30分", now=_pn)[0]
                          - reminders.parse_when("九点半", now=_pn)[0]) < 2,
                  "⛔ 将来那套一个字都没变（20分钟后 / 九点半 / 9点30分 还是老结果）")

        # ── ①′ 英文时间（2026-10-30，用户拍板要的；中文那套一个分支都不动）──
        #    时间基准 = 2026-09-25 星期五 10:00（「tonight / today 3pm」才落在将来）
        _am = datetime(2026, 9, 25, 10, 0)
        _am_ts = clock.stamp(_am)
        ok &= _ck(abs(reminders.parse_when("tomorrow 8am", now=_am)[0]
                      - (_am_ts + 22 * 3600)) < 3
                  and reminders.parse_when("tomorrow morning", now=_am)[0]
                  == reminders.parse_when("tomorrow 8am", now=_am)[0],
                  "英文：「tomorrow 8am / tomorrow morning」= 明天 08:00",
                  reminders.parse_when("tomorrow 8am", now=_am)[1])
        ok &= _ck(abs(reminders.parse_when("in 20 minutes", now=_am)[0]
                      - (_am_ts + 1200)) < 3
                  and abs(reminders.parse_when("in 2 hours", now=_am)[0]
                          - (_am_ts + 7200)) < 3,
                  "英文：「in 20 minutes / in 2 hours」= 准的")
        _h_tonight = reminders.parse_when("tonight", now=_am)[1]
        _h_today3 = reminders.parse_when("today 3pm", now=_am)[1]
        ok &= _ck(_h_tonight.startswith("2026-09-25 今天 20:00")
                  and _h_today3.startswith("2026-09-25 今天 15:00"),
                  "英文：「tonight / today 3pm」= 今天 20:00 / 15:00", _h_tonight)
        _h_at9 = reminders.parse_when("at 9", now=_am)[1]
        _h_830 = reminders.parse_when("8:30pm", now=_am)[1]
        ok &= _ck(_h_at9.startswith("2026-09-26 明天 09:00")
                  and _h_830.startswith("2026-09-25 今天 20:30"),
                  "英文：「at 9」顺延明天 09:00、「8:30pm」= 今天 20:30", _h_830)
        ok &= _ck(reminders.parse_when("next monday", now=_am)[0] > _am_ts + 2 * 86400
                  and reminders.parse_when("this friday", now=_am)[0] > _am_ts,
                  "英文：「next monday / this friday」都能算成将来",
                  "%s ｜ %s" % (reminders.parse_when("next monday", now=_am)[1],
                                reminders.parse_when("this friday", now=_am)[1]))
        ok &= _ck(abs(reminders.parse_when("3 days ago", now=_am, past=True)[0]
                      - (_am_ts - 3 * 86400)) < 3
                  and abs(reminders.parse_when("yesterday 3pm", now=_am, past=True)[0]
                          - (_am_ts - 19 * 3600)) < 3,
                  "英文（过去模式，history 用）：「3 days ago / yesterday 3pm」",
                  reminders.parse_when("yesterday 3pm", now=_am, past=True)[1])

        # ── ② plan：整张表替换 / 去重 / 只留一个进行中 / 注入 / 全完成自动清空 ──
        _pk = ("g", 123456789)
        _plan.clear(_pk)
        _st = [{"content": "查昨天战况", "status": "已完成"},
               {"content": "比对两天数据", "status": "进行中"},
               {"content": "写成一句话发给他", "status": "未开始"},
               {"content": "比对两天数据", "status": "未开始"},        # 重复 → 去重
               {"content": "多插一条", "status": "进行中"}]            # 第二个进行中 → 降级
        _pr = _plan.update(_pk, "把两天的战况比一下", _st)
        ok &= _ck(_pr.get("ok") is True and _pr.get("还有几步") == 3
                  and set(_pr) == {"ok", "目标", "步骤", "还有几步"},
                  "plan：返回键 = 目标 / 步骤 / 还有几步（第 10 条）", str(_pr)[:70])
        _tbl = _plan.table(_pk)
        ok &= _ck(_tbl == ("计划：把两天的战况比一下\n"
                           "1. 查昨天战况 — 已完成\n"
                           "2. 比对两天数据 — 进行中\n"
                           "3. 写成一句话发给他 — 未开始\n"
                           "4. 多插一条 — 未开始"),
                  "plan：整张表**逐字**（附在快照末尾，第 10 条第 (3) 块那种写法）", repr(_tbl))
        ok &= _ck(_plan.table(("g", 424242)) == "",
                  "plan：没有计划 → 一个字都不加")
        _real_call_p = im._napcat_call
        im._napcat_call = lambda ep, payload, **kw: (True, None)     # 群名查不到（别联网）
        try:
            _occ_p = agent._occasion({"key": _pk, "is_group": True, "group_id": 123456789,
                                      "user_id": 10001}, True)
        finally:
            im._napcat_call = _real_call_p
        ok &= _ck(bool(_tbl) and _tbl in _occ_p,
                  "plan：只要还有没做完的步骤 → **每一轮快照**都附整张表")
        _wait_ctx = {"key": _pk, "is_group": True, "group_id": 123456789,
                     "user_id": 10001, "who": "张三"}
        _captured = []
        _real_rt_p = llm.run_turn
        llm.run_turn = lambda msgs, ctx, **kw: (_captured.append(
            [m.get("content") for m in msgs]), ("", [], ""))[1]
        im._napcat_call = lambda ep, payload, **kw: (True, None)
        try:
            agent._on_due({"id": 999, "at": time.time() + 60, "what": "看看",
                           "group_id": 123456789, "user_id": 10001, "who": "张三",
                           "key": ["g", 123456789], "where_qq": "", "where_name": ""})
        finally:
            im._napcat_call = _real_call_p
            llm.run_turn = _real_rt_p
        _wj_p = json.dumps(_captured[0] if _captured else [], ensure_ascii=False)
        ok &= _ck("计划：把两天的战况比一下" in _wj_p and "1. 查昨天战况 — 已完成" in _wj_p,
                  "第 10 条：唤醒到点那一轮也把**整张计划表**带上")
        ok &= _ck(_plan.update(_pk, "", [{"content": "a", "status": "已完成"}]).get("还有几步") == 0
                  and _plan.table(_pk) == "",
                  "plan：全部完成 → 自动清空（快照里一个字都不加）")
        _pe = toolkit.call("plan", {"steps": []}, {"key": ("g", 123456789)})
        ok &= _ck(_pe.get("ok") is False and _pe.get("error") == "步骤表不能是空的",
                  "plan：步骤表空的时候那句话（用户 2026-10-30 逐字定稿）",
                  repr(_pe.get("error")))
        _ = _wait_ctx

        # ═══ 6.z2 2026-10-30 四条定稿（persona 两行 / A6 三个安全阀 / 两句话术）═══
        print()
        _CUR_SECT[0] = "6.z2 四条定稿（persona / A6 安全阀 / 话术）"
        print("=== 6.z2 四条定稿（persona / A6 安全阀 / 话术）===")
        # ⚠️ 2026-10-30（md 第 36 条 / 用户逐字定稿）：TEMPLATE **整段**是用户给的 ——
        #    删了全局「不想说话就只回某个哨兵词」、`你对他的【称呼】` 的方括号照抄。
        #    ⛔ 这段字面量就是钉子：谁把 TEMPLATE 改一个字，这里当场红。
        _TPL = """你的名字是{name}。你是由**{owner}**部署的qq机器人助手。{persona}

对话里每行的格式是【消息前缀】: 他说的话。
【消息前缀】是那个人的名字，可能是你对他的【称呼】、他在这个群的群名片、他的 QQ 昵称，或者他的 QQ 号。
要办事、要准确数字、要知道新东西，就调用工具，然后照工具给的事实说。
请你自己判断要不要调用工具，简单的直接答；复杂的，用户要求时，就用 search 查。
按用户发言的语言回复"""
        ok &= _ck(persona.TEMPLATE == _TPL,
                  "persona.TEMPLATE **逐字** = 用户给的这版（md 第 36 条）",
                  repr(persona.TEMPLATE[-30:]))
        _sys0 = persona.system_prompt()
        ok &= _ck("【称呼】" in _sys0,
                  "persona：`你对他的【称呼】` 的方括号在（用户特意加的）")
        ok &= _ck("end_turn" not in _sys0,
                  "persona：⛔ 不再有全局「不说话」总则（收尾靠工具目录条件出现）")
        ok &= _ck("对话里每行的格式是【消息前缀】: 他说的话。" in _sys0
                  and "【消息前缀】是那个人的名字，可能是你对他的【称呼】、他在这个群的群名片、"
                      "他的 QQ 昵称，或者他的 QQ 号。" in _sys0,
                  "persona 那两行**逐字**（【消息前缀】/【称呼】方括号）", _sys0[-30:])
        ok &= _ck(persona.prompt_chars() <= persona.MAX_CHARS,
                  "运行层提示词还是 ≤ %d 字" % persona.MAX_CHARS,
                  "%d 字" % persona.prompt_chars())

        # ── 收尾工具的两句场合说明（用户 2026-10-30 逐字定稿，md 第 40/41 条）──
        _chime_line = "触发了小概率的自动接话功能，并不是有人叫你。不需要回就调 end_turn。"
        _trig_line = ("刚才对话的「%s」触发了关键词的自动接话功能，并不是有人叫你。"
                      "不需要回就调 end_turn。")
        _real_call_s = im._napcat_call
        im._napcat_call = lambda ep, payload, **kw: (True, None)     # 群名查不到（别联网）
        try:
            # C) 随机接话（1%）：没点她 → 第 41 条那句（⚠️ 新版**结尾有句号**）
            _occ_chime = agent._occasion(mk("今天天气不错"), "")
            ok &= _ck(_occ_chime.splitlines()[-1] == _chime_line,
                      "收尾说明（随机接话）：场合行**逐字** = 第 41 条那句（结尾有句号）",
                      repr(_occ_chime.splitlines()[-1]))
            # A) @她 / 叫名字：一句都不加（人主动找她，必须回；也不给 end_turn）
            _c_at2 = mk("你好", at=True)
            ok &= _ck("end_turn" not in agent._occasion(_c_at2, agent._why(_c_at2)),
                      "收尾说明（@她）：场合行里不加（人主动找她就得回）")
            _c_nm2 = mk("MMZ你好")
            ok &= _ck("end_turn" not in agent._occasion(_c_nm2, agent._why(_c_nm2)),
                      "收尾说明（叫名字）：场合行里不加（人主动找她就得回）")
            # B) 关键词触发：`%s` = 撞上的那个词本身
            _llm2 = llm
            _old_tw2 = _llm2.runtime_get("triggerWords")
            try:
                _llm2.runtime_set("triggerWords", ["摸鱼"])
                _c_tr2 = mk("今天又摸鱼了")
                ok &= _ck(agent._why(_c_tr2) == "触发词"
                          and _c_tr2.get("_trigger_word") == "摸鱼"
                          and _c_tr2.get("_trigger") == "触发词",
                          "触发词：判定在，记下了是哪个词，`_trigger` 也写进去了",
                          repr(_c_tr2.get("_trigger_word")))
                _occ_tr2 = agent._occasion(_c_tr2, "触发词")
                ok &= _ck(_occ_tr2.splitlines()[-1] == _trig_line % "摸鱼",
                          "收尾说明（关键词）：场合行**逐字** = 第 40 条那句（%s = 撞上的词）",
                          repr(_occ_tr2.splitlines()[-1]))
            finally:
                _llm2.runtime_set("triggerWords",
                                  _old_tw2 if isinstance(_old_tw2, list) else [])
            # D) 到点唤醒：⛔ 不加（那一轮靠 `_trigger = "wake"` 给工具，不靠文字）
            _occ_wake = agent._occasion({"key": ("g", 424242), "is_group": False,
                                         "user_id": 10001, "text": ""}, "唤醒")
            ok &= _ck("end_turn" not in _occ_wake,
                      "收尾说明（到点唤醒）：场合行里不加（醒了一定说）")
        finally:
            im._napcat_call = _real_call_s

        ok &= _ck(reminders.LATE_WINDOW_MIN == 120 and reminders.MAX_PER_HOUR == 6
                  and reminders.MAX_CHAIN == 3,
                  "A6 三个安全阀的数（迟到 120 分钟 / 每小时 6 次 / 链 3 层）",
                  "%s / %s / %s" % (reminders.LATE_WINDOW_MIN, reminders.MAX_PER_HOUR,
                                    reminders.MAX_CHAIN))
        # 唤醒链：第 3 层还能设（记成第 3 层），第 4 层直接拒
        reminders._FIRED[:] = []
        _wc = {"key": ("g", 123456789), "is_group": True, "group_id": 123456789,
               "user_id": 10001, "who": "张三", "_wake_depth": 2}
        _w3 = toolkit.call("wake", {"when": "20分钟后", "note": "第三层"}, _wc)
        ok &= _ck(_w3.get("ok") is True,
                  "A6：第 3 层唤醒还能设", str(_w3.get("error"))[:30])
        _w4 = toolkit.call("wake", {"when": "20分钟后", "note": "第四层"},
                           dict(_wc, _wake_depth=3))
        ok &= _ck(_w4.get("ok") is False
                  and _w4.get("error") == "这条唤醒链已经 3 层了，不能再套一个",
                  "A6：第 4 层直接拒（逐字用那句新话术）", repr(_w4.get("error")))
        # 每小时最多 6 次：先塞 6 条已叫醒，再来一条到点的 → 不叫醒、只记日志
        reminders._FIRED[:] = [time.time()] * 6
        _called = []
        reminders.add(("g", 123456789), 123456789, 10001, "张三", "到点那条",
                      time.time() - 1)
        reminders._fire(lambda r: _called.append(r))
        ok &= _ck(not _called,
                  "A6：这一小时已经叫醒 6 次 → 到点的这条**不叫醒**（也不吭声）")
        ok &= _ck("这一小时已经叫醒 6 次了" in _read_log(),
                  "A6：不叫醒也**记日志**（能查出为什么没醒）")
        reminders._FIRED[:] = []
        _hc = _hist.query({}, count=3)
        ok &= _ck(_hc == {"ok": False},
                  "history：认不出会话时**不冒新台词**（只回 ok:false，第 ③ 条裁决）",
                  str(_hc))

        # ── ③ history：NapCat 唯一数据源 / 环形缓冲 + 5 分钟缓存 / 返回形状 ──
        _hist.reset()
        _hn = time.time()
        _HMSGS = [
            {"message_id": 9001, "time": _hn - 3600,
             "sender": {"user_id": 10001, "card": "张三"}, "raw_message": "今天摸鱼了吗"},
            {"message_id": 9002, "time": _hn - 3000,
             "sender": {"user_id": 30003, "card": "小张"}, "raw_message": "摸了两小时"},
            {"message_id": 9003, "time": _hn - 2400,
             "sender": {"user_id": 10001, "card": "张三"},
             "raw_message": "[CQ:image,file=x.jpg]就是这张"},
        ]
        _hctx = {"key": ("g", 123456789), "is_group": True, "group_id": 123456789,
                 "user_id": 10001}
        _calls_h = []

        def _fake_hist(ep, payload, **kw):
            _calls_h.append(ep)
            if ep not in ("get_group_msg_history", "get_friend_msg_history"):
                return (False, "network")
            return (True, {"messages": list(_HMSGS)})

        im._napcat_call = _fake_hist
        try:
            _hr = _hist.query(_hctx, count=2)
            ok &= _ck(_hr.get("ok") is True
                      and set(_hr) == {"ok", "匹配", "给出", "说明", "记录"},
                      "history：返回键 = ok / 匹配 / 给出 / 说明 / 记录（第 9 条）",
                      str(sorted(_hr)))
            ok &= _ck(_hr.get("匹配") == 3 and _hr.get("给出") == 2
                      and _hr.get("说明") == "匹配 3 条，其中 2 条",
                      "history：count=2 → 匹配 3 条、给出最近 2 条（说明那句第 9 条）",
                      str(_hr.get("说明")))
            ok &= _ck(any("摸了两小时" in x for x in _hr["记录"]),
                      "history：记录是「时间 名字: 话」的行", str(_hr["记录"][-1])[:50])
            ok &= _ck(not any("[CQ:" in x for x in _hr["记录"]),
                      "history：CQ 机器码不进给她看的文本（图片变成 [图片]）")
            _n_calls_h = len(_calls_h)
            _hr2 = _hist.query(_hctx, count=2)
            ok &= _ck(_hr2 == _hr and len(_calls_h) == _n_calls_h,
                      "history：同样条件 5 分钟内走缓存（不再打 NapCat）")
            _hr3 = _hist.query(_hctx, q="摸了两小时", count=5)
            ok &= _ck(_hr3.get("匹配") == 1, "history：q 关键词过滤（匹配 1 条）",
                      str(_hr3.get("匹配")))
            _hr4 = _hist.query(_hctx, who_qq="30003", count=5)
            ok &= _ck(_hr4.get("匹配") == 1 and "摸了两小时" in _hr4["记录"][0],
                      "history：who 过滤（只看某个人说的）", str(_hr4.get("记录"))[:40])
            _hr5 = _hist.query(_hctx, after="1小时前", count=5)
            ok &= _ck(_hr5.get("匹配") == 2,
                      "history：after 认「1小时前」（过去模式）", str(_hr5.get("匹配")))
            ok &= _ck(not any(n.startswith("history") for n in os.listdir(store.dir_path())),
                      "history：⛔ 不落盘（内存环形缓冲，重启即失）")
            _hist._RATE[str(10001)] = [time.time()] * _hist.PER_HOUR
            _hr6 = _hist.query(_hctx, count=3)
            ok &= _ck(_hr6.get("ok") is False and "上限" in str(_hr6.get("error")),
                      "history：每人每小时最多 20 次（超了回人话）", str(_hr6.get("error"))[:30])
            _hist._RATE.clear()
        finally:
            im._napcat_call = _real_call_p

        # ── ④ memory-keeper：每记一条就跑一次 / 按序号删 / 校验 / 备份 / 只算新向量 ──
        _kq = "777000111"
        memory.forget_person(_kq)
        memory.ensure_person(_kq)
        memory.add_fact(_kq, "住在杭州")
        memory.add_fact(_kq, "喜欢喝美式")
        _real_util = llm.utility_text
        _ubody = {}

        def _fake_util(messages, max_tokens=None):
            _ubody["body"] = (messages[0].get("content") if messages else "") or ""
            return '{"删": [1], "加": ["现在住在青岛"]}'

        llm.utility_text = _fake_util
        try:
            _kctx = {"key": ("p", _kq), "is_group": False, "user_id": int(_kq), "who": "小七"}
            _kr = toolkit.call("memory", {"text": "住在青岛"}, _kctx)
        finally:
            llm.utility_text = _real_util
        _body = _ubody.get("body") or ""
        ok &= _ck(_body.startswith("这是一个人的记忆，一行一条，行首的数字是编号：\n\n")
                  and "1. 住在杭州" in _body and "刚记下的这一条：\n住在青岛" in _body
                  and '只输出一个 JSON，不要解释：{"删": [1, 3], "加": ["<新句>", …]}' in _body,
                  "管家：喂法**逐字**用第 11 条（带编号 + 新那条 + 那句输出格式）")
        ok &= _ck(_kr.get("ok") and memory.facts_of(_kq)
                  == ["喜欢喝美式", "现在住在青岛"],
                  "管家：先整理再落库（新事实不再被当重复删掉；第 11 条那句「增删改交给后台」真在跑）",
                  json.dumps(memory.facts_of(_kq), ensure_ascii=False))
        ok &= _ck(any(n.startswith(memory.BACKUP_PREFIX)
                      for n in os.listdir(store.dir_path())),
                  "管家：写之前备份了一份 memory.json（留最近 5 版）")
        _cnt_bak = len([n for n in os.listdir(store.dir_path())
                        if n.startswith(memory.BACKUP_PREFIX)])
        for _i in range(memory.BACKUP_KEEP + 2):
            memory.backup_versions()
        _cnt_bak2 = len([n for n in os.listdir(store.dir_path())
                         if n.startswith(memory.BACKUP_PREFIX)])
        ok &= _ck(_cnt_bak2 <= memory.BACKUP_KEEP,
                  "管家：备份只留最近 %d 版" % memory.BACKUP_KEEP, "%d 份" % _cnt_bak2)

        # 删超 3 条 → 整次放弃；序号越界 → 忽略
        _before_k = memory.facts_of(_kq)
        llm.utility_text = lambda messages, max_tokens=None: \
            '{"删": [1, 2, 3, 4], "加": []}'
        try:
            _k2 = _keeper.review(_kq, "随便")
        finally:
            llm.utility_text = _real_util
        ok &= _ck(_k2 is False and memory.facts_of(_kq) == _before_k,
                  "管家：一次要删 4 条（上限 3）→ **整次放弃**，记忆一条都没动")
        llm.utility_text = lambda messages, max_tokens=None: '{"删": [99], "加": []}'
        try:
            _k3 = _keeper.review(_kq, "随便")
        finally:
            llm.utility_text = _real_util
        ok &= _ck(_k3 is False and memory.facts_of(_kq) == _before_k,
                  "管家：序号越界 → 忽略（不删别人 / 不越界乱动）")
        llm.utility_text = lambda messages, max_tokens=None: '{"删": [], "加": ["喜欢喝美式"]}'
        try:
            _k4 = _keeper.review(_kq, "喜欢喝美式")
        finally:
            llm.utility_text = _real_util
        ok &= _ck(_k4 is False and memory.facts_of(_kq) == _before_k,
                  "管家：「加」的那句已经有了 → 去重，不算动了记忆")
        memory.forget_person(_kq)

        # ── ⑤ B1 / B3：私聊按字数切窗口 + 自动压缩摘要 ──
        _cfg_llm = base.cfg().setdefault("llm", {})
        _old_hl = _cfg_llm.get("historyLimitPrivate")
        _cfg_llm["historyLimitPrivate"] = 60
        _seen_sum = {}

        def _fake_util2(messages, max_tokens=None):
            _seen_sum["body"] = (messages[0].get("content") if messages else "") or ""
            return "他昨天问过摸鱼的事\n他在杭州上班"

        llm.utility_text = _fake_util2
        try:
            _pk2 = ("p", 30003)
            memory.reset([_pk2])
            memory.record(_pk2, "user", "一" * 40, qq=30003, name="小张")
            memory.record(_pk2, "assistant", "二" * 40)
            memory.record(_pk2, "user", "三" * 40, qq=30003, name="小张")
            _pm = memory.render(_pk2)
            ok &= _ck(len(_pm) == 2 and _pm[-1]["content"].endswith("三" * 40),
                      "B1：私聊按**字数**切窗口（60 字只装得下最新那条，单条超预算也整条给）",
                      "%d 条消息" % len(_pm))
            ok &= _ck(_pm[0].get("role") == "user" and _pm[0].get("content")
                      == "<compacted-summary>\n他昨天问过摸鱼的事\n他在杭州上班\n</compacted-summary>",
                      "B3：滑出去的那段 → 摘要外壳**逐字**（第 15 条）",
                      repr(_pm[0].get("content"))[:60])
            ok &= _ck((_seen_sum.get("body") or "").startswith(
                          "把下面这段对话压成不超过 3 条事实，每条一行、一句话；"
                          "整段尽量不超过 300 字。不要解释\n\n"),
                      "B3：压缩那次请求的正文**逐字**（第 16 条）",
                      repr((_seen_sum.get("body") or "")[:40]))
            _pm_b = memory.render(_pk2)
            ok &= _ck(_pm_b[0].get("content") == _pm[0].get("content"),
                      "B3：摘要只留一份（下一轮还是同一个外壳，不会越堆越多）")
        finally:
            llm.utility_text = _real_util
            _cfg_llm["historyLimitPrivate"] = _old_hl
            memory.reset([("p", 30003)])

        # ── ⑥ B2：长结果被切时末尾补那句（只有 search / read_url / history）──
        _long = {"text": "啊" * 8000}
        ok &= _ck(toolkit.result_text("search", _long).endswith(toolkit.CLIP_NOTE)
                  and toolkit.result_text("read_url", _long).endswith(toolkit.CLIP_NOTE)
                  and toolkit.result_text("history", _long).endswith(toolkit.CLIP_NOTE),
                  "B2：search / read_url / history 被切时末尾补那句（第 14 条）",
                  toolkit.result_text("search", _long)[-30:])
        ok &= _ck(not toolkit.result_text("weather", _long).endswith(toolkit.CLIP_NOTE),
                  "B2：别的工具照旧静默截断（不冒新文本）")
        ok &= _ck(len(toolkit.result_text("search", {"a": "b"})) < toolkit.CLIP_CHARS,
                  "B2：没超长就不加那句")

        # ── ⑦ B1：群聊请求里有「你看到的是最近 N 条」，私聊没有 ──
        _gmsg = toolkit.call("memory", {}, _hctx)      # 顺手确认 memory 还能查
        ok &= _ck(_gmsg.get("ok") is True, "memory：text 留空 → 还是查（工具合并后没丢功能）")
        _pctx = {"key": ("p", 30003), "is_group": False, "user_id": 30003,
                 "who": "小张", "text": "在吗", "raw": "在吗", "images": [], "evt": {}}
        memory.record(_pctx["key"], "user", "昨天聊过的", qq=30003, name="小张")
        memory.record(_pctx["key"], "user", "在吗", qq=30003, name="小张")
        _pmsgs, _ = agent._build(_pctx, "私聊")
        _pj = json.dumps(_pmsgs, ensure_ascii=False)
        ok &= _ck("你看到的是" not in _pj,
                  "B1：私聊请求里**没有**「你看到的是最近 N 条」那句")
        # ⚠️ 2026-10-31：system 之后多一条**技能目录**（独立 user 消息）——
        #    这里只钉"system + 历史 + 快照 + 当前那句"这段形状（目录那条单独算）。
        _pm_rest = [m for m in _pmsgs if m is not capabilities.catalog_message(_pctx)]
        ok &= _ck([m.get("role") for m in _pm_rest] == ["system", "user", "user", "user"],
                  "B1：私聊请求形状 = system（+ 技能目录）+ 历史 + 快照 + 当前那句",
                  " ".join(m.get("role") for m in _pm_rest))
        memory.reset([_pctx["key"]])

        # ══════════════════════════════════════════════════════════════
        # 6.z3 2026-10-30 `end_turn`（收尾工具）—— 条件出现 + 立刻收尾
        #
        #   ① schemas(ctx)：四种场合出现（13 个）、@她 / 播报 / 私聊无 say 不出现（12 个）
        #      （2026-10-31 起常态目录是 12 个：`pc_status` 也是条件出现的 —— 见 6.z4）
        #   ② 假传输层：只调 end_turn → run_turn 返回 ""，**只请求 1 次**
        #   ③ 先 say 再 end_turn（两步）→ 第 2 次请求的工具里**有** end_turn；返回 ""
        #   ④ say + end_turn 同一批 → say 照常发（`_sends` = 1）；返回 ""、只请求 1 次
        #   ⑤ 全仓：旧的沉默词表 / 判断函数 0 处；给模型看的文本里旧哨兵词 0 处
        #   ⑥ 第 40 / 41 两句**逐字**（场合行 = 真正进请求的那一行）
        #   ⛔ 不联网、不发消息（发送口打桩、模型 = 假传输层）。
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.z3 end_turn 收尾工具（条件出现；打桩、离线）"
        print("=== 6.z3 end_turn 收尾工具（条件出现；打桩、离线）===")

        # ⚠️ 2026-10-31：工具目录现在有**两条条件出现的**（pc_status / end_turn）。
        #    `pc_status` 要「pcStatus.enabled 为真 + 最近一条电脑心跳」，前面战况那几节
        #    往临时目录里塞过心跳 —— 这里先清掉，让这一节的"常态"干净地等于 12 个；
        #    pc_status 自己那两条门控断言在 6.z4 里，会自己造心跳。
        store.remove(statuscache.CACHE_NAME)

        def _et_names(ctx):
            return [t["function"]["name"] for t in toolkit.schemas(ctx)]

        _et_none = _et_names(None)
        ok &= _ck(len(_et_none) == 13 and len(toolkit.names()) == 13
                  and "end_turn" not in _et_none and "pc_status" not in _et_none,
                  "end_turn：常态目录是 13 个（11 个内置 + skill；pc_status 没解锁）、里面没有它（不传 ctx 也不炸）",
                  "%d 个" % len(_et_none))
        # ①②③ 三种"场合"各一轮 → 13 个、end_turn 在最后
        for _trig, _what in (("触发词", "触发词勾起来那一轮"),
                             ("chime", "随机接话（1%）那一轮"),
                             ("wake", "唤醒到点那一轮")):
            _ns = _et_names({"key": ("g", 424242), "user_id": 2, "_trigger": _trig})
            ok &= _ck(len(_ns) == 14 and _ns[-1] == "end_turn",
                      "end_turn：%s → 出现（14 个）" % _what, "、".join(_ns[-2:]))
        # ④ 这一轮已经 say 过（`_allow_send` 会 +1）→ 出现
        _ns_say = _et_names({"_sends": 1})
        ok &= _ck(len(_ns_say) == 14 and _ns_say[-1] == "end_turn",
                  "end_turn：这一轮已经 say 过（_sends=1）→ 出现（14 个）")
        _ns_say0 = _et_names({"_sends": 0})
        ok &= _ck(len(_ns_say0) == 13 and "end_turn" not in _ns_say0,
                  "end_turn：_sends=0 → 还不出现（13 个）")
        # ⛔ @她 / 私聊正常对话 / 播报：不出现
        _c_at3 = mk("你好", at=True)
        ok &= _ck(agent._why(_c_at3) == "at" and "end_turn" not in _et_names(_c_at3)
                  and len(_et_names(_c_at3)) == 13,
                  "end_turn：@她那一轮**不出现**（13 个）", agent._why(_c_at3))
        _c_pv3 = mk("在吗", group=False)
        ok &= _ck(agent._why(_c_pv3) == "私聊" and "end_turn" not in _et_names(_c_pv3)
                  and len(_et_names(_c_pv3)) == 13,
                  "end_turn：私聊正常对话**不出现**（13 个）", agent._why(_c_pv3))
        _c_an3 = {"key": ("g", 424242), "is_group": True, "group_id": 424242,
                  "user_id": 2, "text": "", "raw": "", "images": []}
        ok &= _ck("end_turn" not in _et_names(_c_an3) and len(_et_names(_c_an3)) == 13,
                  "end_turn：播报那一轮**不出现**（13 个）")
        _et_desc = [t["function"]["description"] for t in toolkit.schemas({"_trigger": "chime"})
                    if t["function"]["name"] == "end_turn"]
        ok &= _ck(_et_desc == ["主动结束此轮对话，不再说话"],
                  "end_turn：说明**逐字** = 用户定稿（第 39 条）", repr(_et_desc))

        # ── 假传输层：按批次回；一批 = [("tool", 名, 参数), …] 或 [("text", 内容)] ──
        _ET = {"reqs": [], "sends": []}
        _ET_MARK = "（自检 end_turn）"

        def _et_stub(batches):
            _it = iter(batches)

            def _fn(url, payload, headers, timeout):
                _ms = payload.get("messages") or []
                if not any(m.get("role") == "user" and m.get("content") == _ET_MARK
                           for m in _ms):
                    # 别的回合（后台提醒之类）撞进来：给中性回复，⛔ 不吃脚本
                    return {"model": "stub-模型",
                            "choices": [{"index": 0, "finish_reason": "stop",
                                         "message": {"role": "assistant",
                                                     "content": "（自检：别的回合）"}}],
                            "usage": {}}
                _ET["reqs"].append(json.loads(json.dumps(payload, ensure_ascii=False)))
                try:
                    _b = next(_it)
                except StopIteration:
                    _b = [("text", "（自检：不该再问）")]
                _tcs, _txt = [], ""
                for _x in _b:
                    if _x[0] == "tool":
                        _tcs.append({"id": "et_%d_%d" % (len(_ET["reqs"]), len(_tcs)),
                                     "type": "function",
                                     "function": {"name": _x[1],
                                                  "arguments": json.dumps(_x[2],
                                                                          ensure_ascii=False)}})
                        if len(_x) > 3:          # 第 4 位 = 同一条消息里她还写的字
                            _txt = _x[3]
                    else:
                        _txt = _x[1]
                _msg = {"role": "assistant", "content": _txt}
                if _tcs:
                    _msg["tool_calls"] = _tcs
                return {"model": "stub-模型",
                        "choices": [{"index": 0,
                                     "finish_reason": "tool_calls" if _tcs else "stop",
                                     "message": _msg}],
                        "usage": {}}
            return _fn

        def _et_ctx(**kw):
            c = {"key": ("g", 424242), "is_group": True, "group_id": 424242,
                 "user_id": 2, "who": "自检", "text": "问一句", "raw": "问一句",
                 "images": [], "message_id": 1, "at": time.time()}
            c.update(kw)
            return c

        def _et_turn(batches, ctx):
            _ET["reqs"][:] = []
            llm.set_transport(_et_stub(batches))
            try:
                return llm.run_turn([{"role": "user", "content": _ET_MARK}], ctx,
                                    conn=llm.connection())
            finally:
                llm.set_transport(None)

        def _et_toolnames(payload):
            return [((t.get("function") or {}).get("name") or "")
                    for t in (payload.get("tools") or [])]

        # ② 只调 end_turn → 返回 ""、只请求 1 次
        _c2 = _et_ctx(_trigger="触发词")
        _t2, _called2, _e2 = _et_turn([[("tool", "end_turn", {})],
                                       [("text", "（自检：不该问第二次）")]], _c2)
        ok &= _ck(_t2 == "" and _called2 == ["end_turn"] and not _e2,
                  "② 只调 end_turn → run_turn 返回空串（这一轮不再说话）",
                  "text=%r called=%s" % (_t2, _called2))
        ok &= _ck(len(_ET["reqs"]) == 1,
                  "② 只请求了 **1 次**（不再问第二轮）", "%d 次" % len(_ET["reqs"]))
        _tn2 = _et_toolnames(_ET["reqs"][0]) if _ET["reqs"] else []
        ok &= _ck(len(_tn2) == 14 and "end_turn" in _tn2,
                  "② 第 1 次请求的工具目录里就有 end_turn（触发词那一轮）",
                  "%d 个" % len(_tn2))
        # ②' 同一条 assistant 消息里她还写了字：**一个字都不发**，只在日志里留一笔
        _c2b = _et_ctx(_trigger="wake")
        _t2b, _called2b, _e2b = _et_turn(
            [[("tool", "end_turn", {}, "（自检：这段不许发出去）")],
             [("text", "（自检：不该问第二次）")]], _c2b)
        _log2b = _read_log()
        ok &= _ck(_t2b == "" and not _e2b
                  and "（自检：这段不许发出去）" in _log2b
                  and "她调了 end_turn" in _log2b,
                  "②' end_turn 那条消息里写的字**不发**，但日志里留了一笔（含那段字）",
                  ([l for l in _log2b.splitlines() if "end_turn" in l] or [""])[-1][:80])

        # ③ 先 say、再 end_turn（两个不同的 step）→ 第 2 次请求才有 end_turn
        _c3 = _et_ctx()                       # ⛔ 没有 _trigger：end_turn 只可能因 say 出现
        _re_sg, _re_sp = im.send_group, im.send_private
        im.send_group = lambda *a, **kw: (_ET["sends"].append(a), True)[1]
        im.send_private = lambda *a, **kw: (_ET["sends"].append(a), True)[1]
        try:
            _ET["sends"][:] = []
            _t3, _called3, _e3 = _et_turn(
                [[("tool", "say", {"text": "等下，我查查"})],
                 [("tool", "end_turn", {})],
                 [("text", "（自检：不该问第三次）")]], _c3)
            ok &= _ck(_t3 == "" and _called3 == ["say", "end_turn"] and not _e3,
                      "③ say 之后再 end_turn → 返回空串", "text=%r called=%s" % (_t3, _called3))
            ok &= _ck(len(_ET["reqs"]) == 2,
                      "③ 正好请求 2 次（say 那步 + end_turn 那步）", "%d 次" % len(_ET["reqs"]))
            _tn3a = _et_toolnames(_ET["reqs"][0]) if _ET["reqs"] else []
            _tn3b = _et_toolnames(_ET["reqs"][1]) if len(_ET["reqs"]) > 1 else []
            ok &= _ck(len(_tn3a) == 13 and "end_turn" not in _tn3a,
                      "③ 第 1 次请求里**还没有** end_turn（这一轮没 say 过）",
                      "%d 个" % len(_tn3a))
            ok &= _ck(len(_tn3b) == 14 and "end_turn" in _tn3b,
                      "③ 第 2 次请求的工具里**有** end_turn（schemas 每步重算）",
                      "%d 个" % len(_tn3b))
            ok &= _ck(len(_ET["sends"]) == 1 and _ET["sends"][0][1] == "等下，我查查"
                      and _c3.get("_sends") == 1,
                      "③ say 照常发出去（_sends = 1）", str(_ET["sends"])[:50])

            # ④ say + end_turn **同一批** → say 照旧发，批完立刻收尾
            _c4 = _et_ctx()
            _ET["sends"][:] = []
            _t4, _called4, _e4 = _et_turn(
                [[("tool", "say", {"text": "我先说一句"}), ("tool", "end_turn", {})],
                 [("text", "（自检：不该问第二次）")]], _c4)
            ok &= _ck(_t4 == "" and _called4 == ["say", "end_turn"] and not _e4,
                      "④ 同一批 say + end_turn → 返回空串",
                      "text=%r called=%s" % (_t4, _called4))
            ok &= _ck(len(_ET["reqs"]) == 1,
                      "④ 只请求 1 次（这一批做完就收尾）", "%d 次" % len(_ET["reqs"]))
            ok &= _ck(len(_ET["sends"]) == 1 and _ET["sends"][0][1] == "我先说一句"
                      and _c4.get("_sends") == 1,
                      "④ say 照常发（_sends = 1），收尾不影响已经发出去的话",
                      str(_ET["sends"])[:50])
        finally:
            im.send_group, im.send_private = _re_sg, _re_sp

        # ⑤ 全仓 grep：旧的沉默词表 / 判断函数 0 处（⛔ 源码里不出现它们的字面量）
        _BAD_A = "SK" + "IP" + "_WORDS"
        _BAD_B = "is_" + "skip"
        _bad_hits = []
        for _root5, _dirs5, _files5 in os.walk(base.DIR):
            _dirs5[:] = [d for d in _dirs5 if d != "__pycache__"]
            for _fn5 in _files5:
                if not _fn5.endswith(".py"):
                    continue
                _p5 = os.path.join(_root5, _fn5)
                try:
                    with open(_p5, encoding="utf-8") as _fh5:
                        _s5 = _fh5.read()
                except Exception:
                    continue
                if _BAD_A in _s5 or _BAD_B in _s5:
                    _bad_hits.append(os.path.relpath(_p5, base.DIR))
        ok &= _ck(not _bad_hits, "⑤ 全仓 .py：旧的沉默词表 / 判断函数 **0 处**",
                  "、".join(_bad_hits) if _bad_hits else "0 处")
        # 给模型看的字：persona + 工具目录（含 end_turn）+ 两句场合行
        _OLDWORD = "SK" + "IP"
        _model_blob = "\n".join([
            persona.system_prompt(),
            json.dumps(toolkit.schemas({"_trigger": "wake"}), ensure_ascii=False),
            json.dumps(toolkit.schemas({"_trigger": "chime"}), ensure_ascii=False),
            agent.TRIGGER_END_TURN_NOTE % "摸鱼",
            agent.CHIME_END_TURN_NOTE,
        ])
        ok &= _ck(_OLDWORD not in _model_blob,
                  "⑤ 给模型看的文本（persona / 工具目录 / 两句场合行）里 **0 处**旧哨兵词")

        # ⑥ 第 40 / 41 两句逐字（而且真的出现在场合行里）
        _L40 = ("刚才对话的「%s」触发了关键词的自动接话功能，并不是有人叫你。"
                "不需要回就调 end_turn。")
        _L41 = "触发了小概率的自动接话功能，并不是有人叫你。不需要回就调 end_turn。"
        ok &= _ck(agent.TRIGGER_END_TURN_NOTE == _L40
                  and agent.CHIME_END_TURN_NOTE == _L41,
                  "⑥ 第 40 / 41 条两句**逐字**（含随机那句的句号）",
                  repr(agent.CHIME_END_TURN_NOTE))
        _occ40 = agent._occasion({"key": ("p", 424242), "is_group": False, "user_id": 2,
                                  "text": "今天又摸鱼了", "_trigger_word": "摸鱼"},
                                 "触发词")
        _occ41 = agent._occasion({"key": ("p", 424242), "is_group": False, "user_id": 2,
                                  "text": "今天天气不错"}, "")
        ok &= _ck(_occ40.splitlines()[-1] == _L40 % "摸鱼",
                  "⑥ 触发词那轮的场合行 = 第 40 条那句（逐字）",
                  repr(_occ40.splitlines()[-1]))
        ok &= _ck(_occ41.splitlines()[-1] == _L41,
                  "⑥ 随机接话那轮的场合行 = 第 41 条那句（逐字，结尾有句号）",
                  repr(_occ41.splitlines()[-1]))

        # ══════════════════════════════════════════════════════════════
        # 6.12 运行参数注册表 + 面板设置（2026-10-30）
        #      ① 注册表字段齐  ② 三层优先级  ③ 钳制 + 日志
        #      ④ 非法键 / 非数字类型被拒  ⑤ 默认值 == 改造前
        #      ⑥ GET 快照 / 面板卡片  ⑦ 改 threadLimit 立刻影响渲染
        #      ⑧ settings.json 在 deploy 的 NEVER 名单里
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.12 运行参数注册表 + 面板设置（离线）"
        print("=== 6.12 运行参数注册表 + 面板设置（离线）===")
        import urllib.request as _urq_s

        # ① 字段齐（没有漏项）
        _st_need = ("key", "label", "group", "tier", "type", "default",
                    "unit", "doc", "apply")
        _st_miss = []
        for _st_k, _st_it in settings.REGISTRY.items():
            for _st_f in _st_need:
                if _st_f not in _st_it:
                    _st_miss.append("%s.%s" % (_st_k, _st_f))
            if _st_it.get("type") in ("int", "float"):
                if _st_it.get("min") is None or _st_it.get("max") is None:
                    _st_miss.append("%s.min/max" % _st_k)
                if not str(_st_it.get("unit") or "").strip():
                    _st_miss.append("%s.unit" % _st_k)
            if _st_it.get("tier") not in ("basic", "advanced"):
                _st_miss.append("%s.tier" % _st_k)
            if _st_it.get("apply") not in ("live", "restart"):
                _st_miss.append("%s.apply" % _st_k)
        ok &= _ck(not _st_miss,
                  "① 注册表 %d 项，每项 label/group/tier/type/default/范围/单位/doc/apply 都齐"
                  % len(settings.REGISTRY),
                  "缺：%s" % "、".join(_st_miss) if _st_miss else "0 项缺")
        # ①′ 2026-10-30：思考强度和后台模型**搬去面板那两张卡**（存 llm-apis.txt），
        #     运行参数注册表里这三项必须**彻底消失**（32 - 3 → 30；面板也不许再有入口）。
        _st_gone = ("llm.reasoningEffort", "llm.utility.model",
                    "llm.utility.reasoningEffort")
        ok &= _ck(len(settings.REGISTRY) == 30
                  and not any(k in settings.REGISTRY for k in _st_gone),
                  "①′ 注册表 30 项：思考强度 / 后台模型 / 后台思考强度已搬走"
                  "（存 llm-apis.txt，不在运行参数里）",
                  "%d 项；还在的：%s" % (len(settings.REGISTRY),
                                        "、".join(k for k in _st_gone
                                                  if k in settings.REGISTRY) or "无"))

        # ② 三层优先级：overrides > config > default（各造一条）
        _st_cfg = base.cfg().setdefault("llm", {})
        _st_had = "threadLimit" in _st_cfg
        _st_old = _st_cfg.get("threadLimit")
        _st_srv = None
        try:
            settings.reset("llm.threadLimit")
            _st_cfg.pop("threadLimit", None)
            _st_v1 = settings.get("llm.threadLimit")
            _st_s1 = settings.source("llm.threadLimit")
            _st_cfg["threadLimit"] = 8
            _st_v2 = settings.get("llm.threadLimit")
            _st_s2 = settings.source("llm.threadLimit")
            settings.set("llm.threadLimit", 6)
            _st_v3 = settings.get("llm.threadLimit")
            _st_s3 = settings.source("llm.threadLimit")
            ok &= _ck(_st_v1 == 16 and _st_s1 == "default"
                      and _st_v2 == 8 and _st_s2 == "config"
                      and _st_v3 == 6 and _st_s3 == "panel",
                      "② 三层优先级：默认 16 → config 8 → 面板 6（来源也跟着变）",
                      "%s/%s → %s/%s → %s/%s"
                      % (_st_v1, _st_s1, _st_v2, _st_s2, _st_v3, _st_s3))

            # ③ 钳制：999 → 20（范围 2~20），返回"被夹了"，日志有一行
            _st_v, _st_clamped = settings.set("llm.threadLimit", 999)
            ok &= _ck(_st_v == 20 and _st_clamped is True,
                      "③ 超出范围 999 → 按上限 20 存（返回被夹了）",
                      "%r / %r" % (_st_v, _st_clamped))
            ok &= _ck(settings.clamp_note("llm.threadLimit", 999)
                      == "你填了 999，已按 20 存",
                      "③ 面板提示那句**逐字**：你填了 999，已按 20 存",
                      repr(settings.clamp_note("llm.threadLimit", 999)))
            _st_log = _read_log()
            ok &= _ck("设置：" in _st_log and "llm.threadLimit" in _st_log
                      and "你填了 999，已按 20 存" in _st_log,
                      "③ 日志里有那一行（谁 / 何时 / 旧值 / 新值 / 被夹）")

            # ④ 非法键 / 非数字类型被拒
            _st_badkey = False
            try:
                settings.set("not.a.param", 1)
            except KeyError:
                _st_badkey = True
            _st_badtype = False
            try:
                settings.set("llm.threadLimit", {"x": 1})
            except settings.SettingsError:
                _st_badtype = True
            ok &= _ck(_st_badkey, "④ 注册表里没有的键被拒（KeyError）")
            ok &= _ck(_st_badtype, "④ 非数字类型被拒（SettingsError）")

            # ⑤ 默认值 == 改造前的数（逐项断言；防手滑改行为）
            _st_old_defaults = {
                "llm.threadLimit": 16,
                "llm.historyLimitPrivate": 4096,
                "llm.maxToolRounds": 50,
                "llm.maxTokens": 4000,
                "agent.maxSendsPerTurn": 10,
                "wake.maxChain": 3,
                "wake.maxPerHour": 6,
                "wake.lateWindowMin": 120,
                "wake.histSegs": 6,
                "wake.histChars": 1500,
                "wake.digestChars": 600,
                "wake.briefChars": 120,
                "memory.maxFacts": 30,
                "memory.maxKeep": 120,
                "memory.backupKeep": 5,
                "memory.summaryMaxTokens": 500,
                "keeper.maxDelete": 3,
                "keeper.maxAdd": 10,
                "keeper.maxTokens": 1200,
                "history.defaultDays": 7,
                "history.defaultCount": 30,
                "history.maxCount": 100,
                "history.perHour": 20,
                "history.maxKeep": 2000,
                "history.cacheTtl": 300,
                "plan.maxSteps": 50,
                "plan.maxContent": 120,
                "toolkit.clipChars": 6000,
                "agent.maxGroupReplyChars": 1200,
                "agent.maxPrivateReplyChars": 1500,
            }
            _st_diff = [k for k, v in _st_old_defaults.items()
                        if settings.REGISTRY.get(k, {}).get("default") != v]
            _st_extra = sorted(set(settings.REGISTRY) ^ set(_st_old_defaults))
            ok &= _ck(not _st_diff and not _st_extra,
                      "⑤ 默认值 == 改造前代码里的数（逐项 %d 个，一个不差）"
                      % len(_st_old_defaults),
                      "不对：%s ｜ 多/少：%s"
                      % ("、".join(_st_diff) or "无", "、".join(_st_extra) or "无"))
            _st_consts = [
                (history.MAX_KEEP, 2000), (history.CACHE_TTL, 300),
                (history.DEFAULT_DAYS, 7), (history.DEFAULT_COUNT, 30),
                (history.MAX_COUNT, 100), (history.PER_HOUR, 20),
                (reminders.LATE_WINDOW_MIN, 120), (reminders.MAX_CHAIN, 3),
                (reminders.MAX_PER_HOUR, 6),
                (keeper.MAX_DELETE, 3), (keeper.MAX_ADD, 10), (keeper.MAX_TOKENS, 1200),
                (plan.MAX_STEPS, 50), (plan.MAX_CONTENT, 120),
                (memory.MAX_FACTS, 30), (memory.MAX_KEEP, 120),
                (memory.BACKUP_KEEP, 5), (memory.SUMMARY_MAX_TOKENS, 500),
                (memory.DEFAULT_RENDER, 16), (memory.DEFAULT_PRIVATE, 4096),
                (toolkit.CLIP_CHARS, 6000), (toolkit.WAKE_HIST_SEGS, 6),
                (toolkit.WAKE_HIST_CHARS, 1500), (toolkit.WAKE_DIGEST_CHARS, 600),
                (toolkit.WAKE_BRIEF_CHARS, 120),
            ]
            _st_cdiff = ["%r!=%r" % (a, b) for a, b in _st_consts if a != b]
            ok &= _ck(not _st_cdiff,
                      "⑤ 代码里保留的常量也还是改造前那个数（%d 个）" % len(_st_consts),
                      "、".join(_st_cdiff) if _st_cdiff else "")

            # ⑥ 快照：basic / advanced 一个不少；面板卡片标题在
            _st_snap = settings.snapshot()
            _st_want_basic = [k for k, i in settings.REGISTRY.items()
                              if i["tier"] == "basic"]
            _st_want_adv = [k for k, i in settings.REGISTRY.items()
                            if i["tier"] == "advanced"]
            _st_got_basic = [i["key"] for i in _st_snap["basic"]]
            _st_got_adv = [i["key"] for i in _st_snap["advanced"]]
            ok &= _ck(_st_got_basic == _st_want_basic and _st_got_adv == _st_want_adv,
                      "⑥ 快照里 basic %d 项 / advanced %d 项，一个不少"
                      % (len(_st_want_basic), len(_st_want_adv)),
                      "basic %d / advanced %d"
                      % (len(_st_got_basic), len(_st_got_adv)))
            ok &= _ck("运行参数" in panel.TEMPLATE and "高级参数" in panel.TEMPLATE
                      and 'id="cardParams"' in panel.TEMPLATE
                      and 'id="cardAdvanced"' in panel.TEMPLATE,
                      "⑥ 面板上有卡片「运行参数」+ 折叠区「高级参数」")
            # ⑥c 面板重新加入可搜索、来源/生效时机和恢复默认入口（2026-11-01）。
            ok &= _ck('id="paramSearch"' in panel.TEMPLATE
                      and 'id="paramResetAll"' in panel.TEMPLATE
                      and "data-param-reset" in panel.TEMPLATE
                      and 'action:"settings.reset"' in panel.TEMPLATE
                      and "sourceLabel" in panel.TEMPLATE
                      and "applyLabel" in panel.TEMPLATE,
                      "⑥c 参数可搜索、显示来源/生效时机，并支持恢复单项/全部")

            # ⑥b 走一次真的 GET /settings + POST /api（本机 Bearer，打完就关）
            _st_tok = base.napcat_token()
            _st_srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            threading.Thread(target=_st_srv.serve_forever, daemon=True).start()
            _st_root = "http://127.0.0.1:%d" % _st_srv.server_address[1]

            def _st_req(path, obj=None):
                _b = (json.dumps(obj, ensure_ascii=False).encode("utf-8")
                      if obj is not None else None)
                _rq = _urq_s.Request(_st_root + path, data=_b,
                                     headers={"Authorization": "Bearer " + _st_tok,
                                              "Content-Type": "application/json"},
                                     method=("POST" if obj is not None else "GET"))
                try:
                    with _urq_s.urlopen(_rq, timeout=10) as _r:
                        return _r.status, _r.read().decode("utf-8", "replace")
                except urllib.error.HTTPError as _e:
                    return _e.code, _e.read().decode("utf-8", "replace")

            _st_code, _st_body = _st_req("/settings")
            try:
                _st_got = json.loads(_st_body or "{}")
            except Exception:
                _st_got = {}
            ok &= _ck(_st_code == 200
                      and len(_st_got.get("basic") or []) == len(_st_want_basic)
                      and len(_st_got.get("advanced") or []) == len(_st_want_adv),
                      "⑥b 面板 GET /settings：HTTP 200，basic/advanced 全在",
                      "HTTP %s / %d + %d" % (_st_code,
                                             len(_st_got.get("basic") or []),
                                             len(_st_got.get("advanced") or [])))
            _st_code, _st_body = _st_req("/api", {
                "action": "settings.save",
                "values": {"llm.threadLimit": "7", "not.a.key": 1}})
            try:
                _st_jr = json.loads(_st_body or "{}")
            except Exception:
                _st_jr = {}
            _st_item = next((i for i in (_st_jr.get("settings") or {}).get("items", [])
                             if i["key"] == "llm.threadLimit"), {})
            ok &= _ck(_st_code == 200 and _st_jr.get("ok")
                      and _st_item.get("value") == 7
                      and _st_item.get("source") == "panel"
                      and "已保存（1 项）" in (_st_jr.get("message") or "")
                      and "忽略" in (_st_jr.get("message") or ""),
                      "⑥b 面板 POST 保存：改 threadLimit=7 → 面板改过；不认识的键被忽略",
                      "HTTP %s ｜ %s" % (_st_code, (_st_jr.get("message") or "")[:70]))
            _st_code, _st_body = _st_req("/api", {
                "action": "settings.save", "values": {"llm.threadLimit": "999"}})
            try:
                _st_jr = json.loads(_st_body or "{}")
            except Exception:
                _st_jr = {}
            _st_item = next((i for i in (_st_jr.get("settings") or {}).get("items", [])
                             if i["key"] == "llm.threadLimit"), {})
            ok &= _ck(_st_code == 200 and _st_jr.get("ok")
                      and _st_item.get("value") == 20
                      and "你填了 999，已按 20 存" in (_st_jr.get("message") or ""),
                      "⑥b 面板 POST 超范围：999 → 20，而且回一句「你填了 999，已按 20 存」",
                      (_st_jr.get("message") or "")[:70])
            _st_code, _st_body = _st_req("/api", {
                "action": "settings.reset", "key": "llm.threadLimit"})
            try:
                _st_jr = json.loads(_st_body or "{}")
            except Exception:
                _st_jr = {}
            _st_item = next((i for i in (_st_jr.get("settings") or {}).get("items", [])
                             if i["key"] == "llm.threadLimit"), {})
            ok &= _ck(_st_code == 200 and _st_jr.get("ok")
                      and _st_item.get("value") == 8
                      and _st_item.get("source") == "config",
                      "⑥b 面板 POST「恢复默认」：覆盖值删掉，回到配置文件里的 8",
                      "HTTP %s ｜ %s/%s" % (_st_code, _st_item.get("value"),
                                           _st_item.get("source")))

            # ⑦ 改 threadLimit=8 → 下一轮渲染立刻只带 8 段
            settings.set("llm.threadLimit", 8)
            _st_pk = ("g", 123456789)
            memory.reset([_st_pk])
            for _st_i in range(10):
                memory.record(_st_pk, "user", "u%d" % _st_i, qq=10001, name="张三")
                memory.record(_st_pk, "assistant", "a%d" % _st_i)
            _st_msgs = memory.render(_st_pk)
            ok &= _ck(len(_st_msgs) == 8
                      and (_st_msgs[-1].get("content") or "") == "a9",
                      "⑦ 面板把 threadLimit 改成 8 → 下一轮渲染立刻只带 8 段",
                      "%d 段，最后一条=%r" % (len(_st_msgs),
                                              (_st_msgs[-1].get("content") or "")[:20]))
            memory.reset([_st_pk])

            # ⑧ settings.json 在 deploy 的 NEVER 名单里（不被推代码覆盖）
            try:
                with open(os.path.join(base.DIR, "deploy.py"), encoding="utf-8") as _st_f:
                    _st_dep = _st_f.read()
                _st_never = _st_dep.split("NEVER = {", 1)[-1].split("}", 1)[0]
                _st_never_ok = '"settings.json"' in _st_never
            except Exception as _st_e:
                _st_never_ok = True          # 手机上的暂存目录没有 deploy.py
                print("    ⚠️ 读不到 deploy.py（手机上跑的是暂存目录）：%r" % (_st_e,))
            ok &= _ck(_st_never_ok and settings.FILE == "settings.json",
                      "⑧ settings.json 在 deploy 的 NEVER 名单里（推代码不覆盖）")
        finally:
            try:
                settings.reset_all()
            except Exception:
                pass
            memory.reset([("g", 123456789)])
            if _st_had:
                _st_cfg["threadLimit"] = _st_old
            else:
                _st_cfg.pop("threadLimit", None)
            if _st_srv is not None:
                try:
                    _st_srv.shutdown()
                    _st_srv.server_close()
                except Exception:
                    pass

        # ══════════════════════════════════════════════════════════════
        # 6.13 提供商 / 模型目录 / 后台模型（她的大脑；离线、全打桩）
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.13 提供商 / 模型目录 / 后台模型（离线）"
        print("=== 6.13 提供商 / 模型目录 / 后台模型（离线）===")
        import urllib.request as _urq_p
        _bd = tempfile.mkdtemp(prefix="brain-", dir=tmp)
        _bd_prev = store.dir_path()
        _real_models_fetch = llm._MODELS_FETCH
        try:
            store.set_dir(_bd)
            # ① 老格式（扁平 apis）自动迁移：**一条都不能丢**，而且写回成 v2
            _old_doc = {"active": "opencode-go", "apis": [
                {"name": "opencode-go", "baseUrl": "https://opencode.ai/zen/go/v1",
                 "model": "gemini-4-argon", "key": "sk-test-0001"},
                {"name": "多字的名字", "baseUrl": "https://api.example.com/v1",
                 "model": "m-1", "key": "sk-test-0002"}]}
            store.write_json(llm.APIS_FILE, _old_doc)
            _bd_doc = llm.apis_doc()
            _bd_disk = store.read_json(llm.APIS_FILE) or {}
            _bd_names = [p["name"] for p in _bd_doc["providers"]]
            _bd_ok = (len(_bd_doc["providers"]) == 2
                      and _bd_names == ["opencode-go", "多字的名字"]
                      and _bd_doc["providers"][0]["baseUrl"] == "https://opencode.ai/zen/go/v1"
                      and _bd_doc["providers"][0]["key"] == "sk-test-0001"
                      and [m["id"] for m in _bd_doc["providers"][0]["models"]] == ["gemini-4-argon"]
                      and _bd_doc["providers"][1]["baseUrl"] == "https://api.example.com/v1"
                      and _bd_doc["providers"][1]["key"] == "sk-test-0002"
                      and [m["id"] for m in _bd_doc["providers"][1]["models"]] == ["m-1"]
                      and _bd_doc["active"]["provider"] == "opencode-go"
                      and _bd_doc["active"]["model"] == "gemini-4-argon"
                      and _bd_doc["active"]["effort"] == "low"
                      and "apis" not in _bd_disk
                      and isinstance(_bd_disk.get("active"), dict)
                      and len(_bd_disk.get("providers") or []) == 2)
            ok &= _ck(_bd_ok,
                      "① 老格式自动迁移：2 家 / 2 个模型 / key 一字不差 / 已写回 v2 / "
                      "active.effort=low",
                      "%s ｜ 盘上 v2=%s" % (_bd_names, "apis" not in _bd_disk))
            _bd_alt = _bd_doc["providers"][1]["id"]

            # ② active_api() 按 provider 找；返回形状和老版本一样
            _bd_api = llm.active_api() or {}
            _bd_conn = llm.connection()
            ok &= _ck(_bd_api.get("name") == "opencode-go"
                      and _bd_api.get("baseUrl") == "https://opencode.ai/zen/go/v1"
                      and _bd_api.get("key") == "sk-test-0001"
                      and _bd_api.get("model") == "gemini-4-argon"
                      and set(("name", "baseUrl", "key", "model", "visionModel")) <= set(_bd_api),
                      "② active_api() 按 active.provider 解析出正确的 baseUrl/key/model，"
                      "形状没变（name/baseUrl/key/model/visionModel）")
            ok &= _ck(_bd_conn["url"] == "https://opencode.ai/zen/go/v1/chat/completions"
                      and _bd_conn["model"] == "gemini-4-argon"
                      and _bd_conn["name"] == "opencode-go",
                      "② connection() 用那家拼出 chat/completions",
                      _bd_conn["url"])

            # ③ 切提供商 / 模型 / 强度 → connection() 立刻变；config.json 一字节不动
            _cfg_before = json.dumps(base.cfg(), ensure_ascii=False, sort_keys=True)
            _bd_sw, _bd_swmsg = llm.provider_activate(_bd_alt, "m-1", "none")
            _bd_c2 = llm.connection()
            ok &= _ck(_bd_sw and _bd_c2["name"] == "多字的名字"
                      and _bd_c2["url"] == "https://api.example.com/v1/chat/completions"
                      and _bd_c2["model"] == "m-1"
                      and _bd_c2["key"] == "sk-test-0002"
                      and _bd_c2["effort"] == "none"
                      and json.dumps(base.cfg(), ensure_ascii=False, sort_keys=True) == _cfg_before,
                      "③ 切换提供商/模型/强度 → connection() 立刻跟着变（config.json 没动）",
                      _bd_c2["url"])
            ok &= _ck(llm.effort_now() == ("none", "面板"),
                      "③ active.effort 改了 → effort_now() 立刻读到新值",
                      str(llm.effort_now()))

            # ④ 删当前启用者被拒；切走后再删成功
            _bd_del1 = llm.provider_delete(_bd_alt)
            ok &= _ck(_bd_del1[0] is False and "先切" in _bd_del1[1],
                      "④ 删当前启用的提供商被拒（先切走）", _bd_del1[1])
            llm.provider_activate("opencode-go", "gemini-4-argon")
            _bd_del2 = llm.provider_delete(_bd_alt)
            ok &= _ck(_bd_del2[0] is True
                      and not any(p["name"] == "多字的名字"
                                  for p in llm.apis_doc()["providers"]),
                      "④ 切走后再删成功", _bd_del2[1])

            # ⑤ 获取可用模型（服务端去请求；这里打桩）：URL / 头 / 解析 / 失败话术
            _bd_seen = {}

            def _bd_fetch_ok(url, headers, timeout):
                _bd_seen["url"] = url
                _bd_seen["headers"] = dict(headers)
                return 200, json.dumps({"data": [
                    {"id": "alpha"}, {"id": "beta", "name": "Beta 显示名"}]}).encode("utf-8")

            llm.set_models_fetcher(_bd_fetch_ok)
            _bd_fok, _bd_fms, _bd_fwhy = llm.provider_fetch_models("opencode-go")
            ok &= _ck(_bd_fok and [m["id"] for m in _bd_fms] == ["alpha", "beta"]
                      and _bd_fms[1]["name"] == "Beta 显示名"
                      and _bd_seen["url"] == "https://opencode.ai/zen/go/v1/models"
                      and _bd_seen["headers"].get("Authorization", "").startswith("Bearer ")
                      and _bd_seen["headers"].get("User-Agent") == "curl/8.5.0"
                      and bool(_bd_seen["headers"].get("x-opencode-session")),
                      "⑤ 获取可用模型：GET <baseUrl>/models（Bearer + curl UA + opencode 会话头），"
                      "解析出 id/显示名",
                      _bd_seen.get("url"))
            _bd_add1 = llm.provider_add_models("opencode-go", _bd_fms)
            _bd_add2 = llm.provider_add_models("opencode-go", _bd_fms)
            _bd_models = [m["id"] for m in llm.apis_doc()["providers"][0]["models"]]
            ok &= _ck(_bd_add1[0] and _bd_add2[0]
                      and _bd_models == ["gemini-4-argon", "alpha", "beta"],
                      "⑤ 加进目录；再点一次不重复（已存在的跳过）", str(_bd_models))

            def _bd_fetch_404(url, headers, timeout):
                return 404, b'{"error":{"message":"Not Found"}}'

            llm.set_models_fetcher(_bd_fetch_404)
            _bd_bok, _bd_bms, _bd_bwhy = llm.provider_fetch_models("opencode-go")
            ok &= _ck(not _bd_bok and not _bd_bms and "404" in _bd_bwhy,
                      "⑤ 拉不到时照实说（状态码 + 原因），不假装成功", _bd_bwhy)

            def _bd_fetch_empty(url, headers, timeout):
                return 200, b"<html>not json</html>"

            llm.set_models_fetcher(_bd_fetch_empty)
            _bd_eok, _bd_ems, _bd_ewhy = llm.provider_fetch_models("opencode-go")
            ok &= _ck(not _bd_eok and not _bd_ems and "JSON" in _bd_ewhy,
                      "⑤ 返回不是 JSON 时也说清楚（不崩）", _bd_ewhy)

            # ⑥ key 只在服务端：所有对外列表里**只有打码**（GET /providers 也验一遍）
            _bd_blob = "".join(json.dumps(x, ensure_ascii=False) for x in (
                llm.providers_public(), llm.api_list_public(), llm.stats(), agent.info()))
            ok &= _ck("sk-test-0001" not in _bd_blob
                      and "sk-test-0002" not in _bd_blob
                      and "****" in _bd_blob,
                      "⑥ 对外列表里没有明文 key（只有打码）")
            _bd_srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            threading.Thread(target=_bd_srv.serve_forever, daemon=True).start()
            try:
                _bd_rq = _urq_p.Request(
                    "http://127.0.0.1:%d/providers" % _bd_srv.server_address[1],
                    headers={"Authorization": "Bearer " + base.napcat_token()})
                with _urq_p.urlopen(_bd_rq, timeout=10) as _bd_r:
                    _bd_body = _bd_r.read().decode("utf-8", "replace")
                    _bd_code = _bd_r.status
                _bd_j = json.loads(_bd_body or "{}")
                ok &= _ck(_bd_code == 200 and "providers" in _bd_j
                          and "sk-test-迁移测试" not in _bd_body
                          and "sk-迁移测试" not in _bd_body
                          and "****" in _bd_body,
                          "⑥ GET /providers：HTTP 200，key 打码", _bd_body[:60])
            finally:
                try:
                    _bd_srv.shutdown()
                    _bd_srv.server_close()
                except Exception:
                    pass

            # ⑦ active.effort → connection 立刻变；App 的 effort 动作也写进 active.effort
            llm.set_models_fetcher(None)
            llm.provider_activate("opencode-go", "gemini-4-argon", "medium")
            ok &= _ck(llm.connection()["effort"] == "medium"
                      and llm.connection()["effort_from"] == "面板",
                      "⑦ 面板把 active.effort 改成 medium → connection() 立刻跟着变",
                      str(llm.connection()["effort"]))
            _bd_setok, _bd_setmsg = llm.set_effort("max")
            ok &= _ck(_bd_setok and llm.connection()["effort"] == "max"
                      and llm.connection()["effort_from"] == "手机改的"
                      and llm.apis_doc()["active"]["effort"] == "max",
                      "⑦ App 的 effort 动作也写进 llm-apis.txt（来源标「手机改的」）")

            # ⑧ 后台模型：inherit=true 跟主模型；false 用自己那三个
            _bd_uc = llm.utility_conn()
            ok &= _ck(_bd_uc["name"] == "opencode-go"
                      and _bd_uc["model"] == "gemini-4-argon"
                      and _bd_uc["effort"] == "max",
                      "⑧ utility.inherit=true → 后台模型跟主模型一样",
                      "%s/%s/%s" % (_bd_uc["name"], _bd_uc["model"], _bd_uc["effort"]))
            llm.provider_set_utility({"inherit": False, "provider": "opencode-go",
                                      "model": "alpha", "effort": "low"})
            _bd_uc2 = llm.utility_conn()
            ok &= _ck(_bd_uc2["name"] == "opencode-go" and _bd_uc2["model"] == "alpha"
                      and _bd_uc2["effort"] == "low"
                      and _bd_uc2["effort_from"] == "llm.utility"
                      and llm.connection()["model"] == "gemini-4-argon",
                      "⑧ utility.inherit=false → 用后台自己那三个，主模型不受影响",
                      "%s/%s/%s" % (_bd_uc2["name"], _bd_uc2["model"], _bd_uc2["effort"]))

            # ⑨ 老 settings.json 里那三项：读的时候忽略，不报错、面板上也没有
            store.write_json(settings.FILE, {"llm.reasoningEffort": "high",
                                             "llm.utility.model": "旧的",
                                             "llm.utility.reasoningEffort": "max"})
            _bd_snap = settings.snapshot()
            _bd_keys = {i["key"] for i in _bd_snap["items"]}
            ok &= _ck(len(_bd_snap["items"]) == 30
                      and not (_bd_keys & {"llm.reasoningEffort", "llm.utility.model",
                                           "llm.utility.reasoningEffort"})
                      and llm.connection()["effort"] == "max",
                      "⑨ 老 settings.json 里那三项读的时候忽略（不报错、也不出现在面板）",
                      "%d 项" % len(_bd_snap["items"]))

            # ⑩ 内置 10 家；面板上那几张卡和关键字都在，老输入框全没了
            ok &= _ck(len(llm.BUILTIN_PROVIDERS) == 10
                      and llm.BUILTIN_URL["google"].endswith("/v1beta/openai")
                      and llm.BUILTIN_URL["opencode-go"] == "https://opencode.ai/zen/go/v1",
                      "⑩ 内置 10 家（地址都对）")
            _bd_html = panel.render()
            ok &= _ck(all(k in _bd_html for k in (
                          "她的大脑", "后台模型", "添加提供商", "获取可用模型",
                          "选择要添加的模型", "自定义设置", "还没填", "已保存")),
                      "⑩ 面板：她的大脑 / 后台模型 / 提供商卡 / 添加模型弹窗 都在")
            ok &= _ck(not any(k in _bd_html for k in (
                          'id="apiList"', 'id="apiSave"', 'id="fModel"',
                          'id="apiForm"', 'id="seg"', 'id="apiToggle"')),
                      "⑩ 面板：老那套「API（她的大脑用哪家）」输入框全删了")
        finally:
            try:
                llm.set_models_fetcher(_real_models_fetch)
            except Exception:
                pass
            store.set_dir(_bd_prev)
            shutil.rmtree(_bd, ignore_errors=True)

        # ══════════════════════════════════════════════════════════════
        # 6.14 设置页（2026-10-31）——「新部署的人不用碰任何文件」
        #
        #   ① GET /onboard 的形状：token 只有 ****、检查表 6 项、每块状态
        #   ② onboarding.save：坏值整批不存 / 深合并写 local-config / **立刻生效**
        #   ③ 深合并：只改一个键，同一节的兄弟键（enabled / quoteReply）不丢；
        #      出厂模板 config.json 一个字不动
        #   ④ 人设：正文写进去、尖括号注释原样保留、下一句立刻生效
        #   ⑤ NapCat 测一下 / 拉群（打桩，绝不联网）；拉不到就提示手填
        #   ⑥ pc_status 门控：没心跳 12 → 有心跳 13 → 关掉 12
        #   ⑦ 面板那一页：导航在「设置」前面、各块 / 检查表 / 动作名都在
        #   ⑧ 命令行 `--set` / `--check` 和面板同一份校验、同一个落点
        #   ⚠️ local-config 和人设都指到临时目录 —— 正式目录一个字节都不动。
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.14 设置页（onboarding.save / probe / groups / persona）"
        print("=== 6.14 设置页（onboarding.save / probe / groups / persona）===")
        from fgbot import onboard as _ob
        from fgbot import groups as _og
        _ob_real_local = base.LOCAL_CFG_PATH
        _ob_real_pp = persona.profile_path
        _ob_real_wp = persona.write_path
        _ob_pf = os.path.join(tmp, "personality-onboard.md")
        with open(_ob_pf, "w", encoding="utf-8") as _f:
            _f.write("<!--\n给自检用的备注\n-->\n\n你是个自检用的机器人。\n")
        base.LOCAL_CFG_PATH = os.path.join(tmp, "local-config.json")
        store.remove("local-config.json")
        persona.profile_path = lambda: _ob_pf
        persona.write_path = lambda: _ob_pf      # 写点也指到临时文件（不许碰正式目录）
        persona.forget()
        _ob_real_raw, _ob_real_call = im._napcat_raw, im._napcat_call
        try:
            # ── ① 快照的形状 / 打码 ──
            _ob_s0 = _ob.snapshot()
            _ob_txt = json.dumps(_ob_s0, ensure_ascii=False)
            _ob_tok = str(base.napcat_token() or "")
            ok &= _ck(_ob_s0.get("ok") and len(_ob_s0.get("checklist") or []) == 6
                      and set(_ob_s0.get("blocks") or {}) == set("abcdefg"),
                      "初始化①：/onboard 有 6 项检查表 + 每块状态（a~g）",
                      str([c["key"] for c in _ob_s0.get("checklist") or []]))
            ok &= _ck(_ob_s0["values"]["bot.token"] in ("****", "")
                      and (not _ob_tok or _ob_tok not in _ob_txt),
                      "初始化①：token **永远不回明文**（只有 ****）")
            ok &= _ck([c["label"] for c in _ob_s0["checklist"]] == [
                          "机器人 QQ", "共用令牌", "目标群",
                          "模型与密钥", "人设正文", "NapCat 连接"],
                      "初始化①：检查表那六句**逐字**",
                      "、".join(c["label"] for c in _ob_s0["checklist"]))
            ok &= _ck(_ob_s0["summary"]["text"] in ("可以跑了",) or
                      _ob_s0["summary"]["text"].startswith("还差 "),
                      "初始化①：汇总只有「可以跑了 / 还差 N 项」两种",
                      _ob_s0["summary"]["text"])

            # ── ② 坏值整批不存 ──
            _ob_before = store.read_json("local-config.json")
            _ob_o1, _ob_m1, _ = _ob.save({"bot.selfId": "abc"})
            ok &= _ck(not _ob_o1 and "QQ 号" in _ob_m1
                      and store.read_json("local-config.json") == _ob_before,
                      "初始化②：有一个坏值 → **整批不存**，报原因 + 怎么做", _ob_m1)

            # ── ② 真存：立刻生效（不重启）──
            _ob_o2, _ob_m2, _ob_s2 = _ob.save({
                "bot.selfId": "1888888888",
                "bot.token": "selftest-token-123456",
                "bot.groups": [{"id": "666000111", "note": "自检群"}],
                "napcat.baseUrl": "127.0.0.1:3999",
                "agent.name": "MMZ",
                "agent.wakeWords": "自检大名",
                "agent.triggerWords": ["自检触发词"],
                "agent.chimeIn.chancePercent": "7",
                "pcStatus.enabled": False,
                "pcStatus.dayCutoff": "4:00",
            })
            ok &= _ck(_ob_o2 and base.self_id() == 1888888888
                      and base.napcat_url() == "http://127.0.0.1:3999"
                      and base.napcat_token() == "selftest-token-123456",
                      "初始化②：保存后**立刻生效**（base.cfg 现叠现读，不用重启）", _ob_m2)
            _ob_loc = store.read_json("local-config.json") or {}
            ok &= _ck((_ob_loc.get("bot") or {}).get("token") == "selftest-token-123456"
                      and (_ob_loc.get("bot") or {}).get("napcatToken") == "selftest-token-123456"
                      and bool((base.cfg().get("bot") or {}).get("enabled"))
                      and (base.cfg().get("bot") or {}).get("quoteReply") is True,
                      "初始化②：深合并 —— 写 token 没把 bot 那一节的兄弟键顶掉",
                      str(sorted((_ob_loc.get("bot") or {}).keys())))
            ok &= _ck(666000111 not in (base._read_json(base.CFG_PATH)["bot"]["groups"] or []),
                      "初始化②：出厂模板 config.json 一个字没动")
            ok &= _ck("666000111" in _og.known()
                      and any(r.get("备注") == "自检群" for r in _og.records()),
                      "初始化②：群列表 + 备注立刻生效（local-config + groups.json）",
                      str(_og.records()))
            ok &= _ck((base.cfg().get("agent") or {}).get("name") == "MMZ"
                      and (base.cfg().get("agent") or {}).get("wakeWords") == ["自检大名"]
                      and "MMZ" in persona.call_names()
                      and "自检大名" in persona.call_names(),
                      "初始化②：名字和唤醒词按独立配置列表立刻生效",
                      "、".join(persona.call_names()))

            # ── ② 运行参数那层覆盖要清掉（不然"存了不生效"）──
            settings.set("agent.maxGroupReplyChars", 333)
            _ob_o3, _ob_m3, _ = _ob.save({"agent.maxGroupReplyChars": "888"})
            ok &= _ck(settings.get("agent.maxGroupReplyChars") == 888,
                      "初始化②：运行参数的 settings 覆盖被清掉 —— 填的数真的生效",
                      str(settings.get("agent.maxGroupReplyChars")))
            llm.runtime_set("triggerWords", ["旧的运行时词"])
            _ob_o4, _ob_m4, _ = _ob.save({"agent.triggerWords": ["新词"]})
            ok &= _ck(llm.runtime_get("triggerWords") is None
                      and persona.trigger_words() == ["新词"],
                      "初始化②：触发词的 runtime 覆盖被清掉 —— 下一条就用新的",
                      str(persona.trigger_words()))

            # ── ② 非主人 → FORBIDDEN（server 回 403 空正文）──
            _ob_out = {"id": "x2", "主人": False, "名字": "朋友", "群": ""}
            ok &= _ck(_ob.api("onboarding.save", {"values": {}}) is not None
                      and agent.on_api("onboarding.save",
                                       {"values": {"agent.name": "x"}},
                                       _ob_out) is agent.FORBIDDEN,
                      "初始化②：非主人调 onboarding.save → FORBIDDEN（server 回 403 空正文）")

            # ── ④ 人设：正文 / 注释 / 热生效 ──
            _ob_p_ok, _ob_p_msg, _ob_p = _ob.persona_save("你的名字是自检她。\n")
            _ob_raw = open(_ob_pf, encoding="utf-8").read()
            ok &= _ck(_ob_p_ok and "<!--\n给自检用的备注\n-->" in _ob_raw
                      and "你的名字是自检她。" in _ob_raw,
                      "初始化④：人设正文写进去了，尖括号注释原样保留", repr(_ob_raw))
            ok &= _ck(persona.personality_text() == "你的名字是自检她。",
                      "初始化④：人设**下一句就生效**（不用重启）",
                      repr(persona.personality_text()))
            ok &= _ck(not _ob.persona_save("   ")[0],
                      "初始化④：空正文不写（报原因 + 怎么做）")

            # ── ⑤ NapCat：测一下 / 拉群（打桩）──
            im._napcat_raw = lambda ep, payload, **kw: (
                (True, "", {"user_id": 1888888888, "nickname": "自检"})
                if ep == "get_login_info" else (False, "network", None))
            _ob_pr = _ob.probe()
            ok &= _ck(_ob_pr.get("ok") and _ob_pr.get("qq") == "1888888888"
                      and "QQ 1888888888" in (_ob_pr.get("message") or ""),
                      "初始化⑤：测一下成功 → 显示它登的 QQ 号", _ob_pr.get("message"))
            im._napcat_raw = lambda ep, payload, **kw: (False, "network", None)
            _ob_pr2 = _ob.probe()
            ok &= _ck(not _ob_pr2.get("ok")
                      and "请检查服务、地址和端口" in (_ob_pr2.get("message") or ""),
                      "初始化⑤：测一下失败 → 原因 + 怎么做", _ob_pr2.get("message"))

            def _ob_call(ep, payload, **kw):
                if ep == "get_group_list":
                    return True, [{"group_id": 666000111, "group_name": "自检群"},
                                  {"group_id": 666000222, "group_name": "别的群"}]
                return False, "network"

            im._napcat_call = _ob_call
            _ob_pg = _ob.pull_groups()
            ok &= _ck(_ob_pg.get("ok") and len(_ob_pg.get("groups") or []) == 2
                      and [x["known"] for x in _ob_pg["groups"]] == [True, False],
                      "初始化⑤：从 NapCat 拉群 → 标出哪些已经在名单里",
                      str([(x["id"], x["known"]) for x in _ob_pg.get("groups") or []]))
            im._napcat_call = lambda ep, payload, **kw: (False, "network")
            _ob_pg2 = _ob.pull_groups()
            ok &= _ck(not _ob_pg2.get("ok")
                      and "手动输入群号" in (_ob_pg2.get("message") or ""),
                      "初始化⑤：拉不到 → 提示手动输入群号（不假装成功）", _ob_pg2.get("message"))

            # ── ⑥ pc_status 门控（用户点名要的那条）—— 2026-10-31 起多了**解锁**这一步 ──
            #    原来：`pcStatus.enabled` + 最近心跳 → 直接出现。
            #    现在：`pc_status` 是扩展包的工具 —— 只有**读过技能解锁了**、并且
            #          `available(ctx)`（= enabled + 最近心跳）为真，才进请求。
            #    这里把三步都钉住：没解锁 → 没有；解锁了但没心跳 → 没有；
            #    解锁 + 心跳 → 出现；关开关 → 又不出现；最后再放她回去（不给后面的自检留状态）。
            store.remove(statuscache.CACHE_NAME)
            base.cfg().setdefault("pcStatus", {})["enabled"] = True
            capabilities.clear_sessions()                 # 干净的起点（这场"对话"还没读过技能）
            _ob_c = {"key": ("g", 666000111), "is_group": True, "group_id": 666000111,
                     "user_id": 10001}
            _ob_n0 = [t["function"]["name"] for t in toolkit.schemas(_ob_c)]
            ok &= _ck(len(_ob_n0) == 13 and "pc_status" not in _ob_n0,
                      "pc 门控：开关开着、但**没读技能** → 目录里没有 pc_status（13 个）",
                      "%d 个" % len(_ob_n0))
            toolkit.call("skill", {"name": "pc-status"}, _ob_c)
            _ob_n0b = [t["function"]["name"] for t in toolkit.schemas(_ob_c)]
            ok &= _ck(len(_ob_n0b) == 13 and "pc_status" not in _ob_n0b,
                      "pc 门控：**解锁了但没有心跳** → 还是不发（13 个）",
                      "%d 个" % len(_ob_n0b))
            statuscache.record({"action": "status.push", "ok": True, "日期": _TODAY,
                                "现在": "在忙"}, "ob-selftest", now=time.time() - 5)
            _ob_n1 = [t["function"]["name"] for t in toolkit.schemas(_ob_c)]
            ok &= _ck(len(_ob_n1) == 14 and "pc_status" in _ob_n1,
                      "pc 门控：解锁 + 有心跳 → 出现（14 个，末尾追加）", "、".join(_ob_n1[-2:]))
            base.cfg()["pcStatus"]["enabled"] = False
            _ob_n2 = [t["function"]["name"] for t in toolkit.schemas(_ob_c)]
            ok &= _ck(len(_ob_n2) == 13 and "pc_status" not in _ob_n2,
                      "pc 门控：关掉开关 → 又不出现（13 个）", "%d 个" % len(_ob_n2))
            capabilities.clear_sessions()

            # ── ⑦ 面板那一页 ──
            _ob_html = panel.render()
            ok &= _ck('data-go="onboard"' not in _ob_html,
                      "初始化⑦：侧栏里**不再有「初始化」**（已并进设置页）")
            ok &= _ck(all(k in _ob_html for k in (
                          'data-view="settings"', "机器人身份", "消息通道", "目标群",
                          "主模型", "人设", "对话行为", "运行检查",
                          "obAState", "obCheck", "obSum", "obPull", "obPersona",
                          "onboarding.save", "onboarding.probe", "onboarding.groups",
                          "onboarding.persona", "随机生成", "检测 NapCat", "最近会话群",
                          "obWakeChips", "capHostChips", 'id="setup"', "setupSave")),
                      "初始化⑦：那些卡片 / 检查表 / 动作名 / 首配弹窗都在（设置页里）")
            _ob_seg = _ob_html[_ob_html.index('id="setup"'):]
            _ob_seg = _ob_seg[:_ob_seg.index("</div>\n", _ob_seg.index("qsPersona"))] \
                if "qsPersona" in _ob_seg else _ob_seg
            ok &= _ck(not any(k in _ob_seg for k in ("温馨提示",)),
                      "初始化⑦：首配弹窗里没有「温馨提示」那类废话")

            # ── ⑥ GET /onboard 走真 HTTP：主人 200（token 打码）、非主人 403 空正文 ──
            _ob_srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            threading.Thread(target=_ob_srv.serve_forever, daemon=True).start()
            _ob_root = "http://127.0.0.1:%d" % _ob_srv.server_address[1]
            _ob_f_ok, _ob_f_msg, _ob_f_rec = users.add(
                "初始化自检朋友", "10009", "", "自检（稍后撤销）")

            def _ob_get(path, tok):
                _rq = _urq.Request(_ob_root + path,
                                   headers=({"Authorization": "Bearer " + tok} if tok else {}))
                try:
                    with _urq.urlopen(_rq, timeout=10) as _resp:
                        return _resp.status, _resp.read().decode("utf-8", "replace"), dict(_resp.headers)
                except urllib.error.HTTPError as _e:
                    return _e.code, _e.read().decode("utf-8", "replace"), dict(_e.headers or {})

            try:
                _c_own, _b_own, _h_own = _ob_get("/onboard", base.napcat_token())
                ok &= _ck(_c_own == 200 and "****" in _b_own
                          and base.napcat_token() not in _b_own
                          and "no-store" in (_h_own.get("Cache-Control") or ""),
                          "初始化⑥：本机 + 共享令牌 → GET /onboard 200（token 只有 ****，no-store）",
                          "HTTP %s ｜ %d 字节" % (_c_own, len(_b_own)))
                _c_fr, _b_fr, _ = _ob_get("/onboard", (_ob_f_rec or {}).get("token") or "")
                ok &= _ck(_c_fr == 403 and _b_fr == "",
                          "初始化⑥：非主人 → GET /onboard **403 + 空正文**", "HTTP %s" % _c_fr)

                # ── 远程面板（`panel.allowRemote`，2026-10-31 云端部署那条）──
                #    假装这个请求是**公网来的**：把 client_allowed / panel_allowed 打成
                #    "只有那个开关说了算"。⚠️ 2026-10-31 起口径变了：开着 → 先给**登录页**，
                #    没会话什么数据都拿不到；Bearer（连共享令牌）也不给公网 —— 完整流程
                #    （登录 / 错口令 / 冷却 / 退出 / 伪造 XFF）在 6.55b 那一节。
                _ob_real_ca, _ob_real_pa = server.client_allowed, server.panel_allowed
                try:
                    server.client_allowed = lambda ip: False
                    server.panel_allowed = lambda ip: server.panel_remote()
                    base.cfg()["panel"]["allowRemote"] = False
                    ok &= _ck(_ob_get("/panel", "")[0] == 403,
                              "远程面板：allowRemote 关着 → 公网连**页面本身**都打不开（403）")
                    base.cfg()["panel"]["allowRemote"] = True
                    _c_pg, _b_pg, _ = _ob_get("/panel", "")
                    ok &= _ck(_c_pg == 200 and 'action="/login"' in _b_pg
                              and "fgPanelToken" not in _b_pg
                              and str(base.napcat_token()) not in _b_pg,
                              "远程面板：开着 → 打开的是**登录页**（不是面板；页面里没有令牌）")
                    ok &= _ck(_ob_get("/status", "")[0] == 403,
                              "远程面板：没登录 → /status **403 空正文**")
                    ok &= _ck(_ob_get("/status", base.napcat_token())[0] == 403,
                              "远程面板：**Bearer 不再给公网**（共享令牌也不能跳过登录）")
                    ok &= _ck(_ob_get("/onboard", (_ob_f_rec or {}).get("token") or "")[0] == 403,
                              "远程面板：非主人令牌 → /onboard 403（主人那一层没松）")
                    _rq_api = _urq.Request(
                        _ob_root + "/api",
                        data=json.dumps({"action": "restart"}).encode("utf-8"),
                        headers={"Authorization": "Bearer " + str(base.napcat_token()),
                                 "Content-Type": "application/json"},
                        method="POST")
                    try:
                        with _urq.urlopen(_rq_api, timeout=10) as _rr:
                            _code_api = _rr.status
                    except urllib.error.HTTPError as _ee:
                        _code_api = _ee.code
                    ok &= _ck(_code_api == 403,
                              "远程面板：`POST /api` 从公网**不认 Bearer**（403 空正文）",
                              "HTTP %s" % _code_api)
                finally:
                    server.client_allowed, server.panel_allowed = _ob_real_ca, _ob_real_pa
                    base.cfg()["panel"]["allowRemote"] = False
            finally:
                _ob_srv.shutdown()
                _ob_srv.server_close()
                if _ob_f_rec:
                    users.remove(_ob_f_rec["id"])

            # ── ⑧ 命令行：--check / --set 和面板同一套 ──
            import io as _io
            _ob_oldout = sys.stdout
            _ob_buf = _io.StringIO()
            sys.stdout = _ob_buf
            try:
                _ob_rc = cli_check()
                _ob_rc2 = cli_set(["agent.name=自检命令行"])
                _ob_rc3 = cli_set(["bot.selfId=abc"])
                _ob_rc4 = cli_set(["bot.groups=666000111,666000333"])
                # 远程面板那三个键（2026-10-31）：host / allowRemote / trustedProxies
                _ob_rc5 = cli_set(["host=127.0.0.1", "panel.allowRemote=true",
                                   "panel.trustedProxies=127.0.0.1/32,::1/128"])
                _ob_rc6 = cli_set(["panel.trustedProxies=不是网段"])
                _ob_rc7 = cli_set(["bot.control.allowIps=192.0.2.0/24"])
                _ob_rc8 = cli_set(["bot.control.allowIps=0.0.0.0/0"])
            finally:
                sys.stdout = _ob_oldout
            _ob_out = _ob_buf.getvalue()
            ok &= _ck(_ob_rc in (0, 1) and "=== 能不能跑 ===" in _ob_out
                      and ("还差 " in _ob_out or "可以跑了" in _ob_out),
                      "初始化⑧：命令行 --check 打得出那张检查表（和面板 H 块同一套）")
            ok &= _ck(_ob_rc2 == 0
                      and (base.cfg().get("agent") or {}).get("name") == "自检命令行",
                      "初始化⑧：命令行 --set 和面板写**同一份** local-config、同一个校验")
            ok &= _ck(_ob_rc3 != 0, "初始化⑧：命令行坏值也按同一套校验拒绝")
            ok &= _ck(_ob_rc4 == 0 and "666000333" in _og.known(),
                      "初始化⑧：命令行 --set bot.groups=…,…… 也能加群", str(_og.known()))
            ok &= _ck(_ob_rc5 == 0
                      and base.cfg().get("host") == "127.0.0.1"
                      and (base.cfg().get("panel") or {}).get("allowRemote") is True
                      and (base.cfg().get("panel") or {}).get("trustedProxies")
                      == ["127.0.0.1/32", "::1/128"],
                      "初始化⑧：命令行 --set host / panel.allowRemote / panel.trustedProxies "
                      "→ 写进 local-config（远程部署不用手改文件）")
            ok &= _ck(_ob_rc6 != 0
                      and (base.cfg().get("panel") or {}).get("trustedProxies")
                      == ["127.0.0.1/32", "::1/128"],
                      "初始化⑧：写错的网段也被同一套校验拒绝（不会把名单写脏）")
            ok &= _ck(_ob_rc7 == 0
                      and (base.bot_cfg().get("control") or {}).get("allowIps") == ["192.0.2.0/24"],
                      "初始化⑧：API 来源 IP 白名单能逐项保存")
            ok &= _ck(_ob_rc8 != 0
                      and (base.bot_cfg().get("control") or {}).get("allowIps") == ["192.0.2.0/24"],
                      "初始化⑧：全网段不会被误设为 API 来源白名单")
        finally:
            base.LOCAL_CFG_PATH = _ob_real_local
            persona.profile_path = _ob_real_pp
            persona.write_path = _ob_real_wp
            persona.forget()
            im._napcat_raw, im._napcat_call = _ob_real_raw, _ob_real_call
            store.remove(statuscache.CACHE_NAME)
            base.load()

        # ══════════════════════════════════════════════════════════════
        # 6.16 扩展包（知识锁）—— 2026-10-31
        #
        #   ① 技能目录：逐字 / 位置（system 之后、历史之前）/ 只发一条 / 内容变了原地替换
        #   ② `skill` 工具的名字 / 说明 / 参数**逐字**
        #   ③ 读技能 → `<skill_content>` 正文原文 + 工具 schema **追加在末尾** + 日志一行
        #   ④ 同时最多 6 个包（LRU：最久没用的摘掉、`_skills_opened` 保留记录、再读回来）
        #   ⑤ 技能名不存在 → error **逐字**
        #   ⑥ 六条校验各一条（安装与加载同一份实现）
        #   ⑦ 安装（zip / 目录 / 覆盖备份 / 校验不过一个文件都不落地 / 装完加载失败回滚）/ 卸载
        #   ⑧ 停用 → 目录行消失 + 工具解锁不了；启用 → 回来
        #   ⑨ pc-status 包 = 行为等价（available = 开关 + 最近心跳）；面板「扩展」页；控制面主人闸
        #   ⑩ 命令行 --list-capabilities / --check-capability / --install-capability /
        #      --remove-capability
        #   ⛔ 全程在临时目录里（store 早就指到 tmp 了）：正式目录一个字节都不动。
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.16 扩展包（知识锁 / 六条校验 / 安装 / 回滚 / 停用）"
        print("=== 6.16 扩展包（知识锁 / 六条校验 / 安装 / 回滚 / 停用）===")
        import base64 as _cap64
        import zipfile as _capzip

        _cap_data = capabilities.data_root()
        os.makedirs(_cap_data, exist_ok=True)
        _cap_scratch = os.path.join(tmp, "cap-scratch")
        os.makedirs(_cap_scratch, exist_ok=True)
        _cap_state0 = store.read_json(capabilities.STATE_NAME, default=None)
        _cap_pc_cfg = dict((base.cfg().get("pcStatus") or {}))
        _cap_made = [_cap_scratch]
        _cap_keys = []

        def _cap_write(root, name, desc="一句话", tool=None, body=None, py=None):
            """写一个扩展包（自检用）：`root/<name>/SKILL.md`（+ 可选 tool.py）。"""
            d = os.path.join(root, name)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as _f:
                _f.write("---\nname: %s\ndescription: %s\nformatVersion: 1\n---\n\n%s\n"
                         % (name, desc, body if body is not None else "正文（自检）"))
            if py is not None:
                with open(os.path.join(d, "tool.py"), "w", encoding="utf-8") as _f:
                    _f.write(py)
            elif tool is not None:
                _tn, _td = tool
                with open(os.path.join(d, "tool.py"), "w", encoding="utf-8") as _f:
                    _f.write('NAME = "%s"\nDESC = "%s"\n'
                             'PARAMS = {"type": "object", "properties": {}, "required": []}\n\n'
                             'def run(args, ctx):\n    return {"ok": True, "谁": "%s"}\n'
                             % (_tn, _td, _tn))
            if root == _cap_data and d not in _cap_made:
                _cap_made.append(d)
            return d

        def _cap_zip(src, dest, outer=None):
            """把一个包目录压成 zip；`outer` 给了就套一层同名文件夹。"""
            with _capzip.ZipFile(dest, "w") as zf:
                for _b, _ds, _fs in os.walk(src):
                    for _f in _fs:
                        _full = os.path.join(_b, _f)
                        _rel = os.path.relpath(_full, src).replace("\\", "/")
                        zf.write(_full, (outer + "/" + _rel) if outer else _rel)
            return dest

        def _cap_ctx(gid):
            c = {"key": ("g", gid), "is_group": False, "group_id": None,
                 "user_id": 10001, "who": "自检", "text": "MMZ在吗", "raw": "MMZ在吗",
                 "images": [], "message_id": 1, "at": time.time(), "evt": {}}
            _cap_keys.append(c["key"])
            return c

        try:
            # ── ① 技能目录：逐字 / 位置 / 只发一条 / 原地替换 ──
            capabilities.clear_sessions()
            _c1 = _cap_ctx(1357911)
            _cmsg = capabilities.catalog_message(_c1)
            _want_cat = ("<system-reminder>\n【技能目录】：你的额外技能，用skill工具读取\n\n"
                         "- pack-manager：装或卸扩展包、下载消息里的文件（只有主人能装）\n"
                         "- pc-status：查电脑上今天干了多少活、在忙什么\n"
                         "</system-reminder>")
            ok &= _ck(_cmsg is not None and _cmsg.get("role") == "user"
                      and _cmsg.get("content") == _want_cat,
                      "扩展①：技能目录那条消息**逐字**（用户 2026-10-31 批的四段之一）",
                      repr((_cmsg or {}).get("content"))[:90])
            _cmsgs, _cbuild = agent._build(_c1, "名字")
            ok &= _ck(len(_cmsgs) >= 2 and _cmsgs[0].get("role") == "system"
                      and _cmsgs[1] is _cmsg,
                      "扩展①：位置 = **system 之后、历史之前**（请求的第 2 条）",
                      " ".join(str(m.get("role")) for m in _cmsgs[:4]))
            _cat_n = len([m for m in _cmsgs
                          if str(m.get("content") or "").startswith(
                              "<system-reminder>\n【技能目录】")])
            ok &= _ck(_cat_n == 1,
                      "扩展①：请求里**只有一条**技能目录（⛔ 不是每轮追加一条）",
                      "%d 条" % _cat_n)
            _cmsgs2, _ = agent._build(_c1, "名字")
            ok &= _ck(_cmsgs2[1] is _cmsg and _cmsgs2[2] is _cmsgs2[2],
                      "扩展①：下一轮还是**同一条**（原地复用，不是新加一条）")
            # 一个可用技能都没有 → 那条消息**根本不发**
            #    ⚠️ 打桩成一个**预先算好的集合**（别在 `disabled()` 里回调 `list()`，那会递归）
            _all_names = {c["name"] for c in capabilities.list()}
            _real_disabled = capabilities.disabled
            try:
                capabilities.disabled = lambda: set(_all_names)
                ok &= _ck(capabilities.catalog_text() == ""
                          and capabilities.catalog_message(_c1) is None,
                          "扩展①：一个可用技能都没有 → **不发**技能目录（连那条 user 消息都不出现）")
            finally:
                capabilities.disabled = _real_disabled
            # 装一个新包 → 目录里多一行（按名字排序）；改描述 → 原地替换那一条
            _cd = _cap_write(_cap_data, "capdemo", "第一版说明")
            capabilities.reload_all()
            _m1 = capabilities.catalog_message(_c1)
            _c_txt = (_m1 or {}).get("content") or ""
            ok &= _ck(_m1 is _cmsg and "- capdemo：第一版说明" in _c_txt
                      and _c_txt.index("- capdemo：") < _c_txt.index("- pc-status："),
                      "扩展①：新装的包出现在目录里，**按名字排序**", repr(_c_txt)[:90])
            _cap_write(_cap_data, "capdemo", "第二版说明")
            capabilities.reload_all()
            _m3 = capabilities.catalog_message(_c1)
            ok &= _ck(_m3 is _m1 and "- capdemo：第二版说明" in _m3["content"]
                      and "- capdemo：第一版说明" not in _m3["content"],
                      "扩展①：内容变了 → **原地替换那一条**（还是同一个 dict、不追加）",
                      repr(_m3["content"])[:90])
            # 描述超过 60 字 → 第 ② 条拦（目录里也不会出现截断的半句）
            _cap_write(_cap_data, "caplong", "长" * 61)
            capabilities.reload_all()
            _long_row = [c for c in capabilities.list() if c["name"] == "caplong"][0]
            ok &= _ck(_long_row["status"] == "校验失败：第 2 条"
                      and "- caplong：" not in ((capabilities.catalog_message(_c1) or {})
                                                .get("content") or ""),
                      "扩展①：description 超 60 字 → 第 2 条不过、目录里不出现",
                      _long_row["status"] + " ｜ " + _long_row["error"])

            # ── ② `skill` 工具逐字 ──
            _skill_tool = [t for t in toolkit.TOOLS if t["name"] == "skill"][0]
            _skill_schema = [x for x in toolkit.schemas({})
                             if x["function"]["name"] == "skill"][0]["function"]["parameters"]
            ok &= _ck(_skill_tool["desc"] == "读取一个技能的完整说明"
                      and _skill_tool["params"] == {"name": ("string", "【技能】名字")}
                      and "skill" in toolkit.names()
                      and _skill_schema.get("required") == ["name"]
                      and (_skill_schema.get("properties") or {}).get("name", {})
                      .get("description") == "【技能】名字",
                      "扩展②：`skill` 工具的名字 / 说明 / 参数 / required **逐字**（用户批的那三行）",
                      repr(_skill_tool["params"]) + " ｜ " + str(_skill_schema.get("required")))

            # ── ③ 读技能 → 正文原文 + schema 追加在末尾 + 日志 ──
            store.remove(statuscache.CACHE_NAME)
            base.cfg().setdefault("pcStatus", {})["enabled"] = True
            statuscache.record({"action": "status.push", "ok": True, "日期": _TODAY,
                                "现在": "在忙"}, "cap-selftest", now=time.time() - 5)
            _c3 = _cap_ctx(1357912)
            _names_before = [t["function"]["name"] for t in toolkit.schemas(_c3)]
            _skill_res = toolkit.call("skill", {"name": "pc-status"}, _c3)
            _skill_txt = toolkit.result_text("skill", _skill_res)
            _pc_cap = capabilities.get("pc-status")
            _pc_md = open(os.path.join(_pc_cap.dir, "SKILL.md"), encoding="utf-8").read()
            _pc_body = capabilities.parse_skill(_pc_md)[1].strip()
            ok &= _ck(_skill_txt == '<skill_content name="pc-status">\n'
                      + _pc_body + "\n</skill_content>",
                      "扩展③：回给她的内容 = `<skill_content name=…>` + SKILL.md 正文**原文**",
                      repr(_skill_txt[:70]))
            ok &= _ck(_c3.get("_skills_opened") == ["pc-status"],
                      "扩展③：读完记进 `ctx[\"_skills_opened\"]`（会话级、最新在末尾）",
                      str(_c3.get("_skills_opened")))
            _names_after = [t["function"]["name"] for t in toolkit.schemas(_c3)]
            ok &= _ck(_names_after[:len(_names_before)] == _names_before
                      and _names_after[-1] == "pc_status"
                      and len(_names_after) == len(_names_before) + 1,
                      "扩展③：解锁的 schema **追加在末尾**、不重排已有工具",
                      "、".join(_names_after[-3:]))
            ok &= _ck("工具列表变了" in _read_log(),
                      "扩展③：工具列表变了 → 日志里有一行（排查缓存问题用）")
            # 会话级：换一场对话不继承；一场结束（memory.reset）→ 清空
            _c_other = _cap_ctx(1357919)
            _other_names = [t["function"]["name"] for t in toolkit.schemas(_c_other)]
            ok &= _ck("pc_status" not in _other_names
                      and (_c_other.get("_skills_opened") or []) == [],
                      "扩展③：换一场对话 → 上一场解锁的**不继承**（知识不跨会话乱串）",
                      "、".join(_other_names[-3:]))
            memory.reset([("g", 1357912)])
            ok &= _ck(capabilities.opened(_c3) == [] and "pc_status" not in
                      [t["function"]["name"] for t in toolkit.schemas(_c3)],
                      "扩展③：一场对话结束（`memory.reset`）→ 解锁清空")
            # 再解锁一次（后面的断言还要用）
            toolkit.call("skill", {"name": "pc-status"}, _c3)

            # ── ④ 同时最多 6 个包（LRU）──
            for _i in range(7):
                _cap_write(_cap_data, "capk%d" % _i, "第 %d 个包" % _i,
                           tool=("cap_tool_%d" % _i, "测试工具 %d" % _i))
            capabilities.reload_all()
            _c4 = _cap_ctx(1357913)
            for _i in range(7):
                toolkit.call("skill", {"name": "capk%d" % _i}, _c4)
            _opened4 = list(_c4.get("_skills_opened") or [])
            _n4 = [t["function"]["name"] for t in toolkit.schemas(_c4)]
            ok &= _ck(len(_opened4) == 7 and _opened4[0] == "capk0" and _opened4[-1] == "capk6",
                      "扩展④：`_skills_opened` **保留全部记录**（最新在末尾）", str(_opened4))
            ok &= _ck(all(("cap_tool_%d" % _i) in _n4 for _i in range(1, 7))
                      and "cap_tool_0" not in _n4,
                      "扩展④：同时最多 6 个包 → **最久没用**的那个不再发 schema",
                      "、".join(_n4[-7:]))
            toolkit.call("skill", {"name": "capk0"}, _c4)
            _n4b = [t["function"]["name"] for t in toolkit.schemas(_c4)]
            ok &= _ck("cap_tool_0" in _n4b and "cap_tool_1" not in _n4b,
                      "扩展④：再读一次被摘掉的那个 → 它回来、另一个最久没用的被摘",
                      "、".join(_n4b[-7:]))

            # ── ⑤ 技能名不存在 → error 逐字 ──
            _missing = toolkit.call("skill", {"name": "查无此技能"}, _c4)
            ok &= _ck(_missing == {"ok": False,
                                   "error": "没有叫「查无此技能」的【技能】。看【技能目录】里的名字。"},
                      "扩展⑤：技能名不存在 → error **逐字**（用户批的那句）",
                      repr(_missing))

            # ── ⑥ 六条校验各一条（安装和加载共用这一份 `validate()`）──
            _vroot = os.path.join(_cap_scratch, "validate")
            os.makedirs(_vroot, exist_ok=True)
            _v1 = os.path.join(_vroot, "noskill")
            os.makedirs(_v1, exist_ok=True)
            _r1 = capabilities.validate(_v1, folder_name="noskill")
            ok &= _ck(not _r1["rules"][0]["ok"] and _r1["rules"][0]["rule"] == 1,
                      "扩展⑥①：没有 SKILL.md → 第 1 条不过", _r1["rules"][0]["message"])
            _v2 = _cap_write(_vroot, "othername", "一句话")
            _r2 = capabilities.validate(_v2, folder_name="badname")
            _r2b = capabilities.validate(_cap_write(_vroot, "longdesc", "长" * 61))
            ok &= _ck(not _r2["rules"][1]["ok"] and not _r2b["rules"][1]["ok"],
                      "扩展⑥②：name 与文件夹名不一致 / description 超 60 字 → 第 2 条不过",
                      _r2["rules"][1]["message"])
            _v3 = _cap_write(_vroot, "brokenpy", "一句话",
                             py="NAME = 'x'\nDESC = 'x'\nPARAMS = {}\ndef run(args, ctx)\n")
            _r3 = capabilities.validate(_v3, folder_name="brokenpy")
            ok &= _ck(not _r3["rules"][2]["ok"],
                      "扩展⑥③：tool.py 语法错误 → 第 3 条不过（import 都过不去）",
                      _r3["rules"][2]["message"])
            _v4 = _cap_write(_vroot, "clash", "一句话", tool=("now", "撞内置"))
            _r4 = capabilities.validate(_v4, folder_name="clash")
            ok &= _ck(not _r4["rules"][3]["ok"],
                      "扩展⑥④：工具名撞主程序内置（now）→ 第 4 条不过",
                      _r4["rules"][3]["message"])
            _v5 = _cap_write(_vroot, "badparams", "一句话",
                             py='NAME = "bp_tool"\nDESC = "x"\n'
                                'PARAMS = {"type": "object", "properties": {}}\n'
                                'def run(args, ctx):\n    return {"ok": True}\n')
            _r5 = capabilities.validate(_v5, folder_name="badparams")
            ok &= _ck(not _r5["rules"][4]["ok"],
                      "扩展⑥⑤：PARAMS 缺 required → 第 5 条不过",
                      _r5["rules"][4]["message"])
            _v6 = _cap_write(_vroot, "danger", "一句话",
                             py='NAME = "danger_tool"\nDESC = "x"\n'
                                'PARAMS = {"type": "object", "properties": {}, "required": []}\n'
                                'def run(args, ctx):\n    return {"ok": bool(eval("1"))}\n')
            _r6 = capabilities.validate(_v6, folder_name="danger")
            ok &= _ck(_r6["ok"] and _r6["rules"][5]["warn"],
                      "扩展⑥⑥：eval( → 第 6 条**只警告不拒**（包照样能装）",
                      _r6["rules"][5]["message"])

            # ── ⑦ 安装 / 覆盖备份 / 校验不过不落地 / 装完加载失败回滚 / 卸载 ──
            _src = _cap_write(_cap_scratch, "pkgone", "装进来的包",
                              tool=("cap_one_tool", "第一个工具"))
            _inst1 = capabilities.install(_src)
            _inst_dir = os.path.join(_cap_data, "pkgone")
            ok &= _ck(_inst1["ok"] and os.path.isdir(_inst_dir)
                      and capabilities.get("pkgone") is not None,
                      "扩展⑦：从**目录**装 → 落在 <数据目录>/capabilities/pkgone，加载器认得出",
                      _inst1["message"])
            # 覆盖装：先改旧版的正文当标记，装新版 → 旧版本备份成 pkgone.bak-*
            _cap_write(_cap_data, "pkgone", "旧版说明", body="旧版本标记")
            capabilities.reload_all()
            _src2 = _cap_write(_cap_scratch, "pkgone", "新版说明", body="新版本标记")
            _inst2 = capabilities.install(_src2)
            _baks = [x for x in os.listdir(_cap_data) if x.startswith("pkgone.bak-")]
            _bak_ok = bool(_baks) and "旧版本标记" in open(
                os.path.join(_cap_data, _baks[0], "SKILL.md"), encoding="utf-8").read()
            ok &= _ck(_inst2["ok"] and _bak_ok
                      and "新版本标记" in open(os.path.join(_inst_dir, "SKILL.md"),
                                            encoding="utf-8").read(),
                      "扩展⑦：已存在 → **先备份成 `<名字>.bak-<时间>`** 再换新的",
                      "、".join(_baks))
            # 校验不过：一个文件都不落地
            _bad_src = _cap_write(_cap_scratch, "capbad", "长" * 61)
            _before_dirs = set(os.listdir(_cap_data))
            _inst3 = capabilities.install(_bad_src)
            ok &= _ck(not _inst3["ok"] and "第 2 条" in _inst3["message"]
                      and set(os.listdir(_cap_data)) == _before_dirs,
                      "扩展⑦：校验不过 → 报**第几条**、**一个文件都不落地**",
                      _inst3["message"])
            # 装完加载器认不出来 → 回滚到备份（把加载器那一层打桩）
            _src3 = _cap_write(_cap_scratch, "pkgone", "坏掉的新版", body="坏版本标记")
            _real_load = capabilities._load_dir

            def _cap_broken_load(path, builtin=False, folder_name=None):
                _cap = _real_load(path, builtin, folder_name)
                if os.path.basename(os.path.abspath(path)) == "pkgone":
                    _cap = _cap.clone()          # ⛔ 别改缓存里那个对象（会粘住）
                    _cap.ok = False
                    _cap.rules[0] = {"rule": 1, "ok": False, "warn": False,
                                     "message": "自检：假装装完加载失败"}
                    _cap.tools = []
                return _cap

            capabilities._load_dir = _cap_broken_load
            try:
                _inst4 = capabilities.install(_src3)
            finally:
                capabilities._load_dir = _real_load
            _restored = "新版本标记" in open(os.path.join(_inst_dir, "SKILL.md"),
                                          encoding="utf-8").read()
            ok &= _ck(not _inst4["ok"] and "回滚" in _inst4["message"] and _restored,
                      "扩展⑦：装完加载器认不出来 → **回滚到备份**（旧内容原样回来）",
                      _inst4["message"])
            # 从 zip 装（套一层文件夹 / 不套都认）
            _zsrc = _cap_write(_cap_scratch, "pkgzip", "zip 装的包", tool=("cap_zip_tool", "zip 工具"))
            _zip1 = _cap_zip(_zsrc, os.path.join(_cap_scratch, "pkgzip.zip"), outer="pkgzip")
            _inst5 = capabilities.install(_zip1)
            _zip2 = _cap_zip(_cap_write(_cap_scratch, "pkgbare", "没外层文件夹的包",
                                        tool=("cap_bare_tool", "裸包工具")),
                             os.path.join(_cap_scratch, "pkgbare.zip"))
            _inst6 = capabilities.install(_zip2)
            ok &= _ck(_inst5["ok"] and _inst6["ok"]
                      and os.path.isdir(os.path.join(_cap_data, "pkgzip"))
                      and os.path.isdir(os.path.join(_cap_data, "pkgbare")),
                      "扩展⑦：zip 装（外面套一层 / 不套都自适应）",
                      "%s ｜ %s" % (_inst5["message"], _inst6["message"]))
            # 卸载：目录 + 备份一起清；仓库自带的包删不掉、只能停用
            _rm1 = capabilities.remove("pkgone")
            _left = [x for x in os.listdir(_cap_data) if x == "pkgone" or x.startswith("pkgone.bak-")]
            #    ⚠️ 2026-10-31（示例外置化）：`capabilities/` 下现在只剩 pack-manager
            #       这种"仓库自带"的包（pc-status 是**装的**，删得掉）。所以自带那一档
            #       打桩成一个临时 builtin_root 来测（⛔ 不往仓库里写东西）。
            _bi_root = os.path.join(_cap_scratch, "builtin-root")
            _cap_write(_bi_root, "pkgbuiltin", "仓库自带的包",
                       tool=("cap_builtin_tool", "自带工具"))
            _real_broot = capabilities.builtin_root
            capabilities.builtin_root = lambda: _bi_root
            try:
                _rm2 = capabilities.remove("pkgbuiltin")
            finally:
                capabilities.builtin_root = _real_broot
            ok &= _ck(_rm1["ok"] and not _left and not _rm2["ok"]
                      and capabilities.ERR_BUILTIN in _rm2["message"],
                      "扩展⑦：卸载删目录（备份一起清）；仓库自带的包删不掉、只能停用",
                      "%s ｜ %s" % (_rm1["message"], _rm2["message"]))

            # ── ⑧ 停用 / 启用（state 文件）──
            _cap_write(_cap_data, "capoff", "会被停用的包", tool=("cap_off_tool", "停用后不该出现"))
            capabilities.reload_all()
            _c8 = _cap_ctx(1357918)
            ok &= _ck("- capoff：会被停用的包" in (capabilities.catalog_message(_c8) or {})
                      .get("content", ""),
                      "扩展⑧：停用前 → 目录里有这一行")
            toolkit.call("skill", {"name": "capoff"}, _c8)          # 先解锁
            _on8 = capabilities.set_enabled("capoff", False)
            _cat8 = (capabilities.catalog_message(_c8) or {}).get("content") or ""
            _n8 = [t["function"]["name"] for t in toolkit.schemas(_c8)]
            _off8 = toolkit.call("skill", {"name": "capoff"}, _c8)
            ok &= _ck(_on8[0] and "- capoff：" not in _cat8
                      and "cap_off_tool" not in _n8
                      and _off8.get("ok") is False,
                      "扩展⑧：停用 → **目录行消失** + 已解锁的 schema 也不发 + 技能读不到",
                      _off8.get("error"))
            _on8b = capabilities.set_enabled("capoff", True)
            ok &= _ck(_on8b[0] and "- capoff：会被停用的包" in
                      (capabilities.catalog_message(_c8) or {}).get("content", ""),
                      "扩展⑧：再启用 → 目录行回来")

            # ── ⑨ pc-status 包等价 / 面板 / 控制面主人闸 ──
            base.cfg()["pcStatus"]["enabled"] = True
            _pc_mod = capabilities.get("pc-status").mod
            _hb = statuscache.latest()
            _want_av = bool(_hb is not None and statuscache.fresh(_hb))
            ok &= _ck(_pc_mod.available({}) is _want_av,
                      "扩展⑨：pc-status 的 available = `pcStatus.enabled` + 最近心跳（和原来同一条口径）",
                      "available=%r ｜ fresh=%r" % (_pc_mod.available({}), _want_av))
            store.remove(statuscache.CACHE_NAME)
            ok &= _ck(_pc_mod.available({}) is False,
                      "扩展⑨：没有心跳 → available 假（工具不进请求）")
            base.cfg()["pcStatus"]["enabled"] = False
            ok &= _ck(_pc_mod.available({}) is False,
                      "扩展⑨：开关关掉 → available 假")
            base.cfg()["pcStatus"]["enabled"] = True
            _pc_html = panel.render()
            ok &= _ck(_pc_html.index('data-go="robot"')
                      < _pc_html.index('data-go="extensions"')
                      < _pc_html.index('data-go="system"'),
                      "扩展⑨：扩展位于机器人与系统模块之间")
            ok &= _ck(all(k in _pc_html for k in (
                          'data-view="extensions"', "capList", "capMsg", "capCount",
                          "capability.list", "capability.enable", "capability.disable",
                          "capability.remove", "capability.install", "安装（上传 zip）",
                          "已加载", "校验失败：第 ", "已停用")),
                      "扩展⑨：面板那一页的行 / 状态 / 按钮 / 动作名都在")
            _api_list = capabilities.api("capability.list", {})
            ok &= _ck(bool(_api_list and _api_list.get("ok")
                           and any(c["name"] == "pc-status" for c in _api_list["capabilities"])),
                      "扩展⑨：控制面 `capability.list` 给面板返回一行一个包")
            ok &= _ck(agent.on_api("capability.list", {}, {"id": "x", "主人": False})
                      is agent.FORBIDDEN,
                      "扩展⑨：非主人调 capability.* → FORBIDDEN（server 回 403 空正文）")

            # ── ⑩ 命令行四个开关 ──
            #    ⚠️ 把 CLI 的输出**接进字符串**：它逐条打印时会带「✗ 第 N 条」，
            #       直接放到自检输出里会被当成一条失败（这一节自己断言它）。）
            import contextlib as _cap_ctxlib
            import io as _cap_io
            _zipcli = _cap_zip(_cap_write(_cap_scratch, "pkgcli", "命令行装的包",
                                          tool=("cap_cli_tool", "命令行工具")),
                               os.path.join(_cap_scratch, "pkgcli.zip"), outer="pkgcli")
            _cli_out = _cap_io.StringIO()
            with _cap_ctxlib.redirect_stdout(_cli_out):
                _rc_inst = cli_cap_install(_zipcli)
                _rc_list = cli_cap_list()
                _rc_bad = cli_cap_check(_bad_src)
                _rc_good = cli_cap_check(_src)
                _rc_rm = cli_cap_remove("pkgcli")
            _cli_txt = _cli_out.getvalue()
            ok &= _ck(_rc_list == 0 and _rc_bad == 1 and _rc_good == 0
                      and _rc_inst == 0 and _rc_rm == 0
                      and "带工具：cap_cli_tool" in _cli_txt
                      and "第 2 条" in _cli_txt and "全部通过" in _cli_txt,
                      "扩展⑩：--list-capabilities / --check-capability / --install-capability / "
                      "--remove-capability 的退出码都对（校验不过 = 1、逐条打印）",
                      "list=%s check_bad=%s check_ok=%s install=%s remove=%s"
                      % (_rc_list, _rc_bad, _rc_good, _rc_inst, _rc_rm))
        finally:
            # 清干净：自检造的包 / 停用名单 / 会话解锁 / 心跳，一个都不留给后面的断言
            for _d in _cap_made:
                shutil.rmtree(_d, ignore_errors=True)
            for _x in (os.listdir(_cap_data) if os.path.isdir(_cap_data) else []):
                if _x.startswith(("cap", "pkg")) and _x != "capabilities-state.json":
                    shutil.rmtree(os.path.join(_cap_data, _x), ignore_errors=True)
            if _cap_state0 is None:
                store.remove(capabilities.STATE_NAME)
            else:
                store.write_json(capabilities.STATE_NAME, _cap_state0)
            capabilities.reload_all()
            capabilities.clear_sessions()
            store.remove(statuscache.CACHE_NAME)
            base.cfg()["pcStatus"] = _cap_pc_cfg

        # ══════════════════════════════════════════════════════════════
        # 6.17 `package` 工具（装 / 卸 / 取文件）+ 文件入站 + 示例外置化
        #
        #   · 逐字：SKILL.md / NAME / DESC / 五个参数（op=string、confirm=boolean）
        #   · available = 说话人是主人；别人读技能也不出现、调了回「只有主人能装。」
        #   · op=install / remove 都是**两段式**（第一段只预检、confirm 才动手）
        #   · 预检回执：包名 / 一句话 / 会新增的工具 / 文件清单 / 大小 / sha256 /
        #     六条校验 / 下一步；预检**不落地**、装完加载失败**回滚**
        #   · 白名单（含子域 / 镜像站 / capability.extraHosts）/ 5 MB / 重定向 ≤5 /
        #     只收 zip / 下载失败一句人话（不抛 traceback）
        #   · op=fetch：群文件 get_group_file、私聊 get_file；≤50 MB；
        #     过期 / 取不到 / 太大三种人话
        #   · 文件入站：群聊、私聊、**引用消息里的文件**三种都要（[{id,name,size}]）
        #   · `_template/` 被加载器跳过；示例包在 examples/（仓库里没有 capabilities/pc-status/）
        #     zip 由 tools/build_example_packages.py 生成，和源码逐字节一致
        # ══════════════════════════════════════════════════════════════
        print()
        _CUR_SECT[0] = "6.17 package 工具 / 文件入站 / 示例包 / 模板"
        print("=== 6.17 package 工具 / 文件入站 / 示例包 / 模板 ===")
        import importlib.util as _pk_iu
        import urllib.error as _pk_ue
        import urllib.request as _pk_ur

        _pk_cap = capabilities.get("pack-manager")
        _pk_mod = _pk_cap.mod if _pk_cap is not None else None
        _pk_state0 = store.read_json(capabilities.STATE_NAME, default=None)
        _pk_ok_u, _pk_msg_u, _pk_owner_rec = users.add(
            "自检主人", "1800000001", "", "自检（稍后撤销）", is_owner=True)
        # ⚠ 2026-11-01：主人判定改成只认配置 bot.ownerQQ，自检里也跟着指过去
        base.cfg().setdefault("bot", {})["ownerQQ"] = "1800000001"
        _pk_tmp = os.path.join(tmp, "pk-scratch")
        os.makedirs(_pk_tmp, exist_ok=True)
        _pk_cfg0 = dict(base.cfg().get("capability") or {})
        _pk_owner = {"key": ("g", 1357930), "is_group": True, "group_id": 1357930,
                     "user_id": "1800000001", "who": "自检主人", "text": "装个包",
                     "raw": "装个包", "files": [], "reply_to": None, "message_id": 1,
                     "at": time.time(), "evt": {}}
        _pk_other = dict(_pk_owner, user_id="1800000002", key=("g", 1357931))
        try:
            # ── ① 逐字（SKILL.md / NAME / DESC / 参数类型）──
            _pk_props = ((_pk_mod.PARAMS if _pk_mod is not None else {}).get("properties")
                         or {})
            ok &= _ck(_pk_mod is not None
                      and _pk_mod.NAME == "package"
                      and _pk_mod.DESC == "装或卸扩展包、下载消息里的文件"
                      and (_pk_mod.PARAMS or {}).get("type") == "object"
                      and set(_pk_props) == {"op", "source", "name", "file", "confirm"}
                      and _pk_props["op"].get("type") == "string"
                      and _pk_props["op"].get("enum") == ["install", "remove", "fetch"]
                      and all(_pk_props[k].get("type") == "string"
                              for k in ("source", "name", "file"))
                      and _pk_props["confirm"].get("type") == "boolean"
                      and (_pk_mod.PARAMS or {}).get("required") == [],
                      "包①：`package` 的 NAME / DESC / 五个参数**逐字**"
                      "（op=string、source/name/file=string、confirm=boolean）",
                      repr(_pk_props))
            _pk_md = open(os.path.join(_pk_cap.dir, "SKILL.md"), encoding="utf-8").read()
            _pk_meta, _pk_body = capabilities.parse_skill(_pk_md)
            ok &= _ck(_pk_meta is not None
                      and _pk_meta.get("name") == "pack-manager"
                      and _pk_meta.get("description") == "装或卸扩展包、下载消息里的文件（只有主人能装）"
                      and "# 装扩展包" in _pk_body
                      and ("- op=install，source=网址或本地路径 → 只预检；"
                           "主人同意再加 confirm=true 才真装") in _pk_body
                      and "只有主人的命令才能安装插件。预检回执要念给主人，他同意了再继续。" in _pk_body
                      and "## 只有名字、没有链接" in _pk_body
                      and "搜不到、仓库是私有的、预检下载失败、超过 5 MB。" in _pk_body,
                      "包①：SKILL.md 的用户批文本**逐字**（含「只有名字、没有链接」那一段）",
                      repr(_pk_body[:40]))

            # ── ② 只有主人看得见 / 调得动 ──
            ok &= _ck(_pk_ok_u and users.owner_qq() == "1800000001",
                      "包②：先造一条主人记录（`主人: true`；自检用）", _pk_msg_u)
            ok &= _ck(_pk_mod.available(_pk_owner) is True
                      and _pk_mod.available(_pk_other) is False
                      and _pk_mod.available({}) is False,
                      "包②：available = 说话人是主人（别人 / 空 ctx → 假）")
            capabilities.clear_sessions()
            _pk_c1 = dict(_pk_owner)
            _pk_c2 = dict(_pk_other)
            toolkit.call("skill", {"name": "pack-manager"}, _pk_c1)
            toolkit.call("skill", {"name": "pack-manager"}, _pk_c2)
            _pk_n1 = [t["function"]["name"] for t in toolkit.schemas(_pk_c1)]
            _pk_n2 = [t["function"]["name"] for t in toolkit.schemas(_pk_c2)]
            ok &= _ck("package" in _pk_n1 and "package" not in _pk_n2,
                      "包②：主人读技能后目录里出现 `package`；**别人读同一个技能也不出现**",
                      "、".join(_pk_n1[-3:]))
            ok &= _ck(_pk_mod.run({"op": "install", "source": "x"}, _pk_other)
                      == {"ok": False, "error": "只有主人能装。"},
                      "包②：主人以外的人调 → 逐字 `只有主人能装。`")

            # ── ③ op=install：预检回执 / 不落地 / confirm 才装 / 装完能跑 ──
            _pk_src = _cap_write(_pk_tmp, "pkgpm", "自检装进来的包", body="第一版标记",
                                 tool=("pm_tool", "自检工具"))
            _pk_zip = _cap_zip(_pk_src, os.path.join(_pk_tmp, "pkgpm.zip"), outer="pkgpm")
            _pk_dest = os.path.join(capabilities.data_root(), "pkgpm")
            _pk_pre = _pk_mod.run({"op": "install", "source": _pk_zip}, _pk_owner)
            ok &= _ck(_pk_pre.get("ok") is True and _pk_pre.get("预检") is True
                      and _pk_pre.get("包名") == "pkgpm"
                      and _pk_pre.get("一句话") == "自检装进来的包"
                      and _pk_pre.get("会新增的工具") == ["pm_tool"]
                      and "SKILL.md" in (_pk_pre.get("文件清单") or [])
                      and "tool.py" in (_pk_pre.get("文件清单") or [])
                      and bool(_pk_pre.get("大小"))
                      and len(_pk_pre.get("sha256") or "") == 64
                      and len(_pk_pre.get("六条校验") or []) == 6
                      and all(r["通过"] for r in _pk_pre["六条校验"])
                      and _pk_pre.get("下一步") == capabilities.NEXT_STEP
                      and not os.path.isdir(_pk_dest),
                      "包③：install 第一段只预检 → 回执（包名/一句话/工具/文件/大小/"
                      "sha256/六条/下一步），**一个文件都不落地**",
                      repr(_pk_pre.get("大小")))
            _pk_badsrc = _cap_write(_pk_tmp, "pkgpmbad", "长" * 61)
            _pk_badzip = _cap_zip(_pk_badsrc, os.path.join(_pk_tmp, "pkgpmbad.zip"),
                                  outer="pkgpmbad")
            _pk_prebad = _pk_mod.run({"op": "install", "source": _pk_badzip}, _pk_owner)
            ok &= _ck(_pk_prebad.get("ok") is False
                      and "第 2 条" in (_pk_prebad.get("error") or "")
                      and not os.path.isdir(os.path.join(capabilities.data_root(),
                                                         "pkgpmbad")),
                      "包③：校验不过 → 报**第几条**、还是一个文件都不落地",
                      _pk_prebad.get("error"))
            _pk_inst = _pk_mod.run({"op": "install", "source": _pk_zip,
                                    "confirm": True}, _pk_owner)
            ok &= _ck(_pk_inst.get("ok") is True and capabilities.get("pkgpm") is not None
                      and os.path.isfile(os.path.join(_pk_dest, "SKILL.md")),
                      "包③：confirm=true 才真装（加载器认得出）", _pk_inst.get("说明"))
            ok &= _ck(toolkit.call("pm_tool", {}, _pk_owner).get("谁") == "pm_tool",
                      "包③：装上去的工具派发得到（行为跟普通扩展包一样）")

            # 装完加载器认不出来 → 回滚到上一版（和 install 的 ④ 同一条路）
            _pk_src2 = _cap_write(_pk_tmp, "pkgpm", "第二版", body="第二版标记",
                                  tool=("pm_tool", "自检工具"))
            _pk_zip2 = _cap_zip(_pk_src2, os.path.join(_pk_tmp, "pkgpm2.zip"),
                                outer="pkgpm")
            _pk_real_load = capabilities._load_dir

            def _pk_broken_load(path, builtin=False, folder_name=None):
                _pk_c = _pk_real_load(path, builtin, folder_name)
                if os.path.basename(os.path.abspath(path)) == "pkgpm":
                    _pk_c = _pk_c.clone()
                    _pk_c.ok = False
                    _pk_c.rules[0] = {"rule": 1, "ok": False, "warn": False,
                                      "message": "自检：假装装完加载失败"}
                    _pk_c.tools = []
                return _pk_c

            capabilities._load_dir = _pk_broken_load
            try:
                _pk_roll = _pk_mod.run({"op": "install", "source": _pk_zip2,
                                        "confirm": True}, _pk_owner)
            finally:
                capabilities._load_dir = _pk_real_load
            _pk_back = open(os.path.join(_pk_dest, "SKILL.md"), encoding="utf-8").read()
            ok &= _ck(_pk_roll.get("ok") is False
                      and "回滚" in (_pk_roll.get("error") or "")
                      and "第一版标记" in _pk_back,
                      "包③：装完加载器认不出来 → **回滚到上一版**（旧内容原样回来）",
                      _pk_roll.get("error"))

            # ── ④ op=remove：两段式 / 卸载清停用名单 / 自带包拒绝 ──
            _pk_rpre = _pk_mod.run({"op": "remove", "name": "pkgpm"}, _pk_owner)
            ok &= _ck(_pk_rpre.get("ok") is True and _pk_rpre.get("预检") is True
                      and _pk_rpre.get("包名") == "pkgpm"
                      and _pk_rpre.get("下一步") == "要删就再调一次，confirm=true"
                      and os.path.isdir(_pk_dest),
                      "包④：op=remove 第一段只预检（包还在）", _pk_rpre.get("下一步"))
            capabilities.set_enabled("pkgpm", False)
            _pk_rm = _pk_mod.run({"op": "remove", "name": "pkgpm", "confirm": True},
                                 _pk_owner)
            ok &= _ck(_pk_rm.get("ok") is True and not os.path.isdir(_pk_dest)
                      and "pkgpm" not in capabilities.disabled(),
                      "包④：confirm 才删；**卸载连停用名单一起清**",
                      _pk_rm.get("说明"))
            ok &= _ck((_pk_mod.run({"op": "remove", "name": "pkgpm"}, _pk_owner)
                       .get("error") or "") == "没装过这个包：pkgpm",
                      "包④：没装过 → 人话")
            ok &= _ck((_pk_mod.run({"op": "remove", "name": "pack-manager",
                                    "confirm": True}, _pk_owner).get("error") or "")
                      == capabilities.ERR_BUILTIN,
                      "包④：仓库自带的包拒绝（话术沿用现有那句）")

            # ── ⑤ 白名单 / extraHosts / 5 MB / 重定向 / 只收 zip / 下载失败人话 ──
            ok &= _ck((_pk_mod.run({"op": "install",
                                    "source": "https://evil.com/x.zip"}, _pk_owner)
                       .get("error") or "") == capabilities.ERR_SOURCE
                      and capabilities.host_allowed("https://sub.github.com/x/zip/HEAD")
                      and capabilities.host_allowed("https://ghfast.top/x.zip")
                      and not capabilities.host_allowed("https://github.com@evil.com/x.zip"),
                      "包⑤：来源白名单（含子域 / 镜像站；`user@host` 伪装不行），"
                      "其余 = 逐字那句")
            base.cfg().setdefault("capability", {})["extraHosts"] = ["example-mirror.com"]
            try:
                _pk_extra_ok = (capabilities.host_allowed(
                    "https://cdn.example-mirror.com/a.zip")
                    and "example-mirror.com" in capabilities.allowed_hosts())
            finally:
                base.cfg()["capability"] = dict(_pk_cfg0)
            ok &= _ck(_pk_extra_ok,
                      "包⑤：`capability.extraHosts` 里的域名也放行（生效 = 默认 + 额外）")

            class _PkResp(object):
                def __init__(self, blob):
                    self._blob = blob
                    self.headers = {}

                def read(self, n=-1):
                    return self._blob if n is None or n < 0 else self._blob[:n]

                def close(self):
                    pass

            class _PkOpener(object):
                def __init__(self, fn):
                    self.fn = fn
                    self.calls = 0

                def open(self, req, timeout=0):
                    self.calls += 1
                    return self.fn(req.full_url)

            _pk_real_build = _pk_ur.build_opener

            def _pk_with(opener, url):
                _pk_ur.build_opener = lambda *a, **k: opener
                try:
                    return capabilities._download_zip(url)
                finally:
                    _pk_ur.build_opener = _pk_real_build

            _pk_nz = _pk_with(_PkOpener(lambda u: _PkResp(b"not a zip")),
                              "https://github.com/a/b/zip/HEAD")
            _pk_big = _pk_with(_PkOpener(lambda u: _PkResp(
                b"0" * (capabilities.MAX_PACKAGE_BYTES + 1))),
                "https://github.com/a/b/zip/HEAD")
            _pk_evil = _pk_with(_PkOpener(lambda u: (_ for _ in ()).throw(
                _pk_ue.HTTPError(u, 302, "Found",
                                 {"Location": "https://evil.com/x.zip"}, None))),
                "https://github.com/a/b/zip/HEAD")
            _pk_loop = _pk_with(_PkOpener(lambda u: (_ for _ in ()).throw(
                _pk_ue.HTTPError(u, 302, "Found",
                                 {"Location": "https://codeload.github.com/a/%d/zip/HEAD"
                                  % (len(u) + 1)}, None))),
                "https://github.com/a/b/zip/HEAD")
            _pk_dl = _pk_with(_PkOpener(lambda u: (_ for _ in ()).throw(
                _pk_ue.URLError("boom"))), "https://github.com/a/b/zip/HEAD")
            ok &= _ck(_pk_nz == (None, capabilities.ERR_NOT_ZIP)
                      and _pk_big == (None, capabilities.ERR_TOO_BIG_PKG)
                      and _pk_evil == (None, capabilities.ERR_SOURCE)
                      and _pk_loop == (None, capabilities.ERR_DOWNLOAD)
                      and _pk_dl == (None, capabilities.ERR_DOWNLOAD)
                      and "codeload" in capabilities.ERR_DOWNLOAD,
                      "包⑤：只收 zip / 5 MB / 重定向每一跳过白名单 / ≤5 跳 / "
                      "下载失败一句人话（建议 codeload 直链）",
                      "%r ｜ %r" % (_pk_nz[1], _pk_big[1]))

            # ── ⑥ op=fetch：群 / 私聊两个接口、落盘、三种人话 ──
            _pk_calls = []
            _pk_real_call = im._napcat_call

            def _pk_fake_call(endpoint, payload, timeout=20, retry=False):
                _pk_calls.append(endpoint)
                if payload.get("file_id") == "NOFILE":
                    return False, "network"
                if payload.get("file_id") == "EXPIRED":
                    return False, "文件已过期"
                return True, {"url": "https://files.example/%s" % payload.get("file_id")}

            files.set_fetcher(lambda u: b"hello")
            im._napcat_call = _pk_fake_call
            try:
                _pk_fctx = dict(_pk_owner, is_group=True, group_id=1357930,
                                files=[{"id": "F1", "name": "报告.pdf", "size": 5}],
                                files_all=[{"id": "F1", "name": "报告.pdf", "size": 5}])
                _pk_f1 = _pk_mod.run({"op": "fetch", "file": "报告.pdf"}, _pk_fctx)
                _pk_f2 = _pk_mod.run({"op": "fetch", "file": "F1"},
                                     dict(_pk_fctx, is_group=False, group_id=None))
                _pk_f3 = _pk_mod.run(
                    {"op": "fetch", "file": "大.zip"},
                    dict(_pk_fctx, files=[{"id": "B", "name": "大.zip",
                                           "size": 50 * 1024 * 1024 + 1}],
                         files_all=[]))
                _pk_f4 = _pk_mod.run(
                    {"op": "fetch", "file": "x"},
                    dict(_pk_fctx, files=[{"id": "EXPIRED", "name": "x", "size": 1}],
                         files_all=[]))
                _pk_f5 = _pk_mod.run(
                    {"op": "fetch", "file": "y"},
                    dict(_pk_fctx, files=[{"id": "NOFILE", "name": "y", "size": 1}],
                         files_all=[]))
                _pk_f6 = _pk_mod.run({"op": "fetch", "file": "不存在.zip"}, _pk_fctx)
                _pk_f7 = _pk_mod.run({"op": "fetch", "file": "x"},
                                     dict(_pk_fctx, files=[], files_all=[]))
            finally:
                im._napcat_call = _pk_real_call
                files.set_fetcher(None)
            _pk_fpath = _pk_f1.get("本地路径") or ""
            ok &= _ck(_pk_f1.get("ok") is True and os.path.isfile(_pk_fpath)
                      and open(_pk_fpath, "rb").read() == b"hello"
                      and _pk_f1.get("大小") == "5 B"
                      and os.path.normcase(_pk_fpath).startswith(
                          os.path.normcase(store.path("files")))
                      and _pk_calls[:2] == ["get_group_file", "get_file"],
                      "包⑥：op=fetch 群文件走 `get_group_file`、私聊走 `get_file`；"
                      "下到 <数据目录>/files/，回路径 + 大小",
                      "、".join(_pk_calls))
            ok &= _ck((_pk_f3.get("error") or "") == files._TOO_BIG
                      and (_pk_f4.get("error") or "") == files._EXPIRED
                      and (_pk_f5.get("error") or "") == files._NO_FILE,
                      "包⑥：失败三种人话（太大 / 过期 / 取不到）逐字",
                      "%r ｜ %r ｜ %r" % (_pk_f3.get("error"), _pk_f4.get("error"),
                                          _pk_f5.get("error")))
            ok &= _ck("没找到这个文件" in (_pk_f6.get("error") or "")
                      and (_pk_f7.get("error") or "") == "这条消息里没有文件",
                      "包⑥：名字对不上 / 这条消息没带文件 → 各一句人话")

            # ── ⑥b 真机踩到的接口差异：四个接口挨个试（2026-10-31）──
            #   实测：get_group_file 不支持 / get_file 在但参数不对 /
            #        *_url 要 packetBackend（QQ build 超范围就不可用）
            _pk_calls2 = []

            def _pk_fake_call2(endpoint, payload, timeout=20, retry=False):
                _pk_calls2.append(endpoint)
                if endpoint == "get_file":
                    return True, {"url": "https://files.example/%s" % payload.get("file_id")}
                return False, "不支持的Api %s" % endpoint

            _pk_real_call2 = im._napcat_call
            im._napcat_call = _pk_fake_call2
            files.set_fetcher(lambda u: b"F2OK")
            try:
                _pk_g2 = _pk_mod.run({"op": "fetch", "file": "F2"},
                                     dict(_pk_fctx, files=[{"id": "F2", "name": "F2", "size": 4}],
                                          files_all=[{"id": "F2", "name": "F2", "size": 4}]))
            finally:
                im._napcat_call = _pk_real_call2
                files.set_fetcher(None)
            _pk_g2p = _pk_g2.get("本地路径") or ""
            ok &= _ck(_pk_g2.get("ok") is True
                      and _pk_calls2[:2] == ["get_group_file", "get_file"]
                      and os.path.isfile(_pk_g2p)
                      and open(_pk_g2p, "rb").read() == b"F2OK",
                      "包⑥b：群文件先试 `get_group_file`、不支持就退到 `get_file`（真机就是这样）",
                      "、".join(_pk_calls2))

            # ── ⑦ 文件入站：群聊 / 私聊 / 引用（[{id,name,size}] + 一句事实）──
            _pk_evt = {"post_type": "message", "message_type": "group",
                       "group_id": 1357930, "user_id": 10001,
                       "self_id": base.self_id(), "message_id": 1,
                       "raw_message": ("[CQ:file,file=群文件.zip,file_id=GF1,"
                                       "file_size=2048]"),
                       "sender": {"user_id": 10001, "card": "自检", "nickname": "x"}}
            _pk_ctx_g = server.build_ctx(_pk_evt, b"{}")
            _pk_ctx_p = server.build_ctx(dict(_pk_evt, message_type="private",
                                              group_id=None), b"{}")
            ok &= _ck(_pk_ctx_g.get("files") == [{"id": "GF1", "name": "群文件.zip",
                                                  "size": 2048}]
                      and _pk_ctx_p.get("files") == _pk_ctx_g.get("files"),
                      "包⑦：群聊 / 私聊的文件都进 `ctx[\"files\"]`（{id,name,size}）",
                      repr(_pk_ctx_g.get("files")))
            images.set_quoter(lambda rid: (True, {
                "raw_message": "[CQ:file,file=引用文件.txt,file_id=QF1,file_size=12]",
                "sender": {"user_id": 10002, "card": "甲"},
                "time": time.time()}))
            _pk_qctx = dict(_pk_owner, raw="[CQ:reply,id=1692039999] 看看",
                            reply_to="1692039999", files=[])
            _pk_qrefs = files.quoted_refs(_pk_qctx)
            _pk_qmsgs, _pk_qinfo = agent._build(_pk_qctx, "名字")
            _pk_qocc = "\n".join(str(m.get("content") or "") for m in _pk_qmsgs[:-1])
            ok &= _ck(_pk_qrefs == [{"id": "QF1", "name": "引用文件.txt", "size": 12}]
                      and "（他引用的那条里有文件：引用文件.txt（12 B））" in _pk_qocc,
                      "包⑦：**引用消息里的文件**也认（和图片那条路同口径），"
                      "并给她一句事实", repr(_pk_qocc[-60:]))
            _pk_note = files.note(dict(_pk_owner, raw="",
                                       files=[{"id": "N1", "name": "合同.pdf",
                                               "size": 2048}]))
            ok &= _ck(_pk_note == "（这条消息带了文件：合同.pdf（2.0 KB））",
                      "包⑦：当前这条的文件 → 一句事实（名字 + 大小，不写命令）",
                      repr(_pk_note))

            # ── ⑧ `_template/` 被跳过；示例包在 examples/、zip 由脚本生成 ──
            _pk_tpl = os.path.join(base.CODE_DIR, "capabilities", "_template")
            ok &= _ck(os.path.isfile(os.path.join(_pk_tpl, "SKILL.md"))
                      and os.path.isfile(os.path.join(_pk_tpl, "tool.py"))
                      and "_template" not in capabilities.names()
                      and "_template" not in {c["name"] for c in capabilities.list()}
                      and "my-skill" not in capabilities.catalog_text(),
                      "包⑧：`capabilities/_template/` 在仓库里；加载器**跳过 `_` 开头的包**"
                      "（目录 / 列表都不出现）")
            _pk_ex_dir = os.path.join(base.CODE_DIR, "examples", "packages", "pc-status")
            _pk_ex_zip = os.path.join(base.CODE_DIR, "examples", "packages",
                                      "pc-status-1.0.0.zip")
            _pk_spec = _pk_iu.spec_from_file_location(
                "pk_bep", os.path.join(base.CODE_DIR, "tools",
                                       "build_example_packages.py"))
            _pk_bep = _pk_iu.module_from_spec(_pk_spec)
            _pk_spec.loader.exec_module(_pk_bep)
            _pk_built, _pk_bn, _pk_bv = _pk_bep.build_one(
                _pk_ex_dir, os.path.join(_pk_tmp, "built"))
            # ⚠ 2026-11-01：以前比**原始字节** ✗ zip 头里带 mtime，
            #   换个目录重打就判不一致（VM 验收时真碰到）。现在比内容。
            _pk_same = _pk_bep._zip_same(_pk_built, _pk_ex_zip)
            _pk_pc = capabilities.get("pc-status")
            ok &= _ck(os.path.isfile(os.path.join(_pk_ex_dir, "SKILL.md"))
                      and os.path.isfile(_pk_ex_zip)
                      and not os.path.isdir(os.path.join(base.CODE_DIR, "capabilities",
                                                         "pc-status"))
                      and _pk_same
                      and _pk_pc is not None and _pk_pc.ok
                      and _pk_pc.tools[0]["name"] == "pc_status",
                      "包⑧：示例包只在 `examples/packages/pc-status/`（仓库里没有 "
                      "`capabilities/pc-status/`）；zip 由脚本生成、逐字节一致；装上去能跑",
                      "%s-%s ｜ 一致=%r" % (_pk_bn, _pk_bv, _pk_same))

            # ── ⑨ 面板「扩展」页：从网址安装 / 预检回执 / 额外允许域名 / 来源 ──
            _pk_html = panel.render()
            ok &= _ck(all(k in _pk_html for k in (
                      "从网址安装", "capability.check_url", "capability.install_url",
                      "capUrl", "capReceipt", "capHostChips", "drawHosts", "addHost",
                      "额外允许域名", "仓库自带", "安装（上传 zip）", "卸载", "停用")),
                      "包⑨：面板「扩展」页有「从网址安装」+ 预检回执 + 「额外允许域名」"
                      "+ 来源列，原来的上传 / 卸载 / 停用都还在")
            _pk_apic = capabilities.api("capability.check_url",
                                        {"url": "https://evil.com/x.zip"})
            ok &= _ck(_pk_apic.get("ok") is False
                      and _pk_apic.get("error") == capabilities.ERR_SOURCE
                      and agent.on_api("capability.check_url", {"url": "https://x/y.zip"},
                                       {"id": "x", "主人": False}) is agent.FORBIDDEN,
                      "包⑨：面板的网址预检走同一份白名单；非主人调 → FORBIDDEN")
        finally:
            files.set_puller(None)
            files.set_fetcher(None)
            images.set_quoter(None)
            capabilities.reload_all()
            capabilities.clear_sessions()
            for _x in (os.listdir(capabilities.data_root())
                       if os.path.isdir(capabilities.data_root()) else []):
                if _x.startswith(("pkgpm", "cap", "pkg")) and _x != capabilities.STATE_NAME:
                    shutil.rmtree(os.path.join(capabilities.data_root(), _x),
                                  ignore_errors=True)
            if _pk_state0 is None:
                store.remove(capabilities.STATE_NAME)
            else:
                store.write_json(capabilities.STATE_NAME, _pk_state0)
            if _pk_owner_rec:
                users.remove(_pk_owner_rec["id"])
            base.cfg()["capability"] = dict(_pk_cfg0)

    finally:
        if chime_backup is not None and base.cfg().get("agent", {}).get("chimeIn") is not None:
            base.cfg()["agent"]["chimeIn"]["enabled"] = chime_backup
        try:
            llm.set_transport(None)
            images.set_fetcher(None)
            images.set_puller(None)
            images.set_quoter(None)
            reminders.stop()
        except Exception:
            pass
        base.LOG_PATH = real_log
        persona.name, persona.wake_words = _real_name, _real_wake
        store.set_dir(base.DATA_DIR)
        shutil.rmtree(tmp, ignore_errors=True)

    # ══════════════════════════════════════════════════════════════
    # 6.15 跨环境：数据目录可配 + deploy --dry 不写任何文件
    # ══════════════════════════════════════════════════════════════
    print()
    _CUR_SECT[0] = "6.15 数据目录可配 / deploy --dry"
    print("=== 6.15 数据目录可配 / deploy --dry ===")
    import subprocess as _sp
    _dd = tempfile.mkdtemp(prefix="fg-datadir-")
    _dd_code = (
        "import os,sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from fgbot import base, store\n"
        "base.load()\n"
        "base.log('自检：数据目录重定向')\n"
        "store.write_json('memory.json', {'10001': {'facts': ['x']}})\n"
        "store.write_json('reminders.json', [])\n"
        "store.write_json('plan-10001.json', [])\n"
        "store.write_json('settings.json', {'overrides': {}})\n"
        "assert base.save_local({'selftest': True}), 'local-config 写不进去'\n"
        "from fgbot import onboard, persona\n"
        "assert os.path.dirname(os.path.abspath(persona.write_path())) == "
        "os.path.abspath(os.environ['MMZBOT_DATA']), '人设写点不在数据目录'\n"
        "_p_ok, _p_msg, _p_ret = onboard.persona_save('自检：一句人设')\n"
        "assert _p_ok, _p_msg\n"
        "assert os.path.abspath(base.DATA_DIR) == os.path.abspath(os.environ['MMZBOT_DATA'])\n"
        "for k in ('LOG_PATH', 'LOCAL_CFG_PATH', 'RESTART_PATH'):\n"
        "    p = os.path.abspath(getattr(base, k))\n"
        "    assert p.startswith(os.path.abspath(base.DATA_DIR) + os.sep), (k, p)\n"
        "print('OK')\n")
    _dd_env = dict(os.environ)
    _dd_env["MMZBOT_DATA"] = _dd
    _dd_env["PYTHONIOENCODING"] = "utf-8"
    try:
        _dd_p = _sp.run([sys.executable, "-c", _dd_code], cwd=base.CODE_DIR, env=_dd_env,
                        stdout=_sp.PIPE, stderr=_sp.STDOUT, timeout=180)
        _dd_out = (_dd_p.stdout or b"").decode("utf-8", "replace")
    except Exception as _dd_e:
        _dd_p, _dd_out = None, repr(_dd_e)
    ok &= _ck(_dd_p is not None and _dd_p.returncode == 0 and "OK" in _dd_out,
              "设 MMZBOT_DATA 到临时目录 → 进程按它算数据目录", _dd_out.strip()[-160:])
    _dd_want = ["bot.log", "memory.json", "reminders.json", "plan-10001.json",
                "settings.json", "local-config.json", "personality.md"]
    _dd_miss = [n for n in _dd_want if not os.path.isfile(os.path.join(_dd, n))]
    ok &= _ck(not _dd_miss,
              "所有状态文件都落在 MMZBOT_DATA 里（%d 个，含人设改动）" % len(_dd_want),
              "缺：%s" % _dd_miss if _dd_miss else "、".join(_dd_want))
    shutil.rmtree(_dd, ignore_errors=True)

    # `--set capability.extraHosts=a.com,b.com`（用户 2026-10-31 点名要的那条命令）
    _eh = tempfile.mkdtemp(prefix="fg-extrahosts-")
    _eh_env = dict(os.environ)
    _eh_env["MMZBOT_DATA"] = _eh
    _eh_env["PYTHONIOENCODING"] = "utf-8"
    try:
        _eh_p = _sp.run([sys.executable, os.path.join(base.CODE_DIR, "phone-bot-v2.py"),
                         "--set", "capability.extraHosts=a.com,b.com"],
                        cwd=base.CODE_DIR, env=_eh_env,
                        stdout=_sp.PIPE, stderr=_sp.STDOUT, timeout=180)
        _eh_out = (_eh_p.stdout or b"").decode("utf-8", "replace")
        _eh_cfg = json.load(open(os.path.join(_eh, "local-config.json"),
                                 encoding="utf-8"))
    except Exception as _eh_e:
        _eh_p, _eh_out, _eh_cfg = None, repr(_eh_e), {}
    _eh_got = ((_eh_cfg or {}).get("capability") or {}).get("extraHosts")
    ok &= _ck(_eh_p is not None and _eh_p.returncode == 0
              and _eh_got == ["a.com", "b.com"],
              "`--set capability.extraHosts=a.com,b.com` 存得进（逗号分开 → 数组）",
              _eh_out.strip()[-120:])
    shutil.rmtree(_eh, ignore_errors=True)

    # deploy 的 --help / --dry：**一个文件都不许写**（以前 --help 触发过真部署）
    _dep_py = os.path.join(base.CODE_DIR, "deploy.py")
    if os.path.isfile(_dep_py):
        _dep_root = tempfile.mkdtemp(prefix="fg-deploy-dry-")
        _dep_target = os.path.join(_dep_root, "data")
        _dep_env = dict(os.environ)
        _dep_env.pop("MMZBOT_DATA", None)
        _dep_env["PYTHONIOENCODING"] = "utf-8"

        def _run_deploy(*extra):
            return _sp.run([sys.executable, _dep_py] + list(extra), cwd=base.CODE_DIR,
                           env=_dep_env, stdout=_sp.PIPE, stderr=_sp.STDOUT,
                           timeout=300)

        try:
            _p_help = _run_deploy("--help")
            _p_dry = _run_deploy("--target", "local", "--dry", "--dir", _dep_target)
            _dry_out = (_p_dry.stdout or b"").decode("utf-8", "replace")
        except Exception as _de:
            _p_help, _p_dry, _dry_out = None, None, repr(_de)
        ok &= _ck(_p_help is not None and _p_help.returncode == 0,
                  "deploy.py --help 正常退出（不许触发部署）")
        ok &= _ck(_p_dry is not None and _p_dry.returncode == 0 and "不写文件" in _dry_out,
                  "deploy.py --target local --dry 正常退出、明说不写文件",
                  _dry_out.strip().splitlines()[-1] if _dry_out.strip() else "")
        ok &= _ck(not os.path.exists(_dep_target),
                  "--dry 没建目标目录", _dep_target)
        _dep_left = sorted(os.listdir(_dep_root))
        ok &= _ck(not _dep_left, "--dry 在临时目录里一个文件都没写",
                  "多了：%s" % _dep_left if _dep_left else "")
        shutil.rmtree(_dep_root, ignore_errors=True)
    else:
        print("    ⚠️ 读不到 deploy.py（手机上跑的是暂存目录）—— --dry 那两条在本地自检里查")

    print()
    _CUR_SECT[0] = "7. 自检有没有副作用"
    print("=== 7. 自检有没有副作用 ===")
    after = _snapshot(base.DIR)
    new = sorted(set(after) - set(before))
    chg = sorted(k for k in after if k in before and after[k] != before[k])
    ok &= _ck(not new, "正式目录没多出文件（状态文件都写在临时目录）",
              "多了：%s" % "、".join(new) if new else "")
    ok &= _ck(not chg, "正式目录里原有的文件没被改动", "动了：%s" % "、".join(chg) if chg else "")

    print()
    print("自检%s" % ("通过 ✓" if ok else "**没过**"))
    return 0 if ok else 1


def sections():
    """刚跑过的自检按段汇总。"""
    out, order = {}, []
    for sect, ok, what, detail in _SECT_ROWS:
        if sect not in out:
            out[sect] = {"name": sect, "total": 0, "failed": []}
            order.append(sect)
        out[sect]["total"] += 1
        if not ok:
            out[sect]["failed"].append({"what": what, "detail": detail})
    return [out[k] for k in order]
