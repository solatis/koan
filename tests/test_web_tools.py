# M7 web tools: web_search (DuckDuckGo) + web_fetch (httpx), implemented
# locally in koan/tools/builtin_tools.py. ddgs and httpx are mocked so the
# tests make no network calls.

from __future__ import annotations

import pytest

from koan.tools.builtin_tools import (
    _strip_html,
    build_builtin_toolset,
    web_fetch_tool,
    web_search_tool,
)


def test_strip_html_drops_tags_script_and_collapses_whitespace():
    html = "<html><head><style>x{}</style></head><body>Hello   <b>World</b>\n<script>bad()</script></body></html>"
    assert _strip_html(html) == "Hello World"


def test_web_tools_registered():
    names = set(build_builtin_toolset().tools.keys())
    assert "web_search" in names
    assert "web_fetch" in names


@pytest.mark.anyio
async def test_web_search_formats_results(monkeypatch):
    class FakeDDGS:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def text(self, query, max_results=5):
            return [
                {"title": "First", "href": "http://a", "body": "alpha"},
                {"title": "Second", "href": "http://b", "body": "beta"},
            ]
    monkeypatch.setattr("ddgs.DDGS", FakeDDGS)

    out = await web_search_tool(None, "koan migration", max_results=2)
    assert "Found 2 result(s) for: koan migration" in out
    assert "First" in out and "http://a" in out and "alpha" in out
    assert "Second" in out


@pytest.mark.anyio
async def test_web_search_handles_error(monkeypatch):
    class BoomDDGS:
        def __enter__(self):
            raise RuntimeError("ddg down")
        def __exit__(self, *a):
            return False
    monkeypatch.setattr("ddgs.DDGS", BoomDDGS)

    out = await web_search_tool(None, "q")
    assert out.startswith("Error: web search failed")


@pytest.mark.anyio
async def test_web_fetch_strips_html(monkeypatch):
    class FakeResp:
        text = "<html><body>Page <b>body</b></body></html>"
        headers = {"content-type": "text/html; charset=utf-8"}
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None):
            return FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    out = await web_fetch_tool(None, "http://example.com")
    assert out == "Page body"


@pytest.mark.anyio
async def test_web_fetch_truncates(monkeypatch):
    big = "x" * 100

    class FakeResp:
        text = big
        headers = {"content-type": "text/plain"}
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None):
            return FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    out = await web_fetch_tool(None, "http://example.com", max_chars=10)
    assert out.startswith("x" * 10)
    assert "truncated at 10 chars" in out
