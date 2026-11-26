from billing.ledger_writer import append_immutable_entry


def test_append_immutable_entry_frozen():
    entry = append_immutable_entry({"frozen": True}, 2500)
    assert entry["frozen"] is True
