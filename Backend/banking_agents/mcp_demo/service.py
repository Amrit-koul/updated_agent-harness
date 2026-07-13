"""Defined backend interface used by the MCP server."""
from __future__ import annotations

from pathlib import Path


POLICY_DIR = Path(__file__).resolve().parents[1].parent / "data_ingestion" / "policy_documents"


def get_policy_metadata() -> dict:
    """Return metadata derived from the local policy repository."""
    docs = sorted(POLICY_DIR.glob("*.docx"))
    lending = [path.name for path in docs if "Loan" in path.name or "Lending" in path.name or "Credit" in path.name]
    return {
        "source": "backend_policy_repository",
        "document_count": len(docs),
        "lending_document_count": len(lending),
        "sample_documents": [path.name for path in docs[:5]],
        "seeded_data": False,
    }


def calculate_repayment_plan(principal: float, annual_rate_pct: float, months: int) -> dict:
    """Calculate a deterministic amortized repayment plan."""
    if principal <= 0 or annual_rate_pct < 0 or months <= 0 or months > 360:
        raise ValueError("principal must be > 0, rate >= 0, and months between 1 and 360")
    monthly_rate = annual_rate_pct / 100 / 12
    if monthly_rate == 0:
        emi = principal / months
    else:
        factor = (1 + monthly_rate) ** months
        emi = principal * monthly_rate * factor / (factor - 1)
    total_payment = emi * months
    return {
        "source": "backend_repayment_calculator",
        "principal": round(principal, 2),
        "annual_rate_pct": round(annual_rate_pct, 4),
        "months": months,
        "monthly_payment": round(emi, 2),
        "total_interest": round(total_payment - principal, 2),
        "total_payment": round(total_payment, 2),
        "seeded_data": False,
    }


def get_customer_summary(account_id: str) -> dict:
    """Return a governed Collections account summary."""
    from banking_agents.collections_domain.repository import load_account

    account = load_account(account_id, authorize=False)
    return {
        "source": "collections_seeded_repository",
        "seeded_data": True,
        "account_id": account.get("id"),
        "customer_name": account.get("name"),
        "product": account.get("product"),
        "dpd": account.get("dpd"),
        "bucket": account.get("bucket"),
        "persona": account.get("persona"),
        "next_action": account.get("next_action"),
    }
