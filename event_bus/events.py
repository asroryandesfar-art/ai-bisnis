"""event_bus.events — konstanta tipe event standar BotNesia (P0-C).

Pakai konstanta ini (bukan string mentah) supaya konsisten & mudah di-refactor.
"""
# Durable Task Runtime (P0-D)
TASK_STARTED = "TaskStarted"
TASK_FINISHED = "TaskFinished"
TASK_FAILED = "TaskFailed"

# Memory / Knowledge
MEMORY_UPDATED = "MemoryUpdated"
KNOWLEDGE_UPDATED = "KnowledgeUpdated"

# Web Intelligence
BROWSER_FINISHED = "BrowserFinished"
SCRAPER_FINISHED = "ScraperFinished"

# Workflow
WORKFLOW_COMPLETED = "WorkflowCompleted"

ALL_EVENT_TYPES = (
    TASK_STARTED, TASK_FINISHED, TASK_FAILED,
    MEMORY_UPDATED, KNOWLEDGE_UPDATED,
    BROWSER_FINISHED, SCRAPER_FINISHED,
    WORKFLOW_COMPLETED,
)
