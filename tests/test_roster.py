from openai_420.roster import (
    CAPTAIN,
    SPECIALISTS,
    AgentSpec,
    captain_system_prompt,
    specialist_system_prompt,
)

ROSTER = [*SPECIALISTS, CAPTAIN]


def test_specialist_system_prompt_states_identity_and_full_roster():
    harper = AgentSpec(name="Harper", role="research and fact-checking")
    benjamin = AgentSpec(name="Benjamin", role="logic and math")

    prompt = specialist_system_prompt(harper, roster=[harper, benjamin, CAPTAIN])

    assert "Harper" in prompt
    assert "research and fact-checking" in prompt
    for member in (harper, benjamin, CAPTAIN):
        assert member.name in prompt
        assert member.role in prompt


def test_captain_system_prompt_lists_roster_and_names_the_conclude_tool():
    prompt = captain_system_prompt(CAPTAIN, roster=ROSTER)

    for member in ROSTER:
        assert member.name in prompt
    assert "conclude" in prompt


def test_v1_roster_is_three_named_specialists_plus_a_role_titled_captain():
    names = [s.name for s in SPECIALISTS]

    assert len(SPECIALISTS) == 3
    assert len(set(names)) == 3  # distinct
    assert CAPTAIN.name == "Captain"
    assert "Captain" not in names  # specialists carry real personal names
