"""The formal eval harness — download standard benchmarks, run a system, log scores.

Three benchmarks are wired in (see ``registry.py``), chosen for moderate size, built-in
difficulty discrimination, and a format that fits ``run(query) -> str``:

- ``math500``        — 500 competition problems, 5 explicit difficulty levels, objective.
- ``gpqa_diamond``   — 198 graduate-science MC questions, google-proof, objective.
- ``truthfulqa``     — 817 misconception-baiting questions, graded by an LLM judge.

The flow is three commands, each a module CLI:

    python -m scripts.benchmarks.download all          # → data/<name>.jsonl (gitignored)
    python -m scripts.benchmarks.run --benchmark math500 --system single
    python -m scripts.benchmarks.run --benchmark math500 --system parallel_consensus --group A

Every ``run`` appends one record to ``data/baselines.yaml`` (tracked), so the file is the
single log of every experiment, with a per-difficulty breakdown on each row.
"""
