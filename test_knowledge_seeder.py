import asyncio
import json
from pathlib import Path

import knowledge_seeder as ks


SEED_DIR = Path(__file__).parent / "seeds"


def _load(name):
    return json.loads((SEED_DIR / f"{name}_urls.json").read_text())


def test_seed_files_have_minimum_100_urls_for_required_agents():
    required = [
        "general_ai", "travel_agent", "ecommerce_agent", "clinic_agent", "school_agent",
        "sales_agent", "property_agent", "faq_agent", "customer_service_agent", "botnesia_business",
    ]
    for name in required:
        rows = _load(name)
        assert len(rows) >= 100, name
        assert all("url" in row and "category" in row and "agent" in row for row in rows[:100])


def test_general_travel_ecommerce_seed_first_100_are_importable_urls():
    for name in ["general_ai", "travel_agent", "ecommerce_agent"]:
        rows = _load(name)[:100]
        assert len(rows) == 100
        assert all(ks.is_valid_url(row["url"]) for row in rows), name


class FakePool:
    def __init__(self):
        self.sources = {}
        self.documents = {}
        self.doc_chunks = []
        self.embeddings = {}
        self.executed = []
        self.fetch_calls = []

    async def fetchval(self, query, *args):
        self.fetch_calls.append((query, args))
        if "SELECT id FROM knowledge_sources" in query:
            bot_id, url = args
            for row in self.sources.values():
                if row["bot_id"] == bot_id and row["url"] == url:
                    return row["id"]
            return None
        if "SELECT id FROM documents" in query:
            bot_id, url = args
            for row in self.documents.values():
                if row.get("bot_id") == bot_id and row.get("source_url") == url:
                    return row["id"]
            return None
        if "SELECT status FROM documents" in query:
            return self.documents[str(args[0])]["status"]
        if "SELECT error_msg FROM documents" in query:
            return self.documents[str(args[0])].get("error_msg")
        return None

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if "INSERT INTO knowledge_sources" in query:
            source_id, org_id, bot_id, url, title, category, agent_type, priority, language, trusted = args
            self.sources[source_id] = {
                "id": source_id, "org_id": org_id, "bot_id": bot_id, "tenant_id": org_id,
                "agent_id": bot_id, "url": url, "title": title, "category": category,
                "agent_type": agent_type, "priority": priority, "language": language,
                "trusted": trusted, "status": "pending", "retry_count": 0,
            }
            return "INSERT 0 1"
        if "INSERT INTO documents" in query:
            doc_id, org_id, bot_id, title, _size, _mime, url = args
            self.documents[doc_id] = {"id": doc_id, "org_id": org_id, "bot_id": bot_id, "filename": title, "source_url": url, "status": "pending"}
            return "INSERT 0 1"
        if "SET status='crawling'" in query:
            self.sources[str(args[0])]["status"] = "crawling"
            return "UPDATE 1"
        if "SET status='indexed'" in query:
            doc_id, source_id = args
            self.sources[str(source_id)]["status"] = "indexed"
            self.sources[str(source_id)]["document_id"] = doc_id
            return "UPDATE 1"
        if "SET status='failed'" in query:
            err, source_id = args
            self.sources[str(source_id)]["status"] = "failed"
            self.sources[str(source_id)]["error_message"] = err
            return "UPDATE 1"
        if "INSERT INTO knowledge_chunks" in query:
            return "INSERT 0 1"
        if "SET status='pending', error_message=NULL" in query:
            source_id, org_id, max_retry = args
            row = self.sources.get(str(source_id))
            if row and row["org_id"] == org_id and row["status"] == "failed" and row.get("retry_count", 0) < max_retry:
                row["status"] = "pending"
                row["retry_count"] = row.get("retry_count", 0) + 1
                row.pop("error_message", None)
                return "UPDATE 1"
            return "UPDATE 0"
        return "OK"

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        if "FROM knowledge_sources" in query:
            org_id, bot_id, limit = args[:3]
            rows = [row for row in self.sources.values() if row["org_id"] == org_id and row["bot_id"] == bot_id and row["status"] == "pending"]
            return rows[:limit]
        if "FROM doc_chunks" in query:
            doc_id = args[0]
            return [row for row in self.doc_chunks if row["document_id"] == doc_id]
        return []


async def _fake_process(pool, doc_id, **kwargs):
    pool.documents[str(doc_id)]["status"] = "ready"
    pool.doc_chunks.append({"id": "chunk-1", "document_id": str(doc_id), "content": "Hotel refund policy content", "chunk_index": 0, "embedding": [1.0, 0.0]})


def test_bulk_import_skips_duplicate_urls_per_agent():
    pool = FakePool()
    rows = [
        {"url": "https://example.com/help", "category": "faq", "agent": "faq_agent"},
        {"url": "https://example.com/help/", "category": "faq", "agent": "faq_agent"},
    ]
    result = asyncio.run(ks.bulk_import_urls(pool, org_id="tenant-a", bot_id="agent-a", urls_data=rows))
    assert result["imported"] == 1
    assert result["skipped_duplicate"] == 1
    assert len(pool.sources) == 1


def test_crawler_moves_source_from_pending_to_indexed_and_keeps_agent_isolation():
    pool = FakePool()
    asyncio.run(ks.bulk_import_urls(pool, org_id="tenant-a", bot_id="travel-agent", urls_data=[{"url":"https://example.com/hotel", "agent":"travel_agent"}]))
    result = asyncio.run(ks.run_crawler_batch(pool, org_id="tenant-a", bot_id="travel-agent", fetch_fn=None, process_fn=_fake_process, batch_size=10))
    source = next(iter(pool.sources.values()))
    assert result["crawled"] == 1
    assert source["status"] == "indexed"
    assert source["org_id"] == "tenant-a"
    assert source["bot_id"] == "travel-agent"


def test_failed_source_retry_is_capped_and_tenant_scoped():
    pool = FakePool()
    asyncio.run(ks.bulk_import_urls(pool, org_id="tenant-a", bot_id="agent-a", urls_data=[{"url":"https://example.com/refund"}]))
    source_id = next(iter(pool.sources))
    pool.sources[source_id]["status"] = "failed"
    ok = asyncio.run(ks.retry_source(pool, source_id=source_id, org_id="tenant-a"))
    blocked_other_tenant = asyncio.run(ks.retry_source(pool, source_id=source_id, org_id="tenant-b"))
    assert ok is True
    assert blocked_other_tenant is False


def test_get_sources_query_filters_by_org_and_bot_for_tenant_agent_isolation():
    pool = FakePool()
    asyncio.run(ks.run_crawler_batch(pool, org_id="tenant-a", bot_id="agent-a", fetch_fn=None, process_fn=_fake_process, batch_size=1))
    assert pool.fetch_calls[-1][1][:2] == ("tenant-a", "agent-a")



def test_marketplace_1000_seed_file_contract():
    rows = json.loads((Path(__file__).parent / "backend" / "seeds" / "agent_marketplace_1000_urls.json").read_text())
    urls = [row["url"] for row in rows]
    agents = {}
    categories = set()
    required = {"tenant_id", "agent_id", "agent_name", "category", "url", "source_type", "priority", "language", "trusted", "status"}
    assert len(rows) >= 1000
    assert len(urls) == len(set(urls))
    for row in rows:
        assert required.issubset(row)
        assert row["status"] == "pending"
        assert ks.is_valid_url(row["url"])
        agents[row["agent_id"]] = agents.get(row["agent_id"], 0) + 1
        categories.add(row["category"])
    assert len(agents) >= 100
    assert min(agents.values()) >= 5
    assert len(categories) == 22
