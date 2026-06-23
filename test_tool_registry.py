"""
test_tool_registry.py — Tool Framework (Agent OS Phase 2): entri baru
channel_messaging/email_reader/document_generator/calendar, update
general_web_search, dan web_search_status().
"""
import tool_registry as tr


def test_available_tools_includes_new_entries_and_excludes_calendar():
    available = tr.available_tools()
    assert "channel_messaging" in available
    assert "email_reader" in available
    assert "document_generator" in available
    assert "calendar" not in available
    assert "general_web_search" not in available


def test_describe_tool_channel_messaging_shape():
    meta = tr.describe_tool("channel_messaging")
    assert meta["available"] is True
    assert meta["implementation"] == "bn_platform.channel_manager.ChannelManager.send_message"
    assert "WhatsApp" in meta["description"]


def test_describe_tool_email_reader_shape():
    meta = tr.describe_tool("email_reader")
    assert meta["available"] is True
    assert "TIDAK mengirim email" in meta["description"]


def test_describe_tool_document_generator_shape():
    meta = tr.describe_tool("document_generator")
    assert meta["available"] is True
    assert meta["implementation"] == "document_generator.generate_document"


def test_describe_tool_calendar_unavailable_shape():
    meta = tr.describe_tool("calendar")
    assert meta["available"] is False
    assert "unavailable_reason" in meta


def test_describe_tool_general_web_search_has_implementation_but_unavailable():
    meta = tr.describe_tool("general_web_search")
    assert meta["available"] is False
    assert meta["implementation"] == "web_search_agent.search"
    assert "belum dikonfigurasi" in meta["unavailable_reason"]


def test_web_search_status_unconfigured_by_default():
    status = tr.web_search_status()
    assert status["available"] is False


def test_web_search_status_available_with_searxng_url():
    status = tr.web_search_status(searxng_url="http://localhost:8080")
    assert status["available"] is True


def test_web_search_status_available_with_tavily_key():
    status = tr.web_search_status(tavily_api_key="test-key")
    assert status["available"] is True
