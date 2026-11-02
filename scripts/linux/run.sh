#!/usr/bin/env bash
# MMZBOT 启动入口（Linux / systemd 用）。
#
# 干的事只有一件：挑一个 Python，然后在代码目录里跑 phone-bot-v2.py。
#   ① 有 .venv 就用 .venv/bin/python（装了语义记忆依赖的就是这种）
#   ② 没有就用 python3
#
# 为什么要有这个文件：systemd 的 ExecStart 是一个写死的命令，不能"有 venv 就用、没有就不用"。
# 把选择放进脚本里，unit 就永远指向 /opt/mmzbot/run.sh，装不装依赖都不改 unit。
#
# 可覆盖：MMZBOT_PY（指定解释器）、MMZBOT_DATA（数据目录）

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1

if [ -n "${MMZBOT_PY:-}" ]; then
    PY="$MMZBOT_PY"
elif [ -x "$HERE/.venv/bin/python" ]; then
    PY="$HERE/.venv/bin/python"
else
    PY="python3"
fi

exec "$PY" "$HERE/phone-bot-v2.py"
