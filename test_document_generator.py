import pytest

import document_generator as dg


SAMPLE_SPEC = {
    "title": "Laporan Penjualan Juni",
    "sections": [
        {"heading": "Ringkasan", "body": "Penjualan naik 12%.\nMargin stabil."},
        {"heading": "Rekomendasi", "body": "Naikkan stok produk A."},
    ],
    "table_rows": [["Produk", "Qty", "Total"], ["A", "120", "1.200.000"]],
    "slides": [
        {"title": "Ringkasan", "bullets": ["Naik 12%", "Margin stabil"]},
        {"title": "Rekomendasi", "bullets": ["Naikkan stok A"]},
    ],
}


def test_normalize_spec_fills_defaults_for_empty_input():
    spec = dg.normalize_spec(None, fallback_title="Fallback")
    assert spec["title"] == "Fallback"
    assert spec["sections"] == []
    assert spec["table_rows"] == []
    assert spec["slides"] == []


def test_normalize_spec_drops_malformed_entries():
    raw = {
        "title": "  Judul  ",
        "sections": ["not-a-dict", {"heading": "", "body": ""}, {"heading": "OK", "body": ""}],
        "table_rows": ["not-a-row", [1, 2, 3]],
        "slides": [{"title": "", "bullets": []}, {"title": "Slide", "bullets": ["a"]}],
    }
    spec = dg.normalize_spec(raw)
    assert spec["title"] == "Judul"
    assert spec["sections"] == [{"heading": "OK", "body": ""}]
    assert spec["table_rows"] == [["1", "2", "3"]]
    assert spec["slides"] == [{"title": "Slide", "bullets": ["a"]}]


@pytest.mark.parametrize("fmt", ["pdf", "docx", "xlsx", "pptx"])
def test_generate_document_produces_nonempty_bytes_for_each_format(fmt):
    data, content_type = dg.generate_document(fmt, SAMPLE_SPEC)
    assert isinstance(data, bytes)
    assert len(data) > 100
    assert content_type


@pytest.mark.parametrize("fmt", ["pdf", "docx", "xlsx", "pptx"])
def test_generate_document_handles_empty_spec_without_raising(fmt):
    data, _ = dg.generate_document(fmt, {})
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_generate_document_rejects_unknown_format():
    with pytest.raises(ValueError):
        dg.generate_document("docm", SAMPLE_SPEC)


def test_pdf_bytes_start_with_pdf_magic_number():
    data, _ = dg.generate_document("pdf", SAMPLE_SPEC)
    assert data[:5] == b"%PDF-"


def test_office_formats_are_valid_zip_containers():
    import zipfile
    import io

    for fmt in ("docx", "xlsx", "pptx"):
        data, _ = dg.generate_document(fmt, SAMPLE_SPEC)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.namelist()
