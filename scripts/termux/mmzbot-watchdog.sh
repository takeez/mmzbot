#!/data/data/com.termux/files/usr/bin/bash
# MMZBOT 看门狗（可选）—— **只守 MMZBOT，绝不碰 NapCat**。
#
# 用法（Termux 里）：
#     nohup bash ~/mmzbot-watchdog.sh >>~/mmzbot-watchdog.log 2>&1 &
#
# 或者放进 ~/.bashrc / Termux:Boot，开机自己起。
#
# 判断"她还在不在"**只看端口**：/dev/tcp/127.0.0.1/$MMZBOT_PORT
#   ⚠ 2026-11-01 改的：以前还要求 `pgrep -f phone-bot-v2.py`，但同一台机器上跑两个实例时
#     两边命令行一模一样，pgrep 分不出谁是谁 —— 现在只认端口，端口通就算她活着。
#
# 可配：
#     MMZBOT_WATCH_INTERVAL  多少秒看一次（默认 90）
#     MMZBOT_PORT            端口（默认 17383）
#     MMZBOT_START           启动脚本（默认 $HOME/fg-bot-v2-start.sh）
#     MMZBOT_WATCH_LOG       看门狗自己的日志（默认 $HOME/mmzbot-watchdog.log）
#     MMZBOT_RESTART_FILE    面板「重启她」写的那个文件（默认 $HOME/bookworm-arm64/root/mmzbot/restart.txt）
#                            ⚠ 2026-11-01加：以前只有老看门狗认这个文件，换新后面板重启没人接了
#
# ⚠️ 连续失败之间也等一个间隔，不会疯狂重启（那是把手机烧热的最快办法）。

set -u

INTERVAL="${MMZBOT_WATCH_INTERVAL:-90}"
PORT="${MMZBOT_PORT:-17383}"
# 启动脚本：先用 MMZBOT_START；没给就找常见名字
if [ -n "${MMZBOT_START:-}" ]; then
    START="$MMZBOT_START"
elif [ -f "$HOME/mmzbot-start.sh" ]; then
    START="$HOME/mmzbot-start.sh"
else
    START="$HOME/fg-bot-v2-start.sh"
fi
WLOG="${MMZBOT_WATCH_LOG:-$HOME/mmzbot-watchdog.log}"
RESTART_FILE="${MMZBOT_RESTART_FILE:-$HOME/bookworm-arm64/root/mmzbot/restart.txt}"

log() { echo "$(date '+%F %T') $*" >>"$WLOG" 2>/dev/null; }

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }

alive() { port_open; }

log "看门狗起来了（每 ${INTERVAL}s 看一次，端口 $PORT，启动脚本 $START）"

while :; do
    # 面板/App 点了「重启她」→ 她写一个 restart.txt，这里代办
    if [ -f "$RESTART_FILE" ]; then
        log "收到重启请求（$RESTART_FILE）—— 重启她"
        rm -f "$RESTART_FILE" 2>/dev/null
        pkill -f 'phone-bot-v2.py' 2>/dev/null
        sleep 2
        if [ -f "$START" ]; then
            bash "$START" >>"$WLOG" 2>&1
        else
            log "✗ 启动脚本不存在：$START（用 MMZBOT_START 指过去）"
        fi
        sleep "$INTERVAL"
        continue
    fi
    if ! alive; then
        log "端口 $PORT 不通 —— 拉起她"
        if [ -f "$START" ]; then
            bash "$START" >>"$WLOG" 2>&1
        else
            log "✗ 启动脚本不存在：$START（用 MMZBOT_START 指过去）"
        fi
    fi
    sleep "$INTERVAL"
done
