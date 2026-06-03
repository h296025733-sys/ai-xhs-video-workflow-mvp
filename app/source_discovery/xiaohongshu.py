import os

from app.material_pool.store import add_candidate


KEYWORD_BONUS = ["穿搭", "OOTD", "韩系", "日系", "显瘦", "通勤", "裙子", "毛衣", "小个子", "甜美", "辣妹"]
RISK_WORDS = ["搞笑", "剧情", "宠物", "情侣", "挑战", "变装挑战", "热梗"]


def score_candidate(title: str, tags: list[str], follower_count: int, like_count: int, collect_count: int, comment_count: int) -> tuple[int, str, str]:
    text = f"{title} {' '.join(tags)}"
    score = 50
    reasons: list[str] = []
    risks: list[str] = []
    hit_words = [word for word in KEYWORD_BONUS if word.lower() in text.lower()]
    if hit_words:
        score += min(len(hit_words) * 6, 30)
        reasons.append("标题或标签命中穿搭关键词，适合进入人工筛选。")
    if follower_count > 500000:
        score -= 8
        reasons.append("粉丝量较高，需注意流量可能来自账号体量，已轻微降权。")
    engagement = like_count + collect_count * 2 + comment_count * 3
    if follower_count < 80000 and engagement > 3000:
        score += 12
        reasons.append("粉丝量不高但互动较好，疑似有可复刻价值。")
    risk_hits = [word for word in RISK_WORDS if word in text]
    if risk_hits:
        score -= 10
        risks.append("可能存在非服装因素带动，需要人工确认。")
    return max(score, 0), "；".join(reasons) or "基础候选素材，建议人工查看后再决定是否处理。", "；".join(risks)


def generate_mock_candidates(keyword: str, limit: int, selected_region: str, selected_style: str) -> list[dict]:
    templates = [
        ("韩系通勤穿搭 OOTD：显瘦毛衣和半身裙", "小禾穿搭日记", 42000, 2600, 980, 126, ["韩系", "通勤", "毛衣", "半身裙"]),
        ("小个子甜美穿搭，春季裙子搭配参考", "柚子衣橱", 68000, 4200, 1560, 231, ["小个子", "甜美", "裙子", "OOTD"]),
        ("日系温柔外套穿搭，适合约会和出游", "奈奈搭配", 120000, 5100, 2400, 308, ["日系", "温柔", "外套", "约会"]),
        ("辣妹显瘦上衣搭配，鞋包一起看", "Mia不重样", 35000, 3800, 1750, 188, ["辣妹", "显瘦", "上衣", "鞋包"]),
        ("剧情反转穿搭挑战，热梗变装挑战", "阿琳日常", 820000, 12000, 3000, 1200, ["剧情", "挑战", "变装挑战"]),
    ]
    rows: list[dict] = []
    for idx, (title, author, followers, likes, collects, comments, tags) in enumerate(templates[:limit], start=1):
        full_title = title if keyword in title else f"{keyword}｜{title}"
        score, reason, risk = score_candidate(full_title, tags, followers, likes, collects, comments)
        rows.append(
            {
                "source_platform": "xiaohongshu",
                "source_url": f"https://www.xiaohongshu.com/mock/{keyword}-{idx}",
                "title": full_title,
                "description": "演示候选素材（mock），用于跑通素材池流程，不代表真实平台数据。",
                "author_name": author,
                "author_profile_url": f"https://www.xiaohongshu.com/user/mock-{idx}",
                "follower_count": followers,
                "like_count": likes,
                "collect_count": collects,
                "comment_count": comments,
                "play_count": None,
                "publish_time": None,
                "tags": tags,
                "cover_url": None,
                "selected_region": selected_region,
                "selected_style": selected_style,
                "score": score,
                "reason_for_selection": reason,
                "risk_notes": risk,
            }
        )
    return rows


def search_xiaohongshu(keyword: str, limit: int, mode: str, selected_region: str, selected_style: str) -> dict:
    normalized_mode = (mode or "mock").lower()
    if normalized_mode == "manual":
        return {
            "candidates": [],
            "message_zh": "当前为手动模式（manual），请通过 POST /material-pool/candidates 人工添加候选素材。",
            "mode_used": "manual",
            "next_action_zh": "复制素材链接、标题和作者信息后，人工写入候选素材池。",
        }
    if normalized_mode == "external":
        has_external = bool(os.getenv("XHS_MCP_BASE_URL") or os.getenv("XHS_DOWNLOADER_API_BASE_URL"))
        if not has_external:
            mock_rows = [add_candidate(row, source_type="auto") for row in generate_mock_candidates(keyword, min(limit, 5), selected_region, selected_style)]
            return {
                "candidates": mock_rows,
                "message_zh": "外部小红书服务未配置，当前已使用演示流程（mock）写入候选素材池。",
                "mode_used": "mock",
                "next_action_zh": "如需处理真实作品，后续配置 xiaohongshu-mcp 或 XHS-Downloader 适配器。",
            }
        return {
            "candidates": [],
            "message_zh": "外部模式（external）已预留，但本轮不强制集成第三方服务。",
            "mode_used": "external",
            "next_action_zh": "请先使用演示模式（mock）或手动模式（manual）跑通主流程，后续再接外部适配器。",
        }

    mock_rows = [add_candidate(row, source_type="auto") for row in generate_mock_candidates(keyword, min(limit, 5), selected_region, selected_style)]
    return {
        "candidates": mock_rows,
        "message_zh": "已使用演示模式（mock）生成小红书候选素材，并写入候选素材池。",
        "mode_used": "mock",
        "next_action_zh": "请在候选素材池中人工筛选，选中、放弃或加入长期追更。",
    }
