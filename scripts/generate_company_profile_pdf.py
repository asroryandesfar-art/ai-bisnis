"""
Generate the One-Page BotNesia Company Profile PDF for investor/government
pitching (Investor-Readiness Assets, Phase 18). Reuses document_generator.py's
existing generate_pdf() unchanged -- no new PDF-rendering code. Vision/Mission/
Founder Story copy is reused verbatim from frontend/app.js's renderAbout()/
renderFounderStory() (Phase 14), not rewritten, so the two stay consistent.

Run once: python3 scripts/generate_company_profile_pdf.py
Output: docs/marketing/BotNesia-Company-Profile.pdf
Source-of-truth content (editable without touching Python):
        docs/marketing/company-profile-content.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from document_generator import generate_pdf  # noqa: E402

OUT_DIR = Path(__file__).parent.parent / "docs" / "marketing"

SPEC = {
    "title": "BotNesia — Company Profile",
    "sections": [
        {
            "heading": "Apa itu BotNesia?",
            "body": (
                "AI Workforce Platform untuk bisnis Indonesia: tim AI lengkap "
                "(CS, Sales, Marketing, Finance, HR, Operations, Security, Executive "
                "Assistant) bekerja 24/7, tanpa pelanggan membangun tim teknologi sendiri."
            ),
        },
        {
            "heading": "Visi & Misi",
            "body": (
                "Visi: Menjadi platform AI Workforce nomor satu di Indonesia -- setiap "
                "UMKM hingga perusahaan besar bisa memiliki tim AI selengkap perusahaan "
                "teknologi besar, tanpa membangun tim engineering sendiri.\n"
                "Misi: Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI "
                "tanpa harus memiliki tim teknologi mahal."
            ),
        },
        {
            "heading": "Fitur Utama",
            "body": (
                "Multi Agent System (Supervisor, CS, Sales, FAQ, Knowledge, Trainer, Memory)  •  "
                "AI Workforce (Finance, Marketing, HR, Operations, Security, Executive)  •  "
                "Executive Center & AI Business Analyst (root cause, rekomendasi, action plan otomatis)  •  "
                "Communication Center (WhatsApp/IG/FB/Telegram/Website/Email)  •  "
                "Knowledge Base AI (auto FAQ & SOP)  •  Keamanan enterprise (RBAC, audit log, multi-tenant)"
            ),
        },
        {
            "heading": "Target Pasar & Teknologi",
            "body": (
                "Target: UMKM, bisnis menengah (SME), dan enterprise yang butuh AI Workforce "
                "multi-tenant dengan kendali akses korporat.\n"
                "Teknologi: FastAPI + PostgreSQL, Groq LLM, arsitektur multi-agent dengan "
                "Supervisor Agent; keputusan penting selalu memerlukan persetujuan manusia."
            ),
        },
        {
            "heading": "Founder Story",
            "body": (
                "Didirikan oleh Asrori, yang melihat jarak antara bisnis kecil-menengah Indonesia "
                "dengan AI yang sebenarnya bisa membantu mereka tumbuh -- bukan karena teknologinya "
                "tidak ada, tapi karena terlalu mahal dan rumit untuk dipasang sendiri. Misi pendiri: "
                "\"Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki "
                "tim teknologi mahal.\""
            ),
        },
        {
            "heading": "Kontak",
            "body": (
                "Email: asroryandesfar@gmail.com  •  Demo interaktif (tanpa pendaftaran): "
                "https://app.botnesia.id/demo  •  Website: https://app.botnesia.id"
            ),
        },
        {
            "heading": "Status",
            "body": "Investor Ready  ·  Government Ready  ·  PDF Ready",
        },
    ],
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_bytes = generate_pdf(SPEC)
    out_path = OUT_DIR / "BotNesia-Company-Profile.pdf"
    out_path.write_bytes(pdf_bytes)
    print(f"Wrote {out_path} ({len(pdf_bytes)} bytes)")


if __name__ == "__main__":
    main()
