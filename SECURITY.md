# 安全说明

## 报告问题

用 GitHub 的 [Private vulnerability reporting](https://github.com/takeez/mmzbot/security/advisories/new) 提交；
不要开公开 Issue。请写清复现步骤、影响（能不能读到令牌 / 能不能执行代码）、版本或 commit。
修好并发布之前，请不要公开细节。

## 装错包了怎么办

扩展包的 `tool.py` 在独立子进程里跑（有超时和资源上限），但**没有沙箱**：
它能读数据目录、能联网、能通过 `from fgbot import im` 直接发消息。

如果装了来路不明的包：

1. 面板「扩展」页卸载它（或 `--cap-remove <名字>`）；
2. 换掉 `bot.token` / `bot.napcatToken`（两者都是凭据）；
3. 检查 `bot.log` 里有没有陌生的发送记录。
