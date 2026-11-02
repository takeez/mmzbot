---
name: pack-manager
description: 装或卸扩展包、下载消息里的文件（只有主人能装）
---

# 装扩展包

主人说要装/卸某个包，或者要某个文件时用。

调 `package`：
- op=install，source=网址或本地路径 → 只预检；主人同意再加 confirm=true 才真装
- op=remove，name=包名 → 同样先预检，confirm=true 才删
- op=fetch，file=文件 id 或名字 → 下载消息里的文件，返回本地路径

只有主人的命令才能安装插件。预检回执要念给主人，他同意了再继续。

## 只有名字、没有链接

主人只说一个包的名字时，自己找：

1. 用 `search` 搜「<名字> github site:github.com」；
   搜不到就再搜一次，只留「<名字> github」。
2. 从结果里挑官方仓库：域名必须是 github.com 或 gitee.com，
   名字和主人说的最像、star 多的那个。别挑 fork、别挑转载站。
3. 拼下载直链：
   - GitHub：`codeload.github.com/<owner>/<repo>/zip/HEAD`
     （不确定 owner/repo 就先用 `read_url` 打开仓库页，从页面里的地址抄）
   - Gitee：用仓库页「克隆/下载 → 下载 ZIP」给出的那个地址
4. 用 `package` 做预检：`package(op="install", source="<直链>")`
   把回执里的包名、会新增的工具、大小、sha256、校验结果念给主人。
5. 主人同意后，再调一次：`package(op="install", source="<直链>", confirm=true)`
6. 这几种情况别硬试，直接问主人要链接：
   搜不到、仓库是私有的、预检下载失败、超过 5 MB。
