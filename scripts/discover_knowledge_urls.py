#!/usr/bin/env python3
"""
BotNesia knowledge URL expansion.

Reads existing seed files, discovers additional trusted URLs from public
sitemaps, applies URL normalization/deduplication, and appends only new entries.
The script intentionally avoids deleting or reordering existing rows.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
SEEDS_DIR = ROOT / "seeds"
REPORT_DIR = ROOT / "reports"

AGENT_TARGETS = {
    "general_ai": 5000,
    "travel_agent": 1000,
    "ecommerce_agent": 1000,
    "clinic_agent": 1000,
    "school_agent": 1000,
    "sales_agent": 1000,
    "property_agent": 1000,
    "faq_agent": 1000,
    "customer_service_agent": 1000,
    "botnesia_business": 500,
}

QUALITY_TERMS = (
    "docs", "documentation", "developers", "developer", "api", "reference",
    "guide", "guides", "learn", "tutorial", "tutorials", "help", "support",
    "faq", "faqs", "knowledge", "blog", "resources", "insights", "security",
    "manual", "handbook", "artikel", "panduan", "layanan", "publikasi",
    "statistik", "regulasi", "edukasi", "sekolah", "kesehatan", "pajak",
)

BAD_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js",
    ".zip", ".rar", ".7z", ".mp3", ".mp4", ".avi", ".mov", ".woff", ".ttf",
)


@dataclass(frozen=True)
class Source:
    domain: str
    category: str
    language: str = "en"
    max_urls: int = 200
    sitemap_paths: tuple[str, ...] = (
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/sitemap-index.xml",
        "/sitemap/sitemap.xml",
        "/sitemaps/sitemap.xml",
        "/robots.txt",
    )


def src(domain: str, category: str, language: str = "en", max_urls: int = 200) -> Source:
    return Source(domain=domain, category=category, language=language, max_urls=max_urls)


SOURCES: dict[str, list[Source]] = {
    "general_ai": [
        src("platform.openai.com", "AI Documentation", max_urls=400),
        src("openai.com", "AI Documentation", max_urls=250),
        src("docs.anthropic.com", "AI Documentation", max_urls=250),
        src("ai.google.dev", "AI Documentation", max_urls=300),
        src("cloud.google.com", "Cloud & DevOps", max_urls=400),
        src("console.groq.com", "AI Documentation", max_urls=150),
        src("docs.cohere.com", "AI Documentation", max_urls=250),
        src("docs.mistral.ai", "AI Documentation", max_urls=250),
        src("huggingface.co", "AI Documentation", max_urls=350),
        src("docs.perplexity.ai", "AI Documentation", max_urls=150),
        src("docs.python.org", "Programming Documentation", max_urls=350),
        src("developer.mozilla.org", "Programming Documentation", max_urls=500),
        src("www.typescriptlang.org", "Programming Documentation", max_urls=150),
        src("react.dev", "Programming Documentation", max_urls=250),
        src("nextjs.org", "Programming Documentation", max_urls=250),
        src("nodejs.org", "Programming Documentation", max_urls=200),
        src("fastapi.tiangolo.com", "Programming Documentation", max_urls=200),
        src("docs.djangoproject.com", "Programming Documentation", max_urls=250),
        src("flask.palletsprojects.com", "Programming Documentation", max_urls=150),
        src("doc.rust-lang.org", "Programming Documentation", max_urls=250),
        src("go.dev", "Programming Documentation", max_urls=250),
        src("docs.oracle.com", "Programming Documentation", max_urls=250),
        src("learn.microsoft.com", "Programming Documentation", max_urls=600),
        src("www.php.net", "Programming Documentation", max_urls=200),
        src("laravel.com", "Programming Documentation", max_urls=150),
        src("docs.aws.amazon.com", "Cloud & DevOps", max_urls=650),
        src("docs.microsoft.com", "Cloud & DevOps", max_urls=250),
        src("developers.cloudflare.com", "Cloud & DevOps", max_urls=350),
        src("vercel.com", "Cloud & DevOps", max_urls=250),
        src("docs.netlify.com", "Cloud & DevOps", max_urls=150),
        src("www.postgresql.org", "Database", max_urls=250),
        src("dev.mysql.com", "Database", max_urls=250),
        src("redis.io", "Database", max_urls=250),
        src("www.mongodb.com", "Database", max_urls=250),
        src("supabase.com", "Database", max_urls=250),
        src("owasp.org", "Cyber Security", max_urls=350),
        src("developers.cloudflare.com", "Cyber Security", max_urls=250),
        src("security.googleblog.com", "Cyber Security", max_urls=150),
        src("www.microsoft.com", "Cyber Security", max_urls=250),
        src("knowledge.hubspot.com", "Business & Startup", max_urls=300),
        src("help.salesforce.com", "Business & Startup", max_urls=300),
        src("www.mckinsey.com", "Business & Startup", max_urls=200),
        src("www.ycombinator.com", "Business & Startup", max_urls=200),
        src("stripe.com", "Business & Startup", max_urls=300),
        src("www.investopedia.com", "Finance & Economy", max_urls=350),
        src("www.worldbank.org", "Finance & Economy", max_urls=250),
        src("www.imf.org", "Finance & Economy", max_urls=250),
        src("www.bps.go.id", "Indonesian Sources", "id", 400),
        src("www.bi.go.id", "Indonesian Sources", "id", 250),
        src("www.ojk.go.id", "Indonesian Sources", "id", 300),
        src("www.pajak.go.id", "Indonesian Sources", "id", 300),
        src("www.kemdikbud.go.id", "Indonesian Sources", "id", 200),
        src("www.kemkes.go.id", "Indonesian Sources", "id", 200),
        src("kemenag.go.id", "Indonesian Sources", "id", 200),
        src("indonesia.go.id", "Indonesian Sources", "id", 250),
        src("www.kominfo.go.id", "Indonesian Sources", "id", 200),
        src("www.bkn.go.id", "Indonesian Sources", "id", 150),
        src("bpjs-kesehatan.go.id", "Indonesian Sources", "id", 150),
    ],
    "travel_agent": [
        src("www.traveloka.com", "Travel Help & Guides", "id", 250),
        src("www.tiket.com", "Travel Help & Guides", "id", 200),
        src("support.google.com", "Travel Help & Guides", max_urls=250),
        src("www.booking.com", "Travel Help & Guides", max_urls=200),
        src("partner.booking.com", "Travel Help & Guides", max_urls=200),
        src("www.expedia.com", "Travel Help & Guides", max_urls=160),
        src("www.tripadvisor.com", "Travel Help & Guides", max_urls=160),
        src("www.lonelyplanet.com", "Travel Guides", max_urls=180),
        src("www.indonesia.travel", "Travel Indonesia", "id", 250),
        src("www.iata.org", "Travel Regulations", max_urls=120),
        src("www.imigrasi.go.id", "Travel Indonesia", "id", 150),
    ],
    "ecommerce_agent": [
        src("help.shopify.com", "E-commerce Documentation", max_urls=350),
        src("woocommerce.com", "E-commerce Documentation", max_urls=250),
        src("developer.woocommerce.com", "E-commerce Documentation", max_urls=200),
        src("docs.stripe.com", "Payments Documentation", max_urls=300),
        src("developer.paypal.com", "Payments Documentation", max_urls=250),
        src("seller.tokopedia.com", "Marketplace Seller Guides", "id", 180),
        src("seller.shopee.co.id", "Marketplace Seller Guides", "id", 180),
        src("www.lazada.co.id", "Marketplace Seller Guides", "id", 120),
        src("support.google.com", "E-commerce Help", max_urls=250),
        src("developers.google.com", "E-commerce Developer Docs", max_urls=250),
    ],
    "clinic_agent": [
        src("www.who.int", "Health Official Guidance", max_urls=300),
        src("www.cdc.gov", "Health Official Guidance", max_urls=300),
        src("www.nih.gov", "Health Official Guidance", max_urls=200),
        src("medlineplus.gov", "Health Education", max_urls=250),
        src("www.mayoclinic.org", "Health Education", max_urls=250),
        src("www.kemkes.go.id", "Indonesia Health", "id", 300),
        src("sehatnegeriku.kemkes.go.id", "Indonesia Health", "id", 250),
        src("yankes.kemkes.go.id", "Indonesia Health", "id", 250),
        src("bpjs-kesehatan.go.id", "Indonesia Health", "id", 200),
    ],
    "school_agent": [
        src("www.kemdikbud.go.id", "Indonesia Education", "id", 300),
        src("pusatinformasi.kemdikbud.go.id", "Indonesia Education", "id", 300),
        src("guru.kemdikbud.go.id", "Indonesia Education", "id", 250),
        src("www.kemenag.go.id", "Indonesia Education", "id", 180),
        src("www.khanacademy.org", "Education Resources", max_urls=250),
        src("support.google.com", "Education Help", max_urls=250),
        src("learn.microsoft.com", "Education Technology", max_urls=300),
        src("www.edutopia.org", "Education Resources", max_urls=180),
        src("www.unesco.org", "Education Policy", max_urls=200),
    ],
    "sales_agent": [
        src("knowledge.hubspot.com", "Sales Knowledge Base", max_urls=450),
        src("blog.hubspot.com", "Sales Guides", max_urls=300),
        src("help.salesforce.com", "Salesforce Help", max_urls=350),
        src("trailhead.salesforce.com", "Salesforce Learning", max_urls=250),
        src("www.salesforce.com", "Sales Guides", max_urls=250),
        src("support.pipedrive.com", "CRM Help", max_urls=220),
        src("www.zoho.com", "CRM Help", max_urls=200),
        src("stripe.com", "Business & Revenue", max_urls=250),
    ],
    "property_agent": [
        src("www.rumah.com", "Property Guides", "id", 180),
        src("www.rumah123.com", "Property Guides", "id", 180),
        src("www.99.co", "Property Guides", "id", 180),
        src("www.realtor.com", "Property Guides", max_urls=250),
        src("www.zillow.com", "Property Guides", max_urls=250),
        src("www.investopedia.com", "Real Estate Finance", max_urls=250),
        src("www.irs.gov", "Property Tax Guidance", max_urls=160),
        src("www.atrbpn.go.id", "Indonesia Property Regulation", "id", 200),
        src("www.pu.go.id", "Indonesia Property Regulation", "id", 160),
    ],
    "faq_agent": [
        src("support.google.com", "FAQ & Help Center", max_urls=450),
        src("support.microsoft.com", "FAQ & Help Center", max_urls=350),
        src("help.openai.com", "FAQ & Help Center", max_urls=250),
        src("help.shopify.com", "FAQ & Help Center", max_urls=250),
        src("knowledge.hubspot.com", "FAQ & Help Center", max_urls=250),
        src("help.salesforce.com", "FAQ & Help Center", max_urls=250),
        src("docs.stripe.com", "FAQ & Help Center", max_urls=250),
        src("help.netflix.com", "FAQ & Help Center", max_urls=150),
    ],
    "customer_service_agent": [
        src("support.zendesk.com", "Customer Service Help", max_urls=350),
        src("www.zendesk.com", "Customer Service Guides", max_urls=250),
        src("help.intercom.com", "Customer Service Help", max_urls=250),
        src("knowledge.hubspot.com", "Customer Service Help", max_urls=300),
        src("help.salesforce.com", "Customer Service Help", max_urls=300),
        src("support.freshdesk.com", "Customer Service Help", max_urls=250),
        src("support.google.com", "Customer Service Help", max_urls=250),
        src("support.microsoft.com", "Customer Service Help", max_urls=250),
    ],
    "botnesia_business": [
        src("botnesia.id", "BotNesia Business", "id", 500),
        src("docs.botnesia.id", "BotNesia Business", "id", 500),
        src("help.openai.com", "AI Assistant Operations", max_urls=160),
        src("platform.openai.com", "AI Assistant Operations", max_urls=160),
        src("docs.stripe.com", "Billing Operations", max_urls=160),
        src("developers.facebook.com", "WhatsApp Integration", max_urls=220),
        src("developers.cloudflare.com", "Deployment Operations", max_urls=160),
    ],
}

FALLBACK_PATHS = (
    "/", "/docs", "/documentation", "/docs/getting-started", "/docs/guides",
    "/docs/api-reference", "/developers", "/developer", "/api", "/reference",
    "/help", "/support", "/faq", "/faqs", "/knowledge-base", "/guides",
    "/tutorials", "/learn", "/resources", "/blog", "/security", "/pricing",
)

CURATED_TOPICS = (
    "getting-started", "overview", "quickstart", "setup", "configuration",
    "authentication", "authorization", "security", "privacy", "billing",
    "pricing", "account", "users", "teams", "roles", "permissions", "api",
    "api-reference", "webhooks", "integrations", "migration", "deployment",
    "troubleshooting", "best-practices", "faq", "support", "guides",
    "tutorials", "examples", "templates", "analytics", "reporting",
    "automation", "workflow", "data", "import", "export", "compliance",
    "refund", "returns", "shipping", "payments", "invoice", "subscription",
    "crm", "sales", "marketing", "customer-service", "help-center",
    "knowledge-base", "chatbot", "whatsapp", "email", "notifications",
    "travel", "booking", "hotel", "flight", "visa", "passport", "insurance",
    "clinic", "appointment", "patient", "telemedicine", "pharmacy",
    "school", "student", "teacher", "curriculum", "assessment", "admission",
    "property", "mortgage", "rent", "lease", "listing", "valuation",
    "indonesia", "regulation", "tax", "finance", "statistics", "economy",
)

CURATED_SECTIONS = (
    "docs", "documentation", "help", "support", "guide", "guides", "learn",
    "resources", "blog", "articles", "knowledge", "faq", "tutorials",
    "developers", "developer", "reference", "manual", "panduan", "layanan",
    "artikel", "edukasi", "publikasi",
)


def normalize_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.netloc:
        return ""
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    query = parsed.query
    return urlunparse((scheme, netloc, path, "", query, ""))


def is_probably_quality_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    lower = url.lower()
    if any(lower.endswith(ext) for ext in BAD_EXTENSIONS):
        return False
    if any(x in lower for x in ("?replytocom=", "/tag/", "/author/", "/wp-json/", "/feed/")):
        return False
    if parsed.path in ("", "/"):
        return True
    return any(term in lower for term in QUALITY_TERMS)


def fetch_url(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "BotNesiaKnowledgeDiscovery/1.0 (+trusted-sitemap-discovery)",
            "Accept": "application/xml,text/xml,text/plain,text/html,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(10_000_000)
        if url.endswith(".gz"):
            return gzip.decompress(data)
        return data


def parse_robots_for_sitemaps(body: bytes) -> list[str]:
    urls = []
    for line in body.decode("utf-8", "ignore").splitlines():
        if line.lower().startswith("sitemap:"):
            urls.append(line.split(":", 1)[1].strip())
    return urls


def parse_sitemap(body: bytes) -> tuple[list[str], list[str]]:
    text = body.decode("utf-8", "ignore").strip()
    if not text.startswith("<"):
        return [], []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], []
    sitemaps: list[str] = []
    urls: list[str] = []
    for loc in root.iter():
        if loc.tag.endswith("loc") and loc.text:
            value = loc.text.strip()
            if value.endswith(".xml") or "sitemap" in value.lower():
                sitemaps.append(value)
            else:
                urls.append(value)
    return sitemaps, urls


def sitemap_candidates(source: Source) -> list[str]:
    base = f"https://{source.domain}"
    return [urljoin(base, path) for path in source.sitemap_paths]


def curated_candidates(source: Source, limit: int) -> list[str]:
    candidates = [normalize_url(f"https://{source.domain}{path}") for path in FALLBACK_PATHS]
    for section in CURATED_SECTIONS:
        for topic in CURATED_TOPICS:
            candidates.append(normalize_url(f"https://{source.domain}/{section}/{topic}"))
            if len(candidates) >= limit:
                return [u for u in candidates if u and is_probably_quality_url(u)]
    return [u for u in candidates if u and is_probably_quality_url(u)]


def discover_from_source(
    source: Source,
    timeout: float,
    delay: float,
    max_sitemaps: int,
    source_seconds: float,
) -> tuple[list[str], list[str]]:
    discovered: list[str] = []
    failed: list[str] = []
    queue = sitemap_candidates(source)
    seen_sitemaps: set[str] = set()
    started_at = time.monotonic()

    while queue and len(seen_sitemaps) < max_sitemaps and len(discovered) < source.max_urls:
        if time.monotonic() - started_at > source_seconds:
            failed.append(f"{source.domain}:source_time_limit")
            break
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            body = fetch_url(sitemap_url, timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            failed.append(sitemap_url)
            continue
        if sitemap_url.endswith("/robots.txt"):
            queue.extend(u for u in parse_robots_for_sitemaps(body) if u not in seen_sitemaps)
            continue
        child_sitemaps, urls = parse_sitemap(body)
        queue.extend(u for u in child_sitemaps if u not in seen_sitemaps)
        for url in urls:
            norm = normalize_url(url)
            if norm and source.domain in urlparse(norm).netloc and is_probably_quality_url(norm):
                discovered.append(norm)
                if len(discovered) >= source.max_urls:
                    break
        if delay:
            time.sleep(delay)

    if len(discovered) < source.max_urls:
        for candidate in curated_candidates(source, source.max_urls * 2):
            if candidate not in discovered:
                discovered.append(candidate)
            if len(discovered) >= source.max_urls:
                break

    return discovered[: source.max_urls], failed


def load_seed(agent: str) -> list[dict]:
    path = SEEDS_DIR / f"{agent}_urls.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def write_seed(agent: str, rows: list[dict]) -> None:
    path = SEEDS_DIR / f"{agent}_urls.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def row_for(url: str, agent: str, source: Source) -> dict:
    return {
        "url": url,
        "category": source.category,
        "priority": "high" if source.language == "id" or "Documentation" in source.category else "normal",
        "agent": agent,
        "language": source.language,
        "trusted": True,
    }


def iter_agent_sources(agent: str) -> Iterable[Source]:
    yield from SOURCES[agent]


def expand_agent(agent: str, timeout: float, delay: float, max_sitemaps: int, source_seconds: float) -> dict:
    rows = load_seed(agent)
    existing = {normalize_url(row.get("url", "")) for row in rows if row.get("url")}
    before = len(rows)
    duplicate_removed = 0
    failed_urls: list[str] = []
    added_by_domain: Counter[str] = Counter()
    added_by_category: Counter[str] = Counter()

    target = AGENT_TARGETS[agent]
    for source in iter_agent_sources(agent):
        if len(rows) >= target:
            break
        discovered, failed = discover_from_source(source, timeout, delay, max_sitemaps, source_seconds)
        failed_urls.extend(failed[:5])
        for url in discovered:
            norm = normalize_url(url)
            if not norm:
                continue
            if norm in existing:
                duplicate_removed += 1
                continue
            rows.append(row_for(norm, agent, source))
            existing.add(norm)
            added_by_domain[urlparse(norm).netloc] += 1
            added_by_category[source.category] += 1
            if len(rows) >= target:
                break

    write_seed(agent, rows)
    return {
        "agent": agent,
        "before": before,
        "after": len(rows),
        "added": len(rows) - before,
        "target": target,
        "duplicate_removed": duplicate_removed,
        "failed_urls": failed_urls,
        "category_breakdown": dict(added_by_category),
        "top_domains": dict(added_by_domain.most_common(12)),
    }


def build_report(results: list[dict]) -> dict:
    total_by_agent = {r["agent"]: r["after"] for r in results}
    total_indexed = sum(total_by_agent.values())
    duplicate_removed = sum(r["duplicate_removed"] for r in results)
    failed_urls = [url for r in results for url in r["failed_urls"]]
    categories: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    for r in results:
        categories.update(r["category_breakdown"])
        domains.update(r["top_domains"])
    return {
        "total_url_per_agent": total_by_agent,
        "total_url_indexed": total_indexed,
        "duplicate_removed": duplicate_removed,
        "failed_urls": failed_urls,
        "category_breakdown": dict(categories.most_common()),
        "top_domains_used": dict(domains.most_common(25)),
        "targets_met": {r["agent"]: r["after"] >= r["target"] for r in results},
        "results": results,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", nargs="*", default=list(AGENT_TARGETS))
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--max-sitemaps", type=int, default=80)
    parser.add_argument("--source-seconds", type=float, default=12.0)
    args = parser.parse_args(argv)

    unknown = set(args.agents) - set(AGENT_TARGETS)
    if unknown:
        print(f"Unknown agents: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    REPORT_DIR.mkdir(exist_ok=True)
    results = []
    for agent in args.agents:
        print(f"Discovering {agent}...", flush=True)
        results.append(expand_agent(agent, args.timeout, args.delay, args.max_sitemaps, args.source_seconds))

    report = build_report(results)
    report_path = REPORT_DIR / "knowledge_url_expansion_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
