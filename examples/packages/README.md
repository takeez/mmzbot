# 示例扩展包

本目录包含示例扩展包的源码；同名的 `<包名>-<版本>.zip` 是可直接安装的发布包。

| 包 | 说明 |
|---|---|
| `pc-status/` | 电脑上报状态心跳后查询当日统计。默认不安装。 |

在仓库根目录安装：

```bash
python phone-bot-v2.py --install-capability examples/packages/pc-status-1.0.0.zip
```

修改源码后，使用构建脚本重新生成 ZIP，并可用 `--check` 核对产物：

```bash
python tools/build_example_packages.py
python tools/build_example_packages.py --check
```

ZIP 使用固定时间戳和文件顺序生成；相同源码会得到逐字节一致的文件，自检会验证这一点。
