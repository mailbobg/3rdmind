"""Continue a finished (or stopped) RD-Agent research loop for a few more rounds, in place.

The loop object is restored from the trace's ``__session__`` snapshots, so the agent keeps the whole
history of hypotheses and feedback and its next proposal follows from them. Logs are appended to the
same trace folder, so the rounds show up under the same experiment.
"""
import asyncio
from pathlib import Path

LOOP_SCENARIOS = {
    "Finance Data Building": ("rdagent.app.qlib_rd_loop.factor", "FactorRDLoop"),
    "Finance Model Implementation": ("rdagent.app.qlib_rd_loop.model", "ModelRDLoop"),
    "Finance Whole Pipeline": ("rdagent.app.qlib_rd_loop.quant", "QuantRDLoop"),
}


def loop_class(scenario: str):
    module_name, class_name = LOOP_SCENARIOS[scenario]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


def resume_loop(scenario: str, path: str, loop_n: int, all_duration: str | None = None, user_interaction_queues=None) -> None:
    """Load the latest session under ``path`` and run until ``loop_n`` loops have been kicked off.

    ``loop_n`` counts from loop 0 (the loop's own counter is decremented once per loop it walks past,
    finished ones included), so callers add the rounds they want to the rounds already recorded.
    The session's timer is not restored: a fresh one, with ``all_duration`` if given, so a run whose
    time budget was spent can still continue.
    """
    cls = loop_class(scenario)
    loop = cls.load(Path(path), checkout=True, replace_timer=False)
    if user_interaction_queues is not None:
        # Per-round confirmations keep working; the initial-parameter dialogue is skipped because the
        # plan (research direction, base features) is already in the restored session.
        loop._set_interactor(*user_interaction_queues)
    asyncio.run(loop.run(loop_n=loop_n, all_duration=all_duration))
