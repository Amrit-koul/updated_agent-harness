"""Seeded account access for the Collections domain pipeline."""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .db.database import Base, SessionLocal, engine
from .db.models import AIProfile, Claim, Customer, Interaction, LoanAccount, PTPHistory
from .services.intelligence.account_context import enrich_account_data
from agent_harness.authorization import authorize_current_resource


SEED_PATH = Path(__file__).parent / "data" / "accounts.json"


def ensure_seeded():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(LoanAccount).first():
            return
        for raw in json.loads(SEED_PATH.read_text(encoding="utf-8")):
            customer_id = f"CUST-{uuid.uuid4().hex[:8].upper()}"
            db.add(Customer(id=customer_id, name=raw.get("name", "Unknown"), age=raw.get("age"), city=raw.get("city"), job_profile=raw.get("job"), cibil_score=raw.get("cibil")))
            db.add(LoanAccount(id=raw["id"], customer_id=customer_id, product_type=raw.get("product"), outstanding=raw.get("outstanding", 0), emi=raw.get("emi", 0), dpd=raw.get("dpd", 0), bucket=raw.get("bucket"), status=raw.get("status"), priority=raw.get("priority")))
            scores = raw.get("scores", {})
            db.add(AIProfile(id=f"AIP-{uuid.uuid4().hex[:8].upper()}", account_id=raw["id"], persona=raw.get("persona", "unknown_insufficient_data"), persona_confidence=raw.get("persona_confidence", 0.5), scores=scores, trust_score=scores.get("trust_score"), atp_score=scores.get("ability_to_pay"), itp_score=scores.get("intent_to_pay"), contactability_score=scores.get("contactability"), primary_channel=raw.get("primary_channel"), fallback_channel=raw.get("fallback_channel"), next_action=raw.get("next_action")))
            for index, text in enumerate(raw.get("call_history", [])):
                db.add(Interaction(id=f"INT-{uuid.uuid4().hex[:8].upper()}", account_id=raw["id"], type="historical_log", channel="unknown", status="completed", message=text, timestamp=datetime.utcnow() - timedelta(days=max(0, len(raw.get("call_history", [])) - index))))
            for ptp in raw.get("ptp_history", []):
                db.add(PTPHistory(id=f"PTP-{uuid.uuid4().hex[:8].upper()}", account_id=raw["id"], ptp_date=datetime.utcnow() - timedelta(days=ptp.get("days_ago", 0)), ptp_amount=ptp.get("amount", 0), status=ptp.get("status", "PENDING")))
            for claim in raw.get("claims", []):
                db.add(Claim(id=f"CLM-{uuid.uuid4().hex[:8].upper()}", account_id=raw["id"], claim_type=claim.get("type", "hardship"), claim_details=claim.get("details", ""), verification_state=claim.get("state", "CLAIMED"), contradicted_flag=claim.get("state") == "CONTRADICTED", contradiction_reason=claim.get("contradiction_reason")))
        db.commit()
    finally:
        db.close()


def load_account(account_id, authorize=True):
    if authorize:
        authorize_current_resource("data", "collections_accounts", "read", {"account_id": account_id, "data_scope": "collections_accounts"})
    ensure_seeded()
    db = SessionLocal()
    try:
        row = db.query(LoanAccount).filter(LoanAccount.id == account_id).first()
        if row is None:
            raise ValueError(f"Unknown Collections account_id '{account_id}'")
        customer, profile = row.customer, row.ai_profile
        account = {
            "id": row.id, "name": customer.name if customer else "Unknown", "age": customer.age if customer else None,
            "city": customer.city if customer else "", "job": customer.job_profile if customer else "",
            "cibil": customer.cibil_score if customer else None, "product": row.product_type,
            "outstanding": row.outstanding, "emi": row.emi, "dpd": row.dpd, "bucket": row.bucket,
            "status": row.status, "priority": row.priority,
            "persona": profile.persona if profile else "unknown_insufficient_data",
            "primary_channel": profile.primary_channel if profile else None,
            "fallback_channel": profile.fallback_channel if profile else None,
            "next_action": profile.next_action if profile else None,
        }
        return enrich_account_data(account, db, row)
    finally:
        db.close()


def list_accounts(authorize=True):
    """Return the persisted Collections portfolio without running intelligence."""
    if authorize:
        authorize_current_resource("data", "collections_accounts", "read", {"data_scope": "collections_accounts"})
    ensure_seeded()
    db = SessionLocal()
    try:
        rows = db.query(LoanAccount).order_by(LoanAccount.dpd.desc(), LoanAccount.id.asc()).all()
        return [{
            "id": row.id,
            "customer_id": row.customer_id,
            "name": row.customer.name if row.customer else "Unknown",
            "age": row.customer.age if row.customer else None,
            "city": row.customer.city if row.customer else None,
            "job": row.customer.job_profile if row.customer else None,
            "product": row.product_type,
            "outstanding": row.outstanding,
            "emi": row.emi,
            "dpd": row.dpd,
            "bucket": row.bucket,
            "status": row.status,
            "priority": row.priority,
            "persona": row.ai_profile.persona if row.ai_profile else None,
            "primary_channel": row.ai_profile.primary_channel if row.ai_profile else None,
        } for row in rows]
    finally:
        db.close()
