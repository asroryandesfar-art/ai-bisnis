"""
Generate the professional, investor/government-ready BotNesia Company Profile
PDF (Investor-Readiness Assets, Phase 18 -- revised 2026-06-22 after explicit
user feedback: removed self-declared "Investor/Government/PDF Ready" badges,
added a factual "Current Stage" section, a professional closing statement, and
3 real product screenshots).

Builds the PDF directly with reportlab Platypus (NOT document_generator.py's
generic generate_pdf() spec format) -- the multi-column layout, tinted section
cards, and embedded screenshots needed here go well beyond what that shared
"title + sections + table" spec can express. Same judgment call already made
for the pitch deck script (Phase 19): python-pptx directly instead of forcing
the shared generic helper, which is designed for ad-hoc AI-generated docs, not
curated investor collateral.

Prerequisite: screenshots must already exist (run
scripts/capture_marketing_screenshots.py first, against a live local server).

Run: python3 scripts/generate_company_profile_pdf.py
Output: docs/marketing/BotNesia-Company-Profile.pdf
Source-of-truth content (editable without touching Python):
        docs/marketing/company-profile-content.md
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    HRFlowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

ROOT_DIR = Path(__file__).parent.parent
OUT_DIR = ROOT_DIR / "docs" / "marketing"
ASSETS = ROOT_DIR / "frontend" / "public" / "assets" / "brand"
SHOTS = OUT_DIR / "screenshots"
LOGO_PATH = ASSETS / "botnesia-clean-logo.png"

# Light/white background (standard print-document convention), brand colors
# used only as accents -- deliberately different from the dark website theme,
# since a printable investor one-pager reads as more professional on white.
INK = colors.HexColor("#1A1D24")
INK_2 = colors.HexColor("#5B6472")
BRAND = colors.HexColor("#6657EE")
CYAN = colors.HexColor("#0E8FA0")
TINT = colors.HexColor("#F5F3FF")
LINE = colors.HexColor("#E4E2F0")
GREEN = colors.HexColor("#16A34A")

PAGE_W, PAGE_H = A4
MARGIN = 0.6 * inch
CONTENT_W = PAGE_W - 2 * MARGIN

STYLES = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=INK),
    "tagline": ParagraphStyle("tagline", fontName="Helvetica", fontSize=11, leading=15, textColor=CYAN, spaceAfter=10),
    "eyebrow": ParagraphStyle("eyebrow", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=BRAND, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=INK, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.3, leading=13.5, textColor=INK_2),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.3, leading=13.5, textColor=INK_2, leftIndent=2),
    "caption": ParagraphStyle("caption", fontName="Helvetica-Oblique", fontSize=8, leading=11, textColor=INK_2, alignment=1),
    "quote": ParagraphStyle("quote", fontName="Helvetica-Oblique", fontSize=10, leading=15, textColor=INK, leftIndent=10, spaceBefore=4),
    "closing_body": ParagraphStyle("closing_body", fontName="Helvetica", fontSize=10, leading=15, textColor=colors.white),
    "closing_h": ParagraphStyle("closing_h", fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=colors.white, spaceAfter=6),
    "footer": ParagraphStyle("footer", fontName="Helvetica", fontSize=8.5, leading=12, textColor=INK_2, alignment=1),
}


def _hr():
    return HRFlowable(width="100%", thickness=1, color=LINE, spaceBefore=6, spaceAfter=14)


def _card(eyebrow_text, title, body_text):
    return [
        Paragraph(eyebrow_text.upper(), STYLES["eyebrow"]),
        Paragraph(title, STYLES["h2"]),
        Paragraph(body_text, STYLES["body"]),
    ]


def _two_col(left_cells, right_cells, gap=0.3 * inch):
    col_w = (CONTENT_W - gap) / 2
    table = Table([[left_cells, right_cells]], colWidths=[col_w, col_w])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), gap),
        ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
    ]))
    return table


def _bullet_list(items):
    rows = []
    for item in items:
        rows.append(Paragraph(f"<font color='#16A34A'>✓</font>&nbsp;&nbsp;{item}", STYLES["bullet"]))
        rows.append(Spacer(1, 5))
    return rows


def _screenshot(path, caption, max_h=2.55 * inch):
    reader = ImageReader(str(path))
    iw, ih = reader.getSize()
    ratio = min(CONTENT_W / iw, max_h / ih)
    w, h = iw * ratio, ih * ratio
    img = Image(str(path), width=w, height=h)
    framed = Table([[img]], colWidths=[CONTENT_W], style=TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, LINE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [framed, Spacer(1, 4), Paragraph(caption, STYLES["caption"]), Spacer(1, 16)]


def _closing_box():
    eyebrow_on_dark = ParagraphStyle("eyebrow_on_dark", parent=STYLES["eyebrow"], textColor=colors.HexColor("#C9C2FF"))
    body = [
        Paragraph("BUILT FOR INDONESIAN BUSINESSES", eyebrow_on_dark),
        Paragraph("Mari Berkolaborasi", STYLES["closing_h"]),
        Paragraph(
            "BotNesia is currently focused on helping Indonesian businesses adopt AI through a "
            "practical, affordable, and scalable AI Workforce platform.",
            STYLES["closing_body"],
        ),
        Spacer(1, 4),
        Paragraph(
            "We are open to pilot programs, partnerships, incubation opportunities, and strategic "
            "collaborations.",
            STYLES["closing_body"],
        ),
    ]
    box = Table([[body]], colWidths=[CONTENT_W], style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 18), ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, -1), 16), ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("ROUNDEDCORNERS", [10, 10, 10, 10]),
    ]))
    return box


def build_story() -> list:
    story = []

    # --- Header ---
    logo = Image(str(LOGO_PATH), width=0.5 * inch, height=0.5 * inch)
    header = Table([[logo, Paragraph("BotNesia", STYLES["h1"])]], colWidths=[0.65 * inch, CONTENT_W - 0.65 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [header, Paragraph("AI Workforce Platform for Indonesian Businesses", STYLES["tagline"]), _hr()]

    # --- Apa itu BotNesia ---
    story.append(Paragraph("APA ITU BOTNESIA", STYLES["eyebrow"]))
    story.append(Paragraph(
        "AI Workforce Platform untuk bisnis Indonesia: tim AI lengkap (Customer Service, Sales, "
        "Marketing, Finance, HR, Operations, Security, Executive Assistant) bekerja 24/7, tanpa "
        "pelanggan membangun tim teknologi sendiri.", STYLES["body"],
    ))
    story.append(Spacer(1, 16))

    # --- Vision & Mission ---
    vision = _card("Vision", "Visi", (
        "Menjadi platform AI Workforce nomor satu di Indonesia -- setiap UMKM hingga perusahaan "
        "besar bisa memiliki tim AI selengkap perusahaan teknologi besar, tanpa membangun tim "
        "engineering sendiri."
    ))
    mission = _card("Mission", "Misi", (
        "Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki tim "
        "teknologi mahal."
    ))
    story.append(_two_col(vision, mission))
    story.append(Spacer(1, 18))

    # --- Current Stage (factual, verifiable -- replaces self-declared badges) ---
    story.append(Paragraph("CURRENT STAGE", STYLES["eyebrow"]))
    story.append(Paragraph("Status Platform Saat Ini", STYLES["h2"]))
    story.extend(_bullet_list([
        "Multi-Agent AI Workforce Platform -- dibangun dan beroperasi penuh (8+ AI agent: CS, Sales, "
        "Marketing, Finance, HR, Operations, Security, Executive)",
        "Arsitektur multi-tenant tingkat enterprise -- RBAC, audit log, isolasi data per workspace",
        "Public Interactive Demo -- live dan bisa diakses publik tanpa pendaftaran",
        "Executive Analytics &amp; AI Business Analyst -- beroperasi, menghasilkan root cause "
        "analysis dan rekomendasi nyata dari data live",
        "Pengembangan berkelanjutan -- platform terus diperluas secara aktif",
    ]))
    story.append(Spacer(1, 4))

    story.extend(_screenshot(SHOTS / "landing-page.png", "Landing page publik — app.botnesia.uk"))

    story.append(PageBreak())

    story.extend(_screenshot(
        SHOTS / "executive-center.png",
        "Executive Center — company health score & AI Business Analyst", max_h=2.0 * inch,
    ))
    story.extend(_screenshot(
        SHOTS / "investor-demo.png",
        "Investor Demo Mode — analisis AI live, publik tanpa login (app.botnesia.uk/demo)", max_h=2.0 * inch,
    ))

    target = _card("Target Market", "Siapa yang Kami Layani", (
        "UMKM, bisnis menengah (SME), dan enterprise yang butuh AI Workforce multi-tenant dengan "
        "kendali akses korporat."
    ))
    tech = _card("Technology", "Teknologi", (
        "FastAPI + PostgreSQL, Groq LLM, arsitektur multi-agent dengan Supervisor Agent; "
        "keputusan penting selalu memerlukan persetujuan manusia."
    ))
    story.append(_two_col(target, tech))
    story.append(Spacer(1, 12))

    story.append(Paragraph("FOUNDER STORY", STYLES["eyebrow"]))
    story.append(Paragraph("Asrori, Pendiri BotNesia", STYLES["h2"]))
    story.append(Paragraph(
        "Didirikan oleh Asrori, yang melihat jarak antara bisnis kecil-menengah Indonesia dengan AI "
        "yang sebenarnya bisa membantu mereka tumbuh -- bukan karena teknologinya tidak ada, tapi "
        "karena terlalu mahal dan rumit untuk dipasang sendiri.", STYLES["body"],
    ))
    story.append(Paragraph(
        "“Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki "
        "tim teknologi mahal.”", STYLES["quote"],
    ))
    story.append(Spacer(1, 10))

    story.append(_closing_box())
    story.append(Spacer(1, 16))

    story.append(Paragraph(
        "asroryandesfar@gmail.com  &nbsp;·&nbsp;  app.botnesia.uk  &nbsp;·&nbsp;  "
        "app.botnesia.uk/demo (demo interaktif, tanpa pendaftaran)", STYLES["footer"],
    ))

    return story


def main() -> None:
    missing = [p for p in (
        SHOTS / "landing-page.png", SHOTS / "executive-center.png", SHOTS / "investor-demo.png",
    ) if not p.exists()]
    if missing:
        raise SystemExit(
            "Screenshot belum ada, jalankan dulu: python3 scripts/capture_marketing_screenshots.py\n"
            f"Hilang: {[str(p) for p in missing]}"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "BotNesia-Company-Profile.pdf"
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
        title="BotNesia — Company Profile",
    )
    doc.build(build_story())
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
