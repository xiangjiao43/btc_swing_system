# Sprint 1.8.2-B 重做(精确 diff,严格执行)

## Triggers(偏离建模 / 需用户决策的点)

- 1.8.2-B 初版(commit 1d5f610)被回滚 web 部分;此次按用户 5 个精确 diff 严格复制粘贴
- **未 push**:严格遵守用户红线"不许 push 到 origin/main 之前先让用户 SSH 实证看到 region-3/4 显示对"
- 全部按用户原文 diff 落字符,无任何"自由发挥"

---

## 段 1:做了什么

5 个修改,改 3 个文件:

| Mod | 文件 | 行号(改后) | 内容 |
|---|---|---|---|
| 1 | `src/web_helpers/normalize_state.py` | +79~80(新增 2 行) | `composite_factors` passthrough |
| 2A | `web/assets/app.js` | 263~272(替换 8 行 → 11 行) | `_normalize` 加 v13 检测分支 |
| 2B | `web/assets/app.js` | 274~404(新插入 131 行) | `_to_display_state_v13` + `_reverseLookupState` + `_extractGrade` + `_extractPermission` + `_extractHardInvalidations` |
| 3 | `web/assets/app.js` | 539~549(原 22 行 → 10 行) | `compositeCards()` 改 KEEP filter,只保留 `cycle_position` |
| 4 | `web/index.html` | 539~540(替换 1 行 → 2 行) | 标题"6 个"→ `compositeCards().length + ' 个'` 动态 |
| 5 | `web/index.html` | 89~123(新插入 35 行) | v13 决策摘要 section(headline + decision_time + validator + 反模式/极端事件警告条) |

文件大小变化:
- `web/index.html`: 735 → 771 行(+36)
- `web/assets/app.js`: 802 → 928 行(+126)
- `src/web_helpers/normalize_state.py`: +2 行

git diff stat:
```
src/web_helpers/normalize_state.py |   2 +
web/assets/app.js                  | 164 ++++++++++++++++++++++++++++++++-----
web/index.html                     |  38 ++++++++-
3 files changed, 184 insertions(+), 20 deletions(-)
```

红线遵守自检:
- ✅ region-1 (line 272) / region-3 (line 535) / region-4 (line 625) / region-5 (line 707) 四区全部保留
- ✅ `_to_display_state` 老 v12 路径完全没动(仍在 line ~409)
- ✅ mock/strategy_current.json fallback 完全没动
- ✅ 完全按 diff 复制粘贴,不动任何不在 diff 内的代码

---

## 段 2:用户 SSH 验证脚本

**前置**(本机已完成,等用户在服务器执行):
```bash
# 服务器侧
cd /opt/btc_swing_system   # 或用户实际路径
git pull origin main        # ⚠️ 等本地 push 后再做
sudo systemctl restart btc-swing-api
```

**验证 1 — 后端 composite_factors 透传**:
```bash
curl -s -u admin:Y_RhcxeApFa0H- http://124.222.89.86/api/strategy/current \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
state = d.get('state', {})
print('schema_version:', state.get('schema_version'))
cf = state.get('composite_factors')
print('composite_factors type:', type(cf).__name__)
if isinstance(cf, dict):
    print('keys:', list(cf.keys()))
elif isinstance(cf, list):
    print('list len:', len(cf))
else:
    print('value:', cf)
"
```
**期望**:
- 若 latest run 是 v13(orchestrator 出的) → `schema_version: v13`,`composite_factors` 可能是 `{}`(orchestrator 不写)或仍含 v12 残留 6 keys(取决于 storage 哪条 run)
- 若 latest run 是 v12 → `composite_factors` 是 6 keys 的 dict(`cycle_position / truth_trend / band_position / crowding / macro_headwind / event_risk`)

**验证 2 — 浏览器手测**:
打开 `http://124.222.89.86`(admin / Y_RhcxeApFa0H-)
- ✅ 顶部出现"当前决策"区(headline + decision_time + 状态/方向/validator)
- ✅ region-3 "组合因子" 标题应显示"X 个"(若 v13:1 个 cycle_position;若 v12:1-6 个看后端)
- ✅ region-4 "原始数据因子" 显示完整 5 组(price_technical / derivatives / onchain / macro / events)
- ✅ region-1 AI 策略建议 / 系统自检 / Footer 全部完好
- ✅ F12 console 无报错

---

## 段 3:同类风险

`_to_display_state_v13` 4 个 helpers 字段提取依赖 `supporting_data` 子结构:
- `_extractGrade`:依赖 `l3.supporting_data.opportunity_grade.value` 或 `l3.label` 前缀(`A `/`B `/`C `)
- `_extractPermission`:依赖 `l3.supporting_data.execution_permission.value`
- `_extractHardInvalidations`:依赖 `l4.supporting_data.hard_invalidation_levels.value`(数组)或直接是数组

**风险**:如果 1.10 优化了 `supporting_data` 的结构(比如把嵌套 `.value` 拍平,或字段重命名),这些 helper 会静默返回 `null` / `[]`,导致老前端组件显示"none / watch"或硬失效位空 — **不会崩,但会显示降级**。

**缓解**:
- 1.10 改 `supporting_data` schema 时,同步 review 这 4 个 helpers
- 或更长远:在 `normalize_state.py` 的 v13 路径里就把 `opportunity_grade / execution_permission / hard_invalidation_levels` 拍平到 summary_card,前端不再做 supporting_data 解析

---

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(`tests/web_helpers/` 39 pass + `tests/test_api_routes*` + `tests/test_strategy_stream_overlays_latest.py` 共 65 pass) |
| GitHub push(commit hash:xxxx) | ❌ **故意不 push** — 等用户 SSH 实证看到 region-3/4 显示对再 push |
| 服务器 git pull | 待用户执行(且 push 后) |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(纯前端 + 后端 2 行 passthrough) |

---

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `compositeCards()` 旧排序逻辑(`order` 数组 + `idxOf` helper) | `web/assets/app.js:407-422`(改前) | v1.3 orchestrator 不再产 `truth_trend / band_position / crowding / macro_headwind` 4 个 composite,KEEP filter 替代排序 |

git grep 自检(commit 前):
```bash
git grep -n "truth_trend" web/                # 期望 0
git grep -n "band_position" web/              # 期望 0
git grep -n "macro_headwind" web/             # 期望 0
git grep -n "'crowding'" web/                 # 期望 0(注:crowding 还在 normal factor 库,grep 加引号限定)
```

注:
- `cycle_position` 在 `web/` 仍保留(KEEP 数组)
- 老 `_composite_raw / compositeComposition / compositeCurrentAnalysis / compositeStrategyImpact` 等 helper **未删**(仍服务于 cycle_position 单卡显示),按用户红线"不删除任何 HTML 区域"和"不动不在 diff 内的代码"

---

## 测试记录

```
$ python -m pytest tests/test_api_routes.py tests/test_api_routes_new.py tests/test_strategy_stream_overlays_latest.py tests/web_helpers/ -q
65 passed, 132 warnings in 1.23s
```

normalize_state 单测 39/39 全过 — Mod 1 的 composite_factors passthrough 没破坏任何已有测试。

---

## 下一步

CC **故意不 push**,等用户:
1. 本地用 `python -m uvicorn src.api.app:app` 起 dev server 看 region-3/4(可选)
2. 或 push 后 SSH 服务器看(用户自己执行 `git push origin main`)
3. SSH 验证 region-3 显示对 + region-4 完整 + 浏览器无 console error → 用户认可后 push
