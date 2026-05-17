"""src/ai/agents — Sprint 1.8:6 个 AI 角色 + Validator(主体)。

建模 v1.3 §3.3:从"规则主导 + AI 辅助"切到"AI 主导 + 规则硬约束"。
本子包包含 6 个 AI 角色:
  - L1RegimeAnalyst: 市场状态层(regime / volatility)
  - L2DirectionAnalyst: 方向结构层(stance / phase / confidence)
  - L3OpportunityAnalyst: 机会执行层(grade / permission)
  - L4RiskAnalyst: 风险失效层(position_cap / hard_invalidation_levels)
  - L5MacroAnalyst: 背景事件层(macro_stance / headwind / extreme_event)
  - MasterAdjudicator: 主裁(综合 5 层 + 输出 trade_plan)

每个 agent 继承 BaseAgent,prompt 文件在 src/ai/agents/prompts/*.txt
(Sprint 1.8 实施期间逐个由用户审定后提交)。

调用编排见 src/ai/orchestrator.py。Validator 见 src/ai/validator.py。
"""

from ._base import BaseAgent
from .l1_regime_analyst import L1RegimeAnalyst
from .l2_direction_analyst import L2DirectionAnalyst
from .l3_opportunity_analyst import L3OpportunityAnalyst
from .l4_risk_analyst import L4RiskAnalyst
from .l5_macro_analyst import L5MacroAnalyst
from .master_adjudicator import MasterAdjudicator
from .spot_cycle_agents import LayerACycleAdjudicator

__all__ = [
    "BaseAgent",
    "L1RegimeAnalyst",
    "L2DirectionAnalyst",
    "L3OpportunityAnalyst",
    "L4RiskAnalyst",
    "L5MacroAnalyst",
    "MasterAdjudicator",
    "LayerACycleAdjudicator",
]
