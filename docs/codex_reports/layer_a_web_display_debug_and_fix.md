# Layer A Web Display Debug And Fix

## 1. 任务目标

本轮任务名：`layer_a_web_display_debug_and_fix`。

目标是专门排查并修复网页端没有显示“大周期策略”模块的问题。本轮只处理网页展示链路和测试，不改 Layer B，不改交易逻辑，不改 thesis，不改虚拟账户，不改真实交易。

## 2. 读取和检查的关键文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `src/web_helpers/normalize_state.py`
- `src/api/routes/strategy.py`
- `src/api/models.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 3. 排查结果

### 3.1 `web/index.html` 是否插入“大周期策略”模块

已确认：有。

证据：

- `web/index.html` 中存在唯一模块：
  - `id="region-layer-a-spot"`
  - 标题文字：`大周期策略`
  - 位置在 `region-1` AI 策略建议之后、`region-layer-cards` 五层分析之前。

### 3.2 `web/assets/app.js` 是否读取并渲染 `layer_a_spot_strategy`

已确认：有。

证据：

- `spotStrategy()` 读取：
  - `this.state.layer_a_spot_strategy`
- `spotLayerCards()` 渲染 A1-A5：
  - A1 大周期阶段
  - A2 链上与宏观
  - A3 现货策略机会
  - A4 现货风险
  - A5 大周期主裁

本轮新增：

- `spotStrategyFallbackText()`，专门返回旧 run fallback 文案：
  - `暂无大周期策略，本 run 尚未记录 Layer A 输出。`

这让 fallback 不只藏在 HTML 里，也能被 app.js 测试直接覆盖。

### 3.3 API 最新状态是否返回 `layer_a_spot_strategy`

已检查。

运行命令：

```bash
uv run python -c "from src.api.app import create_app; from src.data.storage.connection import get_connection; from fastapi.testclient import TestClient; app=create_app(conn_factory=get_connection); r=TestClient(app).get('/api/strategy/current'); print(r.status_code); data=r.json(); st=data.get('state',{}); print('has_key', 'layer_a_spot_strategy' in st, 'value_type', type(st.get('layer_a_spot_strategy')).__name__, 'value', st.get('layer_a_spot_strategy')); print('run_id', data.get('run_id'))"
```

结果：

```text
200
has_key True value_type NoneType value None
run_id 9fe34412-d0ee-4892-8621-06fd3b908106
```

解释给小白：

- API 是通的。
- API 已经返回了 `layer_a_spot_strategy` 这个字段。
- 但当前最新 run 是旧数据，所以值是 `null`。
- 因此网页应该显示 fallback，而不是整个模块消失。

### 3.4 最新 `strategy_run.full_state_json` 是否包含 `layer_a_spot_strategy`

已检查本地当前配置数据库 `data/btc_strategy.db`。

运行命令：

```bash
sqlite3 data/btc_strategy.db "SELECT run_id, reference_timestamp_utc, json_type(full_state_json,'$.layer_a_spot_strategy') FROM strategy_runs ORDER BY reference_timestamp_utc DESC, generated_at_utc DESC LIMIT 3;"
```

结果显示最近 3 条 run 的第三列为空。

解释：

- 当前本地最新 run 是 Layer A 上线前的旧 run。
- `full_state_json` 里还没有 `layer_a_spot_strategy`。
- 这不是交易逻辑问题，而是数据还没经历新版本 run。
- 所以前端必须显示：
  - `暂无大周期策略，本 run 尚未记录 Layer A 输出。`

### 3.5 浏览器是否可能加载旧 `app.js`

有可能。

原因：

- 原先 `index.html` 中是：
  - `/assets/app.js`
- 浏览器或服务器缓存可能继续使用旧 JS。

本轮修复：

- 改成：
  - `/assets/app.js?v=layer-a-web-display-20260512`

这叫 cache-busting，意思是让浏览器把它当成一个新资源重新加载。

## 4. 改动文件

- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/layer_a_web_display_debug_and_fix.md`

说明：`uv.lock` 在本轮开始前已有本地未提交修改，本轮未处理、未提交。

## 5. 实际修复

1. 给 `app.js` 加版本参数，降低浏览器加载旧 JS 的概率：

```html
<script src="/assets/app.js?v=layer-a-web-display-20260512"></script>
```

2. 增加 `spotStrategyFallbackText()`：

- 旧 run 没有 `layer_a_spot_strategy` 时，网页仍显示 fallback。
- 这让 fallback 逻辑在 JS 层也能被测试覆盖。

3. HTML fallback 区域继续保留：

- `x-if="!spotStrategy()"`
- 文案：`暂无大周期策略，本 run 尚未记录 Layer A 输出。`

4. 补测试：

- `index.html` 有“大周期策略”
- `app.js` 有 `layer_a_spot_strategy` 渲染逻辑
- 旧数据无 `layer_a_spot_strategy` 时有 fallback 文案
- 大周期策略模块位于 AI 策略总览之后、五层分析之前
- Layer B 五层分析仍保持原样

## 6. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：

```text
115 passed
```

待最终提交前继续运行：

```bash
git diff --check
```

## 7. 是否影响 Layer B

不影响。

本轮没有修改：

- Layer B L1-L5
- Master
- Validator
- thesis
- 虚拟账户
- C 级机会逻辑
- 开仓、平仓、仓位、止损、止盈、反手

## 8. 是否影响真实交易

不影响。

本轮没有新增真实交易接口，没有读取或修改 API key、token、secret，没有任何真实下单逻辑。

## 9. 删除清单 / 废弃清单

本轮无替代关系，无删除项。

原因：本轮是网页展示链路修复，没有新增替代模块，也没有发现可安全删除的旧 Layer A 网页实现。

## 10. 风险和未完成

- 如果服务器还没有 `git pull` 最新代码，生产网页仍然看不到本轮修复。
- 如果浏览器强缓存了旧 HTML，需要刷新页面；本轮已给 `app.js` 加版本参数，但 HTML 本身仍需要加载到新版本。
- 当前最新本地 run 是旧数据，所以真实 Layer A 内容要等下一次新策略 run 后才会出现；旧 run 会显示 fallback。
- `uv.lock` 仍有本轮开始前就存在的本地未提交修改，本轮未处理。

## 11. 下一步建议

- 部署后打开网页强制刷新一次。
- 如果仍不显示，优先看浏览器 Network 里加载的 `app.js` 是否带 `?v=layer-a-web-display-20260512`。
- 等下一次策略 run 后，再确认 `layer_a_spot_strategy` 从 fallback 变成真实 A1-A5 内容。

## 12. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待提交后更新 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

