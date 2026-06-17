from control.agents.base import BaseAgent, AgentResult


class ForecastAwareAgent(BaseAgent):
    name = "forecast_aware"

    def run(self, projection, config) -> AgentResult:
        if projection.forecast is None:
            return AgentResult(
                agent_name=self.name,
                actions=[],
                rationale="inactive — no solar forecast available",
                metrics={},
            )
        return AgentResult(
            agent_name=self.name,
            actions=[],
            rationale="not yet implemented",
            metrics={},
        )
