# 扩展能力

机魂小悦通过能力包扩展功能，无需修改主程序。完整格式、校验规则和开发示例见[扩展包格式规范](capability-format.md)。

## 包结构

```text
capabilities/<包名>/
├── SKILL.md       必需：说明能力用途及使用方式
├── tool.py        可选：实现可调用的工具
├── config.json    可选：配置模板
└── README.md      可选：面向使用者的说明
```

模型平时只看到技能名称和简介。读取 `SKILL.md` 后，对应扩展的工具 schema 才会加入当前对话；同时最多解锁 6 个包，超出时移除最久未使用的包。未安装或未解锁的扩展工具不会进入工具目录。

## 安装与管理

扩展包可以通过命令行、面板上传 ZIP、允许来源的网址安装，也可以由内置的 `pack-manager` 扩展管理。安装前会校验包结构、入口、工具函数、名称、版本和权限声明。

```bash
python phone-bot-v2.py --check-capability package.zip
python phone-bot-v2.py --install-capability package.zip
python phone-bot-v2.py --list-capabilities
python phone-bot-v2.py --remove-capability <包名>
```

也可以从仓库安装示例包：

```bash
python phone-bot-v2.py --install-capability examples/packages/pc-status-1.0.0.zip
```

该示例默认不安装。扩展包包含 Python 工具代码，与主程序以相同权限运行；项目不提供代码沙箱。请只安装可信来源的扩展，并在安装前审阅代码和所需权限。

## 开发资源

- [扩展包格式规范](capability-format.md)：目录结构、元数据、工具接口、校验规则和兼容性。
- [扩展开发模板](../capabilities/_template/README.md)：创建最小扩展包。
- [示例扩展包](../examples/packages/README.md)：源码、安装包及构建命令。
- [电脑状态上报协议](pc-status-protocol.md)：`pc-status` 示例包的数据格式。
