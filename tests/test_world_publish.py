"""Publishing a generation: unfinished runs publish too, and every doc carries when it was published."""
from world.publish import publish_generation


class FakeEs:
    def __init__(self):
        self.docs = {}

    def ix(self, name):
        return name

    def call(self, *a, **kw):
        return {}

    def bulk(self, index, docs):
        self.docs.update({(index, k): v for k, v in docs})


def test_running_generation_publishes_without_a_summary_and_with_a_timestamp():
    from tests.test_world_store import fresh  # a real, unfinished GenerationState
    es = FakeEs()
    st = fresh()
    publish_generation(es, st, None, runner="modal")
    doc = es.docs[("generations", st.checkpoint.generation_id)]
    assert doc["status"] == st.status.value and doc["summary"] == {} and doc["runner"] == "modal"
    assert doc["published_at"] and doc["published_at"].endswith("+00:00")
