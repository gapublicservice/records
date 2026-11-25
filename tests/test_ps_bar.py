import json

from alerts import nav as ghostnav
from harvester import site


def test_clean_keeps_https_and_makes_relative_absolute():
    got = ghostnav.clean([{"label": "Home", "url": "/"},
                          {"label": " Sessions ", "url": "https://www.gapublicservice.org/tag/sessions/"},
                          {"label": "Bad", "url": "javascript:alert(1)"},
                          {"label": "Plain", "url": "http://example.com/"},
                          {"label": "", "url": "https://x.org/"}])
    assert got == [{"label": "Home", "url": "https://www.gapublicservice.org/"},
                   {"label": "Sessions", "url": "https://www.gapublicservice.org/tag/sessions/"}]


def test_from_settings_reads_json_strings():
    settings = [{"key": "title", "value": "Public Service"},
                {"key": "url", "value": "https://www.gapublicservice.org"},
                {"key": "navigation", "value": json.dumps([{"label": "Home", "url": "/"},
                                                           {"label": "Records", "url": "https://records.gapublicservice.org"}])}]
    nav = ghostnav.from_settings(settings)
    assert [i["label"] for i in nav["primary"]] == ["Home", "Records"]
    assert nav["secondary"] == []


def test_bar_marks_records_and_keeps_links_in_tab(monkeypatch):
    monkeypatch.setattr(site, "ghost_nav", lambda: {
        "site": "https://www.gapublicservice.org", "title": "Public Service",
        "primary": [{"label": "Home", "url": "https://www.gapublicservice.org/"},
                    {"label": "Records <b>", "url": "https://records.gapublicservice.org/"},
                    {"label": "About", "url": "https://www.gapublicservice.org/about/"}]})
    out = site.page("T", "<p>x</p>", on="search", depth=1)
    bar = out[out.index('<div class="ps-top">'):out.index("</nav></div></div>")]
    assert 'class="here" aria-current="true" href="../index.html">Records &lt;b&gt;</a>' in bar
    assert 'href="https://www.gapublicservice.org/about/">About' in bar
    assert 'target="_blank"' not in bar
    assert "Visit the site" not in out
    assert out.index('class="ps-top"') < out.index('<header class="site">')


def test_bar_adds_records_when_ghost_menu_lacks_it(monkeypatch):
    monkeypatch.setattr(site, "ghost_nav", lambda: {
        "primary": [{"label": "Home", "url": "https://www.gapublicservice.org/"}]})
    out = site.ps_bar("", "search")
    assert out.count('class="here"') == 1 and ">Records</a>" in out
