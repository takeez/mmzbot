#!/bin/sh
# 容器入口：保证数据卷里有出厂配置 / 人设初版，然后启动她。
#
# ⚠️ 只做"第一次才会有"的事，之后**一个字节都不碰**用户的数据：
#   · /data/config.json 不存在 → 把镜像里的 config.json 复制过去（出厂模板）
#   · /data/personality.md 不存在 → 把人设初版复制过去
#   · /data/local-config.json 不存在 **且** 设了 MMZBOT_ALLOW_IPS
#     → 写一份面板来源白名单（Docker 端口映射的来源是网桥地址，不在白名单里会被 403）
#
# 数据目录、时区都从环境变量来（compose 里已经设好）。
set -eu

DATA="${MMZBOT_DATA:-/data}"
mkdir -p "$DATA"

if [ ! -f "$DATA/config.json" ]; then
    cp /app/config.json "$DATA/config.json"
    echo "==> 初始化 $DATA/config.json（出厂模板，占位值）"
fi

if [ ! -f "$DATA/personality.md" ] && [ -f /app/personality.md ]; then
    cp /app/personality.md "$DATA/personality.md"
    echo "==> 初始化 $DATA/personality.md（人设初版；以后改这个文件）"
fi

if [ ! -f "$DATA/local-config.json" ] && [ -n "${MMZBOT_ALLOW_IPS:-}" ]; then
    python3 - "$DATA/local-config.json" <<'PY'
import json, os, sys
ips = [x.strip() for x in os.environ.get("MMZBOT_ALLOW_IPS", "").split(",") if x.strip()]
if ips:
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump({"bot": {"control": {"lanEnabled": True, "allowIps": ips}}},
                  f, ensure_ascii=False, indent=2)
    print("==> 初始化 %s（面板来源白名单 = %s）" % (sys.argv[1], ", ".join(ips)))
PY
fi

cd /app
exec python3 phone-bot-v2.py
