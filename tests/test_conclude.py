from openai_420.conclude import Conclusion, parse_conclude


def test_parse_conclude_reads_consensus_without_direction():
    conclusion = parse_conclude('{"consensus": true}')

    assert conclusion == Conclusion(consensus=True, direction=None)


def test_parse_conclude_reads_no_consensus_with_direction():
    conclusion = parse_conclude('{"consensus": false, "direction": "focus on cost"}')

    assert conclusion == Conclusion(consensus=False, direction="focus on cost")
