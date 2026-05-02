# Sprint 1.8.2-J:多周期方向一致性 — 4H/1D/1W EMA-20 斜率投票

## Triggers

- 1.8.2-H 时多周期卡按 D1 决策走 A,显示 "n/a"。本 sprint 走 (A) 方案补真算法
- 用户决策:扩展 `_emit_price_tech_primary` 签名 + 加 `compute_tf_alignment` 到 context_builder
- 算法参数确认:**EMA-20 / 0.1% 阈值 / 5 点回归**(用户原指令)
- **未 push**:遵守"PUSH 前等用户 SSH 实证才推"

## 段 1:做了什么

### 改动 2 个文件,5 处编辑(diff +99/-31)

| # | 文件:位置 | 动作 |
|---|---|---|
| 1 | `src/ai/context_builder.py:94-152` | 新增 `compute_tf_alignment(klines_4h, klines_1d, klines_1w)` 函数(58 行,放在 `compute_emas_4h` 之后,`compute_adx_14` 之前) |
| 2 | `src/strategy/factor_card_emitter.py:46-48` | import 加 `compute_tf_alignment`(改成多行 import) |
| 3 | `src/strategy/factor_card_emitter.py:293-296` | 调用点扩展:从 context 取 `klines_4h` / `klines_1w`,传给 `_emit_price_tech_primary` |
| 4 | `src/strategy/factor_card_emitter.py:1048-1054` | `_emit_price_tech_primary` 签名扩展(加 `klines_4h` / `klines_1w` 参数) |
| 5 | `src/strategy/factor_card_emitter.py:1112-1147` | 多周期卡逻辑替换(从 `l1.get("timeframe_alignment")` 改成 `compute_tf_alignment(...)`) |

### 算法实现(`compute_tf_alignment`)

```python
def compute_tf_alignment(klines_4h, klines_1d, klines_1w) -> dict:
    """4H/1D/1W EMA-20 斜率投票 → alignment 等级"""
    def slope_sign(klines):
        # guard: None / empty / 缺 close 列 / <25 行 → None
        if klines is None or klines.empty or "close" not in klines.columns:
            return None
        if len(klines) < 25:
            return None
        ema = klines["close"].astype(float).ewm(span=20, adjust=False).mean()
        last5 = ema.iloc[-5:]
        # 5 点线性回归斜率
        x = list(range(5))
        y = last5.values
        slope = (5*Σxy - Σx*Σy) / (5*Σx² - (Σx)²)
        threshold = 当前价 * 0.001
        return +1 if slope > threshold else (-1 if slope < -threshold else 0)
    
    s_4h, s_1d, s_1w = slope_sign(...) for each
    if any None → "数据不足"
    if all same sign (3) → "三周期一致" (strong)
    if 2 same sign  → "两周期一致" (weak)
    else → "三周期分歧" (none)
```

### 卡片输出格式

```
card_id:              price_tf_alignment_4h_1d_1w_<date>
current_value:        score (-3..+3) 或 None(数据不足)
plain_interpretation: 4 段动态文案,根据 level 选
impact_direction:     bullish (score>0) / bearish (score<0) / neutral
impact_weight:        0.7
linked_layer:         L1
source:               Binance klines
```

### 算法 smoke test 结果

```
all up:     {votes: [1,1,1], score: +3, level: '三周期一致', alignment: 'strong'}
all down:   {votes: [-1,-1,-1], score: -3, level: '三周期一致', alignment: 'strong'}
mixed:      {votes: [1,-1,0], score: 0, level: '三周期分歧', alignment: 'none'}
flat:       {votes: [0,0,0], score: 0, level: '三周期分歧', alignment: 'none'}
data lack:  {votes: [None,1,1], score: None, level: '数据不足'}
None pass:  {votes: [None,1,1], score: None, level: '数据不足'}
```

✅ 6 case 全部按预期分类。

## 段 2:用户 SSH 实证 + 触发新 run

### 完整验证脚本

```bash
ssh user@124.222.89.86 << 'EOF'
cd /opt/btc_swing_system
git pull origin main          # ⚠️ 等本地 push 后再做
sudo systemctl restart btc-strategy.service
sleep 5

# 步骤 1:手动验证算法(不依赖 pipeline run)
echo '=== 算法手动测试(读 DB 真实 K 线)==='
.venv/bin/python -c "
import sqlite3
import os
db_path = os.environ.get('BTC_DB', 'data/btc_strategy.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
from src.data.storage.dao import BTCKlinesDAO
k4 = BTCKlinesDAO.get_recent_as_df(conn, '4h', limit=200)
k1d = BTCKlinesDAO.get_recent_as_df(conn, '1d', limit=200)
k1w = BTCKlinesDAO.get_recent_as_df(conn, '1w', limit=200)
print(f'klines 4h={len(k4)} 1d={len(k1d)} 1w={len(k1w)}')
from src.ai.context_builder import compute_tf_alignment
print(compute_tf_alignment(k4, k1d, k1w))
"

# 步骤 2:触发新 run
echo
echo '=== POST /api/system/run-now ==='
curl -X POST -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/system/run-now
sleep 30

# 步骤 3:验证多周期卡 + ADX/ATR 一并显示真值
echo
echo '=== 多周期 + ADX/ATR 卡值 ==='
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
fc = d['state'].get('factor_cards', [])
for c in fc:
    cid = c.get('card_id', '')
    if any(k in cid for k in ['adx', 'atr_percentile', 'tf_alignment']):
        v = c.get('current_value')
        interp = (c.get('plain_interpretation') or '')[:60]
        print(f\"{c.get('name'):30s} = {v!r:>10s} | {interp}\")
"
EOF
```

期望:
- 算法手动:`{score: -3..+3, level: ..., votes: [...]}` 真数值
- run status: success
- ADX 真数值 / ATR 真分位 / **多周期 score 数字**(不再是 `'n/a'`)+ 对应 level 文案

### 浏览器手测

强刷 → region-4 → 价格技术组:**多周期方向一致性显示数字**(如 `3` / `-3` / `0`)+ 文案"三周期一致"/"两周期一致"/"三周期分歧"。

## 段 3:同类风险

1. **EMA-20 阈值 0.001 × 当前价**(0.1%)是经验值
   - BTC @$80k → 阈值 = $80。1D EMA-20 5 点回归正常波动 $50-200,阈值在合理范围
   - 可能"过严"(把弱趋势归为 0)或"过松"(把噪音归为 ±1),需要生产观察
   - 1.10 加单测覆盖 trend / range / chaos 三种 regime 校准阈值

2. **1W K 线数据依赖**
   - `compute_tf_alignment` 要求每周期 ≥ 25 行
   - 1W 25 行 ≈ 25 周(约半年)。系统已运行 3+ 月可能不足 → 显示"数据不足"
   - 实证后如发现数据不足,需要回填 1W 历史 K 线

3. **跨模块依赖再加深**
   - 1.8.2-H 已加 `strategy → ai`(import compute_adx_14, compute_atr_features)
   - 本 sprint import 列表加 `compute_tf_alignment`,**无新跨模块**,符合既有模式
   - 1.10 长期方案:context_builder 纯计算函数提到 `src/indicators/` 共用

4. **重复计算**
   - context_builder 在 orchestrator 阶段算过 `compute_emas_4h` (4h EMA),emitter 又用 `compute_tf_alignment` 重算 4h+1d+1w 的 EMA-20
   - 单次成本 < 1ms,无性能问题
   - 1.10 优化方案见 1.8.2-H 段 3 同条

5. **`current_value` 类型**
   - 旧:`alignment_value` 可能是 `"n/a"` (字符串)或 `score` (int)
   - 新:`alignment_score` 始终是 `int (-3..+3)` 或 `None`
   - **类型变化**:前端 region-4 渲染如果对此 card 做 `formatFactorValue` 类似数字处理,行为应改善(不再显示字符串 "n/a")
   - 没改前端,Alpine `x-text` 会按值的字符串表达显示("3" / "0" / "null"),**注意 None 显示文本待用户验证**

6. **算法对早期 EMA 初始化敏感**
   - EMA-20 前 30 根受 `adjust=False` 初始化偏差影响
   - 25 根门槛可能略小,但 5 点回归只看末 5 根,初始化偏差影响有限

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 980 passed, 1 skipped, 360 warnings in 9.18s |
| 算法 smoke test | ✅ 6 case 全部按预期分类(手测 trending/mixed/flat/insufficient 路径) |
| GitHub push(commit hash:见末尾) | ❌ **故意不 push** — 等用户 SSH 算法手动测 + run-now 验证 + 浏览器看真值后才推 |
| 服务器 git pull | 待用户执行(且 push 后) |
| 服务器 systemctl restart | 待用户执行 |
| 触发 pipeline 新 run | 待用户执行(`POST /api/system/run-now`) |
| 生产 DB 迁移 / 清污 | N/A(纯算法 + emitter 改动) |

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 旧多周期卡逻辑(`l1.get("timeframe_alignment") / "tf_alignment" / "multi_tf_alignment"` 三段 fallback)+ Sprint 1.5c 注释 | `src/strategy/factor_card_emitter.py:1112-1145`(原) | v13 layer1 不再产 timeframe_alignment / tf_alignment / multi_tf_alignment 任何字段(layer1 改 AI 输出),旧 fallback 永远 None |

**git grep 自检**(commit 前):
```bash
$ grep -n "timeframe_alignment\|tf_alignment\|multi_tf_alignment" src/strategy/factor_card_emitter.py
(empty in 1112-1145 area; 仅 line 443/459 在 _is_low_freshness_threshold 函数内的 freshness 判定 — 不影响,保留)
```

旧 alignment fallback 已彻底移除,新算法直接调 `compute_tf_alignment`。

## 测试记录

```
$ python -m pytest tests/ -q --tb=short
980 passed, 1 skipped, 360 warnings in 9.18s
```

完整 980 测试通过 — 新算法 + 签名扩展无影响。算法 smoke test 6/6 case 验证通过(段 1 末尾)。

## 下一步

CC 故意不 push,等用户:
1. 主动 `git push origin main` 后 SSH 服务器
2. 执行算法手动测试(段 2 步骤 1)— 看真实 DB 1W 数据是否够 25 周
3. `restart` + `curl -X POST .../run-now` 触发新 run
4. 实证多周期卡显示真分类 / score 数字,浏览器 region-4 看到对应文案
5. 用户认可 → push 9 个 commit:1.8.2-B/C/D/D.1/E/G/H/I + 本 commit (1.8.2-J)
