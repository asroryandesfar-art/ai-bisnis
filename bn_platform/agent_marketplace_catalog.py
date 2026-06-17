"""
Professional Agent Marketplace catalog for BotNesia Phase 4.

The catalog is intentionally data-driven so the platform can ship 100+ reusable
agent templates without rebuilding the existing marketplace service.
"""
from __future__ import annotations

import json
import re
from collections import Counter

MARKETPLACE_CATEGORIES = [
    ("Sales & Marketing", "Agents for pipeline generation, acquisition, campaigns, and conversion."),
    ("Customer Service", "Agents for support, complaint handling, retention, and service recovery."),
    ("HR & Recruitment", "Agents for hiring, onboarding, training, policy, and employee operations."),
    ("Finance & Accounting", "Agents for bookkeeping, tax preparation, budgets, reports, and payroll."),
    ("Legal & Compliance", "Agents for contract review, policy guidance, and compliance workflows."),
    ("Ecommerce", "Agents for online store operations, product discovery, checkout, and fulfillment."),
    ("Retail", "Agents for store operations, membership, promotions, and inventory support."),
    ("Restaurant", "Agents for reservations, menu guidance, delivery, and feedback."),
    ("Hospitality", "Agents for hotels, guest service, booking, concierge, and housekeeping."),
    ("Travel", "Agents for itinerary planning, bookings, visas, and travel support."),
    ("Healthcare", "Agents for clinics, hospitals, appointments, patient FAQ, and education."),
    ("Education", "Agents for schools, universities, admissions, tutors, and student support."),
    ("Real Estate", "Agents for property sales, rentals, mortgage, valuation, and FAQ."),
    ("Startup", "Agents for founders, GTM, fundraising, pitch, and growth operations."),
    ("Technology", "Agents for developers, APIs, DevOps, databases, security, docs, QA, and product."),
    ("Logistics", "Agents for shipping, warehousing, fleet, procurement, and supply chain."),
    ("Manufacturing", "Agents for production, maintenance, QA, SOP, and supplier workflows."),
    ("Agriculture", "Agents for farming, livestock, crop planning, and agribusiness support."),
    ("Creator Economy", "Agents for YouTube, TikTok, Instagram, scripts, thumbnails, and community."),
    ("Government", "Agents for public service, permits, citizen FAQ, and program information."),
    ("Religious & Community", "Agents for Islamic FAQ, mosque, community, events, and donation."),
    ("Internal Business Operations", "Agents for supervisor routing, analytics, knowledge, memory, handoff, workflow, and automation."),
]

CATEGORY_DESCRIPTIONS = dict(MARKETPLACE_CATEGORIES)
CATEGORY_COLORS = {
    "Sales & Marketing": "#7C3AED", "Customer Service": "#2563EB", "HR & Recruitment": "#DB2777",
    "Finance & Accounting": "#059669", "Legal & Compliance": "#475569", "Ecommerce": "#EA580C",
    "Retail": "#D97706", "Restaurant": "#DC2626", "Hospitality": "#0891B2", "Travel": "#0EA5E9",
    "Healthcare": "#10B981", "Education": "#F59E0B", "Real Estate": "#8B5CF6", "Startup": "#06B6D4",
    "Technology": "#3B82F6", "Logistics": "#0F766E", "Manufacturing": "#64748B", "Agriculture": "#65A30D",
    "Creator Economy": "#EC4899", "Government": "#1D4ED8", "Religious & Community": "#16A34A",
    "Internal Business Operations": "#14B8A6",
}
CATEGORY_ICONS = {
    "Sales & Marketing": "megaphone", "Customer Service": "headphones", "HR & Recruitment": "users",
    "Finance & Accounting": "calculator", "Legal & Compliance": "shield", "Ecommerce": "cart", "Retail": "store",
    "Restaurant": "utensils", "Hospitality": "hotel", "Travel": "plane", "Healthcare": "heart-pulse",
    "Education": "graduation-cap", "Real Estate": "building", "Startup": "rocket", "Technology": "code",
    "Logistics": "truck", "Manufacturing": "factory", "Agriculture": "leaf", "Creator Economy": "video",
    "Government": "landmark", "Religious & Community": "community", "Internal Business Operations": "workflow",
}

AGENT_NAMES_BY_CATEGORY = {
    "Sales & Marketing": ["Sales Agent", "Lead Generation Agent", "Prospecting Agent", "Cold Outreach Agent", "Follow-up Agent", "WhatsApp Marketing Agent", "Email Marketing Agent", "Content Marketing Agent", "SEO Agent", "SEM Agent", "Facebook Ads Agent", "Google Ads Agent", "TikTok Ads Agent", "Conversion Optimization Agent", "Funnel Agent", "Product Launch Agent", "Market Research Agent", "Competitor Analysis Agent", "Branding Agent", "Copywriting Agent"],
    "Customer Service": ["Customer Service Agent", "Ticket Support Agent", "Complaint Handling Agent", "Retention Agent", "Loyalty Agent", "Escalation Agent", "Refund Agent", "Order Tracking Agent", "Support FAQ Agent", "Service Recovery Agent"],
    "HR & Recruitment": ["HR Agent", "Recruitment Agent", "CV Screening Agent", "Interview Agent", "Onboarding Agent", "Employee Handbook Agent", "Training Agent", "Performance Review Agent", "Attendance Agent", "Internal Policy Agent"],
    "Finance & Accounting": ["Accounting Agent", "Bookkeeping Agent", "Invoice Agent", "Tax Assistant Agent", "Budget Planner Agent", "Financial Report Agent", "Cashflow Agent", "Expense Tracking Agent", "Payroll Agent", "Finance FAQ Agent"],
    "Legal & Compliance": ["Contract Agent", "Compliance Agent", "Legal FAQ Agent", "Policy Agent", "Terms & Conditions Agent"],
    "Ecommerce": ["Ecommerce Agent", "Product Recommendation Agent", "Product Catalog Agent", "Checkout Agent", "Cart Recovery Agent", "Refund Agent", "Shipping Agent", "Marketplace Agent", "Order Tracking Agent", "Inventory Agent"],
    "Retail": ["Retail Store Agent", "POS Support Agent", "Membership Agent", "Promotion Agent", "Store Inventory Agent", "Store Operations Agent"],
    "Restaurant": ["Restaurant Agent", "Reservation Agent", "Menu Agent", "Food Recommendation Agent", "Delivery Agent", "Customer Feedback Agent"],
    "Hospitality": ["Hotel Agent", "Guest Service Agent", "Concierge Agent", "Room Booking Agent", "Housekeeping Agent", "Guest Feedback Agent"],
    "Travel": ["Travel Agent", "Itinerary Agent", "Flight Booking Agent", "Hotel Booking Agent", "Visa Information Agent", "Tour Package Agent"],
    "Healthcare": ["Clinic Agent", "Hospital Agent", "Appointment Agent", "Patient FAQ Agent", "Medical Information Agent", "Health Education Agent"],
    "Education": ["School Agent", "University Agent", "Tutor Agent", "Admission Agent", "Student Service Agent", "Academic FAQ Agent"],
    "Real Estate": ["Property Agent", "Rental Agent", "Mortgage Agent", "Property Valuation Agent", "Real Estate FAQ Agent"],
    "Startup": ["Founder Assistant Agent", "Pitch Deck Agent", "Fundraising Agent", "Go To Market Agent", "MVP Planning Agent", "Startup Metrics Agent"],
    "Technology": ["General AI Agent", "Developer Agent", "API Agent", "DevOps Agent", "Database Agent", "Security Agent", "Documentation Agent", "QA Agent", "Product Management Agent"],
    "Logistics": ["Shipping Agent", "Warehouse Agent", "Fleet Management Agent", "Procurement Agent", "Supply Chain Agent"],
    "Manufacturing": ["Production Planning Agent", "Maintenance Agent", "Quality Control Agent", "SOP Agent", "Supplier Coordination Agent"],
    "Agriculture": ["Agriculture Agent", "Crop Advisory Agent", "Livestock Agent", "Farm Finance Agent", "Agri Marketplace Agent"],
    "Creator Economy": ["YouTube Agent", "TikTok Agent", "Instagram Agent", "Content Planner Agent", "Script Writer Agent", "Thumbnail Agent", "Community Manager Agent"],
    "Government": ["Public Service Agent", "Permit Information Agent", "Citizen FAQ Agent", "Program Outreach Agent", "Document Requirement Agent"],
    "Religious & Community": ["Islamic FAQ Agent", "Mosque Agent", "Community Agent", "Event Agent", "Donation Agent"],
    "Internal Business Operations": ["Supervisor Agent", "Analytics Agent", "Knowledge Agent", "Memory Agent", "Human Handoff Agent", "Workflow Agent", "Automation Agent"],
}

TOOL_PRESETS = {
    "Sales & Marketing": ["lead_capture", "crm_lookup", "campaign_brief", "follow_up_scheduler"],
    "Customer Service": ["knowledge_base_search", "ticket_lookup", "order_lookup", "sentiment_check"],
    "HR & Recruitment": ["candidate_screening", "calendar_scheduling", "policy_search", "training_tracker"],
    "Finance & Accounting": ["invoice_lookup", "expense_tracker", "report_builder", "tax_knowledge"],
    "Legal & Compliance": ["policy_search", "contract_summary", "risk_checklist", "audit_log"],
    "Ecommerce": ["catalog_search", "order_lookup", "cart_recovery", "inventory_check"],
    "Retail": ["inventory_check", "promotion_lookup", "member_lookup", "store_sop"],
    "Restaurant": ["menu_lookup", "reservation_calendar", "delivery_status", "feedback_capture"],
    "Hospitality": ["booking_lookup", "guest_profile", "concierge_suggestions", "housekeeping_queue"],
    "Travel": ["itinerary_builder", "booking_lookup", "visa_knowledge", "destination_search"],
    "Healthcare": ["appointment_scheduler", "service_catalog", "patient_faq", "urgent_care_warning"],
    "Education": ["admission_faq", "academic_calendar", "student_service", "course_catalog"],
    "Real Estate": ["property_search", "mortgage_calculator", "lead_capture", "valuation_notes"],
    "Startup": ["business_model_canvas", "market_research", "pitch_review", "metric_tracker"],
    "Technology": ["code_help", "api_docs_search", "deployment_checklist", "security_review"],
    "Logistics": ["shipment_tracking", "warehouse_lookup", "fleet_status", "procurement_request"],
    "Manufacturing": ["production_sop", "maintenance_log", "quality_check", "supplier_lookup"],
    "Agriculture": ["crop_calendar", "weather_context", "market_price_notes", "farm_sop"],
    "Creator Economy": ["content_calendar", "script_outline", "trend_research", "community_reply"],
    "Government": ["public_faq", "document_checklist", "program_lookup", "case_status"],
    "Religious & Community": ["event_calendar", "donation_info", "community_faq", "announcement_builder"],
    "Internal Business Operations": ["supervisor_router", "analytics_summary", "knowledge_base_search", "workflow_trigger"],
}

VISIBILITY = {"public": True, "featured": False, "recommended": True}
FEATURED_NAMES = {"General AI Agent", "Supervisor Agent", "Customer Service Agent", "Sales Agent", "Ecommerce Agent", "Clinic Agent", "School Agent", "Travel Agent", "Developer Agent", "WhatsApp Marketing Agent", "Lead Generation Agent", "Analytics Agent"}


def _slug(value: str) -> str:
    text = value.lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _agent_type(name: str) -> str:
    return _slug(name).replace("-agent", "").replace("-", "_") + "_agent"


def _description(name: str, category: str) -> str:
    focus = name.replace(" Agent", "").lower()
    return f"Professional {name} untuk {category.lower()}: menangani percakapan, FAQ, rekomendasi, dan workflow operasional terkait {focus}."


def _prompt(name: str, category: str) -> str:
    focus = name.replace(" Agent", "")
    base = (
        f"Kamu adalah {name} di BotNesia untuk kategori {category}. "
        f"Bantu bisnis menyelesaikan kebutuhan {focus.lower()} secara jelas, sopan, terstruktur, dan berbasis knowledge base tenant. "
        "Ikuti urutan Solve, Explain, Recommend, Clarify, Escalate. "
        "Jangan menawarkan human handoff kecuali pengguna memintanya secara eksplisit. "
        "Jika knowledge belum cukup, ajukan pertanyaan klarifikasi singkat dan jelaskan asumsi. "
        "Jangan mengarang harga, legal, medis, pajak, atau data operasional yang tidak tersedia di konteks."
    )
    if name == "General AI Agent":
        return base + " Mode ini menjawab pertanyaan umum seperti ChatGPT: teknologi, coding, bisnis, pendidikan, ekonomi, ide usaha, dan penjelasan konsep."
    if name == "Supervisor Agent":
        return base + " Tugas utama: klasifikasi intent, pilih agent terbaik, beri confidence score, dan fallback ke General AI jika intent tidak cocok."
    return base


def _knowledge_sources(name: str, category: str) -> list[dict]:
    topic = _slug(name.replace(" Agent", ""))
    return [
        {"type": "category", "category": category, "agent": _agent_type(name)},
        {"type": "url_seed", "url": f"https://botnesia.id/docs/agents/{topic}", "priority": "normal"},
    ]


def _starter_questions(name: str, category: str) -> list[str]:
    focus = name.replace(" Agent", "").lower()
    return [
        f"Apa yang bisa dibantu oleh {name}?",
        f"Bantu saya membuat workflow {focus} untuk bisnis saya.",
        f"Informasi apa yang perlu saya tambahkan ke knowledge base {category}?",
    ]


def build_professional_agent_templates() -> list[dict]:
    templates: list[dict] = []
    sequence = 0
    for category, names in AGENT_NAMES_BY_CATEGORY.items():
        for name in names:
            sequence += 1
            key = _slug(name)
            featured = name in FEATURED_NAMES
            install_seed = 1800 - sequence * 7 if featured else 420 - sequence
            templates.append({
                "agent_id": key,
                "key": key,
                "category": category,
                "name": name,
                "description": _description(name, category),
                "system_prompt": _prompt(name, category),
                "greeting": f"Halo! Saya {name} BotNesia. Apa yang ingin Anda bantu hari ini?",
                "primary_color": CATEGORY_COLORS[category],
                "icon": CATEGORY_ICONS[category],
                "tools": TOOL_PRESETS[category],
                "knowledge_sources": _knowledge_sources(name, category),
                "starter_questions": _starter_questions(name, category),
                "visibility": {**VISIBILITY, "featured": featured},
                "rating": 4.9 if featured else 4.7,
                "popularity_score": max(10, 1000 - sequence * 4),
                "install_count": max(0, install_seed),
                "version": "4.0.0",
                "sample_faqs": [
                    {"question": f"Bagaimana cara memakai {name}?", "answer": f"Install {name}, tambahkan knowledge bisnis Anda, lalu gunakan agent untuk percakapan dan workflow {category.lower()}."},
                    {"question": "Apakah knowledge bercampur dengan agent lain?", "answer": "Tidak. Knowledge disimpan per tenant dan per agent agar konteks tidak tercampur."},
                    {"question": "Kapan perlu human handoff?", "answer": "Hanya jika pengguna meminta bantuan manusia atau kasus membutuhkan keputusan di luar wewenang AI."},
                ],
            })
    return templates


PROFESSIONAL_AGENT_TEMPLATES = build_professional_agent_templates()


def marketplace_summary(templates: list[dict] | None = None) -> dict:
    rows = templates or PROFESSIONAL_AGENT_TEMPLATES
    categories = Counter(row["category"] for row in rows)
    return {
        "template_count": len(rows),
        "category_count": len(categories),
        "categories": dict(categories),
        "featured_count": sum(1 for row in rows if row.get("visibility", {}).get("featured")),
    }


async def seed_professional_marketplace(pool) -> dict:
    rows = PROFESSIONAL_AGENT_TEMPLATES
    for category, description in MARKETPLACE_CATEGORIES:
        await pool.execute(
            """INSERT INTO agent_categories (key, name, description, icon, color, sort_order)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (key) DO UPDATE SET
                 name=EXCLUDED.name, description=EXCLUDED.description, icon=EXCLUDED.icon,
                 color=EXCLUDED.color, sort_order=EXCLUDED.sort_order""",
            _slug(category), category, description, CATEGORY_ICONS[category], CATEGORY_COLORS[category],
            [item[0] for item in MARKETPLACE_CATEGORIES].index(category),
        )
    for row in rows:
        await pool.execute(
            """INSERT INTO marketplace_templates
               (key, category, name, description, preview_image, system_prompt, greeting, primary_color,
                sample_faqs, install_count, version, is_active, icon, tools, knowledge_sources,
                starter_questions, visibility, rating, popularity_score)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,TRUE,$12,$13::jsonb,$14::jsonb,$15::jsonb,$16::jsonb,$17,$18)
               ON CONFLICT (key) DO UPDATE SET
                 category=EXCLUDED.category,
                 name=EXCLUDED.name,
                 description=EXCLUDED.description,
                 system_prompt=EXCLUDED.system_prompt,
                 greeting=EXCLUDED.greeting,
                 primary_color=EXCLUDED.primary_color,
                 sample_faqs=EXCLUDED.sample_faqs,
                 version=EXCLUDED.version,
                 is_active=TRUE,
                 icon=EXCLUDED.icon,
                 tools=EXCLUDED.tools,
                 knowledge_sources=EXCLUDED.knowledge_sources,
                 starter_questions=EXCLUDED.starter_questions,
                 visibility=EXCLUDED.visibility,
                 rating=EXCLUDED.rating,
                 popularity_score=EXCLUDED.popularity_score,
                 install_count=GREATEST(marketplace_templates.install_count, EXCLUDED.install_count)""",
            row["key"], row["category"], row["name"], row["description"], None,
            row["system_prompt"], row["greeting"], row["primary_color"], json.dumps(row["sample_faqs"]),
            row["install_count"], row["version"], row["icon"], json.dumps(row["tools"]),
            json.dumps(row["knowledge_sources"]), json.dumps(row["starter_questions"]),
            json.dumps(row["visibility"]), row["rating"], row["popularity_score"],
        )
    await pool.execute(
        """INSERT INTO agents (template_id, agent_id, name, description, category, icon, color, visibility, is_active)
           SELECT id, key, name, description, category, icon, primary_color, visibility, is_active
             FROM marketplace_templates
            WHERE key = ANY($1::text[])
           ON CONFLICT (agent_id) DO UPDATE SET
             template_id=EXCLUDED.template_id, name=EXCLUDED.name, description=EXCLUDED.description,
             category=EXCLUDED.category, icon=EXCLUDED.icon, color=EXCLUDED.color,
             visibility=EXCLUDED.visibility, is_active=EXCLUDED.is_active, updated_at=NOW()""",
        [row["key"] for row in rows],
    )
    await pool.execute(
        """INSERT INTO agent_versions (agent_id, version, prompt, tools, starter_questions, changelog)
           SELECT a.id, mt.version, mt.system_prompt, mt.tools, mt.starter_questions, 'Phase 4 professional marketplace catalog'
             FROM agents a
             JOIN marketplace_templates mt ON mt.id = a.template_id
            WHERE mt.key = ANY($1::text[])
           ON CONFLICT (agent_id, version) DO UPDATE SET
             prompt=EXCLUDED.prompt, tools=EXCLUDED.tools, starter_questions=EXCLUDED.starter_questions""",
        [row["key"] for row in rows],
    )
    await pool.execute(
        """INSERT INTO agent_knowledge_sources (agent_id, template_id, source_type, url, category, priority)
           SELECT a.id, mt.id, COALESCE(src->>'type','url'), src->>'url', COALESCE(src->>'category', mt.category), COALESCE(src->>'priority','normal')
             FROM agents a
             JOIN marketplace_templates mt ON mt.id = a.template_id
             CROSS JOIN LATERAL jsonb_array_elements(mt.knowledge_sources) AS src
            WHERE mt.key = ANY($1::text[]) AND COALESCE(src->>'url','') <> ''
           ON CONFLICT DO NOTHING""",
        [row["key"] for row in rows],
    )
    return marketplace_summary(rows)
