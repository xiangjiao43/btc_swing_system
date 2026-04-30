# Sprint 1.5n — 网页主战场重构(自检面板 + 数据源健康 + 持仓预演 + 五层折叠)

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,13 个新测试 + 958/958 全量回归过

---

## 一、根因(用户 SSH 部署 1.5m 后审视)

1. **五层证据链区**(L1-L5)95% 是给开发者看的内部推导,但 5% 是有价值的
   健康信号(missing / degraded / data_freshness)。需要把健康信号抽出来,
   推导细节默认折叠。

2. **顶栏数据健康**只有一个 FALLBACK 灯,看不出每个数据源最新一次抓取多
   少分钟前。需求"数据是否按要求抓取"要这个一眼判断。

3. **当前 FLAT 状态下**,LONG_PLANNED / 持仓时网页该长什么样,完全看不到 —
   用户对系统建立信任需要看到"系统在不同状态下分别给出什么"。

4. **历史与复盘区**当前没有任何 lifecycle 完成,显示空内容,占主屏空间。

---

## 二、改动

### 任务 A.1:后端 `/api/system/health-detail`(commit `60dc0c1`)

`src/api/routes/system.py` 新增 endpoint。响应结构:

```json
{
  "evidence_layers": [
    {"layer_id": 1, "name": "市场状态层", "health": "healthy",
     "pillars_summary": "3/3 支柱齐", "missing_reasons": []},
    ...
  ],
  "data_sources": [
    {"name": "Binance K 线 (1h)", "status": "ok", "age_minutes": 12.5,
     "captured_at_bjt": "2026-04-30 12:15 (BJT)",
     "expected_cadence": "每 1 小时"},
    ...
  ],
  "overall_status": "all_healthy"
}
```

数据源阈值表 `_SOURCE_CADENCE`(分钟):

| 数据源 | warn | critical |
|---|---|---|
| Binance K 线 (1h) | 120 | 360 |
| CoinGlass 衍生品 | 30h | 48h |
| Glassnode 链上 | 30h | 72h |
| Yahoo / FRED 宏观 | 120 | 24h |

来源:从各表 `max(inserted_at_utc)` 算 age_minutes,按阈值映射 status。

`evidence_layers` 来源:从最新 `strategy_runs.full_state_json` 抽
`evidence_reports.layer_X.health_status` + `pillars[].status` +
`L3.rule_trace.matched_rule` + `L5.data_completeness_pct`。

`overall_status` 聚合:任一 critical/missing → critical;任一 warn/degraded
→ partial_degraded;否则 all_healthy。

新 Pydantic models:`HealthDetailEvidenceLayer / HealthDetailDataSource /
HealthDetailResponse`。

### 任务 A.2:前端系统自检面板(commit `1ab76e2`)

`web/assets/app.js` 新增 helper:
- `_refreshSystemHealth()`:5 分钟轮询 `/api/system/health-detail`
- `toggleSelfCheck()`:用户主动展开后保留状态(`_selfCheckUserToggled`)
- `selfCheckBadgeLabel/Class`:全部正常 ✅ / ⚠️ 部分降级 / ❌ 关键缺失
- `layerHealthDot / sourceStatusDot / sourceAgeLabel / sourceTextClass`:
  状态着色

`web/index.html` 新增 panel(顶栏正下方,占整宽):
- 默认折叠;`overall_status != all_healthy` 且用户未手动 toggle → 自动展开
- 容器边框颜色随 `overall_status` 变(critical 红 / partial 黄)
- 展开后两列布局:左 5 层证据健康 + missing_reasons;右 5 数据源 + age

### 任务 B:五层证据链折叠(commit `ab1b159`)

`web/index.html` 区域 2 整段包 `<details>`(默认 closed):
- `<summary>` 标题 "五层证据推导细节",副标题"给开发者审计 — 一般用户不需打开"
- 完整 HTML / 渲染逻辑保留 — `git grep "五层证据"` 仍 3 处
- 审计需要时仍可展开,但默认不占主屏空间

### 任务 C:持仓预演占位框(commit `ab1b159`)

AI 策略建议区 Row 2.5(全宽)新增灰色虚框:
- `x-show="showPositionPreviewPlaceholder()"` →
  `action_state ∈ {FLAT, FLIP_WATCH}` 时显示
- 两列示意:LONG_PLANNED 时显示什么 / LONG_HOLD 时显示什么
- 当 action_state 进入 PLANNED / OPEN / HOLD → 自动隐藏

### 任务 D:历史与复盘空状态隐藏(commit `ab1b159`)

`region-5` 整段加 `x-show="historyTimeline().length > 0"`:
- 没历史时整段不渲染
- `historyTimeline()` 函数 + 渲染代码保留 — git grep 5 处

---

## 三、测试

### `tests/test_health_detail_endpoint.py`(13 测试)

| 类别 | 测试 |
|---|---|
| Schema | 5 层 / 5 源 数量正确;layer_id 顺序 1-5;source 名单含 5 个 |
| Age 真值 | K 线 30min → ok,3h → warn,8h → critical;空 DB → no_data |
| 衍生品 | 6h 前 → ok(30h warn 阈值,daily cadence) |
| Layer 健康 | 5 层 all healthy;L2 degraded 单点;空 DB → 5 层全 missing |
| Overall 聚合 | 全 healthy → all_healthy;layer missing → critical |

### 全量回归

```
958 passed, 1 skipped, 6.74s
```

(945 baseline + 13 新 = 958)

---

## 四、改动文件

| 文件 | 改动 |
|---|---|
| `src/api/models.py` | 新增 3 个 Pydantic models |
| `src/api/routes/system.py` | 新增 `/health-detail` endpoint + helpers |
| `tests/test_health_detail_endpoint.py` | **新文件** 13 测试 |
| `web/assets/app.js` | 自检面板数据流 + 5 个 helper(toggle/badge/dot/age) |
| `web/index.html` | 自检面板 UI / 五层 details / 持仓预览 / 历史 x-show |

---

## 五、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

**本 sprint 无替代关系,无删除项。** 理由:纯折叠 + 新增占位,所有原代码
保留(只是包了 `<details>` 或 `x-show`)。

git grep 自检:
- ✅ 五层证据链 HTML 仍在(`git grep "五层证据"` 3 处)
- ✅ `historyTimeline()` 函数仍在(`git grep historyTimeline` 5 处)
- ✅ `<details>` 标签包裹 region-2 整段,审计时仍可展开

### §Y
4 个 commit + 1 个报告 commit,一次性 push 到 GitHub。

### §Z(测试用真值断言)
- 数据源 age 真值断言:K 线 30min/180min/480min → ok/warn/critical 三档
- 5 层 health 真值断言:all healthy / L2 degraded / 空 DB 全 missing
- overall_status 聚合断言(all_healthy / critical)
- 不是 `.called=True` only

### 同类风险扫描
- **数据源阈值写死在 `_SOURCE_CADENCE`**:后续可挪 thresholds.yaml,
  留 1.5n.1 续修
- **5 分钟自动刷新频率写死**:如要可配置,1.5n.1 续修
- **自检面板未在前端写测试**:Alpine 模板,改动小,SSH 主观验收
- **`pillars` 字段语义**:某些层(L4 / L5)可能不返回 `pillars` 数组,
  现版兜底显示 `规则匹配:...` / `完整度 X%`

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 958 passed, 1 skipped, 6.74s |
| GitHub push(commit hashes:`60dc0c1..`,见下) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 无 schema 改动 |

### SSH 部署 + 主观验证

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 验证 endpoint
curl -s -u admin:Y_RhcxeApFa0H- http://localhost/api/system/health-detail \
  | python3 -m json.tool | head -50
SSH
```

打开 http://124.222.89.86 主观验收:
- ✅ 顶栏下方有"🩺 系统自检"面板,默认折叠;点击展开看 5 层 + 5 数据源
- ✅ 当前 healthy → 标"全部正常 ✅"绿色;degraded → 自动展开标黄
- ✅ AI 策略建议区下,FLAT 状态显示灰色虚框「持仓预览(系统当前 FLAT)」
- ✅ 「五层证据推导细节」可折叠,默认 closed,标题加"给开发者审计"
- ✅ 「历史与复盘」整段不再显示(没历史时)
- ✅ 「原始数据因子」「组合因子」依然显示

---

## 七、未覆盖 / 留 v0.6

- **数据源阈值** `_SOURCE_CADENCE` 写死,未挪 thresholds.yaml,留 1.5n.1
- **持仓预览框文字静态**;真有持仓时(Sprint 1.5b lifecycle 完成后)
  这个占位框 x-show 自动隐藏。LONG_PLANNED 实际卡片设计在另一个 sprint
- **5 分钟自动刷新频率**写死,如要可配置,1.5n.1 续修
- **前端自检面板没单元测试**:Alpine 模板纯展示层,改动小,SSH 主观验收
- **pillars 字段语义**:L4 三角度 / L5 四类分析未必走 `pillars[]` 数组,
  现版兜底显示 `规则匹配:` / `完整度 %`,未来若 L4/L5 加结构化 pillars
  字段需对应改 endpoint
