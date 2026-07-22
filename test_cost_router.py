"""P2-A — Cost Router: klasifikasi 5-arah + mapping + dispatch router."""
import asyncio

from cost_intelligence import classify_task_class, router_params, TASK_CLASSES


def test_classify_vision():
    assert classify_task_class("apa isi gambar ini?") == "vision"
    assert classify_task_class("analisa ini", has_image=True) == "vision"


def test_classify_coding():
    assert classify_task_class("tolong debug error python ini") == "coding"
    assert classify_task_class("```def f(): pass```") == "coding"


def test_classify_complex_via_hint():
    # hint analitis (heuristic_complexity → 'complex'), bukan coding/vision
    assert classify_task_class("tolong analisa dampak keputusan ini terhadap bisnis") == "complex"
    assert classify_task_class("bandingkan kelebihan dan kekurangan dua opsi ini") == "complex"


def test_classify_simple_short():
    assert classify_task_class("halo") == "simple"
    assert classify_task_class("makasih ya") == "simple"


def test_classify_medium_longish_plain():
    msg = ("tolong buatkan kalimat sapaan hangat untuk pelanggan baru yang ramah "
           "sopan dan singkat supaya mereka merasa dihargai saat pertama kali datang")
    assert len(msg) > 120
    assert classify_task_class(msg) == "medium"


def test_router_params_mapping():
    assert router_params("coding") == {"tier": "pro", "task_type": "coding"}
    assert router_params("vision") == {"tier": "pro", "task_type": "multimodal"}
    assert router_params("complex") == {"tier": "pro", "task_type": "reasoning"}
    assert router_params("simple") == {"tier": "standard", "task_type": "standard"}
    assert router_params("tak_dikenal") == {"tier": "standard", "task_type": "standard"}   # default medium
    assert set(TASK_CLASSES) == {"simple", "medium", "complex", "coding", "vision"}


def test_route_for_message_dispatches_by_class():
    from ai_providers.router import SmartModelRouter
    r = SmartModelRouter()
    captured = {}

    async def fake_route(request, *, tier, task_type):
        captured.clear(); captured.update(tier=tier, task_type=task_type)
        return "resp"
    r.route = fake_route

    asyncio.run(r.route_for_message(object(), user_message="tolong debug error python"))
    assert captured == {"tier": "pro", "task_type": "coding"}
    asyncio.run(r.route_for_message(object(), user_message="halo"))
    assert captured == {"tier": "standard", "task_type": "standard"}
    asyncio.run(r.route_for_message(object(), user_message="apa ini", has_image=True))
    assert captured["task_type"] == "multimodal"


def test_stream_answer_uses_cost_router_when_flag_on(monkeypatch):
    import chat_streaming
    import feature_flags as ff
    captured = {}

    class FakeRouter:
        async def stream(self, req, *, tier, task_type):
            captured.clear(); captured.update(tier=tier, task_type=task_type)
            for _ in ():                                    # async gen kosong
                yield _
    monkeypatch.setattr(chat_streaming, "build_provider_router", lambda cfg: FakeRouter())

    async def _drain(**kw):
        async for _ in chat_streaming.stream_answer([{"role": "user", "content": "x"}], object(), **kw):
            pass

    ff.set_override("cost_router", True)
    asyncio.run(_drain(user_message="tolong debug error python", org_id="org1"))
    assert captured == {"tier": "pro", "task_type": "coding"}    # dirutekan ke coding

    ff.clear_all_overrides()                                     # flag OFF → default
    asyncio.run(_drain(user_message="tolong debug error python", org_id="org1"))
    assert captured == {"tier": "standard", "task_type": "standard"}
    asyncio.run(_drain())                                        # tanpa user_message → default
    assert captured == {"tier": "standard", "task_type": "standard"}
