from leitesol_agent.application.get_agent_profile import GetAgentProfile


def test_get_agent_profile() -> None:
    profile = GetAgentProfile().execute()

    assert profile.name == "leitesol-agent"
