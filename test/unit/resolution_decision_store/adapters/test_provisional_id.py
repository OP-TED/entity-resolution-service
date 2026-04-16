from erspec.models.core import EntityMentionIdentifier

from ers.resolution_decision_store.adapters.provisional_id import derive_provisional_cluster_id


def make_identifier(source_id="s1", request_id="r1", entity_type="Person") -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id=source_id, request_id=request_id, entity_type=entity_type)


def test_returns_64_char_hex_string():
    result = derive_provisional_cluster_id(make_identifier())
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_deterministic_for_same_triad():
    i = make_identifier()
    assert derive_provisional_cluster_id(i) == derive_provisional_cluster_id(i)


def test_different_triads_produce_different_ids():
    a = derive_provisional_cluster_id(make_identifier(source_id="s1"))
    b = derive_provisional_cluster_id(make_identifier(source_id="s2"))
    assert a != b


def test_all_three_fields_contribute():
    base = make_identifier()
    base_id = derive_provisional_cluster_id(base)
    assert derive_provisional_cluster_id(make_identifier(source_id="X")) != base_id
    assert derive_provisional_cluster_id(make_identifier(request_id="X")) != base_id
    assert derive_provisional_cluster_id(make_identifier(entity_type="X")) != base_id
