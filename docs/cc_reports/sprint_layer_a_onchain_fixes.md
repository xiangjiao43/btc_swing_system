# Sprint Layer A 链上 2 项确定性 bug 修复(A.1 + A.2)

**日期**:2026-05-17
**目标**:修复上一份调查(`sprint_layer_a_onchain_audit.md`)定位到的两个与 Glassnode 配额无关的代码 bug:
- A.1:`fetch_hash_rate` 没注册到 scheduler 的 `_GLASSNODE_FETCHERS`,生产端 `collect_onchain` job 从未采集算力 → DB 永远没行 → Layer A 算力永远 missing。
- A.2:Layer A 上层 `metric("hodl_waves")` 查询的是裸名,但 DB 里只有 `hodl_waves_<bucket>` 12 个 bucket 名(Sprint 1.6 拆桶入库),永远查不到 → 字段永远 missing。

两条都是确定性代码 bug,与 Puell Multiple 429 / 月度配额完全独立。

---

## 1. 改动文件清单

| 文件 | 改动 |
|---|---|
| [src/scheduler/jobs.py](src/scheduler/jobs.py#L278) | `_GLASSNODE_FETCHERS` tuple 尾部追加 `"fetch_hash_rate"`(共 1 行新代码 + 3 行注释解释 Sprint `82e59f9` 漏注册的历史)。生产端下一次 `collect_onchain` job(每天 08:35 BJT)即开始采集算力,月用量 +30 次(960 EH/s 级别的日级数据)|
| [src/ai/spot_cycle_context_builder.py](src/ai/spot_cycle_context_builder.py#L1006-L1009) | 删除 `"hodl_waves": metric("hodl_waves"),` 这行死查询;同位置加 4 行注释说明 mismatch 历史。下方 `hodl_waves_1y_plus_aggregate` 派生(对 6 个长尾 bucket 求和)保留不动,继续给 Layer A 提供"1 年+ HODL 占比"|

## 2. 自检 `git grep`

```
$ git grep '"hodl_waves":' src/
(0 hits — bare-name query 已干净删除)

$ git grep 'metric("hodl_waves")' src/
(0 hits)

$ git grep '"fetch_hash_rate"' src/
src/scheduler/jobs.py:282:    "fetch_hash_rate",        # ← 新加
src/data/collectors/glassnode.py:774:            ("hash_rate",          self.fetch_hash_rate),
```

两个路径都注册了 `fetch_hash_rate`(scheduler + collect_and_save_all)。没有任何旧代码堆叠,Sprint `82e59f9` 的漏洞补齐。

下游核查(确认删 `metric("hodl_waves")` 行没有破坏任何引用):
```
$ git grep -E 'available.*hodl_waves"|hb\.get\("hodl_waves"\)|holder_behavior\[.hodl_waves.\]'
(0 hits — bare-name 没有任何 downstream consumer)
```

## 3. 测试结果

```
.venv/bin/python -m pytest --tb=line -q
1 failed, 1876 passed, 1 skipped, 672 warnings in 47.26s
```

唯一失败 `test_collect_klines_1h_kline_succeeds_derivatives_fail`:从 commit `16cad4f` 起多个 sprint 报告记录的上游遗留(`_classify_failure` 输出从 `api_error` 改 `provider_error` 后未同步更新的断言),与本次完全无关。

Layer A 专项 95/95 + 全量其他 1875 项通过。

## 4. 上线后预期效果

| 指标 | 修复前 | 修复后 |
|---|---|---|
| hash_rate(Layer A onchain_packet 字段)| 永远 None | 服务器下次 `collect_onchain`(08:35 BJT)即采集;Layer A 当晚 / 次日 10:00 BJT 跑能读到 |
| hodl_waves(Layer A onchain_packet 字段)| 永远 missing,占着 prompt JSON 一个空槽 | 字段彻底从 cycle_evidence_summary.holder_behavior 移除,prompt 不再看到 "hodl_waves: null" 这种噪音条目;`hodl_waves_1y_plus_aggregate` 派生继续提供长尾 HODL 占比 |
| Glassnode 月用量 | 660 次/月(22 fetcher × 30 天)| 690 次/月(+ hash_rate 30 次)— 仍远低于 1700/月 quota |

## 5. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(1876 通过 + 1 上游遗留 + 1 skipped;Layer A 专项全绿)|
| GitHub 推送 | ❌ 本报告写完后立即 commit + push |
| 服务器 git pull | ❌ 待用户执行 |
| 服务器 systemctl restart | ❌ 待用户执行;**restart 不必紧迫,等下次 08:35 BJT collect_onchain 自动触发即可。**也可手动跑 `cd /home/ubuntu/btc_swing_system && .venv/bin/python -c "from src import _env_loader; from src.data.storage.connection import get_connection; from src.scheduler.jobs import job_collect_onchain; print(job_collect_onchain(conn_factory=get_connection))"` 立即触发一次 |
| 生产 DB schema 迁移 | N/A(纯逻辑修复,无 schema 改动)|

## 6. 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `"hodl_waves": metric("hodl_waves"),`(1 行死查询)| `src/ai/spot_cycle_context_builder.py:1004`(旧版)| Sprint 1.6 起的命名 mismatch,查的名字 DB 里不存在,永远返 None;下方 aggregate 已提供等效信息 |

无新增冗余代码,无其他堆叠。

## 7. 风险提示

- A.1 修复后,首次 `collect_onchain` job 会比之前多调 1 个 Glassnode endpoint(`/v1/metrics/mining/hash_rate_mean`)。若服务器本次 collect_onchain **已经因为月度配额耗尽** 在跑前撞 429,**hash_rate 与其他所有 fetcher 一样会失败** — 这种情况下 hash_rate 在生产端仍会 missing,但**根因变成配额而非代码 bug**,与本次修复无关。要排除这点,等用户回贴段 7 的 5 条 SQL 输出后我再判断。
- A.2 删除的字段在 `prompts/layer_a_cycle_adjudicator.txt` 第二节列出的 onchain_packet 字段里**没有明文提到 hodl_waves**(prompt 只提"HODL Waves"作为整体概念),所以 AI 不会因这个字段消失而出错。`hodl_waves_1y_plus_aggregate` 字段名也没在 prompt 里写过,AI 读 JSON 时会自动按字段名理解为"1 年+ HODL 聚合占比"。无 prompt 同步需求。
