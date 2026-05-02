# Sprint 1.8.2-H:修 ADX/ATR 因子卡数据源(emitter 改用 context_builder)

## Triggers

- v13 layer1 改 AI 输出后,不再返回客观计算值(`adx_14_1d` / `atr_percentile_180d`)
- emitter 仍按 v12 假设 `l1.get("adx_14_1d")` → 永远 None → region-4 ADX/ATR 卡显示 "n/a"
- 1.8.2-H 修复:emitter 直接调 `context_builder.compute_adx_14()` / `compute_atr_features()` 重算
- 多周期方向一致性卡按用户决策走 A:**不动,继续显示 n/a**(待 1.10 决策是否在 context_builder 加新函数 + 1W 数据采集)
- **新跨模块依赖披露**:`src/strategy/` → `src/ai/`,本仓库**首次**出现(grep 验证 strategy 历史 0 处 import ai)
- **未 push**:遵守"PUSH 前等用户 SSH 实证才推"

## 段 1:做了什么

### 改动 1 个文件,4 处编辑(diff +10/-4)

| 处 | 文件:位置 | 动作 |
|---|---|---|
| 1 | `src/strategy/factor_card_emitter.py:42-45` | 顶部加 `from src.ai.context_builder import compute_adx_14, compute_atr_features` + 2 行注释披露 |
| 2 | `src/strategy/factor_card_emitter.py:1049-1052` | ADX 数据来源:`l1.get("adx_14_1d")` → `compute_adx_14(klines_1d).get("adx_current")` |
| 3 | `src/strategy/factor_card_emitter.py:1073-1075` | ATR 数据来源:`l1.get("atr_percentile_180d")` → `compute_atr_features(klines_1d).get("atr_180d_percentile")` |
| 4 | (无改动) | 多周期方向一致性 line 1100-1131 完全不动(走 D1 决策 A) |

```
$ git diff --stat src/strategy/factor_card_emitter.py
src/strategy/factor_card_emitter.py | 14 ++++++++++----
1 file changed, 10 insertions(+), 4 deletions(-)
```

### 跨模块依赖披露(用户红线要求)

```
$ grep -nE "from src\.ai|from \.\.ai|import.*src\.ai|import.*\.ai" src/strategy/*.py
(empty before this commit)
```

**本 commit 是 `src/strategy/` 模块首次 import `src/ai/`**。理由(按用户红线"不改 layer1 AI prompt / 不改 context_builder 算法"):
- v13 设计意图是 layer1 输出 AI judgment(regime/confidence),客观计算值由 context_builder 单独提供
- emitter 之前的 v12 假设(layer1 也返客观值)在 v13 不成立
- 修复的最小路径是让 emitter 直接复用 context_builder 的纯函数(无副作用,接受 DataFrame 返 dict),避免改 layer1 prompt 或在 emitter 内重写算法

潜在问题:**重复计算**(orchestrator 阶段 context_builder 算过 1 次,emitter 再算 1 次)。低成本(纯 numpy + 30 行 DataFrame)但不优雅。**1.10 优化方案**:orchestrator 把 `computed_indicators` 写到 context dict,emitter 通过 `context["computed_indicators"]` 读取,避免重复。本 sprint 红线"不改 orchestrator",留作后续。

## 段 2:用户 SSH 验证 + 触发新 run

### 触发方式(CC 推荐 3 选 1)

| 方式 | 命令 | 优劣 |
|---|---|---|
| **(a) 推荐** | `curl -X POST -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/system/run-now` | 立刻跑,通过 API,无需重启 |
| (b) 等 cron | 等 16:05 BJT 自动跑(今日 / 明日) | 无需手动操作但慢 |
| (c) restart | `sudo systemctl restart btc-strategy.service` | 重启不会自动跑 pipeline,只重载代码;还需走 (a) 或 (b) |

### 完整验证脚本

```bash
ssh user@124.222.89.86 << 'EOF'
cd /opt/btc_swing_system
git pull origin main          # ⚠️ 等本地 push 后再做
sudo systemctl restart btc-strategy.service
sleep 3

# 触发新 run(用方式 a)
echo '=== POST /api/system/run-now ==='
curl -s -X POST -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/system/run-now
sleep 30  # pipeline 跑完约 20-30 秒

# 验证 ADX/ATR 卡的 current_value 不再是 None
echo
echo '=== ADX-14 + ATR percentile + tf_alignment cards ==='
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -c "
import sys, json
s = json.load(sys.stdin)['state']
fcs = s.get('factor_cards') or []
targets = ['price_adx_14_1d', 'price_atr_percentile_180d', 'price_tf_alignment_4h_1d_1w']
for t in targets:
    matches = [c for c in fcs if c.get('card_id', '').startswith(t)]
    if matches:
        c = matches[0]
        print(f\"{t}: value={c.get('current_value')!r}\")
    else:
        print(f\"{t}: <missing>\")"
EOF
```

**期望输出**:
```
price_adx_14_1d:                value=23.7   (或类似真数值,**不再是 None / 'n/a'**)
price_atr_percentile_180d:      value=55     (或类似 0-100 真分位)
price_tf_alignment_4h_1d_1w:    value='n/a'  (D1 决策 A:不修)
```

### 浏览器手测

强刷 http://124.222.89.86 → region-4 → "价格技术" 组:
- ✅ ADX-14(1D) 显示真数值(如 23.7)
- ✅ ATR 180 日分位 显示真分位(如 55%)
- ⚪ 多周期方向一致性 仍显示 "n/a"(D1 决策 A 保持现状)

## 段 3:同类风险

1. **多周期方向一致性卡仍 n/a**(D1 决策 A 已知妥协)
   - 待 1.10 决策:是否在 context_builder 加 `compute_tf_alignment()` + 让 collector 拉 1W K 线
   - 当前用户 region-4 看到 "n/a" + "数据不足或各周期方向分歧" 兜底文案

2. **重复计算**(orchestrator 算 1 次 + emitter 又算 1 次)
   - 低成本(纯 numpy DataFrame 操作),但浪费
   - 1.10 改 orchestrator 把 computed_indicators 写到 context,emitter 共享读取

3. **跨模块依赖披露**(`src/strategy/` 首次 import `src/ai/`)
   - 本 sprint 是首次,后续若 strategy 还需 ai 其他工具,会更深耦合
   - 长期看 context_builder 的纯计算函数应该提取到 `src/indicators/` 共用模块,strategy 和 ai 都从那里 import — 但属于架构重构,本 sprint 不做

4. **`compute_adx_14` 需要 ≥ 30 行 klines_1d / `compute_atr_features` 需要 ≥ 14 行**
   - 数据不足时返回字段为 None → emitter `adx = None` → 卡显示 None
   - 与原代码行为一致(原代码 `l1.get("adx_14_1d")` 也会返 None),无回归

5. **`compute_atr_features` 实际上是 ATR 系列+分位+当前值的"全套"计算**
   - emitter 只用了 `atr_180d_percentile` 一个字段
   - 性能上 14 行 ATR 系列计算 + 180 行 percentile 滚动 = 微秒级,无问题

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 980 passed, 1 skipped, 360 warnings in 9.71s |
| GitHub push(commit hash:见末尾) | ❌ **故意不 push** — 等用户 SSH 实证 ADX/ATR 显示真数值 + 多周期仍 n/a 后才推 |
| 服务器 git pull | 待用户执行(且 push 后) |
| 服务器 systemctl restart | 待用户执行(只重载代码;新 factor_cards 需触发 pipeline,见段 2) |
| 触发 pipeline 新 run | 待用户执行(`POST /api/system/run-now` 或等 16:05 cron) |
| 生产 DB 迁移 / 清污 | N/A(emitter 改动,DB schema 不变) |

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| (无) | — | 本 sprint 是 hot-fix,只替换 `l1.get(...)` 数据源,无函数 / 文件 / 字段删除 |

**本 sprint 无替代关系,无删除项**。

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
980 passed, 1 skipped, 360 warnings in 9.71s
```

完整 980 测试通过 — 新 import + 数据源替换无影响。

## 下一步

CC 故意不 push,等用户:
1. 主动 `git push origin main` 后 SSH 服务器
2. `sudo systemctl restart btc-strategy.service` + `curl -X POST .../run-now` 触发新 run
3. 实证 region-4 ADX/ATR 卡显示真数值
4. 用户认可 → push 7 个 commit:1.8.2-B + 1.8.2-C + 1.8.2-D + 1.8.2-D.1 + 1.8.2-E + 1.8.2-G + 本 commit (1.8.2-H)
