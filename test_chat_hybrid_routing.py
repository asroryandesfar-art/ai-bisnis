"""Hybrid chat routing: pesan simpel -> brain (cepat), kompleks/analitis -> multi-agent."""
import main


def test_simple_message_stays_on_brain(monkeypatch):
    monkeypatch.setattr(main.cfg, "chat_multiagent_for_complex", True)
    for msg in ["Halo", "Jam buka toko berapa?", "Terima kasih ya", "Ada promo?"]:
        assert main._chat_prefers_multi_agent(msg) is False, msg


def test_complex_or_analytical_goes_multi_agent(monkeypatch):
    monkeypatch.setattr(main.cfg, "chat_multiagent_for_complex", True)
    hard = [
        "Kenapa penjualan bisa turun padahal traffic naik? Beri analisis dan langkah konkret.",
        "Tolong bandingkan strategi pemasaran kami dengan kompetitor dan beri rekomendasi.",
        "Bagaimana strategi agar margin keuntungan naik tahun depan?",
    ]
    assert any(main._chat_prefers_multi_agent(m) for m in hard)
    # minimal satu pemicu analitis panjang harus lolos
    assert main._chat_prefers_multi_agent(hard[0]) is True


def test_flag_off_keeps_everything_on_brain(monkeypatch):
    monkeypatch.setattr(main.cfg, "chat_multiagent_for_complex", False)
    assert main._chat_prefers_multi_agent(
        "Kenapa penjualan turun padahal traffic naik? Analisis mendalam dong."
    ) is False


def test_helper_is_fail_open(monkeypatch):
    # Input aneh tidak boh melempar; default aman = brain (False) bila tak terklasifikasi kompleks.
    monkeypatch.setattr(main.cfg, "chat_multiagent_for_complex", True)
    assert main._chat_prefers_multi_agent("") is False
