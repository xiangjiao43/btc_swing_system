# Deploy And Verify Layer A On Production Web

## 1. 当前分支和最终 commit

本地分支：`main`

部署前本地 HEAD：

```text
d467679 Update Layer A refresh verification report status
```

生产服务器 `/home/ubuntu/btc_swing_system` 已从旧 commit：

```text
167bda3 docs: update takeover deployment status
```

快进到：

```text
d467679 Update Layer A refresh verification report status
```

说明：本轮后续只新增本报告文件；报告 commit 不影响生产网页代码。

## 2. 是否 git pull

已执行生产服务器：

```bash
cd /home/ubuntu/btc_swing_system
git pull --ff-only
```

结果：

```text
Fast-forward 167bda3..d467679
```

## 3. 是否有 uv.lock 遗留修改

本地仍有一个任务开始前就存在的 `uv.lock` 未提交修改。

本轮没有提交 `uv.lock`，也没有把它放入审查包。

## 4. 服务重启命令

用户本轮明确允许的唯一 sudo 命令：

```bash
sudo systemctl restart btc-strategy.service
sleep 3
systemctl is-active btc-strategy.service
```

执行结果：

```text
active
```

结论：`btc-strategy.service` 已成功重启。

## 5. Pipeline run 命令

服务器没有 `uv` 命令，因此按项目历史部署方式使用服务器虚拟环境：

```bash
cd /home/ubuntu/btc_swing_system
.venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

执行结果：

```text
persisted=true
ai_status=ok
degraded_stages=[]
failures=[]
```

说明：这是项目安全手动 pipeline，不是真实交易，不下单。

## 6. 最新 run_id 和时间

最新生产 run：

- `run_id=f99ce07de5af4467aad890933750f4d4`
- `run_time=2026-05-12T06:26:17Z`

## 7. layer_a_spot_strategy 是否存在

存在。

生产 DB 最新 run 摘要：

```text
has_layer_a=True
enabled=True
a1_cycle_stage=accumulation
a5_spot_action=dca_buy
validator_passed=True
validator_violations=[]
validator_warnings=['high_confidence_with_many_missing_factors']
```

## 8. A1 cycle_stage

`accumulation`

网页中文会显示为：

```text
底部吸筹
```

## 9. A5 spot_action

`dca_buy`

网页中文会显示为：

```text
分批买入
```

## 10. Validator 结果

```text
validator_passed=True
violations=[]
warnings=['high_confidence_with_many_missing_factors']
```

解释给小白：

- 没有硬违规。
- 有一个 warning，意思是“缺失因子较多但置信度偏高”，这是 Layer A 风控提示，不会影响 Layer B，也不是交易下单。

## 11. 线上 API 验证结果

公网 URL：

```text
http://124.222.89.86/api/strategy/current
```

未登录直接访问返回：

```text
401
```

这说明公网 API 在 nginx / Basic Auth 保护层后面，未带网页登录凭据不会返回 JSON。为避免泄露或使用任何账号密码，本轮没有在报告或命令里使用网页登录凭据。

同一台生产服务器内部 FastAPI 验证：

```bash
curl http://127.0.0.1:8000/api/strategy/current
```

验证摘要：

```text
run_id=f99ce07de5af4467aad890933750f4d4
has_layer_a=True
enabled=True
a1_cycle_stage=accumulation
a5_spot_action=dca_buy
validator_passed=True
validator_violations=[]
validator_warnings=['high_confidence_with_many_missing_factors']
```

结论：生产 API 本体已返回真实 `layer_a_spot_strategy`。

## 12. http://124.222.89.86/ 网页验证结果

公网 URL：

```text
http://124.222.89.86/
```

未登录直接访问返回：

```text
401
```

说明公网网页也在 Basic Auth 保护层后面。

同一台生产服务器内部访问前端首页，确认 HTML 已更新：

```text
<script src="/assets/app.js?v=layer-a-web-display-20260512"></script>
大周期策略
暂无大周期策略，本 run 尚未记录 Layer A 输出。
五层分析
```

同时确认：

- HTML 有“大周期策略”模块；
- HTML 引用新版 app.js；
- Layer B “五层分析”仍在；
- FastAPI API 返回真实 Layer A，所以登录后页面应显示真实 A1-A5，而不是 fallback。

## 13. 如果网页不显示，原因

本轮已确认：

- 服务器代码已 pull 到 `d467679`；
- `btc-strategy.service` 已重启且 active；
- 生产 pipeline 已成功写入新 run；
- 最新 run 已有 `layer_a_spot_strategy`；
- 生产 FastAPI 本体返回真实 Layer A；
- 前端 HTML 已有“大周期策略”和新版 app.js；
- Layer B 五层分析仍保留。

如果用户浏览器仍不显示，最可能原因是：

1. 浏览器缓存旧 HTML/JS，需要 Cmd+Shift+R 强刷；
2. 用户未通过网页 Basic Auth 登录；
3. 浏览器仍使用旧页面缓存。

## 14. 测试命令和结果

本轮未继续改交易代码。

保留上一轮测试结果：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
# 115 passed
```

```bash
uv run pytest -q tests/test_layer_a_spot_validator.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_orchestrator_integration.py
# 18 passed
```

本轮已运行：

```bash
git diff --check
```

结果：通过。

## 15. 是否改代码

本轮没有改运行代码。

只新增本报告文件：

- `docs/codex_reports/deploy_and_verify_layer_a_on_production_web.md`

## 16. 是否影响 Layer B

否。

本轮没有修改 Layer B L1-L5、Master、Validator、thesis、C 级机会、仓位、止损、止盈、开仓、平仓、反手规则。

## 17. 是否影响虚拟账户

否。

Layer A 不进入虚拟账户，虚拟账户仍只管理 Layer B。

## 18. 是否影响真实交易

否。

本轮没有真实下单，没有新增真实交易接口，没有读取或输出 `.env`、API key、token、secret。

## 19. 风险和未完成

- 公网网页/API 未登录时返回 `401`，本轮没有使用网页登录凭据，因此无法在未授权 curl 下直接抓取登录后的页面 DOM。
- 生产服务器内部 FastAPI 与 HTML 已验证通过，用户登录后应能看到“大周期策略”。
- 生产 Layer A validator 有一个 warning：`high_confidence_with_many_missing_factors`，这是可审计提示，不是硬违规。
- 本地 `uv.lock` 仍有遗留未提交修改，本轮未处理。

## 20. 删除清单 / 废弃清单

本轮无替代关系，无删除项。

原因：本轮是生产部署和验证，没有新增替代实现，也没有删除旧逻辑。

## 21. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 使用上一轮结果：Web 115 passed；Layer A 18 passed |
| GitHub push(commit hash:11c63d0) | ✅ |
| 服务器 git pull | ✅ 已到 `d467679` |
| 服务器 systemctl restart | ✅ `btc-strategy.service active` |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | ✅ 服务 active；公网受 Basic Auth 保护 |
