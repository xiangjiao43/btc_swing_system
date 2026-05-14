# fix_layer_a_cpi_core_cpi_factor_display

## 1. 任务目标

修复网页「原始数据因子」模块中 CPI / Core CPI 显示为 `-`、红点或不可用的问题。本轮只处理 CPI / Core CPI，不改 Layer A A1-A5 策略 prompt，不改 Layer B，不改交易规则。

## 2. 问题原因

本轮检查发现：

1. 生产数据库 `macro_metrics` 中已经有 CPI / Core CPI 真实值：
   - `cpi = 332.407`
   - `core_cpi = 335.423`
2. 生产 `latest_layer_a_spot_strategy.layer_a_json.input_context_snapshot` 中也已经包含：
   - `macro_inflation_rates.cpi.status = available`
   - `macro_inflation_rates.core_cpi.status = available`
3. 因此问题不是 FRED collector 缺失，也不是数据未入库。
4. 风险点主要在两处：
   - CPI / Core CPI 是月度数据，不能被源级短频 freshness 误判成过期。
   - 前端只读取 `input_context_snapshot`，对旧/兼容结构缺少 fallback，可能导致卡片拿不到值。

结论：本轮修复为“月度 freshness 保护 + CPI/Core CPI key 兼容 + 前端读取路径兼容 + app.js cache busting”。

## 3. CPI / Core CPI 数据流检查结果

| 环节 | 检查结果 |
|---|---|
| `config/data_catalog.yaml` | 已登记 `fred_cpi` / `fred_core_cpi`，series 为 `CPIAUCSL` / `CPILFESL`，frequency 为 monthly |
| `config/data_sources.yaml` | FRED 数据源已配置，timeout 为 15 秒 |
| `src/data/collectors/fred.py` | `CPIAUCSL -> cpi`，`CPILFESL -> core_cpi` |
| 生产 DB `macro_metrics` | 已有 CPI / Core CPI 真实值 |
| Layer A context | 最新独立 Layer A 结果中 CPI / Core CPI 均为 available |
| factor_coverage | 最新 Layer A coverage 中可用因子计数正常，CPI / Core CPI 未被列入 unavailable |
| plain_reading | 已支持 CPI / Core CPI，并本轮调整为更清晰的月度宏观说明 |
| 网页 `app.js` | 本轮增加兼容读取 `input_context_snapshot` / `spot_cycle_context` / `context` |

## 4. 修复文件

| 文件 | 说明 |
|---|---|
| `src/ai/spot_cycle_context_builder.py` | 增加 CPI / Core CPI 月度 freshness 保护；增加 FRED series id 旧 key 兼容 |
| `src/evidence/plain_reading.py` | 调整 CPI / Core CPI deterministic 人话说明 |
| `web/assets/app.js` | 原始因子卡片兼容读取 Layer A context 的多种位置；同步 CPI / Core CPI 说明 |
| `web/index.html` | 更新 app.js 版本参数，避免旧缓存继续显示旧逻辑 |
| `tests/test_layer_a_spot_context_builder.py` | 增加月度 freshness 与旧 series id 兼容测试 |
| `tests/test_plain_reading.py` | 增加 CPI / Core CPI 人话说明测试 |
| `tests/test_web_modules_1_2_3.py` | 更新 app.js cache-busting 测试 |
| `tests/test_web_modules_4_5_rp_failure.py` | 增加前端 context fallback 和说明文案测试 |

## 5. 月度 freshness 处理

CPI / Core CPI 是 FRED 月度宏观数据。最新一期数据存在时，即使源级 `fred_macro` freshness 短暂显示 stale，也不应把它们判成不可用。

本轮增加：

- `freshness.frequency = "monthly"`
- `freshness.monthly_latest_ok = true`
- 有真实值时保持 `status = available`

这只影响 CPI / Core CPI，不改变其它宏观因子。

## 6. 网页显示修复

修复后，网页 raw factor 卡片应显示：

- CPI：数值、说明、状态、抓取时间
- Core CPI：数值、说明、状态、抓取时间

说明仍然由 deterministic plain_reading / 前端模板生成，不调用 AI，不显示 raw key、proxy error 或内部异常。

## 7. 实际运行命令和结果

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_plain_reading.py
# 39 passed

uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
# 118 passed

uv run pytest -q tests/test_layer_a_key_factor_collectors.py
# 4 passed

git diff --check
# passed
```

只读生产检查：

- 服务器最新代码：`1dcca03 Add AI fallback handling for pipeline agents`
- `macro_metrics` 中 CPI / Core CPI 有真实值
- `latest_layer_a_spot_strategy` 中 CPI / Core CPI 均为 `available`
- 未读取或输出 `.env`、API key、token、secret

## 8. 是否影响高风险区域

| 项目 | 结果 |
|---|---|
| 是否影响 Layer A 策略逻辑 | 否，只修 context/网页显示和 deterministic 说明 |
| 是否影响 Layer B | 否 |
| 是否影响虚拟账户 | 否 |
| 是否影响真实交易 | 否 |
| 是否改 AI prompt | 否 |
| 是否真实下单 | 否 |

## 9. 删除清单 / 废弃清单

本轮无替代关系，无删除项。原因：本轮为 CPI / Core CPI 显示链路修复，没有引入替代实现，也没有发现可安全删除的旧逻辑。

## 10. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 提交并 push 后以对话最终回执和审查包 metadata 为准 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 11. 风险和未完成

1. 本轮没有自动跑长时间 Layer A pipeline，避免再次卡在 AI provider。
2. 生产数据库当前已经有 CPI / Core CPI 值；如果用户刷新后仍看到 `-`，优先检查浏览器缓存、服务是否已 pull 最新 commit、app.js 版本参数是否更新。
3. `/api/strategy/current` 线上有 Basic Auth，Codex 未输出认证信息，也未绕过认证。

## 12. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

然后刷新：

```text
http://124.222.89.86/
```
