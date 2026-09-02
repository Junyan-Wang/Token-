# ⚡ GPU 算力活动监控

7×24 自动盯「送算力 / 免费额度 / 白嫖羊毛」情报，一有新动静推送到你微信。

**原理**：GitHub Actions 免费云服务器每 2 小时跑一次脚本 → 抓 linux.do 最新帖、GitHub 免费资源仓库更新、V2EX 热帖 → 关键词命中 + 去重 → 有新情报才推送（Server酱 → 微信）。全程零费用。

---

## 🚀 部署清单（明早 15 分钟）

### 第 1 步：把项目推上 GitHub

**方式 A（推荐）**：在电脑上打开 WorkBuddy 对我说：
> "按 E:\gpu-deal-monitor\deploy.md 帮我部署算力监控到 GitHub"

**方式 B（手动）**：把 `gpu-deal-monitor` 文件夹放到电脑任意位置（如 `E:\`），在文件夹上右键 → Git Bash Here，依次执行：

```bash
git init
git add .
git commit -m "init: 算力活动监控"
git branch -M main
git remote add origin https://github.com/你的用户名/gpu-deal-monitor.git
git push -u origin main
```

> 推送前先去 github.com 网页上 New repository 建一个**空仓库**（名字 `gpu-deal-monitor`，不要勾选 README）。

### 第 2 步：拿微信推送钥匙（SendKey）

1. 手机或电脑浏览器打开 **https://sct.ftqq.com**
2. 用**微信扫码**登录（免费版每天 5 条推送，够用）
3. 登录后首页就有 **SendKey**（形如 `SCT123456XXXXXXXX`），复制

### 第 3 步：把钥匙填进 GitHub

1. 打开你的仓库网页 → **Settings** → 左侧 **Secrets and variables** → **Actions**
2. 点 **New repository secret**
   - Name 填：`SERVERCHAN_SENDKEY`
   - Secret 填：刚才复制的 SendKey
3. 点 Add secret

### 第 4 步：手动跑一次验证

1. 仓库页面 → 顶部 **Actions** 标签
2. 左侧选 **GPU 算力活动监控** → 右侧 **Run workflow** 按钮点一下
3. 第一次运行会**建立基线，不推送**（正常！避免老情报轰炸）
4. 再点一次 Run workflow → 本次无新增也不推送
5. 验证推送：把仓库里 `state.json` 文件里 `"first_run": false` 改回 `true`（网页上点铅笔图标编辑），再 Run workflow，微信就会收到一条测试推送 ✅

之后它就全自动了：每 2 小时自己跑，有新情报才发微信。

---

## 📁 文件说明

| 文件 | 作用 |
|---|---|
| `monitor.py` | 主程序：抓取 → 过滤 → 去重 → 推送 |
| `config.json` | 监控配置：关键词、盯哪些源（想加源就改这里） |
| `state.json` | 去重记录（脚本自动维护，不用管） |
| `.github/workflows/monitor.yml` | 定时任务（每 2 小时，GitHub Actions） |

## ❓ 常见问题

**收不到推送？**
- 检查 SendKey 是否填对（Settings → Secrets → Actions）
- 检查 Actions 页面运行日志有没有报错
- Server酱免费版每天限 5 条，当天超额就收不到了

**Actions 没自动跑？**
- GitHub 免费额度每月 2000 分钟，本项目每月只用约 90 分钟，不会超
- 长期（60 天）不活动仓库会被暂停定时任务，偶尔打开仓库网页看一眼即可

**想改监控频率 / 关键词 / 数据源？**
- 频率：改 `.github/workflows/monitor.yml` 里的 cron
- 关键词和数据源：改 `config.json`
- 或者直接对 WorkBuddy 说需求，让 AI 改

**想停掉？**
- 仓库 Settings → 最底部 Danger Zone → Archive 或 Delete
