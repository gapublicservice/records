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


def test_plants_sit_inside_georgia_and_get_boxes():
    import json
    from harvester import regionmap
    reg = json.loads((regionmap.ROOT / "data" / "index" / "regional_generation.json").read_text())
    geo = json.loads(regionmap.GEO.read_text())
    total = sum(len(v["plants"]) for v in reg["regions"].values())
    pls, off = regionmap.plants(reg, geo)
    assert len(pls) + off == total and len(pls) > 100
    _, _, w, h = geo["viewBox"]
    assert all(0 <= q["px"] <= w and 0 <= q["py"] <= h for q in pls)
    out = regionmap.map_html([], reg=reg)
    assert out.count('class="pin plant') == len(pls)
    assert out.count('id="rm-p') == len(pls)
    assert 'data-layer="plant"' in out
