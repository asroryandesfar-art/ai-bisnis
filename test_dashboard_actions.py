import re
from pathlib import Path

import main


ROOT = Path(__file__).resolve().parent


def test_every_rendered_data_action_has_a_click_handler():
    source = "\n".join(
        (ROOT / relative).read_text()
        for relative in ("frontend/app.js", "frontend/components.js", "frontend/index.html")
    )
    rendered = set(re.findall(r'data-action=["\']([^"\']+)["\']', source))
    handled = set(re.findall(r'action\s*===\s*["\']([^"\']+)["\']', source))

    assert rendered
    assert rendered - handled == set()


def test_fastapi_dependencies_are_not_exposed_as_query_parameters():
    suspicious = []
    dependency_names = {"user", "pool", "current_user", "request"}
    for route in main.app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        leaked = dependency_names.intersection(parameter.name for parameter in dependant.query_params)
        if leaked:
            suspicious.append((route.path, sorted(leaked)))

    assert suspicious == []


def test_frontend_has_no_inert_conversation_menu_button():
    source = (ROOT / "frontend/app.js").read_text()
    assert "<button class=\"icon-button\">${icon('more')}</button>" not in source
