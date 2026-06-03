# ai-xhs-video-workflow-mvp

面向跨境电商短视频素材处理的小红书视频采集、BGM 替换、批量处理与 OpenClaw / 企业 IM 调度工作流 MVP。

这个项目不是完整商业系统，也不是自动发布系统。它更准确的定位是：把运营侧常见的“小红书素材链接/作者主页 -> 本地视频素材 -> 替换 BGM -> 批量输出 -> 中文结果反馈”整理成一个可本地运行、可接入自动化入口、可继续扩展的工作流骨架。

## 项目背景

跨境电商短视频素材本地化通常会遇到几个重复工作：从小红书收集参考素材，判断是否是视频，下载到本地，替换适合日韩 TikTok / 服装穿搭场景的 BGM，再把结果按清晰命名规则输出给运营同事复核。

原始工作流是一个本地 MVP，围绕 Python、FastAPI、FFmpeg、XHS-Downloader 和 OpenClaw 做工具链打通。本公开版只保留可公开复用的代码、示例配置和说明，真实 token、cookie、OpenClaw 配置、日志、素材和成品视频都已排除。

## 适用场景

- 跨境电商短视频素材的本地批处理。
- 小红书作品链接转本地待处理素材。
- 给同一批视频替换不同 BGM，生成可复核版本。
- 用 OpenClaw 作为自然语言入口，把“帮我处理这个链接”转成脚本任务。
- 后续扩展到钉钉、飞书、企业微信等企业 IM 入口。

## 核心功能

- 小红书作品链接处理思路：支持单条作品链接导入，优先通过本地 XHS-Downloader API/CLI 或人工上传兜底。
- 作者主页处理思路：作者主页最近 N 条通常需要登录态、Cookie、MCP 或辅助脚本，本项目保留接口和包装脚本，不内置真实登录态。
- 视频下载与本地素材处理：将作品或本地视频整理成待处理任务，记录状态、封面、时长和失败原因。
- FFmpeg BGM 替换：支持替换原声、保留原声、指定 BGM 起始秒数，并在失败时给出中文错误。
- 批量任务处理：支持多链接、多视频、dry-run 预览和正式执行。
- 输出命名规范：使用标题、作品 ID 片段、BGM 版本号等信息避免覆盖。
- 去重与缓存思路：对作品链接、note_id、输出 hash 和 BGM 搜索结果做去重或缓存，减少重复处理。
- OpenClaw 调度层：把自然语言消息解析成 CLI/API 参数，适合作为自动化入口。
- 企业 IM 扩展：钉钉、飞书、企业微信等可以把消息写入临时文件，再调用包装脚本。
- 日韩 TikTok / 跨境电商素材本地化：BGM 搜索提示词会偏向日本、韩国、OOTD、fashion、lookbook 等方向。

## 技术栈

- Python 3.11+
- FastAPI / Uvicorn
- FFmpeg / ffprobe
- requests / httpx
- XHS-Downloader，可选外部工具
- OpenClaw，可选调度入口
- PowerShell，用于 Windows 本地启动脚本

## 架构说明

```text
企业 IM / OpenClaw / 手工命令
        |
        v
scripts/openclaw_*.py 或 quick_bgm_automation.py
        |
        v
FastAPI quick-bgm 接口
        |
        +-- 小红书链接导入适配器
        +-- 本地视频 / BGM 管理
        +-- FFmpeg 处理
        +-- 任务状态与输出记录
        |
        v
outputs/ 本地结果目录
```

## 目录结构

```text
ai-xhs-video-workflow-mvp/
  README.md
  LICENSE
  .gitignore
  .env.example
  requirements.txt
  app/                      # FastAPI 应用和 quick-bgm 核心逻辑
  scripts/                  # CLI、OpenClaw、企业 IM 包装脚本
  config/                   # 示例配置，不包含真实密钥
  docs/                     # 中文说明文档
  examples/                 # 示例任务和输出结构
  assets/                   # 仅放说明，不放真实素材
```

## 快速开始

1. 创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. 准备 FFmpeg：

```powershell
ffmpeg -version
ffprobe -version
```

3. 复制示例配置：

```powershell
Copy-Item .env.example .env
```

4. 启动 FastAPI：

```powershell
.\scripts\run_api.ps1
```

或直接运行：

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8004 --reload
```

5. 打开本地页面：

```text
http://127.0.0.1:8004/quick-bgm/page
```

## 示例配置

本仓库只提供示例配置，真实密钥、token、cookie、OpenClaw 配置都不要提交。

```text
.env.example
config/config.example.json
config/openclaw.example.json
config/models.example.json
config/dingtalk.example.json
config/feishu.example.json
```

常见占位符包括：

```text
YOUR_API_KEY_HERE
YOUR_DINGTALK_TOKEN_HERE
YOUR_FEISHU_APP_ID_HERE
YOUR_OPENCLAW_GATEWAY_URL
YOUR_XHS_DOWNLOADER_PATH
YOUR_MODEL_PROVIDER
YOUR_MODEL_NAME
```

## 运行流程

单条作品链接：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --note-url "https://www.xiaohongshu.com/explore/YOUR_NOTE_ID" `
  --bgm-strategy search_download `
  --bgm-query "日本 TikTok OOTD 热门歌" `
  --run
```

作者主页 dry-run：

```powershell
.\.venv\Scripts\python.exe .\scripts\quick_bgm_automation.py `
  --api-base http://127.0.0.1:8004 `
  --creator-home-url "https://www.xiaohongshu.com/user/profile/YOUR_CREATOR_ID" `
  --limit 5 `
  --dry-run
```

OpenClaw / 企业 IM 入口：

```powershell
.\.venv\Scripts\python.exe .\scripts\openclaw_quick_bgm.py `
  --message "把这个小红书作品换成韩国 TikTok 穿搭 BGM：https://www.xiaohongshu.com/explore/YOUR_NOTE_ID" `
  --api-base http://127.0.0.1:8004
```

## OpenClaw 接入说明

OpenClaw 适合作为自然语言入口和调度层。推荐做法是让 OpenClaw 收到用户消息后调用 `scripts/openclaw_quick_bgm.py` 或 `scripts/run_xhs_author_from_dingtalk.ps1`，由脚本负责解析链接、BGM 意图、dry-run、起始秒数、是否保留原声等参数。

公开版不包含真实 OpenClaw workspace、模型配置、登录态或渠道配置。请复制 `config/openclaw.example.json` 后按自己的本地环境填写。

## 钉钉 / 飞书 / 企业 IM 扩展说明

企业 IM 的推荐模式是：

1. IM 机器人收到中文消息。
2. 网关将消息写入 UTF-8 临时文件。
3. 调用 PowerShell 或 Python 包装脚本。
4. 脚本输出中文摘要、失败原因和本地结果路径。
5. IM 只返回业务可读摘要，不暴露完整日志、cookie、下载直链或系统路径。

本仓库只提供示例配置，不包含真实钉钉、飞书、企业微信 token。

## 安全与隐私说明

- 不提交 `.env`、cookie、token、OpenClaw 私人配置、浏览器登录态。
- 不提交真实视频、音频、BGM、封面、下载缓存和运行日志。
- 小红书登录态只允许保存在本机环境变量或私有配置中。
- 输出结果默认进入 `outputs/`，该目录已被 `.gitignore` 排除。
- 使用小红书素材和 BGM 时，请自行确认授权、版权和平台规则。

## 当前限制

- 这是本地 MVP，不保证所有小红书链接都能自动解析。
- 作者主页最近 N 条通常需要 Cookie、MCP、浏览器登录态或外部辅助工具。
- 不包含自动发布 TikTok、剪映云端发布或商业后台。
- BGM 搜索下载依赖外部网络和来源可用性，可能失败。
- 视频处理以 FFmpeg 为主，不是深度算法项目。

## 后续规划

- 抽离统一配置加载，减少脚本环境变量分散。
- 增加任务队列和可视化批量状态页。
- 接入更稳定的小红书内容采集适配层。
- 为 OpenClaw / 钉钉 / 飞书补充更标准的 webhook 示例。
- 增加 pytest 覆盖 BGM 意图解析、URL 去重、输出命名和 dry-run。
- 增加剪映草稿或 n8n 工作流的示例导出。
