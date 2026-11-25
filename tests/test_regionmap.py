from harvester import infrastructure, regionmap


def test_every_project_with_a_county_gets_one_pin_and_the_rest_are_counted():
    lists = infrastructure.project_lists()
    geo = regionmap.json.loads(regionmap.GEO.read_text())
    pins, left_off = regionmap.pins(lists, geo)
    total = sum(len(d["projects"]) for d in lists)
    assert len(pins) + left_off == total
    for p in pins:
        assert p["home"] in p["counties"]
        assert 0 <= p["px"] <= geo["viewBox"][2] and 0 <= p["py"] <= geo["viewBox"][3]


def test_map_has_a_box_per_pin_and_says_how_many_are_left_off():
    lists = [{"layer": "Test lines", "sources": {"s": {"label": "A source", "url": "https://example.org/a"}},
              "projects": [{"name": "Placed", "kind": "New line", "size": "115 kV", "counties": ["Hall"],
                            "status": "Planned", "sources": ["s"], "checked": "confirmed"},
                           {"name": "Unplaced", "kind": "New line", "size": "115 kV", "counties": [],
                            "status": "Planned", "sources": ["s"]}]}]
    for d in lists:
        for x in d["projects"]:
            x["counties"] = list(x["counties"])
    out = regionmap.map_html(lists)
    assert out.count('class="pin ') == 1 and out.count('class="rm-box"') == 1
    assert "1 project whose source names no county is not on the map" in out
    assert "Confirmed by a second public source" in out and "Georgia Mountains" in out
