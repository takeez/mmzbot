#!/data/data/com.termux/files/usr/bin/bash
# MMZBOT —— 「进容器跑一条命令」的入口（Termux 侧）。
#
# 用法（由 fg-bot-v2-start.sh / mmzbot-watchdog.sh 调用）：
#     bash ~/runinc.sh "cd /root/mmzbot && MMZBOT_DATA=/root/mmzbot exec python3 phone-bot-v2.py"
#
# 它会找到 proot 的 rootfs，在里面执行你给的那条命令。
#
# 可覆盖的环境变量：
#     MMZBOT_ROOTFS         直接指定 rootfs 目录（最优先）
#     MMZBOT_PROOT_DISTRO   proot-distro 的发行版别名，默认 debian
#     MMZBOT_PROOT          proot 可执行文件，默认 proot（Termux 里 pkg install proot）
#
# ⚠️ 找 rootfs 的顺序：
#     ① $MMZBOT_ROOTFS
#     ② proot-distro 的安装位置：$PREFIX/var/lib/proot-distro/installed-rootfs/<别名>
#     ③ 手工装解压出来的常见名字：~/<别名>、~/bookworm-arm64、~/debian
#   全都找不到就报错退出（不静默降级 —— 静默降级会让人以为"起来了其实没进容器"）。

set -u

CMD="${1:-/bin/bash}"
PD="${MMZBOT_PROOT_DISTRO:-debian}"
PROOT_BIN="${MMZBOT_PROOT:-proot}"

if ! command -v "$PROOT_BIN" >/dev/null 2>&1; then
    echo "✗ 找不到 $PROOT_BIN（Termux 里先跑：pkg install proot）" >&2
    exit 1
fi

ROOTFS="${MMZBOT_ROOTFS:-}"
if [ -z "$ROOTFS" ]; then
    for c in \
        "${PREFIX:-/data/data/com.termux/files/usr}/var/lib/proot-distro/installed-rootfs/$PD" \
        "$HOME/$PD" \
        "$HOME/bookworm-arm64" \
        "$HOME/debian"
    do
        if [ -d "$c" ]; then ROOTFS="$c"; break; fi
    done
fi

if [ -z "$ROOTFS" ] || [ ! -d "$ROOTFS" ]; then
    echo "✗ 找不到容器 rootfs（用 MMZBOT_ROOTFS=/路径 指定；proot-distro 装的话别名默认 $PD）" >&2
    exit 1
fi

BINDS=""
for d in /dev /proc /sys; do
    [ -e "$d" ] && BINDS="$BINDS --bind=$d"
done

# HOME 绑进去（Termux 家目录），这样容器里能访问 /data/data/com.termux/files/home 下的东西
if [ -d "$HOME" ]; then
    BINDS="$BINDS --bind=$HOME"
fi

exec "$PROOT_BIN" \
    --kill-on-exit --link2symlink -0 \
    --rootfs="$ROOTFS" --cwd=/root \
    $BINDS \
    /usr/bin/env -i \
        HOME=/root \
        LANG=zh_CN.UTF-8 \
        TERM=xterm-256color \
        PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    /bin/bash -lc "$CMD"
