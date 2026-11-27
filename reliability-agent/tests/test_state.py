from reliability_agent.storage.state import StateStore


def test_incremental_upsert_and_delete(tmp_path):
    store = StateStore(tmp_path / "state.db")
    try:
        items = [{"record_id": "r1", "row": {"a": 1}, "updated_at_ms": None}]
        diff = store.upsert_records("t", items)
        assert diff.changed == 1 and diff.added == 1

        diff = store.upsert_records("t", items)
        assert diff.changed == 0 and diff.added == 0

        changed_items = [
            {"record_id": "r1", "row": {"a": 2}, "updated_at_ms": None},
            {"record_id": "r2", "row": {"a": 3}, "updated_at_ms": None},
        ]
        diff = store.upsert_records("t", changed_items)
        assert diff.changed == 2 and diff.added == 1
        assert len(store.load_dataframe("t")) == 2

        assert store.delete_missing("t", {"r2"}) == 1
        assert store.count_records("t") == 1

        store.mark_sync("t", total_records=1)
        state = store.get_sync_state("t")
        assert state is not None and state["run_count"] == 1
    finally:
        store.close()
