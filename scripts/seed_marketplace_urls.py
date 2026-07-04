#!/usr/bin/env python3
"""Generate/import BotNesia marketplace knowledge URL seeds.

Default mode writes a normalized JSON seed file. With --import and database env
vars configured, it queues sources without crawling them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / "backend" / "seeds" / "agent_marketplace_1000_urls.json"

import sys
sys.path.insert(0, str(ROOT))
from bn_platform.agent_marketplace_catalog import PROFESSIONAL_AGENT_TEMPLATES  # noqa: E402

CATEGORY_URLS = {
    "Sales & Marketing": [
        "https://www.hubspot.com/sales", "https://blog.hubspot.com/sales", "https://knowledge.hubspot.com/sales",
        "https://mailchimp.com/resources/", "https://ads.google.com/home/resources/", "https://www.facebook.com/business/help",
        "https://www.tiktok.com/business/en/resources", "https://moz.com/beginners-guide-to-seo", "https://support.google.com/google-ads",
        "https://www.salesforce.com/resources/", "https://www.shopify.com/blog/marketing", "https://stripe.com/atlas/guides",
    ],
    "Customer Service": [
        "https://www.zendesk.com/blog/customer-service-skills/", "https://support.zendesk.com/hc/en-us", "https://www.intercom.com/help",
        "https://knowledge.hubspot.com/service", "https://www.salesforce.com/service/resources/", "https://support.freshdesk.com/support/home",
        "https://support.google.com/business", "https://support.microsoft.com", "https://www.nngroup.com/articles/customer-service/", "https://www.shopify.com/blog/customer-service",
    ],
    "HR & Recruitment": [
        "https://www.shrm.org/resourcesandtools/", "https://www.linkedin.com/business/talent/blog", "https://help.linkedin.com/app/home",
        "https://www.indeed.com/hire/resources", "https://www.glassdoor.com/employers/resources/", "https://www.bamboohr.com/resources",
        "https://www.workday.com/en-us/resources.html", "https://support.google.com/a/users/answer/9282720", "https://learn.microsoft.com/en-us/viva/", "https://www.dol.gov/general/topic/hiring",
    ],
    "Finance & Accounting": [
        "https://www.investopedia.com/accounting-4689741", "https://www.irs.gov/businesses", "https://www.pajak.go.id/id",
        "https://www.ojk.go.id/id/kanal/edukasi-dan-perlindungan-konsumen/", "https://www.bi.go.id/id/edukasi/", "https://www.xero.com/resources/",
        "https://quickbooks.intuit.com/r/", "https://stripe.com/docs/invoicing", "https://docs.stripe.com/billing", "https://www.worldbank.org/en/topic/financialsector",
    ],
    "Legal & Compliance": [
        "https://www.hukumonline.com/klinik/", "https://peraturan.bpk.go.id/", "https://www.kominfo.go.id/",
        "https://www.termsfeed.com/blog/", "https://gdpr.eu/", "https://www.ftc.gov/business-guidance",
        "https://www.iso.org/standards.html", "https://www.ojk.go.id/id/regulasi/", "https://www.docusign.com/blog", "https://www.contractscounsel.com/b/contract",
    ],
    "Ecommerce": [
        "https://help.shopify.com/en/manual", "https://woocommerce.com/documentation/", "https://developer.woocommerce.com/docs/",
        "https://docs.stripe.com/payments", "https://developer.paypal.com/docs/", "https://seller.shopee.co.id/edu/home",
        "https://seller.tokopedia.com/edu", "https://support.google.com/merchants", "https://www.shopify.com/blog/ecommerce", "https://woocommerce.com/posts/",
    ],
    "Retail": [
        "https://www.shopify.com/retail", "https://www.shopify.com/blog/retail", "https://squareup.com/us/en/the-bottom-line/operating-your-business",
        "https://www.nrf.com/resources", "https://support.google.com/business", "https://help.shopify.com/en/manual/sell-in-person",
        "https://www.lightspeedhq.com/blog/", "https://quickbooks.intuit.com/r/retail/", "https://www.sba.gov/business-guide/manage-your-business", "https://www.investopedia.com/terms/i/inventory-management.asp",
    ],
    "Restaurant": [
        "https://squareup.com/us/en/the-bottom-line/restaurants", "https://pos.toasttab.com/blog", "https://www.restaurant.org/research-and-media/resource-library/",
        "https://support.google.com/business/answer/3039617", "https://www.foodsafety.gov/", "https://www.fda.gov/food",
        "https://www.tripadvisor.com/Owners", "https://www.ubereats.com/merchant", "https://help.doordash.com/merchants/s/", "https://www.shopify.com/blog/food-business",
    ],
    "Hospitality": [
        "https://partner.booking.com/en-us/help", "https://www.expediapartnercentral.com/", "https://www.tripadvisor.com/Owners",
        "https://www.unwto.org/resources", "https://www.oracle.com/hospitality/resources/", "https://www.cloudbeds.com/articles/",
        "https://www.siteminder.com/r/", "https://support.google.com/business", "https://www.ahla.com/resources", "https://www.hospitalitynet.org/",
    ],
    "Travel": [
        "https://www.iata.org/en/publications/", "https://www.unwto.org/resources", "https://www.indonesia.travel/gb/en/home",
        "https://www.imigrasi.go.id/", "https://www.traveloka.com/en-id/help", "https://www.tiket.com/help-center",
        "https://support.google.com/travel", "https://partner.booking.com/en-us/help", "https://www.lonelyplanet.com/articles", "https://www.tripadvisor.com/TravelersChoice",
    ],
    "Healthcare": [
        "https://www.who.int/health-topics", "https://www.cdc.gov/", "https://medlineplus.gov/",
        "https://www.mayoclinic.org/patient-care-and-health-information", "https://www.kemkes.go.id/", "https://sehatnegeriku.kemkes.go.id/",
        "https://yankes.kemkes.go.id/", "https://bpjs-kesehatan.go.id/", "https://www.nih.gov/health-information", "https://www.halodoc.com/artikel",
    ],
    "Education": [
        "https://www.kemdikbud.go.id/", "https://pusatinformasi.kemdikbud.go.id/", "https://guru.kemdikbud.go.id/",
        "https://www.kemenag.go.id/", "https://www.khanacademy.org/", "https://support.google.com/edu",
        "https://learn.microsoft.com/en-us/training/educator-center/", "https://www.unesco.org/en/education", "https://www.edutopia.org/", "https://www.coursera.org/articles",
    ],
    "Real Estate": [
        "https://www.investopedia.com/mortgage-and-real-estate-4689743", "https://www.realtor.com/advice/", "https://www.zillow.com/learn/",
        "https://www.rumah.com/panduan-properti", "https://www.rumah123.com/panduan-properti/", "https://www.99.co/id/panduan",
        "https://www.atrbpn.go.id/", "https://www.consumerfinance.gov/consumer-tools/mortgages/", "https://www.irs.gov/businesses/small-businesses-self-employed/real-estate-tax-center", "https://www.bankrate.com/mortgages/",
    ],
    "Startup": [
        "https://www.ycombinator.com/library", "https://www.ycombinator.com/startup-library", "https://stripe.com/atlas/guides",
        "https://www.sba.gov/business-guide", "https://www.firstround.com/review/", "https://a16z.com/category/company-building/",
        "https://www.producthunt.com/stories", "https://www.notion.so/help", "https://www.hubspot.com/startups", "https://www.mckinsey.com/capabilities/growth-marketing-and-sales/our-insights",
    ],
    "Technology": [
        "https://platform.openai.com/docs", "https://ai.google.dev/docs",
        "https://developer.mozilla.org/en-US/docs/Web", "https://docs.python.org/3/", "https://react.dev/learn",
        "https://nextjs.org/docs", "https://nodejs.org/en/learn", "https://docs.aws.amazon.com/", "https://developers.cloudflare.com/",
        "https://owasp.org/www-project-top-ten/", "https://www.postgresql.org/docs/", "https://docs.github.com/",
    ],
    "Logistics": [
        "https://www.dhl.com/global-en/home/insights-and-innovation.html", "https://www.fedex.com/en-us/small-business.html", "https://www.ups.com/us/en/supplychain/resources.page",
        "https://www.maersk.com/insights", "https://www.flexport.com/blog/", "https://www.shopify.com/blog/shipping-and-fulfillment",
        "https://support.google.com/business", "https://www.investopedia.com/terms/s/supplychain.asp", "https://www.oracle.com/scm/resources/", "https://aws.amazon.com/blogs/supply-chain/",
    ],
    "Manufacturing": [
        "https://www.nist.gov/manufacturing", "https://www.iso.org/standards.html", "https://www.oracle.com/scm/manufacturing/resources/",
        "https://www.ibm.com/topics/manufacturing", "https://www.sap.com/products/scm/industry-4-0.html", "https://www.mckinsey.com/capabilities/operations/our-insights",
        "https://www.siemens.com/global/en/company/stories/industry.html", "https://www.autodesk.com/industry/manufacturing/resources", "https://www.osha.gov/manufacturing", "https://www.epa.gov/sustainability",
    ],
    "Agriculture": [
        "https://www.fao.org/home/en", "https://www.fao.org/family-farming/en/", "https://www.usda.gov/topics/farming",
        "https://www.worldbank.org/en/topic/agriculture", "https://www.pertanian.go.id/", "https://pustaka.setjen.pertanian.go.id/",
        "https://www.cgiar.org/research/", "https://www.agriculture.com/", "https://www.fao.org/markets-and-trade/en/", "https://www.irri.org/knowledge-bank",
    ],
    "Creator Economy": [
        "https://support.google.com/youtube/", "https://www.youtube.com/creators/", "https://www.tiktok.com/creators/creator-portal/en-us/",
        "https://www.tiktok.com/business/en/resources", "https://help.instagram.com/", "https://creators.instagram.com/",
        "https://www.canva.com/learn/", "https://support.patreon.com/hc/en-us", "https://blog.hootsuite.com/", "https://buffer.com/resources/",
    ],
    "Government": [
        "https://indonesia.go.id/", "https://www.kominfo.go.id/", "https://www.bps.go.id/",
        "https://www.bi.go.id/id/", "https://www.ojk.go.id/id/", "https://www.pajak.go.id/id",
        "https://www.bkn.go.id/", "https://www.usa.gov/", "https://www.gov.uk/", "https://data.go.id/",
    ],
    "Religious & Community": [
        "https://quran.kemenag.go.id/", "https://kemenag.go.id/", "https://bimasislam.kemenag.go.id/",
        "https://simbi.kemenag.go.id/", "https://baznas.go.id/", "https://mui.or.id/",
        "https://islamic-relief.org/", "https://www.muslimhands.org.uk/", "https://www.eventbrite.com/blog/", "https://support.google.com/nonprofits/",
    ],
    "Internal Business Operations": [
        "https://support.google.com/a/users/", "https://support.microsoft.com/", "https://learn.microsoft.com/en-us/power-automate/",
        "https://zapier.com/resources", "https://www.atlassian.com/software/confluence/resources", "https://support.atlassian.com/jira-software-cloud/",
        "https://www.notion.so/help", "https://slack.com/help", "https://www.tableau.com/learn/articles", "https://www.zendesk.com/blog/knowledge-management/",
    ],
}
SOURCE_TYPE_BY_DOMAIN = {
    "go.id": "government", "gov": "government", "who.int": "official_health", "cdc.gov": "official_health",
    "support": "official_help_center", "docs": "official_docs_or_guide", "developer": "official_docs_or_guide",
}


def slug_value(value: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def source_type(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for key, value in SOURCE_TYPE_BY_DOMAIN.items():
        if key in host:
            return value
    return "official_docs_or_guide"


def _load_existing_seed_pool(filename: str) -> list[str]:
    path = ROOT / "seeds" / filename
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [normalize_url(row.get("url", "")) for row in rows if row.get("url")]


CATEGORY_POOL_FILES = {
    "Sales & Marketing": ["sales_agent_urls.json", "general_ai_urls.json"],
    "Customer Service": ["customer_service_agent_urls.json", "faq_agent_urls.json"],
    "HR & Recruitment": ["general_ai_urls.json", "botnesia_business_urls.json"],
    "Finance & Accounting": ["general_ai_urls.json", "botnesia_business_urls.json"],
    "Legal & Compliance": ["general_ai_urls.json", "botnesia_business_urls.json"],
    "Ecommerce": ["ecommerce_agent_urls.json", "customer_service_agent_urls.json"],
    "Retail": ["ecommerce_agent_urls.json", "sales_agent_urls.json"],
    "Restaurant": ["customer_service_agent_urls.json", "ecommerce_agent_urls.json"],
    "Hospitality": ["travel_agent_urls.json", "customer_service_agent_urls.json"],
    "Travel": ["travel_agent_urls.json", "customer_service_agent_urls.json"],
    "Healthcare": ["clinic_agent_urls.json", "faq_agent_urls.json"],
    "Education": ["school_agent_urls.json", "general_ai_urls.json"],
    "Real Estate": ["property_agent_urls.json", "sales_agent_urls.json"],
    "Startup": ["botnesia_business_urls.json", "general_ai_urls.json"],
    "Technology": ["general_ai_urls.json"],
    "Logistics": ["ecommerce_agent_urls.json", "general_ai_urls.json"],
    "Manufacturing": ["general_ai_urls.json", "botnesia_business_urls.json"],
    "Agriculture": ["general_ai_urls.json", "botnesia_business_urls.json"],
    "Creator Economy": ["general_ai_urls.json", "sales_agent_urls.json"],
    "Government": ["general_ai_urls.json"],
    "Religious & Community": ["general_ai_urls.json", "botnesia_business_urls.json"],
    "Internal Business Operations": ["botnesia_business_urls.json", "general_ai_urls.json"],
}


def _category_pool(category: str) -> list[str]:
    urls: list[str] = []
    urls.extend(CATEGORY_URLS.get(category, []))
    for filename in CATEGORY_POOL_FILES.get(category, ["general_ai_urls.json"]):
        urls.extend(_load_existing_seed_pool(filename))
    out = []
    seen = set()
    for url in urls:
        normalized = normalize_url(url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def build_seed_rows(target_file: Path) -> tuple[list[dict], dict]:
    rows = []
    global_seen = set()
    duplicate_removed = 0
    failed_url: list[str] = []
    pools = {category: _category_pool(category) for category in CATEGORY_URLS}
    cursors = defaultdict(int)
    base_counts = Counter(template["agent_id"] for template in PROFESSIONAL_AGENT_TEMPLATES)

    for template in PROFESSIONAL_AGENT_TEMPLATES:
        category = template["category"]
        base_agent_id = template["agent_id"]
        agent_id = f"{slug_value(category)}_{base_agent_id}" if base_counts[base_agent_id] > 1 else base_agent_id
        pool = pools.get(category) or _category_pool("Technology")
        added = 0
        attempts = 0
        while added < 7 and attempts < len(pool):
            index = cursors[category] % len(pool)
            cursors[category] += 1
            attempts += 1
            normalized = normalize_url(pool[index])
            if not normalized or normalized in global_seen:
                duplicate_removed += 1
                continue
            global_seen.add(normalized)
            lang = "id" if any(domain in normalized for domain in ("go.id", "kemkes", "kemdikbud", "kemenag", "pajak", "ojk", "bi.go.id", "bps.go.id", "bpjs", "rumah", "traveloka", "tiket", "tokopedia", "shopee", "baznas", "mui", "indonesia.go.id", "kominfo")) else "en"
            rows.append({
                "tenant_id": None,
                "agent_id": agent_id,
                "agent_name": template["name"],
                "category": category,
                "url": normalized,
                "source_type": source_type(normalized),
                "priority": "high" if added < 3 else "normal",
                "language": lang,
                "trusted": True,
                "status": "pending",
            })
            added += 1
        if added < 7:
            failed_url.append(f"{agent_id}: only {added} unique URLs available")
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    category_counts = Counter(row["category"] for row in rows)
    agent_counts = Counter(row["agent_id"] for row in rows)
    return rows, {
        "total_agent": len(agent_counts),
        "total_url": len(rows),
        "url_per_category": dict(category_counts),
        "min_url_per_agent": min(agent_counts.values()) if agent_counts else 0,
        "max_url_per_agent": max(agent_counts.values()) if agent_counts else 0,
        "duplicate_removed": duplicate_removed,
        "failed_url": failed_url,
        "file": str(target_file),
    }


async def import_to_database(file_path: Path, tenant_id: str, bot_id: str) -> dict:
    import asyncpg
    import knowledge_seeder
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL wajib diset untuk --import")
    rows = json.loads(file_path.read_text(encoding="utf-8"))
    pool = await asyncpg.create_pool(dsn)
    try:
        result = await knowledge_seeder.bulk_import_urls(pool, org_id=tenant_id, bot_id=bot_id, urls_data=[{
            "url": row["url"], "title": row["agent_name"], "category": row["category"],
            "priority": row.get("priority", "normal"), "agent": row["agent_id"],
            "language": row.get("language", "id"), "trusted": row.get("trusted", True),
        } for row in rows])
        result["stats"] = await knowledge_seeder.get_source_stats(pool, org_id=tenant_id, bot_id=bot_id)
        return result
    finally:
        await pool.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=str(DEFAULT_FILE))
    parser.add_argument("--import", dest="do_import", action="store_true", help="Queue URLs into DB without crawling")
    parser.add_argument("--tenant-id")
    parser.add_argument("--bot-id")
    args = parser.parse_args()
    target = Path(args.file)
    rows, report = build_seed_rows(target)
    if args.do_import:
        if not args.tenant_id or not args.bot_id:
            raise SystemExit("--tenant-id dan --bot-id wajib untuk --import")
        report["import_result"] = asyncio.run(import_to_database(target, args.tenant_id, args.bot_id))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
