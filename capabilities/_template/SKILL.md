---
name: my-skill
description: 一句话说清这个技能能干什么（不超过 60 字）
version: 1.0.0
formatVersion: 1
tools: my_tool
---

# 什么时候用

（这里写：什么时候该用、参数怎么给、结果怎么读、失败/没数据时怎么办。
不写"你必须 / 绝对不要"—— 规矩归代码管。）

调 `my_tool`，参数 `who` 填他的【消息前缀】（不填 = 当前说话的人）。
返回 `ok` 和几个中文键，话自己组织。

`ok` 为 false 时 `error` 里是现成原因，照实说，别编。
