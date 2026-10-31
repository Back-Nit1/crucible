from datetime import datetime, timezone

from agents.actions import EpisodeRecord
from agents.memory import InMemoryMemoryProvider, RetrievalRequest
from tasks.schemas import TaskSplit


NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def episode(identifier, *, killed=False):
    return EpisodeRecord(episode_id=identifier, task_id=f"task-{identifier}", agent_id="agent",
                         generation_id="gen", seed=1, tool_calls=(), final_answer="fixture",
                         killed=killed, kill_information=({"rule": "fixture"},) if killed else (),
                         termination="instant_kill" if killed else "success", started_at=NOW, ended_at=NOW)


def test_memory_enforces_split_kill_threshold_k_and_stable_ties():
    memory = InMemoryMemoryProvider()
    memory.store(episode("test"), split=TaskSplit.TEST, category="shoes", fitness=1)
    memory.store(episode("dead", killed=True), split=TaskSplit.TRAIN, category="shoes", fitness=1)
    memory.store(episode("low"), split=TaskSplit.TRAIN, category="shoes", fitness=-1)
    memory.store(episode("b"), split=TaskSplit.TRAIN, category="shoes", fitness=.8)
    memory.store(episode("a"), split=TaskSplit.TRAIN, category="shoes", fitness=.8)
    request = RetrievalRequest("new", TaskSplit.TRAIN, "shoes", "query", 1, .5)
    assert [item.episode_id for item in memory.retrieve(request)] == ["a"]
    assert memory.retrieve(RetrievalRequest("test", TaskSplit.TEST, "shoes", "q", 3, 0)) == ()
