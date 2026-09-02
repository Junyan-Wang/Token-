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
import re
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


def match_keywords(text, keywords, neg_keywords=None):
    """关键词命中（大小写不敏感），且排除否定词。

    正向命中：标题含任一福利关键词；
    否定排除：标题含任一否定词（辟谣/翻车/停运等）则视为无效情报，
    避免把"某平台免费额度被砍"这类负面消息当福利推送。
    """
    if not text:
        return False
    low = text.lower()
    if not any(str(k).lower() in low for k in keywords):
        return False
    if neg_keywords and any(str(k).lower() in low for k in neg_keywords):
        return False
    return True


# ---------- 数据源 1：Discourse 论坛（linux.do） ----------

def fetch_discourse(base, keywords, neg_keywords=None):
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
            if not title or not match_keywords(title, keywords, neg_keywords):
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

def extract_added_resources(patch):
    """从 resources.json 的 diff patch 中提取「新增资源」条目。

    只在新增行（+ 开头）里识别 `"name"` 字段，避免把巡检导致的
    status / free_tier 等字段变化误判为新增资源。
    返回：[{"name", "url", "description", "free_tier"}, ...]
    """
    if not patch:
        return []
    added = []
    cur = None
    for raw in patch.split("\n"):
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if not raw.startswith("+"):
            # 遇到非新增行，收尾上一个未闭合对象
            if cur and cur.get("name"):
                added.append(cur)
            cur = None
            continue
        line = raw[1:].strip()
        m = re.search(r'"name"\s*:\s*"([^"]+)"', line)
        if m:
            if cur and cur.get("name"):
                added.append(cur)  # 上一个新增对象收尾
            cur = {"name": m.group(1)}
            continue
        if cur is not None:
            m = re.search(r'"url"\s*:\s*"([^"]+)"', line)
            if m and "url" not in cur:
                cur["url"] = m.group(1)
            m = re.search(r'"free_tier"\s*:\s*"([^"]+)"', line)
            if m and "free_tier" not in cur:
                cur["free_tier"] = m.group(1)
            m = re.search(r'"description"\s*:\s*"([^"]+)"', line)
            if m and "description" not in cur:
                cur["description"] = m.group(1)
    if cur and cur.get("name"):
        added.append(cur)
    return added


def _get_commit_detail(repo, sha, headers):
    """拉取单个 commit 的文件级 diff"""
    api = f"https://api.github.com/repos/{repo}/commits/{sha}"
    try:
        r = requests.get(api, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[warn] 获取 commit {sha[:8]} 详情失败: {type(e).__name__}: {e}")
        return None


def _extract_added_from_commit(detail):
    """从 commit 详情的 files 数组中，汇总 resources.json 里新增的资源"""
    files = detail.get("files", []) or []
    added = []
    for f in files:
        fn = f.get("filename", "")
        if fn.endswith("resources.json"):
            added += extract_added_resources(f.get("patch", ""))
    return added


def fetch_github_commits(repo, token=None):
    """监控 GitHub 仓库的「新增免费资源」，而非所有 commit。

    逐个拉取最新 commit 的文件级 diff，只在 data/resources.json 出现
    新增资源条目（新增 `"name"` 字段）时才生成情报，并附带免费额度摘要。
    例行巡检类 commit（只改 status.json / 无新增资源）会被跳过。
    """
    api = f"https://api.github.com/repos/{repo}/commits?per_page=5"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "gpu-deal-monitor"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(api, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        commits = r.json()
        items = []
        for c in commits:
            sha = c.get("sha", "")
            if not sha:
                continue
            detail = _get_commit_detail(repo, sha, headers)
            if detail is None:
                continue
            added = _extract_added_from_commit(detail)
            if not added:
                # 无新增资源（纯巡检/维护），跳过，不推送
                continue
            names = [a.get("name", "?") for a in added]
            title = f"新增免费资源: {'、'.join(names[:5])}"
            if len(names) > 5:
                title += f" 等 {len(names)} 个"
            items.append({
                "id": f"github:{repo}:{sha[:12]}",
                "source": f"GitHub·{repo.split('/')[-1]}",
                "title": title,
                "url": c.get("html_url", ""),
                "time": c.get("commit", {}).get("author", {}).get("date", ""),
                "added": added,  # 附带详情，供推送摘要展开
            })
        print(f"[ok] {repo} 最近 {len(commits)} 个 commit，含新增资源 {len(items)} 个")
        return items
    except Exception as e:
        print(f"[warn] {repo} 抓取失败（跳过）: {type(e).__name__}: {e}")
        return []


# ---------- 数据源 3：RSS / Atom 订阅 ----------

def fetch_rss(url, keywords, neg_keywords=None):
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
            if not title or not match_keywords(title, keywords, neg_keywords):
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
    neg_keywords = config.get("negative_keywords", [])
    state = load_json(STATE_FILE, {"seen": {}, "first_run": True})
    seen = state.get("seen", {})

    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip() or None

    all_items = []
    for site in config.get("linuxdo_sites", []):
        all_items += fetch_discourse(site, keywords, neg_keywords)
    for repo in config.get("github_repos", []):
        all_items += fetch_github_commits(repo, gh_token)
    for feed in config.get("rss_feeds", []):
        all_items += fetch_rss(feed, keywords, neg_keywords)

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
    lines = [f"### 🔍 发现 {len(fresh)} 条算力福利\n"]
    for i, it in enumerate(show, 1):
        lines.append(f"**{i}. {it['title']}**")
        # GitHub 源附带新增资源详情，直接展开免费额度，一眼可判是否福利
        for a in it.get("added", [])[:5]:
            name = a.get("name", "?").strip()
            ft = a.get("free_tier", "").strip()
            url = a.get("url", "").strip()
            if ft:
                lines.append(f"- {name}：{ft}")
            elif url:
                lines.append(f"- {name}：{url}")
            else:
                lines.append(f"- {name}")
        lines.append(f"来源: {it['source']} → [点此查看]({it['url']})\n")
    if len(fresh) > MAX_PUSH_ITEMS:
        lines.append(f"> 还有 {len(fresh) - MAX_PUSH_ITEMS} 条未展开")
    desp = "\n".join(lines)
    title = f"⚡算力福利: 新增 {len(fresh)} 条（{now}）"

    print("\n----- 推送预览 -----")
    print(desp)
    print("--------------------\n")

    push_serverchan(sendkey, title, desp)


if __name__ == "__main__":
    main()
