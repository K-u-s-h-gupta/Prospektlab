"""Unit tests for director-network pure assembly."""

from __future__ import annotations

from finagent.ikg.director_network import assemble_director_network


def test_empty_rows_seed_only():
    out = assemble_director_network("company:LSEED", "Seed Ltd", [])
    assert out["summary"]["connected_companies"] == 0
    assert len(out["nodes"]) == 1
    assert out["nodes"][0]["is_seed"] is True


def test_single_shared_director():
    rows = [
        {"person_id": "person:D1", "director_name": "Alice", "company_id": "company:LB",
         "company_name": "Beta Ltd", "designation": "Director", "seed_designation": "Chairman"},
    ]
    out = assemble_director_network("company:LSEED", "Seed Ltd", rows)
    node_ids = {n["id"] for n in out["nodes"]}
    assert node_ids == {"company:LSEED", "person:D1", "company:LB"}
    assert out["summary"]["directors"] == 1
    assert out["summary"]["connected_companies"] == 1
    assert out["connected_companies"][0]["id"] == "company:LB"
    assert out["connected_companies"][0]["shared_directors"] == 1


def test_two_directors_same_connected_company_counts_shared():
    rows = [
        {"person_id": "person:D1", "director_name": "Alice", "company_id": "company:LB", "company_name": "Beta"},
        {"person_id": "person:D2", "director_name": "Bob", "company_id": "company:LB", "company_name": "Beta"},
    ]
    out = assemble_director_network("company:LSEED", "Seed", rows)
    assert out["connected_companies"][0]["shared_directors"] == 2
    assert out["summary"]["directors"] == 2


def test_connected_companies_sorted_by_shared_count():
    rows = [
        {"person_id": "person:D1", "director_name": "A", "company_id": "company:LB", "company_name": "Beta"},
        {"person_id": "person:D2", "director_name": "B", "company_id": "company:LB", "company_name": "Beta"},
        {"person_id": "person:D3", "director_name": "C", "company_id": "company:LC", "company_name": "Gamma"},
    ]
    out = assemble_director_network("company:LSEED", "Seed", rows)
    assert out["connected_companies"][0]["id"] == "company:LB"  # 2 shared
    assert out["connected_companies"][1]["id"] == "company:LC"  # 1 shared


def test_seed_company_excluded_from_connected():
    rows = [
        {"person_id": "person:D1", "director_name": "A", "company_id": "company:LSEED", "company_name": "Seed"},
    ]
    out = assemble_director_network("company:LSEED", "Seed", rows)
    # self-link filtered; only seed + director nodes, no connected companies
    assert out["summary"]["connected_companies"] == 0


def test_links_carry_designation():
    rows = [
        {"person_id": "person:D1", "director_name": "Alice", "company_id": "company:LB",
         "company_name": "Beta", "designation": "Independent Director"},
    ]
    out = assemble_director_network("company:LSEED", "Seed", rows)
    dir_company_link = next(l for l in out["links"] if l["target"] == "company:LB")
    assert dir_company_link["designation"] == "Independent Director"
    assert dir_company_link["label"] == "DIRECTOR_OF"


def test_board_only_rows_no_connected_companies():
    rows = [
        {"person_id": "person:D1", "director_name": "Alice", "company_id": "", "company_name": ""},
        {"person_id": "person:D2", "director_name": "Bob", "company_id": "", "company_name": ""},
    ]
    out = assemble_director_network("company:LSEED", "Seed", rows)
    assert out["summary"]["directors"] == 2
    assert out["summary"]["connected_companies"] == 0
    # seed connected to both directors
    seed_links = [l for l in out["links"] if l["target"] == "company:LSEED"]
    assert len(seed_links) == 2
