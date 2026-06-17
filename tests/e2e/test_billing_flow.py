"""
E2E billing flow — READ-ONLY per "JANGAN UBAH BILLING & USAGE / PRICING".
Validates the existing billing/usage surface works end-to-end against the
real DB; never calls /api/billing/checkout or any payment-gateway mutation.
"""


def test_billing_plans_are_publicly_listable(client):
    resp = client.get("/api/billing/plans")
    assert resp.status_code == 200, resp.text
    plans = resp.json()["plans"]
    assert len(plans) >= 1
    assert all("key" in p for p in plans)


def test_new_org_has_trial_subscription_and_usage(client, registered_org):
    sub_resp = client.get("/api/billing/subscription", headers=registered_org["headers"])
    assert sub_resp.status_code == 200, sub_resp.text
    sub_data = sub_resp.json()
    assert "subscription" in sub_data
    assert "usage" in sub_data
    assert "limits" in sub_data

    usage_resp = client.get("/api/billing/usage", headers=registered_org["headers"])
    assert usage_resp.status_code == 200, usage_resp.text
    usage = usage_resp.json()["usage"]
    assert isinstance(usage, dict) and len(usage) > 0
    for dim_detail in usage.values():
        assert "within_limit" in dim_detail


def test_billing_endpoints_require_auth(client):
    resp = client.get("/api/billing/subscription")
    assert resp.status_code in (401, 403)
