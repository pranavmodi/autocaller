from app.services import pif_sitemap_monitor as service


def test_xml_locations_reads_sitemap_index_and_urlset():
    kind, locations = service._xml_locations(b"""<?xml version="1.0"?>
      <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://example.com/posts.xml</loc></sitemap>
      </sitemapindex>""")
    assert kind == "sitemapindex"
    assert locations == ["https://example.com/posts.xml"]

    kind, locations = service._xml_locations(b"""<?xml version="1.0"?>
      <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://example.com/</loc></url>
        <url><loc>https://example.com/new-page?source=sitemap#section</loc></url>
      </urlset>""")
    assert kind == "urlset"
    assert locations == [
        "https://example.com/",
        "https://example.com/new-page?source=sitemap#section",
    ]


def test_robots_sitemaps_accepts_case_and_relative_urls():
    assert service._robots_sitemaps(
        "User-agent: *\nSITEMAP: /sitemap-index.xml\nSitemap: https://cdn.example.com/pages.xml",
        "https://example.com",
    ) == [
        "https://example.com/sitemap-index.xml",
        "https://cdn.example.com/pages.xml",
    ]


def test_page_normalization_removes_fragments_but_keeps_query():
    assert service._normalized_page_url("HTTPS://Example.COM/new/#details") == "https://example.com/new/"
    assert service._normalized_page_url("https://example.com/search?q=law#results") == "https://example.com/search?q=law"


def test_private_network_addresses_are_rejected():
    assert service._public_ip("8.8.8.8") is True
    assert service._public_ip("127.0.0.1") is False
    assert service._public_ip("10.0.0.4") is False
    assert service._public_ip("169.254.169.254") is False
