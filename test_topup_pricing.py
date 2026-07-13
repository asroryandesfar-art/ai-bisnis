"""P0-1 — Kunci invariant pricing Top-Up baru.

Top-up HARUS lebih mahal per-percakapan daripada kuota bawaan paket termahal
(Starter = Rp99/percakapan) supaya jadi solusi darurat overflow, bukan celah
arbitrase yang meng-cannibalize paket. Juga harus di atas COGS realistis
(~Rp40) agar margin sehat. Test ini mencegah regresi ke harga rugi lama.
"""
from bn_platform.billing import TOPUP_PACKAGES, TopupReq, _TOPUP_CONV_MAP

# Harga per-percakapan paket TERTINGGI saat ini (Starter 99.000 / 1.000).
STARTER_PRICE_PER_CONV = 99_000 / 1_000  # = 99,0
COGS_PER_CONV_ESTIMATE = 40  # estimasi biaya realistis (model murah + infra)


def _price_per_conv(pkg: dict) -> float:
    return pkg["amount_idr"] / pkg["conversations"]


def test_every_topup_is_more_expensive_than_plan_included():
    # Tiap top-up > Rp99/percakapan → upgrade paket selalu lebih hemat.
    for pkg in TOPUP_PACKAGES:
        ppc = _price_per_conv(pkg)
        assert ppc > STARTER_PRICE_PER_CONV, (
            f"{pkg['label']} = Rp{ppc:.1f}/conv <= Starter Rp{STARTER_PRICE_PER_CONV} "
            "(top-up TIDAK boleh lebih murah dari kuota paket)"
        )


def test_every_topup_has_healthy_margin_over_cogs():
    for pkg in TOPUP_PACKAGES:
        ppc = _price_per_conv(pkg)
        # margin kotor minimal ~50% terhadap COGS estimasi
        assert ppc >= COGS_PER_CONV_ESTIMATE * 2, (
            f"{pkg['label']} = Rp{ppc:.1f}/conv terlalu dekat COGS Rp{COGS_PER_CONV_ESTIMATE}"
        )


def test_price_per_conv_decreases_with_larger_packages():
    # Diskon volume: nominal lebih besar → Rp/percakapan lebih rendah (monoton).
    ordered = sorted(TOPUP_PACKAGES, key=lambda p: p["amount_idr"])
    ppc = [_price_per_conv(p) for p in ordered]
    assert ppc == sorted(ppc, reverse=True), f"Rp/conv tidak monoton menurun: {ppc}"


def test_legacy_loss_making_25k_package_removed():
    amounts = {p["amount_idr"] for p in TOPUP_PACKAGES}
    assert 25_000 not in amounts  # paket rugi lama dihapus
    # Semua nominal >= floor baru
    assert min(amounts) >= 50_000


def test_conv_map_matches_packages():
    assert _TOPUP_CONV_MAP == {p["amount_idr"]: p["conversations"] for p in TOPUP_PACKAGES}


def test_topupreq_floor_matches_min_package():
    # Batas bawah request harus konsisten dengan paket terkecil (50.000).
    schema = TopupReq.model_json_schema()
    assert schema["properties"]["amount_idr"]["minimum"] == 50_000
    assert schema["properties"]["amount_idr"]["maximum"] == 750_000
