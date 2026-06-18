from openai_420.scratchpad import Scratchpad


def test_append_records_entry_with_full_shape():
    board = Scratchpad()

    board.append(round=1, author="Harper", kind="answer", content="spaces win")

    assert len(board.entries) == 1
    entry = board.entries[0]
    assert entry.round == 1
    assert entry.author == "Harper"
    assert entry.kind == "answer"
    assert entry.content == "spaces win"


def test_delta_excludes_the_agents_own_entries():
    board = Scratchpad()
    board.append(round=1, author="Harper", kind="answer", content="H1")
    board.append(round=1, author="Benjamin", kind="answer", content="B1")

    delta = board.delta(for_author="Harper", since_round=0)

    assert [e.author for e in delta] == ["Benjamin"]


def test_delta_excludes_rounds_already_seen():
    board = Scratchpad()
    board.append(round=1, author="Benjamin", kind="answer", content="B1")
    board.append(round=2, author="Benjamin", kind="answer", content="B2")

    # Harper already incorporated round 1; her next delta starts after it.
    delta = board.delta(for_author="Harper", since_round=1)

    assert [e.content for e in delta] == ["B2"]


def test_delta_includes_the_captains_direction():
    board = Scratchpad()
    board.append(round=1, author="Captain", kind="direction", content="focus on cost")

    # The captain's steering must reach specialists (Law 8/9): delta filters by author,
    # not by kind.
    delta = board.delta(for_author="Harper", since_round=0)

    assert [(e.author, e.kind) for e in delta] == [("Captain", "direction")]
