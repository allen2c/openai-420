import json
import logging

from openai_420.trace import log_decision


def test_log_decision_emits_one_structured_json_record(caplog):
    with caplog.at_level(logging.INFO, logger="openai_420"):
        log_decision("Harper", "respond", round=1, output="spaces win")

    records = [r for r in caplog.records if r.getMessage().startswith("DECISION ")]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage()[len("DECISION ") :])
    assert payload == {
        "agent": "Harper",
        "event": "respond",
        "round": 1,
        "output": "spaces win",
    }
