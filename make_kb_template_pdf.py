from __future__ import annotations

from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors


def build(path_out: str) -> None:
    doc = SimpleDocTemplate(
        path_out,
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        title="BotNesia Knowledge Base (Template)",
    )

    styles = getSampleStyleSheet()
    normal = styles["BodyText"]
    normal.fontName = "Helvetica"
    normal.fontSize = 11
    normal.leading = 14

    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=8)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, spaceAfter=6)
    title = ParagraphStyle("Title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=26, spaceAfter=6)
    subtitle = ParagraphStyle("Subtitle", parent=normal, fontName="Helvetica-Oblique", fontSize=11, textColor=colors.grey, spaceAfter=12)

    today = date.today().isoformat()
    story: list = []

    story.append(Paragraph("BotNesia Knowledge Base (Template)", title))
    story.append(
        Paragraph(
            f"Versi: {today}  •  Bahasa: Indonesia  •  Isi dokumen ini lalu upload ke Dashboard → Documents",
            subtitle,
        )
    )

    story.append(Paragraph("<b>Cara pakai:</b> Isi bagian-bagian di bawah dengan informasi bisnis kamu (SOP/FAQ). Setelah selesai, upload dokumen teks/DOCX.", normal))
    story.append(Spacer(1, 10))

    story.append(Paragraph("1. Profil Bisnis", h1))
    for line in ["Nama bisnis: …", "Jam operasional CS: …", "Kontak CS (email/WA): …", "Link kebijakan/terms (jika ada): …"]:
        story.append(Paragraph(line, normal))
    story.append(Spacer(1, 10))

    story.append(Paragraph("2. Aturan Jawaban Bot", h1))
    for line in [
        "Tone: ramah, singkat, profesional.",
        "Jika info tidak ada, minta detail yang relevan (nomor pesanan, email, tanggal).",
        "Jika user marah/ancam legal, eskalasi ke human agent.",
    ]:
        story.append(Paragraph("• " + line, normal))
    story.append(Spacer(1, 10))

    story.append(Paragraph("3. FAQ Utama", h1))

    def qa_block(title_text: str, rows: list[tuple[str, str, str]]) -> None:
        story.append(Paragraph(title_text, h2))
        data = [["Keyword", "Pertanyaan (contoh)", "Jawaban (versi final)"], *rows]
        tbl = Table(data, colWidths=[1.1 * inch, 2.3 * inch, 3.9 * inch])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d5dd")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbfbfb")]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(tbl)
        story.append(Spacer(1, 10))

    qa_block(
        "3.1 Login / Daftar",
        [
            ("login", "Saya tidak bisa login, selalu gagal.", "Pastikan email dan password benar. Jika lupa password, gunakan fitur reset. Jika masih gagal, kirim screenshot error dan email yang dipakai."),
            ("daftar", "Daftar akun gagal / email sudah terdaftar.", "Jika email sudah terdaftar, silakan login atau gunakan fitur lupa password. Kalau masih error, kirim pesan errornya agar kami cek."),
        ],
    )
    qa_block(
        "3.2 Pengiriman",
        [
            ("pengiriman", "Pesanan saya belum sampai, bagaimana cek statusnya?", "Kirim nomor pesanan atau nomor resi. Kami akan cek status (diproses/dikirim/tertahan) dan bantu tindak lanjut sesuai kondisi."),
            ("estimasi", "Estimasi pengiriman berapa hari?", "Estimasi pengiriman: … hari kerja (tergantung lokasi). Jika sudah lewat estimasi, kirim nomor pesanan untuk dicek."),
        ],
    )
    qa_block(
        "3.3 Refund / Retur",
        [
            ("refund", "Saya mau refund, prosedurnya bagaimana?", "Kirim nomor pesanan, tanggal transaksi, metode pembayaran, dan alasan refund. Estimasi proses refund: … hari kerja setelah disetujui."),
            ("retur", "Barang rusak, bisa retur?", "Bisa. Kirim nomor pesanan + foto/video kondisi barang. Kami cek dan informasikan langkah retur/penggantian."),
        ],
    )
    qa_block(
        "3.4 Harga / Paket",
        [
            ("harga", "Harga paket dan fiturnya apa saja?", "Paket tersedia: … (isi detail). Kalau sebutkan kebutuhan (jumlah bot & chat/bulan), kami bantu rekomendasikan paket."),
        ],
    )

    story.append(Paragraph("4. SOP Eskalasi (Human Agent)", h1))
    for line in [
        "Eskalasi jika user meminta bicara manusia/admin.",
        "Eskalasi jika ada ancaman legal/publik atau emosi sangat negatif.",
        "Eskalasi jika kendala teknis berulang / error server.",
        "Template balasan: “Baik, saya bantu hubungkan ke tim kami agar ditangani lebih cepat. Mohon tunggu sebentar ya.”",
    ]:
        story.append(Paragraph("• " + line, normal))
    story.append(Spacer(1, 10))

    story.append(Paragraph("5. Lampiran (Opsional)", h1))
    story.append(Paragraph("Tambah kebijakan lengkap, daftar produk, atau SOP internal di sini.", normal))

    doc.build(story)


if __name__ == "__main__":
    build("BotNesia_Knowledge_Base_Template.pdf")

