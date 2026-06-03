# 小红书视频采集与 BGM 替换自动化工作流

> ai-xhs-video-workflow-mvp｜面向跨境电商短视频素材处理的小红书作者主页筛选、视频采集、BGM 替换与 OpenClaw 调度 MVP。

这是一个偏“真实业务工作台”的本地项目，不是单纯把视频换个音乐的小脚本，也不是夸张到全自动运营账号的商业系统。

我当时想解决的问题很具体：运营/选品同事看到一批小红书穿搭、OOTD、带货参考视频后，往往要手动复制链接、下载素材、判断是不是最近热门、筛掉低赞或图文内容、找适合日韩 TikTok 风格的 BGM、再批量生成版本给人复核。这个项目就是把这些散落在浏览器、下载器、命令行、剪辑工具和企业 IM 里的步骤，整理成一条可以复用的本地自动化流程。

简单说，它可以做到：

```text
一句中文任务
  -> 识别小红书号 / 作者主页 / 作品链接 / BGM 要求
  -> 浏览器自动化搜索作者并采集主页作品
  -> 按最近 N 天、点赞数、是否视频筛选
  -> XHS-Downloader 或本地素材进入处理流程
  -> FFmpeg 批量替换 BGM
  -> 输出命名清晰的本地成品和筛选报告
```

适用场景：跨境电商短视频素材整理、日韩 TikTok / Reels / Shorts 素材本地化、服装穿搭参考视频复核、批量 BGM 替换、OpenClaw / 钉钉 / 飞书等入口调度。小而实用，能跑起来，才是它的重点。ヽ(・∀・)ﾉ

---

## 一个具体例子

如果你已经在本机登录了小红书，并启动了带调试端口的 Chrome，可以给 OpenClaw、钉钉脚本或本地命令行这样一段话：

```text
找小红书号 YOUR_XHS_ID，最近7天内点赞100以上的视频，取5条。
BGM 用韩国 TikTok OOTD 热门歌，从第20秒开始。
先 dry-run 看看筛选结果。
```

项目会把它拆成这些动作：

1. 识别 `YOUR_XHS_ID` 是作者搜索条件。
2. 识别“最近 7 天”和“点赞 100 以上”是筛选条件。
3. 识别“取 5 条”是数量限制。
4. 识别 BGM 搜索方向和起始秒数。
5. 用 Playwright 连接已登录 Chrome，搜索作者并进入主页。
6. 滚动主页采集作品链接，结合 DOM、网络响应和页面状态对象做兜底。
7. 预览作品类型，筛掉图文或不符合条件的内容。
8. dry-run 只输出筛选报告；正式执行时再交给 quick-bgm 批量换 BGM。

公开版不会放入任何真实 cookie、token、登录态、素材、运行日志或 OpenClaw 私人配置。需要登录态的部分，只复用你本机浏览器环境。

---

## 功能一览

| 模块 | 当前状态 | 说明 |
| --- | --- | --- |
| 本地视频换 BGM | 可直接验证 | FastAPI 页面和 CLI 都能跑，适合先检查 FFmpeg 链路 |
| FFmpeg 音轨处理 | 可用 | 支持替换原声、保留原声、指定 BGM 起始秒、失败中文提示 |
| 批量任务处理 | 可用 | 支持多视频、多作品链接、预览模式（dry-run）和正式执行 |
| 小红书单条作品链接 | 已适配 | 对接 XHS-Downloader API / CLI / MCP，也支持人工下载后走本地视频流程 |
| 小红书号 / 昵称搜索 | 已实现公开版脚本 | Playwright + Chrome CDP 连接已登录浏览器，自动搜索作者 |
| 作者主页作品采集 | 已实现公开版脚本 | 滚动主页，从 DOM、网络响应、`window.__INITIAL_STATE__` 多路提取作品链接 |
| 时间与点赞筛选 | 可用 | 支持“最近7天”“最近30天”“7-15天前”“点赞100以上”等中文说法 |
| 视频类型判断 | 可用 | 结合 XHS-Downloader 预览信息、视频 URL 线索和页面数据判断是否进入换 BGM |
| BGM 搜索下载 | 可用原型 | 用搜索词 + `yt-dlp` 辅助获取候选 BGM，生成后建议人工试听 |
| OpenClaw 自然语言入口 | 已封装 | 把中文消息解析成 CLI/API 参数，适合作为自动化调度层 |
| 钉钉 / 飞书 / 企业 IM | 有示例入口 | 只保留示例配置和脚本思路，不包含真实 webhook 或 app secret |
| 视频结构分析 | 可用辅助 | FFmpeg、PySceneDetect、OpenCV 做镜头切分、关键帧总览、长镜头采样 |
| 自动发布 TikTok | 未包含 | 当前定位是本地素材处理与交付，不做自动发布和账号运营 |

这个 MVP 的亮点不在“发明新算法”，而在把真实会用到的工具接起来：浏览器自动化、下载器、视频处理、BGM 搜索、本地页面、中文任务入口、企业 IM 包装和安全脱敏，都在一个项目里有清晰边界。

---

## 技术栈

- Python：主流程、任务编排、自然语言意图解析、CLI 包装。
- FastAPI：本地 Web 页面、quick-bgm API、任务状态接口。
- FFmpeg / ffprobe：视频探测、封面抽帧、BGM 替换、音轨混合。
- Playwright + Chrome CDP：复用已登录浏览器，搜索小红书作者并采集主页作品。
- XHS-Downloader：作为可选外部依赖，用于小红书作品解析、预览和下载。
- yt-dlp：用于 BGM 搜索下载链路的可选工具。
- OpenCV / PySceneDetect：视频基础分析、镜头切分、关键帧/画面辅助处理。
- PowerShell：Windows 本地启动脚本、OpenClaw / 企业 IM 包装入口。

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
      media.py                      # FFmpeg / ffprobe 音视频处理
      store.py                      # 本地任务、BGM 库、输出记录
      xhs_adapter.py                # 单条小红书作品适配
      xhs_creator_importer.py       # XHS-Downloader API/CLI/MCP 适配
    services/
      scene_detect.py               # 场景 / 镜头切分
      video_profile.py              # 视频结构与关键帧辅助分析
  scripts/
    quick_bgm_automation.py         # 通用命令行入口
    openclaw_quick_bgm.py           # 单条/批量作品自然语言入口
    openclaw_xhs_author.py          # 作者主页自然语言入口
    xhs_author_auto_pipeline.py     # 浏览器采集 + 条件筛选 + 批量处理
    openclaw_xhs_author_direct_v2.py# 筛选报告复用与多 BGM 版本实验入口
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

本地视频换 BGM 是最稳的第一步，不需要登录小红书，也不依赖 XHS-Downloader。

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

如果只是先处理本地视频，Playwright 这一步可以晚点装；如果要跑作者主页自动化，建议一起安装。

### 2. 确认 FFmpeg 可用

```powershell
ffmpeg -version
ffprobe -version
```

如果这里报错，先安装 FFmpeg，并把 `ffmpeg.exe` 和 `ffprobe.exe` 加到系统 PATH。

### 3. 准备本机配置

```powershell
Copy-Item .env.example .env
```

`.env` 只在你本机使用，不要提交。公开仓库只保留 `.env.example`。

### 4. 启动服务

```powershell
.\scripts\run_api.ps1
```

打开本地页面：

```text
http://127.0.0.1:8004/quick-bgm/page
```

上传一个 `.mp4`，再上传或选择一个 BGM，点击生成。跑通这一步，就说明 FastAPI + FFmpeg + 本地文件处理链路没有问题。

---

## 命令行处理本地视频

正式生成：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --video-path "D:\workspace\demo\input.mp4" `
  --bgm-strategy local_random `
  --run
```

只预览任务，不真的生成视频：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --video-path "D:\workspace\demo\input.mp4" `
  --bgm-strategy local_random `
  --dry-run
```

这里的 `dry-run` 可以理解成“先看看系统准备怎么做”，适合批量任务前检查参数。

---

## 处理单条小红书作品链接

小红书内容解析依赖外部合法下载/解析能力。本项目已经整理了 XHS-Downloader 的 API / CLI / MCP 三种适配方式，但不会把真实 cookie 或登录态放进仓库。

如果你本机已经启动了 XHS-Downloader API：

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

如果解析失败，常见原因通常是：下载器没启动、登录态过期、作品不是视频、平台页面结构变化，或者当前链接需要更完整的登录上下文。项目会尽量给出中文失败原因，方便继续排查。

---

## 作者主页自动化：按小红书名/号筛选作品

这一块是项目最值得展示的地方：不是手动复制一堆链接，而是让脚本连接你已经登录的小红书浏览器，自动找作者、进主页、抓作品、按条件筛。

主入口：

```text
scripts/openclaw_xhs_author.py
```

它会做这些事：

1. 从中文消息里识别作者主页、小红书号、昵称。
2. 如果只有昵称/小红书号，就用 Playwright 连接已登录 Chrome 搜索作者。
3. 进入作者主页后二次校验，避免点错账号。
4. 滚动主页，同时从 DOM、网络响应、`window.__INITIAL_STATE__` 提取作品链接。
5. 按“最近 N 天”“点赞 N 以上”“是否视频”筛选。
6. 把筛选出的作品交给 quick-bgm 批量换 BGM。

### 1. 启动一个带调试端口的 Chrome

Windows 示例：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="D:\workspace\xhs-cdp-profile"
```

然后在这个 Chrome 里登录小红书。登录态只保存在你本机的 Chrome 用户目录里，不进入 GitHub。

### 2. 配置 CDP 地址

```powershell
$env:XHS_CDP_URL = "http://127.0.0.1:9222"
```

### 3. 先解析消息，不打开浏览器

```powershell
.\.venv\Scripts\python.exe .\scripts\openclaw_xhs_author.py `
  --message "找小红书号 YOUR_XHS_ID，最近7天内点赞100以上的视频，取5条，BGM用韩国 TikTok OOTD 热门歌，从第20秒开始，先看看" `
  --parse-only
```

### 4. 正式筛选作者主页

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

运行中会生成筛选报告和中间链接文件，默认在 `outputs/` 和 `.runtime/` 下，这些目录已经被 `.gitignore` 排除。

---

## OpenClaw / 钉钉 / 飞书接入思路

OpenClaw 或企业 IM 不需要直接处理视频，只要把用户消息写成 UTF-8 文本，再调用脚本即可：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_xhs_author_from_dingtalk.ps1 `
  -MessageFile "D:\workspace\demo\message.txt"
```

`message.txt` 可以像人话一样写：

```text
找小红书号 YOUR_XHS_ID，最近7天内点赞100以上的视频，取5条。
BGM 用韩国 TikTok OOTD 热门歌，从第20秒开始。
先 dry-run 看看筛选结果。
```

真正接钉钉/飞书时，建议只返回这些信息：成功几条、失败几条、输出目录、失败原因、下一步建议。不要在企业 IM 里回传 cookie、下载直链、完整日志或本机真实路径。

---

## 输出长什么样

建议输出到本地 `outputs/`，不要上传 GitHub：

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

命名里保留标题、作品短 ID 和 BGM 版本，是为了避免同标题作品互相覆盖，也方便运营复核。

---

## 安全与隐私

公开版刻意不包含：

- 真实 API key、token、cookie、Authorization。
- 真实小红书登录态、浏览器缓存、OpenClaw 私人配置。
- 真实视频素材、成品视频、BGM 文件、下载缓存。
- 运行日志、报错日志、公司数据、个人路径。

作者主页自动化会复用你本机 Chrome 的登录态。这样做是为了避免把 cookie 写进代码，但也意味着你需要自己管理浏览器环境，遵守平台规则，只处理你有权处理的素材。

---

## 第三方依赖与致谢

本仓库没有内置第三方项目源码，只整理了与这些工具的对接方式：

- [JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)：小红书作品解析/下载工具，本项目按外部可选依赖接入，使用前请阅读其许可证和使用说明。
- [Microsoft Playwright](https://github.com/microsoft/playwright)：浏览器自动化与 Chrome CDP 连接。
- [FFmpeg](https://ffmpeg.org/)：视频与音频处理基础设施。
- [FastAPI](https://fastapi.tiangolo.com/)：本地 API 与页面服务。
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：BGM 搜索下载链路的可选工具。
- [OpenCV](https://opencv.org/) / [PySceneDetect](https://www.scenedetect.com/)：镜头切分、关键帧和画面辅助分析。

更完整说明见 [docs/第三方依赖与致谢.md](docs/第三方依赖与致谢.md)。

---

## 当前限制

- 这是 MVP / 本地工作流，不是商业 SaaS。
- 小红书页面结构、登录态、风控策略变化时，作者主页自动化可能需要维护。
- XHS-Downloader、MCP、Chrome CDP 都属于本机可选依赖，需要按合法方式自行配置。
- BGM 搜索下载依赖外部搜索结果，质量和版权需要人工复核。
- 当前不做自动发布，不承诺播放量、转化率或收益。

---

## 后续规划

- 把作者主页筛选报告做成更友好的本地审核页。
- 给 BGM 候选增加可视化试听、黑名单和收藏池。
- 将 OpenClaw / 钉钉 / 飞书入口抽象成更统一的任务网关。
- 增加任务队列、失败重试、断点续跑。
- 给视频封面、人物主体、场景标签增加更稳定的人工校验流程。

---

这个项目最想表达的不是“我做了一个万能采集器”，而是：我能把真实业务里一堆分散、麻烦、容易出错的工具，整理成一个有安全边界、能复用、能交付给别人试跑的自动化工作流。
