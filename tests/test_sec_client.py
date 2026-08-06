from app.clients.sec import SECClient


def test_information_table_locator_prefers_named_xml():
    index = {
        "directory": {
            "item": [
                {"name": "primary_doc.xml"},
                {"name": "other.xml"},
                {"name": "infotable.xml"},
            ]
        }
    }
    assert SECClient.information_table_name(index, "primary_doc.xml") == "infotable.xml"


def test_archive_url_normalizes_cik_and_accession():
    url = SECClient.archive_url(
        "0001067983", "0000950123-25-000001", "infotable.xml"
    )
    assert url.endswith("/1067983/000095012325000001/infotable.xml")
