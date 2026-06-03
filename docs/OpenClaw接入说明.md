# OpenClaw 接入说明

OpenClaw 在这个项目里更像“自然语言调度层”：用户说人话，OpenClaw 把消息交给本地脚本，脚本再决定是处理本地视频、单条小红书链接，还是作者主页批量筛选。

## 推荐接入方式

### 单条作品 / 本地视频

```powershell
python scripts/openclaw_quick_bgm.py `
  --message-file YOUR_MESSAGE_FILE `
  --api-base http://127.0.0.1:8004
```

### 作者主页 / 小红书号

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/run_xhs_author_from_dingtalk.ps1 `
  -MessageFile YOUR_MESSAGE_FILE
```

`run_xhs_author_from_dingtalk.ps1` 默认会调用：

```text
scripts/openclaw_xhs_author.py
```

这条链路支持用 Playwright 连接已登录 Chrome，自动搜索作者、进入主页、采集作品并筛选。

## 消息示例

```text
找小红书号 YOUR_XHS_ID，最近7天内点赞100以上的视频，取5条。
BGM 用韩国 TikTok OOTD 热门歌，从第20秒开始。
先 dry-run 看看筛选结果。
```

```text
处理这个作者主页最近30天点赞200以上的视频，取8条。
BGM 用日本 TikTok 穿搭热门歌。
https://www.xiaohongshu.com/user/profile/YOUR_CREATOR_ID
```

## 脚本会识别什么

- 小红书作品链接。
- 小红书作者主页链接。
- 小红书号 / 昵称 / 作者名。
- 最近 3 天、最近 7 天、最近 30 天、7-15 天前。
- 点赞 100 以上、至少 200 赞。
- BGM 搜索词或 BGM 链接。
- BGM 起始秒数。
- 是否 dry-run。
- 是否只下载原视频、不换 BGM。
- 批量处理数量。

## 企业 IM 回复建议

建议只返回业务摘要：

- 成功数 / 失败数。
- 筛选条件。
- 输出目录。
- 失败原因和下一步建议。

不要在 IM 中输出：

- cookie、token、Authorization。
- 小红书完整临时参数。
- 下载直链。
- 完整异常堆栈。
- 本机真实路径。
- OpenClaw 私人配置。

## 部署小提醒

作者主页自动化依赖本机已登录 Chrome：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="D:\workspace\xhs-cdp-profile"
```

然后配置：

```powershell
$env:XHS_CDP_URL = "http://127.0.0.1:9222"
```

登录态留在你本机 Chrome 里，不写入 GitHub。这样更适合公开展示，也更容易解释安全边界。
