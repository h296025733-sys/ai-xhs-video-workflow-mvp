# ai-xhs-video-workflow-mvp

> 面向跨境电商短视频素材处理的小红书视频采集、BGM 替换、批量处理与 OpenClaw / 企业 IM 调度工作流 MVP。

这个项目解决的是一个很具体、很接地气的问题：

运营同事丢过来一个小红书作品链接，或者一批本地视频素材，希望快速换成适合日韩 TikTok / 服装穿搭场景的 BGM，然后输出一批能复核、能交付、命名清楚的视频文件。

所以它不是“炫技型 AI 项目”，也不是完整商业系统。它更像一个本地短视频处理工作台：把小红书链接、本地视频、BGM、FFmpeg、OpenClaw、钉钉/飞书入口这些零散工具串起来，让一件本来要来回切软件的事，尽量变成一句话或一个命令就能跑的流程。ヽ(・∀・)ﾉ

---

## 项目背景：为什么会有这个东西？

跨境电商做短视频时，经常不是“缺一个算法”，而是缺一个顺手的流程。

比如一条很普通的需求：

```text
找几条小红书穿搭参考视频
换成更适合日韩 TikTok 的 BGM
每条都生成清楚命名的本地文件
发给运营挑选
```

如果全手工做，通常要在浏览器、下载器、视频工具、文件夹、聊天软件之间来回切。这个项目就是把这些小步骤尽量收拢到一个本地工作流里。

我希望它看起来不是“论文项目”，而是一个真的能被运营场景使用、能继续接 OpenClaw/钉钉/飞书的工具雏形。

---

## 先看效果：它能帮你做什么？

你可以把它当成一个“小红书素材转 TikTok 本地化素材”的半自动工具箱：

```text
小红书作品链接 / 作者主页 / 本地视频
        ↓
导入或整理成本地素材
        ↓
选择 BGM：本地上传 / 本地随机 / 在线搜索 / 指定歌曲
        ↓
FFmpeg 替换音轨
        ↓
按标题、作品 ID、BGM 版本输出成品
        ↓
返回中文结果摘要，方便运营复核
```

典型例子：

- “这个小红书视频换成韩国 TikTok 穿搭 BGM。”
- “这 5 条视频都保留画面，去掉原声，换成日系 OOTD 音乐。”
- “先 dry-run 看看能不能抓到作品，不要直接生成。”
- “每条视频生成 3 个不同 BGM 版本，方便挑。”

---

## 适合谁用？

✨ 适合：

- 做跨境电商短视频素材整理的人。
- 做 TikTok / Reels / Shorts 素材本地化的人。
- 想把“小红书参考素材 -> 本地成品视频”流程自动化的人。
- 想研究 OpenClaw 怎么接本地脚本、FastAPI、企业 IM 的人。
- 想看一个真实业务场景下 AI 应用落地 MVP 的人。

⚠️ 不适合：

- 想要开箱即用的商业 SaaS。
- 想要全自动发布 TikTok。
- 想要绕过平台规则批量采集内容。
- 想要一个深度算法/推荐算法项目。

---

## 核心功能一览

| 能力 | 当前状态 | 说明 |
| --- | --- | --- |
| 本地视频换 BGM | ✅ 可用 | 最稳的测试路线，适合先跑通项目 |
| 本地 BGM 上传/选择 | ✅ 可用 | 页面里可以上传音频，CLI 可走本地随机 |
| FFmpeg 音轨替换 | ✅ 可用 | 支持替换原声、保留原声、指定 BGM 起始秒 |
| 批量任务 | ✅ 可用 | 支持多视频、多链接、dry-run |
| 单条小红书作品链接 | 🧩 可接入 | 需要配置 XHS-Downloader 或其它合法解析方式 |
| 作者主页最近 N 条 | 🧩 预留 | 通常需要登录态/Cookie/MCP/浏览器辅助 |
| OpenClaw 自然语言入口 | ✅ 有脚本 | 把中文消息解析成 API/CLI 参数 |
| 钉钉/飞书/企业 IM | 🧩 有示例 | 公开版只给接入方式，不放真实 token |
| 自动发布 TikTok | ❌ 未做 | 当前只负责本地处理，不负责发布 |

---

## 最快跑通：先不碰小红书，只验证本地视频换 BGM

如果你只是想看看项目能不能跑，建议先走这条路线，最稳。

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 确认 FFmpeg 可用

```powershell
ffmpeg -version
ffprobe -version
```

如果这里报错，先安装 FFmpeg，并把 `ffmpeg.exe`、`ffprobe.exe` 加到 PATH。

### 3. 启动服务

```powershell
.\scripts\run_api.ps1
```

也可以手动启动：

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8004 --reload
```

### 4. 打开本地页面

```text
http://127.0.0.1:8004/quick-bgm/page
```

然后按页面操作：

1. 上传一个本地 `.mp4` 视频。
2. 上传一个本地 `.mp3` / `.m4a` / `.wav` BGM。
3. 选择是否保留原声。
4. 设置 BGM 从第几秒开始。
5. 点击生成，查看输出视频。

如果这一步跑通，说明 FastAPI + FFmpeg + 本地文件处理链路基本正常。

---

## 常用玩法 1：用命令行处理本地视频

适合你想把它接到脚本、OpenClaw 或企业 IM 之前，先自己手动试一下。

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --video-path "D:\workspace\demo\input.mp4" `
  --bgm-strategy local_random `
  --run
```

说明：

- `--video-path`：本地视频路径，可以传多次。
- `--bgm-strategy local_random`：从本地 BGM 库随机选一个。
- `--run`：创建任务后直接执行。

如果你想先看看任务会怎么创建，不想真的生成视频：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --video-path "D:\workspace\demo\input.mp4" `
  --bgm-strategy local_random `
  --dry-run
```

---

## 常用玩法 2：处理单条小红书作品链接

小红书链接处理依赖外部下载/解析能力。这个公开版不会内置你的 cookie、登录态或下载器配置。

如果你已经在本地跑了 XHS-Downloader API，并且它能把小红书作品解析成本地视频，可以这样配置：

```powershell
$env:XHS_DOWNLOAD_MODE = "api"
$env:XHS_DOWNLOADER_API_BASE_URL = "http://127.0.0.1:5556"
```

然后执行：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --note-url "https://www.xiaohongshu.com/explore/YOUR_NOTE_ID" `
  --bgm-strategy search_download `
  --bgm-query "韩国 TikTok OOTD 热门歌 2026" `
  --start 20 `
  --run
```

参数解释：

- `--note-url`：小红书作品链接。
- `--bgm-strategy search_download`：按关键词搜索下载 BGM。
- `--bgm-query`：BGM 搜索词，可以写得像人话一点。
- `--start 20`：从 BGM 的第 20 秒开始截取。

如果小红书解析失败，通常不是 FFmpeg 的问题，而是下面这些原因：

- XHS-Downloader 没启动。
- 小红书链接需要登录态。
- cookie 失效。
- 当前作品不是视频。
- 小红书侧请求被限制。

这时可以先人工下载视频，再走“本地视频换 BGM”的路线。

---

## 常用玩法 3：OpenClaw / 钉钉 / 飞书自然语言入口

这个项目里我比较看重的一点，是让工具能听懂类似运营同事的话。

比如：

```text
把这个小红书作品换成日本 TikTok 穿搭热门 BGM，从第 18 秒开始，先不要保留原声：
https://www.xiaohongshu.com/explore/YOUR_NOTE_ID
```

可以交给包装脚本：

```powershell
.\.venv\Scripts\python.exe .\scripts\openclaw_quick_bgm.py `
  --api-base http://127.0.0.1:8004 `
  --message "把这个小红书作品换成日本 TikTok 穿搭热门 BGM，从第 18 秒开始：https://www.xiaohongshu.com/explore/YOUR_NOTE_ID"
```

脚本会尝试识别：

- 小红书链接。
- BGM 描述。
- 是否 dry-run。
- 是否保留原声。
- BGM 起始秒数。
- 是否是作者主页。

企业 IM 的思路也很简单：

```text
钉钉/飞书收到消息
        ↓
写入 UTF-8 临时文件
        ↓
PowerShell 调用脚本
        ↓
脚本返回中文摘要
        ↓
IM 只回复结果，不暴露日志和 cookie
```

示例脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_xhs_author_from_dingtalk.ps1 `
  -MessageFile "D:\workspace\demo\message.txt"
```

---

## 作者主页批量处理说明

作者主页最近 N 条是最容易踩坑的部分。

原因很现实：小红书作者主页通常需要登录态、Cookie、MCP、浏览器脚本或外部下载器支持。这个公开版不会内置任何真实 cookie，也不会把私人 OpenClaw 工作区放进来。

可以先 dry-run：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --creator-home-url "https://www.xiaohongshu.com/user/profile/YOUR_CREATOR_ID" `
  --limit 5 `
  --dry-run
```

如果拿不到作品列表，建议先用外部工具提取具体作品链接，再批量传入：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --note-urls-file "D:\workspace\demo\xhs_links.txt" `
  --bgm-strategy search_download `
  --bgm-query "日韩 TikTok fashion outfit 2026" `
  --run
```

`xhs_links.txt` 示例：

```text
https://www.xiaohongshu.com/explore/YOUR_NOTE_ID_1
https://www.xiaohongshu.com/explore/YOUR_NOTE_ID_2
https://www.xiaohongshu.com/explore/YOUR_NOTE_ID_3
```

---

## 输出文件长什么样？

建议输出放在本地 `outputs/`，这个目录默认不会上传 GitHub。

```text
outputs/
  小红书单条/
    简单随意__换BGM.mp4
  作者主页批量/
    01_视频成品/
      开始期待夏天啦__4a85__BGM01.mp4
      开始期待夏天啦__4c46__BGM02.mp4
    02_封面/
      开始期待夏天啦__4a85__cover_frame.jpg
  reports/
    xhs_direct_v2_report_YYYYMMDD.json
```

命名里带标题、作品 ID 片段或 BGM 版本，是为了避免同标题视频互相覆盖。

---

## 项目结构

```text
ai-xhs-video-workflow-mvp/
  README.md
  .env.example
  requirements.txt
  app/
    main.py                         # FastAPI 入口
    quick_bgm/
      router.py                     # quick-bgm API 和页面
      media.py                      # FFmpeg / ffprobe 处理
      store.py                      # 本地任务和 BGM 库记录
      xhs_adapter.py                # 单条小红书链接适配
      xhs_creator_importer.py       # 作者主页/作品预览适配
  scripts/
    quick_bgm_automation.py         # 通用 CLI
    openclaw_quick_bgm.py           # 自然语言消息包装
    openclaw_xhs_author_direct_v2.py
    run_xhs_author_from_dingtalk.ps1
  config/
    *.example.json                  # 示例配置
  docs/
    快速开始.md
    架构说明.md
    OpenClaw接入说明.md
    安全与隐私说明.md
    常见问题.md
```

---

## 示例配置：配置文件怎么填？

先复制：

```powershell
Copy-Item .env.example .env
```

常用配置：

```text
API_BASE_URL=http://127.0.0.1:8004
XHS_DOWNLOAD_MODE=disabled
XHS_DOWNLOADER_API_BASE_URL=http://127.0.0.1:5556
XHS_DOWNLOADER_PROJECT_DIR=D:\workspace\your-XHS-Downloader
VIDEO_DELIVERY_DIR=D:\workspace\your-project\outputs
```

注意：

- `.env` 不要提交。
- `XHS_COOKIE` 不要写进公开仓库。
- OpenClaw、钉钉、飞书的真实 token 只放你自己的私有环境里。

---

## 技术栈

| 类型 | 使用内容 |
| --- | --- |
| 后端接口 | FastAPI / Uvicorn |
| 视频处理 | FFmpeg / ffprobe |
| 脚本语言 | Python / PowerShell |
| 小红书适配 | XHS-Downloader，可选 |
| 自动化入口 | OpenClaw，可选 |
| 企业 IM 扩展 | 钉钉 / 飞书 / 企业微信，可选 |

---

## 这个项目现在做到了什么？

✅ 已有：

- 本地视频上传和 BGM 替换。
- BGM 库管理。
- 单条小红书作品链接适配接口。
- 批量任务创建和执行。
- dry-run 预览。
- BGM 起始秒数。
- 中文错误提示。
- OpenClaw/企业 IM 包装脚本。
- 示例配置和安全排除规则。

🧩 预留但不保证开箱即用：

- 作者主页最近 N 条自动抓取。
- XHS-Downloader API/CLI 深度适配。
- MCP / 浏览器登录态链路。
- n8n、剪映草稿、自动发布。

---

## 当前限制

这部分我写直白一点，免得别人 clone 下来以后误会：

- 小红书链接不是无脑可抓，很多时候会卡在登录态、风控、Cookie 或外部下载器。
- 作者主页最近 N 条不是公开版的稳定能力，需要你自己配置合法的采集/解析链路。
- BGM 在线搜索依赖外部来源，失败很正常，建议先用本地上传 BGM 跑通。
- 项目没有做 TikTok 自动发布，也没有接商业后台。
- 它是 MVP，重点是工作流打通，不是高并发后端系统。

---

## 安全边界

这个公开仓库特意不包含：

- 真实 API key。
- 真实 token / cookie / Authorization。
- 小红书登录态。
- OpenClaw 私人 workspace。
- 钉钉 / 飞书真实配置。
- 真实视频素材、BGM、封面、成品视频。
- 日志、缓存、浏览器 profile。

相关示例都用 `YOUR_..._HERE` 占位符。

---

## 常见问题

### Q：为什么我输入小红书链接不能直接下载？

公开版不带登录态，也不内置下载器。你需要先配置 XHS-Downloader 或其它合法的本地解析方式。最稳的测试方式是先上传本地视频。

### Q：为什么 BGM 搜索失败？

可能是网络、来源不可用、关键词太泛，或者外部下载器不可用。你可以先上传一个本地 BGM，再用 `local_random` 或页面手动选择。

### Q：这是 AI 项目吗？

它更偏 AI 应用落地和自动化调度。OpenClaw 负责理解自然语言和调度脚本，真正的视频处理仍然由 Python + FFmpeg 完成。

### Q：能自动发 TikTok 吗？

不能。当前只做到本地素材处理和可扩展调度，不包含自动发布。

---

## 后续可以继续做的事

- 把配置加载统一起来，减少脚本里到处读环境变量。
- 加任务队列和可视化任务面板。
- 补充 pytest，覆盖 URL 解析、BGM 意图解析、输出命名。
- 增加更标准的钉钉/飞书 webhook 示例。
- 增加 n8n 或剪映草稿导出示例。
- 做一个完全脱敏的演示截图，让 README 更直观。

---

如果你只是想快速体验，记住一句话：

> 先用本地视频 + 本地 BGM 跑通，再接小红书链接和 OpenClaw。这样最不容易被登录态、平台风控和外部下载器卡住。
