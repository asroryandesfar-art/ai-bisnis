"""
One-time data-quality fix for the 13 legacy marketplace templates (the
original 6-template marketplace from before the 100+ template Agent
Marketplace Catalog was added) flagged by
bn_platform.marketplace.agent_health_report(): normalize their `category`
to match the newer agent_categories taxonomy, and backfill missing
starter_questions. Run once: python3 scripts/fix_marketplace_template_quality.py

Does not touch knowledge_sources — these legacy templates were never
assigned a curated knowledge pack (unlike the new catalog's seeded URL
packs), and fabricating fake source URLs would be dishonest. Documented
as a known gap in the production readiness report instead.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
import main

CATEGORY_FIXES = {
    "toko-online":       "Ecommerce",
    "klinik":            "Healthcare",
    "pesantren":         "Education",
    "properti":          "Real Estate",
    "umkm":              "Retail",
    "customer-service":  "Customer Service",
    "property":          "Real Estate",
    "faq":               "Customer Service",
    "e-commerce":        "Ecommerce",
    "sales":             "Sales & Marketing",
}

STARTER_QUESTIONS = {
    "clinic": [
        "Bagaimana cara booking jadwal dokter?",
        "Apa saja layanan kesehatan yang tersedia?",
        "Apakah bisa konsultasi untuk kondisi non-darurat?",
    ],
    "customer-service": [
        "Bagaimana cara menghubungi customer service?",
        "Saya mau komplain, bagaimana caranya?",
        "Bagaimana cara cek status permintaan saya?",
    ],
    "e-commerce": [
        "Apakah produk ini masih tersedia?",
        "Berapa estimasi ongkos kirim ke kota saya?",
        "Bagaimana cara cek status pesanan saya?",
    ],
    "faq": [
        "Apa pertanyaan yang paling sering ditanyakan?",
        "Bagaimana cara menggunakan layanan ini?",
        "Di mana saya bisa cari info lebih lanjut?",
    ],
    "klinik": [
        "Bagaimana cara booking janji temu dengan dokter?",
        "Layanan kesehatan apa yang tersedia di klinik ini?",
        "Apakah ada triase untuk kondisi non-darurat?",
    ],
    "pesantren": [
        "Bagaimana cara mendaftar santri/siswa baru?",
        "Berapa biaya pendaftaran dan SPP?",
        "Apa kurikulum yang digunakan?",
    ],
    "properti": [
        "Apa saja listing properti yang tersedia saat ini?",
        "Bagaimana cara menjadwalkan survei lokasi?",
        "Bisa bantu simulasi KPR?",
    ],
    "property": [
        "Properti apa saja yang sedang dijual/disewakan?",
        "Bagaimana cara menjadwalkan survei lokasi?",
        "Bisa bantu simulasi pembelian atau sewa?",
    ],
    "sales": [
        "Apa kelebihan produk ini dibanding lainnya?",
        "Berapa harga dan promo yang tersedia?",
        "Bagaimana cara melakukan pemesanan?",
    ],
    "school": [
        "Bagaimana cara mendaftar sebagai siswa baru?",
        "Apa informasi akademik yang bisa saya dapatkan?",
        "Bagaimana cara orang tua menghubungi pihak sekolah?",
    ],
    "toko-online": [
        "Apakah produk ini ready stock?",
        "Berapa ongkos kirim ke daerah saya?",
        "Bagaimana cara melakukan checkout?",
    ],
    "travel": [
        "Paket wisata apa yang direkomendasikan?",
        "Bagaimana cara menyusun itinerary perjalanan?",
        "Bagaimana proses booking paket wisata?",
    ],
    "umkm": [
        "Apa saja produk/jasa yang ditawarkan?",
        "Berapa harga dan bagaimana cara pemesanan?",
        "Jam operasional buka jam berapa?",
    ],
}


async def main_() -> None:
    pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
    try:
        for key, category in CATEGORY_FIXES.items():
            result = await pool.execute(
                "UPDATE marketplace_templates SET category=$1, updated_at=NOW() WHERE key=$2",
                category, key,
            )
            print(f"category fix: {key} -> {category} ({result})")

        for key, questions in STARTER_QUESTIONS.items():
            result = await pool.execute(
                "UPDATE marketplace_templates SET starter_questions=$1::jsonb, updated_at=NOW() WHERE key=$2",
                json.dumps(questions), key,
            )
            print(f"starter_questions fix: {key} ({result})")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main_())
