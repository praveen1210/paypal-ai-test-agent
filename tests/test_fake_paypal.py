"""The fake mirrors behaviour verified against the real sandbox."""

from payagent.fake_paypal import FakePayPalClient


def test_card_order_is_captured_at_create():
    r = FakePayPalClient().create_order("10.00")
    assert r.status == 201 and r.body["status"] == "COMPLETED"
    assert r.body["purchase_units"][0]["payments"]["captures"][0]["status"] == "COMPLETED"


def test_over_capture_allowed_up_to_115_percent():
    pp = FakePayPalClient()
    auth_id = pp.create_order("40.00", intent="AUTHORIZE").body["purchase_units"][0]["payments"]["authorizations"][0]["id"]
    assert pp.capture_authorization(auth_id, "25.00", final_capture=False).status == 201
    assert pp.capture_authorization(auth_id, "20.00", final_capture=False).status == 201  # total 45 <= 46
    assert pp.capture_authorization(auth_id, "2.00").status == 422  # total 47 > 46


def test_refund_equal_to_gross_is_truncated_like_sandbox():
    pp = FakePayPalClient()
    cap_id = pp.create_order("20.00").body["purchase_units"][0]["payments"]["captures"][0]["id"]
    assert pp.refund_capture(cap_id, "10.00").status == 201
    assert pp.refund_capture(cap_id, "15.00").status == 422
    r = pp.refund_capture(cap_id, "20.00")
    assert r.status == 201 and r.body["amount"]["value"] == "10.00"


def test_void_remainder_after_partial_capture():
    pp = FakePayPalClient()
    auth_id = pp.create_order("40.00", intent="AUTHORIZE").body["purchase_units"][0]["payments"]["authorizations"][0]["id"]
    assert pp.capture_authorization(auth_id, "25.00", final_capture=False).status == 201
    r = pp.void_authorization(auth_id)
    assert r.status == 200 and r.body["status"] == "VOIDED"
    assert pp.void_authorization(auth_id).status == 422


def test_responses_are_snapshots_and_order_view_is_current():
    pp = FakePayPalClient()
    order = pp.create_order("40.00", intent="AUTHORIZE").body
    auth_id = order["purchase_units"][0]["payments"]["authorizations"][0]["id"]
    before = pp.get_authorization(auth_id)
    pp.capture_authorization(auth_id, "25.00", final_capture=False)
    pp.void_authorization(auth_id)
    assert before.body["status"] == "CREATED"          # earlier response unchanged
    assert "captured" not in before.body               # no internal bookkeeping leaks
    view = pp.get_order(order["id"]).body["purchase_units"][0]["payments"]
    assert view["authorizations"][0]["status"] == "VOIDED"
    assert view["captures"][0]["amount"]["value"] == "25.00"
