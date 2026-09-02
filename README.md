# 📊 Token 价格监测

7×24 自动盯各大 AI 平台的 Token 价格，一有价格变动（涨价/降价/新模型上线/下架）就推送到你微信。

**原理**：GitHub Actions 免费云服务器每 6 小时跑一次脚本 → 拉取 OpenRouter 公开接口（免费、无需 key，覆盖 400+ 模型）→ 按关注清单过滤出国产/国际旗舰模型 → 与上次价格快照对比 → 有变动才推送（Server酱 → 微信）。全程零费用。

---

## 🎯 当前监测的模型（18 个，可在 config.json 增删）

**国产**：DeepSeek V4 Pro/Flash、通义千问 Qwen3.8 Max、Kimi K3、智谱 GLM-5.3、腾讯混元 Hy4、字节豆包 Seed 2.1、美团 LongCat 2.0、MiniMax M3、百度文心 4.5、小米 MiMo V2.5 Pro、阶跃星辰 Step 3.7

**国际**：OpenAI GPT-5.5、Claude Opus 5、Gemini 3.1 Pro、xAI Grok 4.6、Meta Llama 4、Amazon Nova Premier

---

## 📁 文件说明

| 文件 | 作用 |
|---|---|
| `monitor.py` | 主程序：拉价格 → 过滤 → 对比快照 → 推送 |
| `config.json` | 监控清单 `track_models`（想加/删模型改这里）、汇率 |
| `state.json` | 价格快照（脚本自动维护，不用管） |
| `.github/workflows/monitor.yml` | 定时任务（每 6 小时，GitHub Actions） |

## 🔧 想加/删监控的模型？

编辑 `config.json` 里的 `track_models`，格式：`"模型id": "显示名称"`。

模型 id 从哪找？打开 https://openrouter.ai/models ，点进任意模型，URL 里的最后一段就是 id（含厂商前缀，如 `deepseek/deepseek-v4-pro-0813`）。

## ❓ 常见问题

**收不到推送？**
- 价格没变动时本来就不推（这是设计目标，只在变动时提醒）
- 检查 SendKey 是否填对、Actions 运行日志有无报错
- Server酱免费版每天限 5 条

**Actions 没自动跑？**
- GitHub 定时任务有 5~30 分钟随机延迟，属正常
- 长期（60 天）不活动仓库会被暂停定时任务，偶尔打开仓库网页看一眼即可

**价格单位？**
- OpenRouter 原生为美元，脚本已换算为「美元/百万token」，推送时附人民币估算（按 config.json 里 `usd_to_cny` 汇率）

**想停掉？**
- 仓库 Settings → 最底部 Danger Zone → Archive 或 Delete
