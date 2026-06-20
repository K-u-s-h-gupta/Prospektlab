import base64

from finagent.tools.data.news_feed import (
    _decode_escaped_url,
    _extract_external_link_from_google_html,
    _extract_image_from_html,
    _extract_url_from_google_token,
    _unwrap_google_news_link,
)


def test_unwrap_google_news_link_prefers_query_url() -> None:
    wrapped = (
        "https://news.google.com/rss/articles/CBMiYWh0dHBzOi8vd3d3LmV4YW1wbGUuY29tL2FydGljbGXSAQA"
        "?oc=5&url=https%3A%2F%2Fwww.moneycontrol.com%2Fnews%2Fbusiness%2Fmarkets%2Ffoo-123.html"
    )
    assert _unwrap_google_news_link(wrapped) == "https://www.moneycontrol.com/news/business/markets/foo-123.html"


def test_decode_escaped_url_normalizes_slashes_and_entities() -> None:
    raw = r"https:\\/\\/www.example.com\\/story\\u003d1\\u0026src\\u003drss"
    assert _decode_escaped_url(raw) == "https://www.example.com/story=1&src=rss"


def test_extract_external_link_from_google_html_finds_non_google_href() -> None:
    html = """
    <html><body>
      <a href="https://news.google.com/articles/abc">google wrapper</a>
      <a href="https://www.livemint.com/market/stock-market-news/sample.html">publisher</a>
    </body></html>
    """
    assert _extract_external_link_from_google_html(html) == "https://www.livemint.com/market/stock-market-news/sample.html"


def test_extract_image_from_html_uses_og_and_relative_path() -> None:
    html = """
    <html><head>
      <meta property="og:image" content="/images/cover-hero.jpg" />
    </head></html>
    """
    assert _extract_image_from_html("https://www.example.com/story", html) == "https://www.example.com/images/cover-hero.jpg"


def test_extract_url_from_google_token_finds_embedded_http_url() -> None:
    original = "https://www.reuters.com/markets/asia/example-story"
    payload = b"\x08\x13" + bytes([len(original)]) + original.encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    assert _extract_url_from_google_token(token) == original


def test_unwrap_google_news_link_decodes_token_payload() -> None:
    original = "https://www.moneycontrol.com/news/business/markets/test-story-123.html"
    payload = b"\x08\x13" + bytes([len(original)]) + original.encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    wrapped = f"https://news.google.com/rss/articles/{token}?oc=5"
    assert _unwrap_google_news_link(wrapped) == original
