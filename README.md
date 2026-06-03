# ai-xhs-video-workflow-mvp

> 面向跨境电商短视频素材处理的小红书视频采集、BGM 替换、批量处理与 OpenClaw / 企业 IM 调度工作流 MVP。

这个项目不是“写个脚本改一下音频”那么简单，也不是夸张到能全自动运营账号的商业系统。

它更像一个本地短视频处理工作台：把 **小红书作品/作者主页、浏览器自动化、XHS-Downloader、FFmpeg、BGM 搜索、OpenClaw、钉钉/飞书入口** 串起来，让原本要在浏览器、下载器、剪辑软件、文件夹和聊天工具之间来回切的流程，尽量变成一句话可以调度的本地工作流。ヽ(・∀・)ﾉ

适合的场景很具体：跨境电商、日韩 TikTok / Reels / Shorts 素材本地化、服装穿搭参考视频整理、批量换 BGM、交付给运营复核。

---

## 先看它能干什么

你可以从三种入口开始：

```text
本地视频文件
  -> 上传/选择 BGM
  -> FFmpeg 替换音轨
  -> 输出成品视频

小红书单条作品链接
  -> XHS-Downloader API/CLI/MCP 解析或下载
  -> 转成本地素材
  -> 批量换 BGM

小红书作者昵称 / 小红书号 / 作者主页
  -> Playwright 连接已登录 Chrome
  -> 自动搜索作者并进入主页
  -> 滚动采集作品链接
  -> 按最近 N 天、点赞数、视频类型筛选
  -> 交给 quick-bgm 批量处理
```

一句话例子：

```text
找小红书号 YOUR_XHS_ID，最近7天内点赞100以上的视频，取5条，
BGM 用韩国 TikTok OOTD 热门歌，从第20秒开始，正式生成。
```

公开版不会内置你的 cookie、登录态、真实素材、运行日志或 OpenClaw 私人配置。要跑作者主页自动化，需要你本机自己登录小红书，并用 Chrome 远程调试端口让脚本复用这个登录态。

---

## 核心功能

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 本地视频换 BGM | 可用 | FastAPI 页面和 CLI 都能跑，适合作为第一条验证路线 |
| FFmpeg 音轨处理 | 可用 | 支持替换原声、保留原声、指定 BGM 起始秒 |
| 批量任务 | 可用 | 支持多视频、多小红书链接、dry-run 预览 |
| 小红书单条作品链接 | 已接入骨架 | 通过 XHS-Downloader API/CLI/MCP 或人工下载转本地素材 |
| 小红书作者搜索 | 已整理公开版 | Playwright + Chrome CDP，支持按小红书名/号搜索作者 |
| 作者主页作品采集 | 已整理公开版 | DOM、网络响应、`window.__INITIAL_STATE__` 多路提取作品链接 |
| 最近 N 天筛选 | 可用 | 支持“最近7天”“最近30天”“7-15天前”等说法 |
| 点赞门槛筛选 | 可用 | 支持“点赞100以上”“至少200赞”等说法 |
| BGM 智能搜索 | 可用骨架 | 通过搜索词 + `yt-dlp` 辅助下载，适合本地验证 |
| OpenClaw 自然语言入口 | 有脚本 | 把中文消息解析成 CLI/API 参数 |
| 钉钉/飞书/企业 IM | 有接入示例 | 只放示例配置，不放真实 token |
| 自动发布 TikTok | 未做 | 当前定位是“本地素材处理与交付”，不是自动发布系统 |

说得直白一点：这个 MVP 的价值不在“发明新算法”，而在把一堆真实会用到的工具打通，并且把容易出错的手工步骤收进一个可复用流程里。

---

## 技术栈

- Python：主流程、任务编排、自然语言意图解析、CLI 包装。
- FastAPI：本地 Web 页面和自动化 API。
- FFmpeg / ffprobe：视频探测、封面抽帧、BGM 替换、音轨混合。
- Playwright + Chrome CDP：复用已登录浏览器，搜索小红书作者并采集主页作品。
- XHS-Downloader：作为可选外部依赖，用于小红书作品解析/下载。
- yt-dlp：用于 BGM 搜索下载的可选链路。
- OpenCV / PySceneDetect：视频基础分析、场景切分、关键帧/画面辅助处理。
- PowerShell：Windows 本地启动、钉钉/企业 IM 脚本入口。

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
      router.py                     # quick-bgm 页面和 API
      media.py                      # FFmpeg / ffprobe 处理
      store.py                      # 本地任务、BGM 库、输出记录
      xhs_adapter.py                # 单条小红书作品适配
      xhs_creator_importer.py       # XHS-Downloader API/CLI/MCP 适配
    services/
      scene_detect.py               # 场景切分
      video_profile.py              # 视频画面分析
  scripts/
    quick_bgm_automation.py         # 通用 CLI
    openclaw_quick_bgm.py           # 单条/批量作品自然语言入口
    openclaw_xhs_author.py          # 作者主页自然语言入口
    xhs_author_auto_pipeline.py     # 浏览器采集 + 条件筛选 + 批量处理
    openclaw_xhs_author_direct_v2.py# 复用筛选报告的多 BGM 版本实验路径
    bgm_smart_resolver.py           # BGM 搜索词解析
  config/
    *.example.json                  # 只放示例配置
  docs/
    快速开始.md
    小红书作者主页自动化说明.md
    OpenClaw接入说明.md
    第三方依赖与致谢.md
    安全与隐私说明.md
    常见问题.md
  examples/
    示例任务.json
    作者主页筛选消息示例.md
```

---

## 快速开始：先跑通本地视频换 BGM

这是最稳的验证方式，不需要登录小红书。

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

如果只跑本地视频换 BGM，Playwright 这一步可以先跳过；如果要跑作者主页自动化，建议装上。

### 2. 确认 FFmpeg 可用

```powershell
ffmpeg -version
ffprobe -version
```

如果这里报错，先安装 FFmpeg，并把 `ffmpeg.exe`、`ffprobe.exe` 加到 PATH。

### 3. 准备配置

```powershell
Copy-Item .env.example .env
```

`.env` 只在你本机使用，不要提交。公开仓库里只保留 `.env.example`。

### 4. 启动服务

```powershell
.\scripts\run_api.ps1
```

打开页面：

```text
http://127.0.0.1:8004/quick-bgm/page
```

然后上传一个本地 `.mp4`，再上传或选择一个 BGM，点击生成。跑通这一步，就说明 FastAPI + FFmpeg + 本地文件处理链路是通的。

---

## 用命令行处理本地视频

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --video-path "D:\workspace\demo\input.mp4" `
  --bgm-strategy local_random `
  --run
```

想先看任务会怎么创建，不想真的生成视频：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --video-path "D:\workspace\demo\input.mp4" `
  --bgm-strategy local_random `
  --dry-run
```

---

## 处理单条小红书作品链接

小红书内容解析依赖外部合法下载/解析能力。这个项目已经整理了 XHS-Downloader API / CLI / MCP 的适配入口，但不会把你的真实 cookie 或登录态放进仓库。

如果你本地已经启动了 XHS-Downloader API：

```powershell
$env:XHS_DOWNLOADER_API_BASE_URL = "http://127.0.0.1:5556"
$env:XHS_DOWNLOAD_MODE = "api"
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

如果解析失败，不一定是本项目坏了，常见原因是：下载器没启动、登录态过期、作品不是视频、平台页面结构变化，或者当前链接需要更完整的登录上下文。

---

## 作者主页自动化：按小红书名/号筛选作品

这一块是你最容易拿去讲项目亮点的地方。

公开版整理后的主入口是：

```text
scripts/openclaw_xhs_author.py
```

它会做这些事：

1. 从中文消息里识别作者主页、小红书号、昵称。
2. 如果只有昵称/小红书号，就用 Playwright 连接已登录 Chrome 搜索作者。
3. 进入作者主页后二次校验，避免点错账号。
4. 滚动主页，结合 DOM、网络响应、`window.__INITIAL_STATE__` 抓作品链接。
5. 按“最近 N 天”“点赞 N 以上”“是否视频”筛选。
6. 把筛选出的作品交给 quick-bgm 批量换 BGM。

### 1. 先启动一个带调试端口的 Chrome

Windows 示例：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="D:\workspace\xhs-cdp-profile"
```

然后在这个 Chrome 里登录小红书。登录态只保存在你本机的 Chrome 用户目录，不进 GitHub。

### 2. 配置 CDP 地址

```powershell
$env:XHS_CDP_URL = "http://127.0.0.1:9222"
```

### 3. 先做一次只解析，不打开浏览器

```powershell
.\.venv\Scripts\python.exe .\scripts\openclaw_xhs_author.py `
  --message "找小红书号 YOUR_XHS_ID，最近7天内点赞100以上的视频，取5条，BGM用韩国 TikTok OOTD 热门歌，从第20秒开始，先看看" `
  --parse-only
```

### 4. 正式跑作者主页筛选

```powershell
.\.venv\Scripts\python.exe .\scripts\openclaw_xhs_author.py `
  --api-base http://127.0.0.1:8004 `
  --message "找小红书号 YOUR_XHS_ID，最近7天内点赞100以上的视频，取5条，BGM用韩国 TikTok OOTD 热门歌，从第20秒开始，正式生成"
```

如果你已经有作者主页链接，也可以直接写：

```powershell
.\.venv\Scripts\python.exe .\scripts\openclaw_xhs_author.py `
  --api-base http://127.0.0.1:8004 `
  --message "处理这个作者主页最近30天点赞200以上的视频，取8条，BGM用日本 TikTok 穿搭热门歌：https://www.xiaohongshu.com/user/profile/YOUR_CREATOR_ID"
```

运行中会生成筛选报告和中间链接文件，默认在 `outputs/` 和 `.runtime/` 下，已经被 `.gitignore` 排除。

---

## OpenClaw / 钉钉 / 飞书接入思路

OpenClaw 或企业 IM 不需要直接操作网页，只要把用户消息写成 UTF-8 文本，再调用脚本即可：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_xhs_author_from_dingtalk.ps1 `
  -MessageFile "D:\workspace\demo\message.txt"
```

`message.txt` 可以很像人话：

```text
找小红书号 YOUR_XHS_ID，最近7天内点赞100以上的视频，取5条。
BGM 用韩国 TikTok OOTD 热门歌，从第20秒开始。
先 dry-run 看看筛选结果。
```

实际接钉钉/飞书时，建议只回给用户这些信息：成功几条、失败几条、输出目录、失败原因、下一步建议。不要在 IM 里回传 cookie、下载直链、完整日志或本机真实路径。

---

## 输出长什么样

建议输出到本地 `outputs/`，不上传 GitHub：

```text
outputs/
  作者主页批量/
    01_视频成品/
      春季通勤穿搭__4a85__BGM01.mp4
      春季通勤穿搭__4a85__BGM02.mp4
    02_封面/
      春季通勤穿搭__4a85__cover_frame.jpg
  reports/
    author_auto_filter_YYYYMMDD_HHMMSS.json
    author_auto_selected_YYYYMMDD_HHMMSS.txt
```

命名里保留标题、作品短 ID、BGM 版本，是为了避免同标题作品互相覆盖，也方便运营复核。

---

## 安全与隐私

公开版刻意不包含：

- 真实 API key、token、cookie、Authorization。
- 真实小红书登录态、浏览器缓存、OpenClaw 私人配置。
- 真实视频素材、成品视频、BGM 文件、下载缓存。
- 运行日志、报错日志、公司数据、个人路径。

请注意：作者主页自动化会复用你本机 Chrome 的登录态。这个设计是为了避免把 cookie 写进代码，但也意味着你必须自己管理浏览器环境，遵守平台规则，只处理你有权处理的素材。

---

## 第三方依赖与致谢

本仓库没有内置第三方项目源码，但整理了与这些工具的对接方式：

- [JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)：小红书作品解析/下载工具，本项目按外部可选依赖接入，使用前请阅读其许可证和使用说明。
- [Microsoft Playwright](https://github.com/microsoft/playwright)：浏览器自动化与 Chrome CDP 连接。
- [FFmpeg](https://ffmpeg.org/)：视频与音频处理基础设施。
- [FastAPI](https://fastapi.tiangolo.com/)：本地 API 与页面服务。
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：BGM 搜索下载链路的可选工具。

更完整说明见 [docs/第三方依赖与致谢.md](docs/第三方依赖与致谢.md)。

---

## 当前限制

- 这是 MVP / 本地工作流，不是商业 SaaS。
- 小红书页面结构、登录态、风控策略变化时，作者主页自动化可能需要调整。
- XHS-Downloader、MCP、Chrome CDP 都属于本机可选依赖，需要你自己按合法方式配置。
- BGM 搜索下载依赖外部搜索结果，质量需要人工复核。
- 当前不做自动发布，不承诺播放量、转化率或收益。

---

## 后续规划

- 把作者主页筛选报告做成更友好的本地审核页。
- 给 BGM 候选增加可视化试听、黑名单和收藏池。
- 将 OpenClaw / 钉钉 / 飞书入口抽象成更统一的任务网关。
- 增加任务队列、失败重试、断点续跑。
- 给视频封面/人物主体/场景标签增加更稳定的人工校验流程。

这个项目的目标不是“神奇地全自动运营”，而是把真实短视频素材处理里最烦、最重复、最容易漏的步骤整理成能复用的工作流。小而实用，才是它的重点。
