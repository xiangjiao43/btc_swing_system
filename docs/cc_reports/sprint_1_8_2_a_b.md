# Sprint 1.8.2-A 修 decision_time + 1.8.2-B 前端重写

**日期:** 2026-05-01
**Sprint 范围:** Part 1(1.8.2-A 收尾:decision_time UTC→BJT)+ Part 2(1.8.2-B:前端 index.html + app.js 重写消费新 schema)
**状态:** 完成,1 commit `1d5f610` push origin/main
**前置:** Sprint 1.8.2-A(commit d63206b)

---

## 0. 用户硬约束遵守

| 约束 | 状态 |
|---|---|
| 普通用户能看懂的中文 | ✅ 全部经 1.8.2-A labels 翻译,前端只透传 |
| 卡片密度 C(默认折叠 + 查看详细 ▼) | ✅ cardOpen[i] 默认 false,点击 toggleCard(i) 展开 |
| 原值显示(ADX 28 / EMA / OI 等) | ✅ supporting_data 表 value + explanation |
| 金融术语保留英文 | ✅ 翻译表只覆盖枚举,不动金融术语 |
| 不动后端(后端 1.8.2-A 完成) | ✅ 仅 normalize_state 加 keyword 参数 + strategy.py 传递,Part 1 |
| 严格按 UI 设计(不擅自加新 component) | ✅ 仅:summary_card / 警告条 / 6 layer_cards / 自检面板 |
| schema 字段名不重命名 | ✅ summary_card / layer_cards / anti_patterns_active / extreme_events_active 全沿用 |
| v12 兼容只是降级显示 | ✅ schemaVersion=='v12' → 红字提醒 banner |
| 不引入 npm / build system | ✅ 继续 Alpine.js 3.14 + Tailwind CDN,无 npm |

---

## 1. Part 1 — 1.8.2-A decision_time UTC → BJT(2 行修)

### 1.1 改动

`src/web_helpers/normalize_state.py`:
```python
# 新增导入
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
_BJT = ZoneInfo("Asia/Shanghai")

# 签名加 keyword 参数
def normalize_state(state, run_mode=None, *, generated_at_utc=None):
    ...
    # 在 _normalize_v13/_v12 后:
    bjt = _format_bjt(generated_at_utc) if generated_at_utc else None
    if bjt is None:
        bjt = _format_bjt(_decision_time(state))
    normalized["summary_card"]["decision_time"] = bjt

# 新 helper
def _format_bjt(utc_iso):
    """UTC ISO → 'YYYY-MM-DD HH:MM BJT';无效返回 None。"""
    try:
        s = str(utc_iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_BJT).strftime("%Y-%m-%d %H:%M BJT")
    except (ValueError, TypeError):
        return None
```

`src/api/routes/strategy.py::_row_to_model`:
```python
normalized = normalize_state(
    state or {}, row.get("run_mode"),
    generated_at_utc=row.get("generated_at_utc"),  # 新增
)
```

### 1.2 4 个新测试

| 测试 | 验证 |
|---|---|
| test_decision_time_format_bjt | "2026-05-01T12:48:00Z" → "2026-05-01 20:48 BJT"(UTC+8 转换) |
| test_decision_time_handles_none_generated_at_utc | 未传 → state.generated_at_utc fallback |
| test_decision_time_invalid_utc_returns_none | "not-a-date" → None,不抛 |
| test_decision_time_handles_iso_with_offset | "+00:00" 后缀也支持 |

---

## 2. Part 2 — 1.8.2-B 前端重写

### 2.1 文件改动

| 文件 | 行数变化 | 说明 |
|---|---|---|
| `web/index.html` | 735 → 261 行(-474) | 重写,只保留 sticky nav / BTC 价格 / 🩺 系统自检面板 + 新 schema 消费区 |
| `web/assets/app.js` | 802 → 178 行(-624) | 重写,Alpine app() 仅暴露 schema 字段 + 简单 fetch |

### 2.2 新 UI 结构

```
[Sticky Top Nav]                   ← 保留(BTC Strategy + 时钟 + 暗色切换)
[BTC 价格条]                        ← 保留($价格 + 24h 涨跌)
[v12 红字提醒]                       ← 新(schemaVersion=='v12' 才显示)
[🩺 系统自检面板]                     ← 保留(5 layer health + 数据源)
[决策摘要卡 summary_card]            ← 新(headline 大字 + action_state + decision_time + validator)
[警告条 anti/extreme(非空才显示)]    ← 新
[6 张 layer_cards 网格(密度 C)]    ← 新(默认折叠,查看详细 ▼ 展开)
  - 标题 + 可信度
  - 主标签(大字)+ 次要标签
  - 摘要(narrative 第一句)+ [查看详细 ▼]
  - 展开后:关键观察 / 完整分析 / 矛盾信号 / 支持数据
[Footer:schema + run_id]
```

### 2.3 删除的旧组件

| 旧组件 | 原因 |
|---|---|
| Region 1: AI 策略建议(老 evidence_reports 7 行布局) | 替代为新 summary_card + 6 layer_cards |
| Region 3: 5 张组合因子卡(TruthTrend/BandPosition/Crowding/MacroHeadwind/EventRisk) | 这 4 个 composite 1.8.1 已退役;CyclePosition 仍在,但融入 layer_cards 的 supporting_data |
| Region 4: 原始因子(5 组平铺) | 可后续 sprint 重新设计;v13 的 supporting_data 已含主要原值 |
| 老旧 AI 字段路径访问(state.adjudicator / state.evidence_reports) | normalize_state 已统一 v12/v13 |

### 2.4 app.js 数据绑定(~178 行精简版)

```js
function app() {
  return {
    // 状态
    loading: true, darkMode: false, nowBjt: '', dataSource: 'api',
    btcPrice: '—', btc24hChangePct: null, btc24hChangeText: '', btcSource: '',

    // schema 字段(从 state.* 来)
    runId: '', schemaVersion: '', decisionTime: '', headline: '',
    actionStateLabel: '', stanceLabel: '', validatorPassed: null,
    layerCards: [], antiPatternsActive: [], extremeEventsActive: [],
    systemHealth: null,

    // 卡片状态(密度 C)
    cardOpen: {},

    // 方法
    init(), toggleDark(), tickClock(),
    fetchBtcPrice(), fetchStrategy(), fetchSystemHealth(),
    applyState(state),       // 把 normalize 后的 state 解构到顶层字段
    toggleCard(idx),         // 卡片展开/收起
    formatValue(v),          // supporting_data 表值格式化
    layerHealthGlyph(h), sourceStatusGlyph(s),  // ● / ⚠ / ✗ 视觉
  };
}
```

---

## 3. pytest 输出

```
$ uv run pytest tests/
================ 980 passed, 1 skipped, 360 warnings in 8.59s ================
```

- 1.8.2-A 完成时:976 passed
- 本 sprint:Part 1 +4 tests + Part 2 不影响测试(前端代码无 pytest 覆盖)
- = **980 passed, 0 failed, 0 regression**

---

## 4. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ 980 passed, 0 failed |
| GitHub push(commit 1d5f610) | ✅ push origin/main |
| 服务器 git pull | ⏳ 待用户 SSH |
| 服务器 systemctl restart | ⏳ 待用户(API + 静态文件都需重启 nginx/uvicorn 加载新内容) |
| 生产 DB 迁移 | N/A |

**说明**:Part 1 改了后端 normalize_state + strategy.py(API 内部);Part 2
改了前端 index.html + app.js。两者都需要 service restart 才能在生产生效。

---

## 5. 用户验证脚本

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

echo "=== 1. pytest 全套 ==="
.venv/bin/pytest tests/ 2>&1 | tail -3
# 期望:980 passed, 1 skipped, 0 failed

echo ""
echo "=== 2. service restart ==="
sudo systemctl restart btc-strategy.service && sleep 5
sudo systemctl status btc-strategy.service | head -3

echo ""
echo "=== 3. curl /api/strategy/current 看 decision_time + 翻译 ==="
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
state = d['state']
print('schema:', state.get('schema_version'))
print('decision_time:', state['summary_card'].get('decision_time'))
print('headline:', state['summary_card'].get('headline'))
print('action_state_label:', state['summary_card'].get('action_state_label'))
print('layer_cards:', len(state.get('layer_cards', [])))
for c in state.get('layer_cards', []):
    print(f\"  {c['title']}: {c['label']}\")
"
# 期望:
#   schema: v13(或 v12)
#   decision_time: "2026-05-01 17:49 BJT"(BJT 格式)
#   headline / 6 layer_cards 全有

# 4. 浏览器打开
echo ""
echo "=== 4. 浏览器打开 http://124.222.89.86 ==="
echo "用户名:admin / 密码:Y_RhcxeApFa0H-"
echo "应该看到:"
echo "  - 顶部 BTC 价格 + 时钟"
echo "  - 🩺 系统自检面板(5 层 health + 数据源)"
echo "  - 决策摘要卡(headline 大字 + 中文标签)"
echo "  - 6 张 layer_cards(默认折叠,点 [查看详细 ▼] 展开)"
echo "  - 如果是 v12 行,顶部红字 ⚠️ 提醒"
```

---

## 6. 同类风险扫描

1. **性能**:30s 轮询 3 个 endpoint(strategy + btc-price + system/health-detail),
   服务器负载小,但前端在 fetchStrategy 慢(API 调 normalize_state ~0.5ms)
   时会有短暂闪烁。**1.10 可考虑**:用 SSE 替代轮询(旧版有 /api/strategy/stream),
   但 SSE 对新 schema 适配需另写。

2. **兼容性**:新 schema 删除了大量旧字段(state.evidence_reports /
   state.adjudicator / state.factor_cards 的某些子结构)。如果有外部脚本 /
   API 客户端依赖这些路径,会崩。**临时缓解**:`state.raw` 仍保留原始 v12/v13
   state,外部客户端可读 `state.raw.evidence_reports.layer_X` 等老路径。

3. **后续 1.10 待改**:
   - **原始因子(区域 4)被整体删除** — 用户可能希望保留某些表(BTC 价格历史 /
     funding 历史 / OI 历史等),1.10 重新设计
   - **factor_cards passthrough** 但前端没渲染 — 1.10 可加"原始数据"展开区
     展示历史 factor_cards
   - **lifecycle / review_generator 在 v13 路径不跑** — `/api/lifecycle/current`
     在 v13 行返回空,前端不显示;1.10 集成
   - **headline 规则只覆盖 11 种最常组合**,其他 fallback "空仓观察";
     14 状态 × 4 grade = 56 种,1.10 评估补全或简化

4. **手机端响应式**:`grid-cols-1 lg:grid-cols-2` 在 < 1024px 单列堆叠,
   layer_cards 全宽,展开内容占整屏。手机端 OK,但 supporting_data 表横排
   可能溢出 — 用户实际打开看是否需要 1.10 改 stack。

5. **实测未做截图验证**:CC 在本地无法跑 service + 浏览器渲染验证,
   只能保证 pytest 通过 + 代码合理性。**用户 SSH 打开 http://124.222.89.86
   是验证 UI 对错的唯一途径**。如果 UI 错了(例如 cardOpen 切换不灵 /
   formatValue 输出怪 / dark mode 切换坏),反馈用具体 bug 描述,我修。

---

## 7. Sprint 1.8.2 全部 commit

```
1d5f610 Sprint 1.8.2-A 修 decision_time + 1.8.2-B 前端重写  ← 本次
67858bb docs(sprint): 1.8.2-A 完整报告
d63206b Sprint 1.8.2-A: 后端 normalize_state + i18n 翻译函数(网页改造前置)
```

---

## 8. 总结

Sprint 1.8.2 整体完成 — 后端(A)+ 前端(B)端到端打通:

- ✅ Part 1:`decision_time` UTC→BJT 转换(4 新测试)
- ✅ Part 2:前端重写
  - `web/index.html` 735 → 261 行(-65%)
  - `web/assets/app.js` 802 → 178 行(-78%)
  - 完全消费 Sprint 1.8.2-A 的统一 schema(`summary_card` / `layer_cards`
    / `anti_patterns_active` / `extreme_events_active`)
  - 卡片密度 C(默认折叠 + 查看详细 ▼ 展开)
  - 中文翻译完全在后端(前端只透传)
- ✅ pytest tests/ 980 passed, 0 failed, 0 regression

普通用户打开 http://124.222.89.86 看到的应是:
- BTC 价格条 + 系统自检
- "保持空仓观察(机会一般)" 这类大字 headline(中文人话)
- 6 张可展开的层卡片,标签全中文,详细数据原值保留 + 中文解释

下一步(1.10):评估前端是否需要补 region-4 原始因子 / lifecycle 集成 /
SSE 实时推送 / headline 56 种组合补全。
