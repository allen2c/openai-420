"""Orchestrators — the systems the harness runs, each behind one ``run`` contract.

Every variant lives here forever (old ones are never deleted) and registers under a name
stating its mechanism, so the harness dispatches by name without a branch per system. This
package imports each module on load so importing ``openai_420.orchestrators`` is enough to
populate the registry; new orchestrators must be added to the imports below to register.

    from openai_420 import orchestrators
    cls = orchestrators.get("parallel_consensus")
    system = cls.from_args(client=client, model=model, gen_params=params, group="A")
    answer = await system.run(prompt)
"""

from openai_420.orchestrators.base import Orchestrator, get, names, register
from openai_420.orchestrators.parallel_consensus import ParallelConsensusOrchestrator
from openai_420.orchestrators.single import SingleOrchestrator, ToolSingleOrchestrator
from openai_420.orchestrators.tool_grounded_verification import (
    ToolGroundedVerificationOrchestrator,
)

__all__ = [
    "Orchestrator",
    "ParallelConsensusOrchestrator",
    "SingleOrchestrator",
    "ToolGroundedVerificationOrchestrator",
    "ToolSingleOrchestrator",
    "get",
    "names",
    "register",
]
