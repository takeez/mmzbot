#!/data/data/com.termux/files/usr/bin/bash
# MMZBOT —— 手机（Termux + proot Debian）上的启动入口。
#
# 她跑在 Debian 容器里（和 NapCat 同一个网络命名空间），所以 NapCat 的上报地址
# 写 http://127.0.0.1:17383/ 就能直接投给她。
#
# 由 mmzbot-watchdog.sh（可选）守护：进程不在了就重新拉起来。
#
# ⚠️ 这个脚本里**不再写死任何路径**（2026-10-31 改的）。全部可以用环境变量覆盖：
#
#     MMZBOT_HOME    Termux 家目录                默认 $HOME
#     MMZBOT_DIR     **容器里**的代码目录           默认 /root/mmzbot
#     MMZBOT_DATA    数据目录（容器里）             默认 = MMZBOT_DIR
#     MMZBOT_PY      容器里的解释器                 默认 python3
#     MMZBOT_RUNINC  进容器的入口脚本（Termux 侧）   默认 $MMZBOT_HOME/runinc.sh
#     MMZBOT_STDOUT  stdout/stderr 落哪个文件       默认 $MMZBOT_HOME/mmzbot-stdout.log
#
# 例：老手机上装在 /root/fg-bot-v2：
#     MMZBOT_DIR=/root/fg-bot-v2 MMZBOT_DATA=/root/fg-bot-v2 bash ~/fg-bot-v2-start.sh
#
# stdout/stderr 一律落到日志文件 —— 上一次「明明处理了却没回复」就是因为
# traceback 打进了被丢弃的 stdout，白找半天。

set -u

MMZBOT_HOME="${MMZBOT_HOME:-$HOME}"
MMZBOT_DIR="${MMZBOT_DIR:-/root/mmzbot}"
MMZBOT_DATA="${MMZBOT_DATA:-$MMZBOT_DIR}"
# ⚠ 2026-11-01：有 .venv 就用它（装了语义记忆依赖的就是这种），否则 python3
if [ -n "${MMZBOT_PY:-}" ]; then
    :
elif [ -x "$MMZBOT_DIR/.venv/bin/python" ]; then
    MMZBOT_PY="$MMZBOT_DIR/.venv/bin/python"
else
    MMZBOT_PY="python3"
fi
MMZBOT_RUNINC="${MMZBOT_RUNINC:-$MMZBOT_HOME/runinc.sh}"
MMZBOT_STDOUT="${MMZBOT_STDOUT:-$MMZBOT_HOME/mmzbot-stdout.log}"
MMZBOT_SCRIPT="${MMZBOT_SCRIPT:-phone-bot-v2.py}"

export MMZBOT_DATA
export MMZBOT_TZ="${MMZBOT_TZ:-Asia/Shanghai}"

# 太大就轮转，免得把手机塞满
if [ -f "$MMZBOT_STDOUT" ] && [ "$(wc -c <"$MMZBOT_STDOUT" 2>/dev/null || echo 0)" -gt 1048576 ]; then
    mv -f "$MMZBOT_STDOUT" "$MMZBOT_STDOUT.1"
fi

RUN_CMD="cd '$MMZBOT_DIR' && MMZBOT_DATA='$MMZBOT_DATA' exec '$MMZBOT_PY' '$MMZBOT_SCRIPT'"

if [ -f "$MMZBOT_RUNINC" ]; then
    # 正常的手机部署：Termux 侧 → proot 容器里
    exec bash "$MMZBOT_RUNINC" "$RUN_CMD" >>"$MMZBOT_STDOUT" 2>&1
fi

# 没找到 runinc.sh：如果这个脚本本身就是在容器里跑（或者 Termux 里直接装了 Python），
# 直接启动 —— 总比什么都不做、也不报错要好。
if [ ! -d "$MMZBOT_DIR" ]; then
    echo "$(date '+%F %T') ✗ 代码目录不存在：$MMZBOT_DIR（用 MMZBOT_DIR 指过去）" >>"$MMZBOT_STDOUT"
    echo "✗ 代码目录不存在：$MMZBOT_DIR" >&2
    exit 1
fi
cd "$MMZBOT_DIR" || exit 1
exec "$MMZBOT_PY" phone-bot-v2.py >>"$MMZBOT_STDOUT" 2>&1
