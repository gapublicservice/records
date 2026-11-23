from harvester import infrastructure


def test_gas_certificates_skip_telecom_and_keep_county():
    rows = [
        {"description": "Atlanta Gas Light Company's Application for Amended Certificate of Public Convenience and Necessity for Hall County",
         "units": ["Natural Gas"], "counties_in_title": ["Hall"], "document_id": 1, "dockets": [5], "filed_date": "2024-01-01"},
        {"description": "Request to Cancel Certificate of Public Convenience and Necessity to Provide Intrastate Interexchange",
         "units": [], "counties_in_title": [], "document_id": 2, "dockets": [6], "filed_date": "2024-01-02"},
    ]
    certs = infrastructure.gas_certificates(rows)
    assert [c["document_id"] for c in certs] == [1]
    assert certs[0]["regions"] == ["Georgia Mountains"]


def test_project_lists_place_only_named_counties():
    lists = infrastructure.project_lists()
    assert [d["order"] for d in lists] == sorted(d["order"] for d in lists)
    for d in lists:
        for x in d["projects"]:
            assert len(x["regions"]) <= len(x["counties"])
            for k in x["sources"]:
                assert k in d["sources"]
