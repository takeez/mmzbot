# 扩展包格式（v1）

本文面向扩展开发者，定义包结构、元数据、工具接口、安装校验和兼容规则。扩展包可独立安装，无需修改主程序。

## 目录

- [包结构](#1-一个扩展包--一个文件夹)
- [`SKILL.md`](#2-skillmd)
- [`tool.py`](#3-toolpy可选)
- [技能解锁流程](#4-解锁流程知识锁不是程序锁)
- [安装与管理](#5-一键安装)
- [六项校验](#6-校验规则安装与加载共用同一份)
- [安全与信任](#7-安全与信任)
- [面板管理](#8-面板扩展页)
- [示例包](#9-示例pc-status第一个真实包)
- [版本兼容](#10-版本与兼容)
- [快速入门](#11-5-分钟写一个包)
- [文件读取限制](#12-取文件packageopfetch的已知限制)


## 1. 一个扩展包 = 一个文件夹

```
capabilities/<包名>/
    SKILL.md          必需。技能正文 + 头部元信息（见 §2）
    tool.py           可选。有它 = 这个包带工具（能真的做事）
    config.json       可选。这个包的配置模板（进仓库；真值写 config.local.json）
    README.md         可选。给人看的安装说明
    assets/           可选。模板/示例等（模型看不到，只有 tool.py 会读）
```

包名 = 文件夹名，只允许 `[a-z0-9][a-z0-9_-]{0,63}`。

> `_` 开头的文件夹**不是包**（`capabilities/_template/` 是给人复制的模板）：
> 加载器跳过它，面板「扩展」页也不列它。

## 2. SKILL.md

```markdown
---
name: pc-status
description: 查电脑上今天干了多少活（查询今日战况）
---

正文（会被模型读到）：
- 什么时候该用
- 参数怎么给（如果带工具）
- 结果怎么解读
- 失败/没数据时怎么办
```

| 字段 | 必需 | 说明 |
|---|---|---|
| `name` | 是 | 技能名，和文件夹名一致；模型用这个名字读技能 |
| `description` | 是 | 一句话（≤ 60 字），**会一直出现在技能目录里**，所以要写"能干什么" |
| `version` | 否 | 语义化版本，仅用于展示与升级判断 |
| `tools` | 否 | 声明本包带的工具名（多个用逗号）；必须和 `tool.py` 里的一致 |

约定：

- 描述**不超过 60 字**，超了截断并在安装时警告。
- 正文**不写"你必须/绝对不要"**（规矩归代码管），写"什么时候用、怎么做"。
- 正文里**不重复**目录那行已经说过的内容。

## 3. tool.py（可选）

```python
NAME = "pc_status"                  # 工具名（模型看到的就是它）
DESC = "查电脑上今天干了多少活"        # 一句话；和普通工具一样短
PARAMS = {                          # JSON Schema
    "type": "object",
    "properties": {
        "what": {"type": "string", "enum": ["today", "now"], "description": "查什么"}
    },
    "required": []
}

def run(args, ctx):
    """返回 dict 或 str。抛异常会被兜住，变成 {"ok": false, "error": ...} 回给模型。"""
    return {"ok": True, "专注": "3 小时"}
```

规则：

| 事 | 约定 |
|---|---|
| 一个包多个工具 | `TOOLS = [{...}, {...}]`（每项同 NAME/DESC/PARAMS/run 四个键） |
| 可见性 | 可选 `available(ctx) -> bool`；返回假时该工具不进请求 |
| 超时 | 默认 20 秒；`TIMEOUT = 60` 可覆盖 |
| 依赖 | 只用标准库。要第三方包 → 写 `requirements.txt`，安装时提示（不自动装） |
| 日志 | 用 `from fgbot import base; base.log(...)`，不要 print |
| 副作用 | 允许（发消息、写文件），但必须在 SKILL.md 里写明 |

## 4. 解锁流程（知识锁，不是程序锁）

```
平时      目录里一行「- pc-status：查电脑上今天干了多少活」
          工具 schema **不发** ✗ 她只是知道有这么个技能

她读技能  skill("pc-status") → 返回 <skill_content name="pc-status">正文</skill_content>
          程序把本包声明的工具的**完整 schema** 加进这场对话后续每一轮的 tools

之后      她可以原生调用 pc_status（参数由 schema 精确约束）
```

约束：

- **会话级**：只在这一场对话里有效，换个会话要重读（知识不跨会话乱串）。
- **上限**：同时最多解锁 6 个包的 schema；超了按最久未用摘掉（再读一次就回来）。
- **位置**：解锁的 schema 追加在工具列表末尾，不重排已有工具（缓存友好）。

## 5. 一键安装

```bash
# 从 zip（别人发来的包）
python phone-bot-v2.py --install-capability 包.zip

# 装仓库里的示例包（pc-status，见 §9）
python phone-bot-v2.py --install-capability examples/packages/pc-status-1.0.0.zip

# 从文件夹（开发时）
python phone-bot-v2.py --install-capability ./pc-status

# 校验但不装
python phone-bot-v2.py --check-capability 包.zip

# 列出 / 卸载
python phone-bot-v2.py --list-capabilities
python phone-bot-v2.py --remove-capability pc-status
```

安装做的事：

```
1 解包到临时目录 → 校验（§6 全部规则）
2 不通过 → 报**具体哪一条**，一个文件都不落地 ✗
3 通过 → 复制到 capabilities/<name>/（已存在则先备份成 <name>.bak-<时间>）
4 跑一次加载器，确认能被发现；失败 → 回滚到第 3 步的备份
5 打一行日志；面板「扩展」页立刻能看到
```

zip 结构必须是**包根目录**（可以外面再套一层同名文件夹，会自适应）：

```
pc-status.zip
└ pc-status/
    SKILL.md
    tool.py
```

## 6. 校验规则（安装与加载共用同一份）

```
① 包名合法、SKILL.md 存在、frontmatter 有 name + description
② name 与文件夹名一致；description ≤ 60 字
③ tool.py 能被 import（语法错误 = 直接拒），且 NAME/DESC/PARAMS/run 齐全、类型对
④ 工具名不撞主程序内置工具、不撞已装包的别的工具
⑤ PARAMS 是合法 JSON Schema（type/properties/required 至少齐全）
⑥ 不出现 eval/exec/os.system 这种（只警告不拒，因为它可能真需要调外部程序）
```

## 7. 安全与信任

```
· 插件和主程序同权限跑 → **只装你信任的包**（README 与安装提示都要写这句）
· 包不能改主程序的提示词、不能改别的包
· 包不能自己申请网络权限 —— 它跑在进程里，有什么权限就用什么权限（写清楚，不假装有沙箱）
```

## 8. 面板「扩展」页

```
一行一个包：名字 / 一句话 / 带不带工具 / 状态（已加载 / 校验失败 / 已停用）/
            来源（仓库自带 / 装的）
  · 停用 / 启用（等价于让它的目录行消失、工具不可解锁）
  · 卸载（仓库自带的包删不掉，只能停用）
  · 安装（上传 zip）
  · **从网址安装**：填地址 → 服务端下载 → 直接显示预检结果 → 「确认安装」
      只认白名单（含子域）：github.com / codeload.github.com /
      raw.githubusercontent.com / objects.githubusercontent.com / gitee.com /
      cdn.jsdelivr.net，以及镜像站 ghproxy.com / gh-proxy.com / ghfast.top /
      hub.gitmirror.com / gh.llkk.cc / mirror.ghproxy.com；
      另外可以在这一页加「额外允许域名」（写进 config.local.json 的
      `capability.extraHosts`，也可以 `--set capability.extraHosts=a.com,b.com`）。
      最大 5 MB、重定向 ≤5 跳、只收 zip、不带 cookie/凭据。
  · 下载失败只给一句人话 + 建议换 codeload.github.com 直链（镜像站经常不通）
报错直接显示校验规则编号 + 一句人话
```

## 9. 示例：pc-status（第一个真实包）

仓库里**不再内置**它：源码在 `examples/packages/pc-status/`，安装包是
`examples/packages/pc-status-1.0.0.zip`（由 `tools/build_example_packages.py`
从源码生成，⛔ 别手搓）：

```bash
python phone-bot-v2.py --install-capability examples/packages/pc-status-1.0.0.zip
```

```
examples/packages/pc-status/
    SKILL.md      说明什么时候用、参数 what=today|now、没数据怎么办
    tool.py       NAME="pc_status"，读本地状态缓存，available = 有心跳
```

装完才会出现 `<数据目录>/capabilities/pc-status/`；**全新部署默认是没装的**
（`capabilities/` 里只有仓库自带的 `pack-manager` 和模板 `_template`）。

这是"从主代码里搬出来"的示范：搬完之后 `pc_status` 不再是内置工具，而是**装上去的扩展**。

## 10. 版本与兼容

```
formatVersion: 1     （写在 SKILL.md 的 frontmatter，可省；省 = 1）
主程序加载时：不认识的 formatVersion > 1 → 报"需要更新的主程序"，不加载 ✗
```

## 11. 5 分钟写一个包

### 最小可跑示例

`capabilities/my-skill/SKILL.md`（正文会被模型读到）：

```markdown
---
name: my-skill
description: 一句话说清这个技能能干什么（不超过 60 字）
version: 1.0.0
formatVersion: 1
tools: my_tool
---

# 什么时候用

他问 XXX 的时候用。

调 `my_tool`，`who` 填他的【消息前缀】（不填 = 当前说话的人）。
返回 `ok` 和几个中文键，话自己组织。

`ok` 为 false 时 `error` 里是现成原因，照实说，别编。
```

`capabilities/my-skill/tool.py`（逐行注释）：

```python
# 工具名：英文/数字/下划线，不能以数字开头；⛔ 不能和内置工具重名（now / memory …）
NAME = "my_tool"

# 一句话「什么时候用」。模型看到的就是这一句，和普通工具一样短。
DESC = "一句话说清这个工具能干什么"

# 合法 JSON Schema：type / properties / required 三个键缺一不可。
PARAMS = {
    "type": "object",
    "properties": {
        "who": {"type": "string", "description": "他的【消息前缀】；不填=当前说话的人"},
    },
    "required": [],          # 没有必填参数就写 []
}


def available(ctx=None):
    # 可选。返回假 = 这个工具**不进**给模型的工具目录（技能目录那行还在）。
    # ctx 和 run() 拿到的是同一个：user_id / group_id / is_group ……
    # 抛异常也当"不可见"，不会炸对话。
    return True


def run(args, ctx):
    # 真正干活。返回 dict（推荐）或 str；抛异常会被兜住成
    # {"ok": false, "error": "这个工具出错了：…"}，所以能预料的失败自己回人话。
    # 超时默认 20 秒；要久一点就在模块级写 TIMEOUT = 60。
    who = str((args or {}).get("who") or "").strip()
    qq = str((ctx or {}).get("user_id") or "")
    if not qq:
        return {"ok": False, "error": "不知道当前说话的人是谁"}
    return {"ok": True, "QQ": qq, "问的是": who or qq}
```

### 三步上手

1. **建文件夹**：`capabilities/my-skill/`（名字只能小写字母 / 数字 / `-` / `_`）。
   最快的起点是把 `capabilities/_template/` 整个复制过去再改名 —— 它前面的 `_`
   让加载器**跳过**模板本身，所以模板不会被当成一个包。
2. **写两个文件**：`SKILL.md`（frontmatter 的 `name` 必须和文件夹名**一样**）
   和 `tool.py`（带工具才要；只有说明就不写）。
3. **放进 `capabilities/`**：不用重启、不用装 —— 下一轮消息她的【技能目录】里
   就会多一行「- my-skill：一句话」；她读一次技能，`my_tool` 的 schema 才进请求。

想给别人：把文件夹压成 zip（**外面套一层同名文件夹**），用
`--install-capability` 或面板「扩展 → 安装（上传 zip）」装。

### 常见错误对照表（六条校验各对应"怎么改"）

| 报错 | 怎么改 |
|---|---|
| 第 ① 条：包名不合法 / 没有 SKILL.md / 缺 name 或 description | 文件夹名改成 `^[a-z0-9][a-z0-9_-]{0,63}$`；`SKILL.md` 第一行必须是 `---`，紧跟着写 `name:` 和 `description:`，再用一行 `---` 收尾 |
| 第 ② 条：name 和文件夹名不一致 / description 超 60 字 | 两边写成同一个名字；一句话删到 60 字以内（目录里只露这一句，写"能干什么"） |
| 第 ③ 条：tool.py 语法错误 / 四件套不齐 / 工具名不合法 / tools 不一致 | 先 `python -c "import tool"` 看语法；`NAME` / `DESC` / `PARAMS` / `run` 四件都要有；`NAME` 用 `[A-Za-z_][A-Za-z0-9_]{0,63}`；frontmatter 的 `tools` 要么不写，写了就和 `tool.py` 里的工具名一模一样 |
| 第 ④ 条：工具名撞内置 / 撞已装的包 | 换个名字（`now`、`memory`、`search`、`skill`、`end_turn`……都是内置的）；两个包装了同名工具也会撞，卸载/改名一个 |
| 第 ⑤ 条：PARAMS 不是合法 JSON Schema | 顶层 `"type": "object"`、`"properties": {...}`、`"required": [...]` 三个都要有；`required` 里只能写 `properties` 里定义过的参数名 |
| 第 ⑥ 条：出现 eval / exec / os.system | **只警告不拒**（有些包真的要调外部程序）；自己看一眼再装 |

### 一句话

**一个包 = 一个文件夹；卸载就删这个文件夹**（数据目录里那个）。
仓库自带的包（比如 `pack-manager`）是代码，删不掉 —— 不想用就停用。

## 12. 取文件（`package(op="fetch")`）的已知限制

NapCat 的版本不同，取文件的接口也不一样。实现里**按顺序挨个试**：

```
① get_group_file        （群）
② get_file
③ get_group_file_url    （群）
④ get_private_file_url
```

真机实测（2026-10-31，QQ `3.2.20-40990` + NapCat 4.x）：

| 接口 | 结果 |
|---|---|
| `get_group_file` | `不支持的Api get_group_file` |
| `get_file` | 可用（`file not found` 是参数问题，接口在） |
| `get_group_file_url` / `get_private_file_url` | `packetBackend不可用` |

`packetBackend` 是 NapCat 的“原生增强”后端，它按 QQ 的内部结构写死，**只支持特定 build 区间**
（官方文档：Linux arm64 → `28498 ~ 36580`）。QQ 比这个新时它就不可用，于是文件直链类接口全失败。

**结论**：群文件下载能不能用，取决于你那台机器的 QQ 版本。用不了时，`fetch` 会回一句人话
（“拿不到这个文件”），不影响其他功能。
