---
name: pc-status
description: 查电脑上今天干了多少活、在忙什么
version: 1.0.0
formatVersion: 1
tools: pc_status
---

# 战况

他问今天干了多少活、在忙什么、摸了多久鱼时用。

调 `pc_status`，`who` 填他的【消息前缀】（不填 = 当前说话的人）。返回 `日期` `专注` `摸鱼` `摸鱼来源` `现在` `数据时间` 六个键，话自己组织。

`ok` 为 false 时 `error` 里是现成原因（没开机 / 没登记 / 不在上报时段），照实说，别编数字。
