"""TravelReads bulk add: many links in one paste, in order, no duplicates."""


def test_parse_bulk():
    from routes.travel_reads import parse_bulk
    items, errors = parse_bulk("""# a comment
https://www.youtube.com/watch?v=aaa | 18 min | Talk A | Leadership
not a link
https://example.com/b

https://www.youtube.com/watch?v=ccc | 9""")
    assert [i["url"] for i in items] == ["https://www.youtube.com/watch?v=aaa", "https://example.com/b",
                                         "https://www.youtube.com/watch?v=ccc"]
    assert items[0]["minutes"] == 18 and items[0]["title"] == "Talk A" and items[0]["note"] == "Leadership"
    assert items[2]["minutes"] == 9 and items[1]["minutes"] is None
    assert errors == ["Line 3: not a link"]


def test_bulk_endpoint(auth_client, monkeypatch):
    import routes.travel_reads as tr
    saved = []
    monkeypatch.setattr(tr, "get", lambda *a, **k: [{"url": "https://www.youtube.com/watch?v=old"}])
    monkeypatch.setattr(tr, "post", lambda t, row, **k: saved.append(row) or [dict(row, id=str(len(saved)))])
    monkeypatch.setattr(tr, "fetch_meta", lambda url: {"title": "Fetched", "description": ""})
    r = auth_client.post("/api/travel-reads/bulk", json={"text":
        "https://www.youtube.com/watch?v=oneONE12345 | 12 | First\n"
        "https://www.youtube.com/watch?v=old | 5 | Already queued\n"
        "https://www.youtube.com/watch?v=twoTWO12345\n"
        "https://www.youtube.com/watch?v=oneONE12345 | 12 | Duplicate line"})
    j = r.get_json()
    assert r.status_code == 200 and j["added"] == 2 and j["skipped"] == 2
    assert saved[0]["title"] == "First" and saved[0]["duration_minutes"] == 12 and saved[0]["kind"] == "video"
    assert saved[1]["title"] == "Fetched"
    assert saved[0]["added_at"] > saved[1]["added_at"]          # first line lists first
    assert "img.youtube.com/vi/oneONE12345" in saved[0]["thumbnail_url"]
    assert auth_client.post("/api/travel-reads/bulk", json={"text": "nothing here"}).status_code == 400
    assert b"Bulk add" in auth_client.get("/travel-reads").data
