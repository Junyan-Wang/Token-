#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU 算力活动监控
================
抓取多个情报源（linux.do 最新帖 / GitHub 仓库更新 / RSS 订阅），
按关键词过滤出「送算力、免费额度、白嫖羊毛」类情报，
与 state.json 中已见过的条目对比，发现新增即通过 Server酱 推送到微信。

用法：
    python monitor.py

环境变量（均可选）：
    SERVERCHAN_SENDKEY   Server酱的 SendKey，未配置时只打印日志不推送
    GITHUB_TOKEN         GitHub API token，Actions 里自动注入，可提高限速额度
"""

import json
import os
import sys
import datetime
import requests

try:
    import feedparser
except ImportError:
    feedparser = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")

MAX_PUSH_ITEMS = 8        # 单次最多推送条数（防轰炸）
STATE_KEEP = 800          # 状态文件最多保留的已见条目数
HTTP_TIMEOUT = 25
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# ---------- 工具 ----------

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def match_keywords(text, keywords):
    """关键词命中（大小写不敏感）"""
    if not text:
        return False
    low = text.lower()
    return any(str(k).lower() in low for k in keywords)


# ---------- 数据源 1：Discourse 论坛（linux.do） ----------

def fetch_discourse(base, keywords):
    """抓 Discourse 站点最新帖，按标题关键词过滤"""
    url = base.rstrip("/") + "/latest.json"
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        topics = r.json().get("topic_list", {}).get("topics", []) or []
        items = []
        for t in topics:
            title = t.get("title", "")
            if not title or not match_keywords(title, keywords):
                continue
            tid = t.get("id")
            slug = t.get("slug") or "topic"
            items.append({
                "id": f"discourse:{base}:{tid}",
                "source": base.split("//")[-1].split("/")[0],
                "title": title,
                "url": f"{base.rstrip('/')}/t/{slug}/{tid}",
                "time": t.get("created_at", ""),
            })
        print(f"[ok] {base} 最新帖 {len(topics)} 条，命中 {len(items)} 条")
        return items
    except Exception as e:
        print(f"[warn] {base} 抓取失败（跳过）: {type(e).__name__}: {e}")
        return []


# ---------- 数据源 2：GitHub 仓库更新 ----------

def fetch_github_commits(repo, token=None):
    """监控指定 GitHub 仓库的最新 commit，有新提交即提醒"""
    api = f"https://api.github.com/repos/{repo}/commits?per_page=3"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "gpu-deal-monitor"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(api, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        items = []
        for c in r.json():
            msg = (c.get("commit", {}).get("message", "") or "").split("\n")[0][:60]
            items.append({
                "id": f"github:{repo}:{c.get('sha', '')[:12]}",
                "source": f"GitHub·{repo.split('/')[-1]}",
                "title": f"仓库有更新: {msg}",
                "url": c.get("html_url", ""),
                "time": c.get("commit", {}).get("author", {}).get("date", ""),
            })
        print(f"[ok] {repo} 最新 {len(items)} 个 commit")
        return items
    except Exception as e:
        print(f"[warn] {repo} 抓取失败（跳过）: {type(e).__name__}: {e}")
        return []


# ---------- 数据源 3：RSS / Atom 订阅 ----------

def fetch_rss(url, keywords):
    """抓 RSS/Atom 源，按标题关键词过滤"""
    if feedparser is None:
        print("[warn] feedparser 未安装，跳过 RSS 源")
        return []
    try:
        d = feedparser.parse(url, request_headers={"User-Agent": UA})
        entries = getattr(d, "entries", [])[:40]
        items = []
        for e in entries:
            title = e.get("title", "")
            if not title or not match_keywords(title, keywords):
                continue
            link = e.get("link", "")
            # 生成稳定 id：优先用 guid/id，否则用链接哈希
            eid = e.get("id") or e.get("guid") or link or title
            items.append({
                "id": f"rss:{eid}",
                "source": url.split("//")[-1].split("/")[0],
                "title": title,
                "url": link,
                "time": e.get("published", "") or e.get("updated", ""),
            })
        print(f"[ok] RSS {url} 共 {len(entries)} 条，命中 {len(items)} 条")
        return items
    except Exception as e:
        print(f"[warn] RSS {url} 抓取失败（跳过）: {type(e).__name__}: {e}")
        return []


# ---------- 推送（Server酱 → 微信） ----------

def push_serverchan(sendkey, title, desp):
    if not sendkey:
        print("[info] 未配置 SERVERCHAN_SENDKEY，本次只打印不推送")
        return False
    api = f"https://sctapi.ftqq.com/{sendkey}.send"
    try:
        r = requests.post(api, data={"title": title, "desp": desp}, timeout=HTTP_TIMEOUT)
        data = r.json()
        if data.get("code") == 0:
            print("[ok] 微信推送成功")
            return True
        print(f"[warn] 推送接口返回异常: {data}")
    except Exception as e:
        print(f"[warn] 推送失败: {type(e).__name__}: {e}")
    return False


# ---------- 主流程 ----------

def main():
    config = load_json(CONFIG_FILE, {})
    keywords = config.get("keywords", [])
    state = load_json(STATE_FILE, {"seen": {}, "first_run": True})
    seen = state.get("seen", {})

    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip() or None

    all_items = []
    for site in config.get("linuxdo_sites", []):
        all_items += fetch_discourse(site, keywords)
    for repo in config.get("github_repos", []):
        all_items += fetch_github_commits(repo, gh_token)
    for feed in config.get("rss_feeds", []):
        all_items += fetch_rss(feed, keywords)

    # 跨源去重：同一 URL 只保留一条（同一情报可能被多个源同时覆盖）
    dedup = {}
    for it in all_items:
        key = it.get("url") or it["id"]
        if key:
            dedup.setdefault(key, it)
    all_items = list(dedup.values())

    print(f"\n共采集 {len(all_items)} 条候选情报")

    # 去重：只保留未见过的
    fresh = [it for it in all_items if it["id"] not in seen]
    print(f"其中新增 {len(fresh)} 条")

    # 标记全部为已见
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for it in all_items:
        seen[it["id"]] = {"first_seen": now, "title": it["title"]}

    # 状态裁剪，防止无限增长
    if len(seen) > STATE_KEEP:
        keep = dict(list(seen.items())[-STATE_KEEP:])
        seen = keep

    state["seen"] = seen
    state["last_run"] = now
    state["last_new_count"] = len(fresh)

    if state.get("first_run", True):
        state["first_run"] = False
        save_json(STATE_FILE, state)
        print("[info] 首次运行：建立基线，不推送。下次运行起新增情报才会推送。")
        return

    save_json(STATE_FILE, state)

    if not fresh:
        print("[info] 本次无新增情报，不推送")
        return

    # 组装推送内容
    show = fresh[:MAX_PUSH_ITEMS]
    lines = [f"### 🔍 发现 {len(fresh)} 条算力情报\n"]
    for i, it in enumerate(show, 1):
        lines.append(f"**{i}. {it['title']}**")
        lines.append(f"来源: {it['source']} → [点此查看]({it['url']})\n")
    if len(fresh) > MAX_PUSH_ITEMS:
        lines.append(f"> 还有 {len(fresh) - MAX_PUSH_ITEMS} 条未展开")
    desp = "\n".join(lines)
    title = f"⚡算力情报: 新增 {len(fresh)} 条（{now}）"

    print("\n----- 推送预览 -----")
    print(desp)
    print("--------------------\n")

    push_serverchan(sendkey, title, desp)


if __name__ == "__main__":
    main()
