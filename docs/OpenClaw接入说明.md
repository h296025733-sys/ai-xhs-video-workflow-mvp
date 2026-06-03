# OpenClaw 接入说明

## 推荐接入方式

OpenClaw 收到用户自然语言消息后，不直接操作网页，而是调用本地脚本：

```powershell
python scripts/openclaw_quick_bgm.py --message-file YOUR_MESSAGE_FILE --api-base http://127.0.0.1:8004
```

对于作者主页批量处理，可以调用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_xhs_author_from_dingtalk.ps1 -MessageFile YOUR_MESSAGE_FILE
```

## 消息解析能力

脚本会尝试识别：

- 小红书作品链接。
- 小红书作者主页链接。
- BGM 搜索词或 BGM 链接。
- 是否 dry-run。
- 是否保留原声。
- BGM 起始秒数。
- 批量处理数量。
- 输出目录。

## 回复原则

企业 IM 回复建议只给业务摘要：

- 成功数 / 失败数。
- 处理条件。
- 输出目录。
- 失败原因和下一步建议。

不要在 IM 中输出 cookie、下载直链、完整异常堆栈、内部缓存路径和真实配置。
