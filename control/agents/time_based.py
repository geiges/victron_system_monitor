from control.agents.base import BaseAgent, AgentResult


class TimeBasedAgent(BaseAgent):
    name = "time_based"

    def run(self, projection, config) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            actions=[],
            rationale="not yet implemented",
            metrics={},
        )
