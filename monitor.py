#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token 价格监测
==============
定时拉取 OpenRouter 公开接口（openrouter.ai/api/v1/models，免费无需 key），
获取 400+ 大模型的实时价格，按 config.json 的 track_models 清单过滤出
关注的国产/国际旗舰模型，与 state.json 中的价格快照对比，发现
「价格变动 / 新模型上线 / 模型下架」即通过 Server酱 推送到微信。

用法：
    python monitor.py

环境变量（均可选）：
    SERVERCHAN_SENDKEY   Server酱的 SendKey，未配置时只打印日志不推送
    GITHUB_TOKEN         GitHub API token，Actions 里自动注入（本脚本未用，保留占位）
"""

import json
import os
import datetime
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")

OPENROUTER_API = "https://openrouter.ai/api/v1/models"
HTTP_TIMEOUT = 30
MAX_PUSH_ITEMS = 20       # 单次最多推送的变动条数（防轰炸）
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


def _to_num(x):
    """把价格字段（可能是 float 或 str）安全转为 float，失败返回 None"""
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fmt(usd_per_mtok):
    """格式化：美元/百万token，保留 4 位小数"""
    if usd_per_mtok is None:
        return "?"
    return f"${usd_per_mtok:.4f}"


def _fmt_cny(usd_per_mtok, rate):
    """格式化：人民币/百万token（按固定汇率估算）"""
    if usd_per_mtok is None or not rate:
        return "?"
    return f"¥{usd_per_mtok * rate:.3f}"


# ---------- 数据获取 ----------

def fetch_openrouter_prices():
    """拉取 OpenRouter 全量模型价格。

    返回 dict: { model_id: {"name": ..., "prompt": float, "completion": float} }
    prompt/completion 单位已换算为「美元/百万token」。
    """
    try:
        r = requests.get(OPENROUTER_API, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", []) or []
    except Exception as e:
        print(f"[warn] 拉取 OpenRouter 失败（跳过）: {type(e).__name__}: {e}")
        return None

    models = {}
    for m in data:
        mid = m.get("id", "")
        if not mid:
            continue
        pricing = m.get("pricing", {}) or {}
        prompt = _to_num(pricing.get("prompt"))
        completion = _to_num(pricing.get("completion"))
        # 换算成 美元/百万token（原值是 美元/token）
        models[mid] = {
            "name": m.get("name", mid),
            "prompt": prompt * 1e6 if prompt is not None else None,
            "completion": completion * 1e6 if completion is not None else None,
        }
    print(f"[ok] OpenRouter 拉取成功，共 {len(models)} 个模型")
    return models


# ---------- 对比 ----------

def compare_prices(track_models, current, previous):
    """对比当前价格与快照，返回变动列表。

    返回 list of dict，每项：
      { "kind": "change"|"new"|"removed", "label", "id",
        "prompt_old", "prompt_new", "completion_old", "completion_new" }
    其中 old/new 单位均为 美元/百万token。
    """
    changes = []
    for mid, label in track_models.items():
        cur = current.get(mid)
        prev = previous.get(mid)

        if cur is None:
            # 当前接口里已无此模型
            if prev is not None:
                changes.append({
                    "kind": "removed", "label": label, "id": mid,
                    "prompt_old": prev.get("prompt"), "completion_old": prev.get("completion"),
                    "prompt_new": None, "completion_new": None,
                })
            continue

        if prev is None:
            # 快照里没有，属于新上线的模型
            changes.append({
                "kind": "new", "label": label, "id": mid,
                "prompt_old": None, "completion_old": None,
                "prompt_new": cur.get("prompt"), "completion_new": cur.get("completion"),
            })
            continue

        # 价格变动检测（容忍极小浮点误差）
        p_changed = _differs(prev.get("prompt"), cur.get("prompt"))
        c_changed = _differs(prev.get("completion"), cur.get("completion"))
        if p_changed or c_changed:
            changes.append({
                "kind": "change", "label": label, "id": mid,
                "prompt_old": prev.get("prompt"), "completion_old": prev.get("completion"),
                "prompt_new": cur.get("prompt"), "completion_new": cur.get("completion"),
            })
    return changes


def _differs(a, b):
    """判断两个价格是否不同（容忍浮点误差，None 视为不同）"""
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(a - b) > 1e-9


# ---------- 推送 ----------

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


def _pct(old, new):
    """计算涨跌幅百分比，返回字符串如 "+12.3%" / "-5.0%"；old<=0 时返回 None"""
    if old is None or new is None or old <= 0:
        return None
    return (new - old) / old * 100.0


def _build_desp(changes, rate):
    """根据变动列表构建推送正文（Markdown）"""
    lines = [f"### 📊 检测到 {len(changes)} 项 Token 价格变动\n"]
    for i, ch in enumerate(changes[:MAX_PUSH_ITEMS], 1):
        label = ch["label"]
        if ch["kind"] == "removed":
            lines.append(f"**{i}. {label}**  🚫 已下架")
            if ch["prompt_old"] is not None:
                lines.append(f"- 原输入 {_fmt(ch['prompt_old'])} / 输出 {_fmt(ch['completion_old'])}")
        elif ch["kind"] == "new":
            lines.append(f"**{i}. {label}**  🆕 新上线")
            lines.append(
                f"- 输入 {_fmt(ch['prompt_new'])} / 输出 {_fmt(ch['completion_new'])}"
            )
        else:
            p_pct = _pct(ch["prompt_old"], ch["prompt_new"])
            c_pct = _pct(ch["completion_old"], ch["completion_new"])
            arrow_p = _arrow(p_pct)
            arrow_c = _arrow(c_pct)
            lines.append(f"**{i}. {label}**")
            if p_pct is not None:
                lines.append(
                    f"- 输入: {_fmt(ch['prompt_old'])} → {_fmt(ch['prompt_new'])} {arrow_p}{p_pct:+.1f}%"
                )
            if c_pct is not None:
                lines.append(
                    f"- 输出: {_fmt(ch['completion_old'])} → {_fmt(ch['completion_new'])} {arrow_c}{c_pct:+.1f}%"
                )
        lines.append("")
    if len(changes) > MAX_PUSH_ITEMS:
        lines.append(f"> 还有 {len(changes) - MAX_PUSH_ITEMS} 项未展开")
    lines.append("\n> 单位：美元/百万token；人民币按 1 USD ≈ " + f"{rate} CNY 估算")
    lines.append("> 数据源: OpenRouter")
    return "\n".join(lines)


def _arrow(pct):
    """涨价用红色▲，降价用绿色▼（国内习惯：涨红跌绿）"""
    if pct is None:
        return ""
    return "🔴 " if pct > 0 else "🟢 "


# ---------- 主流程 ----------

def main():
    config = load_json(CONFIG_FILE, {})
    track_models = config.get("track_models", {})
    rate = config.get("usd_to_cny", 7.2)

    if not track_models:
        print("[warn] config.json 未配置 track_models，退出")
        return

    state = load_json(STATE_FILE, {"first_run": True, "prices": {}})
    previous = state.get("prices", {}) or {}

    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()

    current = fetch_openrouter_prices()
    if current is None:
        print("[warn] 本次拉取失败，不更新快照、不推送")
        return

    changes = compare_prices(track_models, current, previous)
    print(f"\n关注模型 {len(track_models)} 个，检测到 {len(changes)} 项变动")

    # 更新快照：把关注模型的最新价格写回
    new_prices = {}
    for mid, label in track_models.items():
        cur = current.get(mid)
        if cur is not None:
            new_prices[mid] = {
                "prompt": cur.get("prompt"),
                "completion": cur.get("completion"),
            }
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    state["prices"] = new_prices
    state["last_run"] = now

    if state.get("first_run", True):
        state["first_run"] = False
        save_json(STATE_FILE, state)
        print("[info] 首次运行：建立价格基线，不推送。下次起价格变动才会推送。")
        print("      当前基线价格：")
        for mid, p in new_prices.items():
            print(f"        {track_models.get(mid, mid)}: 输入 {_fmt(p['prompt'])} / 输出 {_fmt(p['completion'])}")
        return

    save_json(STATE_FILE, state)

    if not changes:
        print("[info] 本次无价格变动，不推送")
        return

    desp = _build_desp(changes, rate)
    title = f"📊 Token价格监测: {len(changes)} 项变动（{now}）"

    print("\n----- 推送预览 -----")
    print(desp)
    print("--------------------\n")

    push_serverchan(sendkey, title, desp)


if __name__ == "__main__":
    main()
