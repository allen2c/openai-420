from openai_420.roster import CAPTAIN, SPECIALISTS, AgentSpec, system_prompt


def test_system_prompt_states_the_agents_own_identity():
    harper = AgentSpec(name="Harper", role="research and fact-checking")

    prompt = system_prompt(harper, roster=[harper])

    assert "Harper" in prompt
    assert "research and fact-checking" in prompt


def test_system_prompt_lists_every_participant_name_and_role():
    harper = AgentSpec(name="Harper", role="research")
    benjamin = AgentSpec(name="Benjamin", role="logic and math")
    captain = AgentSpec(name="Captain", role="synthesis")

    prompt = system_prompt(harper, roster=[harper, benjamin, captain])

    for spec in (harper, benjamin, captain):
        assert spec.name in prompt
        assert spec.role in prompt


def test_v1_roster_is_three_named_specialists_plus_a_role_titled_captain():
    names = [s.name for s in SPECIALISTS]

    assert len(SPECIALISTS) == 3
    assert len(set(names)) == 3  # distinct
    assert CAPTAIN.name == "Captain"
    assert "Captain" not in names  # specialists carry real personal names
