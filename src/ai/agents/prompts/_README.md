# Sprint 1.8 Prompt Drafts — User Review Required

每个 `.txt` prompt 文件都需要用户**逐字审定**后才会提交。

实施流程:
1. CC 写一个 prompt 草稿,commit + push,让用户审
2. 用户在对话里改 prompt(或要求重写)
3. CC 按反馈改 → 重新 commit
4. 用户通过 → 进下一个 prompt

每个 prompt 必须包含 9 段:
1. 角色定位
2. 输入数据说明
3. 输出 JSON schema(严格)
4. 判定标准(每个枚举值的触发条件)
5. 你必须做的
6. 你绝对不能做的(防偏见)
7. 你必须诚实承认的
8. 输出格式(严格 JSON,首字符 {,尾字符 })
9. fewshot 示例(1-2 个真实场景)

文件名(对应 6 AI 角色):
- l1_regime.txt
- l2_direction.txt
- l3_opportunity.txt
- l4_risk.txt
- l5_macro.txt
- master_adjudicator.txt

如 prompt 文件缺失,BaseAgent.analyze() 会走 fallback 路径返回
`status='degraded_prompt_load_failed'`,系统不崩。
