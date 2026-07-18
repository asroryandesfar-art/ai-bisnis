from __future__ import annotations

from pathlib import Path
import html
import re


BASE_DIR = Path(__file__).resolve().parent

DOCS = [
    ("MultiAgent_Quick_Start.md", "MultiAgent_Quick_Start.html", "Quick Start"),
    ("MultiAgent_AI_Framework.md", "MultiAgent_AI_Framework.html", "AI Framework"),
    ("MultiAgent_App_Integration.md", "MultiAgent_App_Integration.html", "App Integration"),
]


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def md_to_html(markdown_text: str, title: str) -> str:
    lines = markdown_text.splitlines()
    out: list[str] = []
    in_code = False
    in_list = False
    para: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append(f"<p>{_inline(' '.join(s.strip() for s in para if s.strip()))}</p>")
            para = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_para()
            close_list()
            if not in_code:
                out.append("<pre><code>")
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            continue

        if in_code:
            out.append(html.escape(line))
            continue

        if not stripped:
            flush_para()
            close_list()
            continue

        if stripped.startswith("# "):
            flush_para()
            close_list()
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
            continue
        if stripped.startswith("## "):
            flush_para()
            close_list()
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
            continue
        if stripped.startswith("### "):
            flush_para()
            close_list()
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
            continue

        if stripped.startswith("- [ ] ") or stripped.startswith("- [x] "):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            mark = "☑" if stripped.startswith("- [x] ") else "☐"
            out.append(f"<li>{mark} {_inline(stripped[6:])}</li>")
            continue

        if stripped.startswith("- "):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
            continue

        para.append(stripped)

    flush_para()
    close_list()
    if in_code:
        out.append("</code></pre>")

    body = "\n".join(out)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #0b0d10;
      --surface: #12161b;
      --card: #171c22;
      --text: #f2f5f7;
      --muted: #a6b0ba;
      --border: #28303a;
      --accent: #58d7ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 16px/1.7 Inter, Segoe UI, Arial, sans-serif;
    }}
    .wrap {{
      max-width: 980px;
      margin: 0 auto;
      padding: 40px 24px 80px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 28px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--border);
    }}
    .topbar a {{
      color: var(--accent);
      text-decoration: none;
      font-size: 14px;
    }}
    h1, h2, h3 {{
      line-height: 1.25;
      margin-top: 32px;
      margin-bottom: 12px;
    }}
    h1 {{ font-size: 34px; }}
    h2 {{ font-size: 24px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
    h3 {{ font-size: 18px; color: var(--accent); }}
    p {{ color: var(--text); margin: 12px 0; }}
    ul {{ padding-left: 22px; }}
    li {{ margin: 8px 0; }}
    pre {{
      background: var(--card);
      border: 1px solid var(--border);
      padding: 16px;
      overflow: auto;
      border-radius: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    code {{
      background: rgba(255,255,255,.06);
      border: 1px solid rgba(255,255,255,.08);
      padding: 2px 6px;
      border-radius: 6px;
      font-family: Consolas, monospace;
      font-size: .95em;
    }}
    pre code {{
      background: transparent;
      border: none;
      padding: 0;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <strong>{html.escape(title)}</strong>
      <div>
        <a href="/multiagent">Index</a>
        <a href="/dashboard">Dashboard</a>
      </div>
    </div>
    {body}
  </div>
</body>
</html>"""


def build_index(entries: list[tuple[str, str, str]]) -> str:
    cards = []
    for _, out_name, label in entries:
        route = "/multiagent/" + out_name.replace(".html", "").lower()
        cards.append(
            f"""
            <div class="card">
              <h2>{html.escape(label)}</h2>
              <p>Buka versi web yang siap dibaca, dibagikan, atau di-print ke PDF.</p>
              <a href="{route}">Buka dokumen →</a>
            </div>
            """
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Multi-Agent Docs</title>
  <style>
    body {{ margin:0; background:#0b0d10; color:#f2f5f7; font:16px/1.6 Inter,Segoe UI,Arial,sans-serif; }}
    .wrap {{ max-width:980px; margin:0 auto; padding:40px 24px 80px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; }}
    .card {{ background:#171c22; border:1px solid #28303a; padding:20px; border-radius:14px; }}
    h1 {{ font-size:34px; margin:0 0 12px; }}
    h2 {{ font-size:20px; margin:0 0 10px; }}
    p {{ color:#a6b0ba; }}
    a {{ color:#58d7ff; text-decoration:none; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Multi-Agent Documentation</h1>
    <p>Dokumen ini disiapkan agar framework multi-agent, quick start, dan integrasi app bisa dibuka langsung dari BotNesia.</p>
    <div class="grid">
      {''.join(cards)}
    </div>
  </div>
</body>
</html>"""


def main() -> None:
    for md_name, html_name, title in DOCS:
        md_path = BASE_DIR / md_name
        html_path = BASE_DIR / html_name
        text = md_path.read_text(encoding="utf-8")
        html_path.write_text(md_to_html(text, title), encoding="utf-8")

    (BASE_DIR / "MultiAgent_Index.html").write_text(build_index(DOCS), encoding="utf-8")


if __name__ == "__main__":
    main()
