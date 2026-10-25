from decimal import Decimal

from models import TipEntry
from app import app


def test_local_net_tip_calculations_preserved():
    tip = TipEntry(cash_tips=20, card_tips=80, tip_out=15, hours_worked=5, sales_amount=500)
    assert tip.total_tips == Decimal("100")
    assert tip.net_tips == Decimal("85")
    assert tip.tips_per_hour == Decimal("17")
    tip.tip_out = 25
    tip.recalculate_derived_fields()
    assert tip.tips_per_hour == Decimal("15")


def test_pages_health_and_auth_guards(client):
    for path in ["/", "/terms", "/privacy", "/healthz", "/api/tips?demo=true"]:
        assert client.get(path).status_code == 200
    assert client.get("/auth/user").status_code == 401
    assert client.get("/api/tips").status_code == 401
    assert client.post("/auth/session", json={}).status_code == 400
    assert client.post("/api/tips", json={}).status_code == 401


def test_health_does_not_expose_connection_details(client):
    assert client.get("/healthz").json["db_uri"] == "configured database"
