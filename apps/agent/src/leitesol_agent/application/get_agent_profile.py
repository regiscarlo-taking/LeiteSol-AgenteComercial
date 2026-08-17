from leitesol_agent.domain.agent_profile import AgentProfile


class GetAgentProfile:
    def execute(self) -> AgentProfile:
        return AgentProfile(
            name="leitesol-agent",
            purpose="Espaco inicial para orquestrar o agente comercial.",
        )
