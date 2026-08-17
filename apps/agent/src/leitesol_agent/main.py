from leitesol_agent.application.get_agent_profile import GetAgentProfile


def main() -> None:
    profile = GetAgentProfile().execute()
    print(f"{profile.name}: {profile.purpose}")


if __name__ == "__main__":
    main()
