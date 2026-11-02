# MMZBOT Docker 镜像：构建时从 requirements.txt 安装向量语义记忆所需的 Python 依赖。
# 模型文件在容器启动后下载到 /data 数据卷，不烘进镜像。基础镜像为 Python 3.11-slim。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MMZBOT_DATA=/data \
    MMZBOT_TZ=Asia/Shanghai

WORKDIR /app

# 只拷运行需要的东西（代码 + 出厂配置模板 + 人设初版 + 自带的扩展包示例）
COPY phone-bot-v2.py /app/phone-bot-v2.py
COPY config.json /app/config.json
COPY personality.md /app/personality.md
COPY fgbot /app/fgbot
COPY capabilities /app/capabilities
COPY examples /app/examples
# 语义记忆的运行时依赖（磁盘上的模型不烘进镜像，启动后下到数据卷）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY tools/fetch_model.py /app/tools/fetch_model.py
COPY scripts/linux/run.sh /app/run.sh
RUN chmod +x /app/run.sh
COPY docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /data

# 数据卷：config.json / local-config.json / memory.json / reminders.json /
# settings.json / plan-*.json / bot.log / personality.md 全在 /data 里
VOLUME ["/data"]

EXPOSE 17383

# 健康检查使用标准库建立 TCP 连接（容器里没有 curl；
# /status 无凭据会返回 403，因此不用 HTTP 状态码判断进程是否存活）。
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import socket,sys; s=socket.socket(); s.settimeout(4); sys.exit(0 if s.connect_ex(('127.0.0.1',17383))==0 else 1)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
