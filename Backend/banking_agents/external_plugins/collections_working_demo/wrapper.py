"""
Collections Workflow Plugin Wrapper
====================================
This is the sole entry point the Agent Harness invokes.
All Collections business logic lives in banking_agents.collections_domain.

Client-facing story:
  "The Collections system was originally a standalone agentic workflow.
   We onboarded it into the Agent Harness through this plugin wrapper and
   YAML manifest contract.  The harness governs it using the same registry,
   policy, guardrail, lifecycle, tracing, audit, and usage layer as every
   other agent."

Supported modes (sent as payload["mode"]):
  pre_call         — five-score intelligence + persona + trust + NBA + risk flags
  post_call        — server-side transcript extraction + full post-call pipeline
  full_lifecycle   — pre_call then post_call in sequence
  voice_greet      — generate ARIA voice greeting for account
  voice_analyze    — run ConversationIntelligenceAgent on a transcript snippet

Voice notes:
  The Groq Whisper STT + LLaMA conversational + Orpheus TTS pipeline is
  migrated and available (vendor_src/voice_pipeline.py).
  Backend voice routes are wired at /collections/voice/status,
  /collections/voice/start, /collections/voice/turn, and
  /collections/voice/finalize.
  Browser microphone wiring uses MediaRecorder in the harness frontend.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# ── Harness imports ───────────────────────────────────────────────────────────
from banking_agents.collections_domain import run_account_workflow, list_accounts
from banking_agents.collections_domain.repository import load_account, ensure_seeded
from banking_agents.collections_domain.services.transcript_extraction import extract
from banking_agents.collections_domain.post_call_service import (
    process_recorded_call,
    account_post_call_history,
)

_SAMPLES_DIR = Path(__file__).parent / "samples"


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (harness calls this)
# ─────────────────────────────────────────────────────────────────────────────

def invoke(payload: Dict[str, Any], trace_id: str = "") -> Dict[str, Any]:
    """
    Dispatch Collections workflow based on payload["mode"].

    Args:
        payload: {
            mode:                   "pre_call" | "post_call" | "full_lifecycle" |
                                    "voice_greet" | "voice_analyze" | "voice_turn"
            account_id:             str (required for all modes)
            transcript:             str (required for post_call / voice_analyze)
            captured_transcript_id: str (optional — load from sample library)
            call_metadata:          dict (optional)
            override_persona:       str (optional, pre_call / full_lifecycle)
            new_claims:             list (optional, pre_call)
        }
        trace_id: Harness-assigned trace identifier

    Returns:
        Mode-specific result dict.  Always includes:
            mode, trace_id, workflow_status, source
    """
    if not trace_id:
        trace_id = str(uuid.uuid4())

    mode = payload.get("mode", "pre_call")
    account_id = payload.get("account_id", "ACC-DEMO-01")

    try:
        if mode == "pre_call":
            return _pre_call(payload, account_id, trace_id)
        elif mode == "post_call":
            return _post_call(payload, account_id, trace_id)
        elif mode == "full_lifecycle":
            return _full_lifecycle(payload, account_id, trace_id)
        elif mode == "voice_greet":
            return _voice_greet(payload, account_id, trace_id)
        elif mode == "voice_analyze":
            return _voice_analyze(payload, account_id, trace_id)
        elif mode == "voice_turn":
            return _voice_turn(payload, account_id, trace_id)
        else:
            return {
                "mode": mode,
                "workflow_status": "error",
                "error": f"Unknown mode '{mode}'. Valid: pre_call, post_call, full_lifecycle, voice_greet, voice_analyze",
                "trace_id": trace_id,
                "source": "collections_working_demo.wrapper",
            }
    except Exception as exc:
        return {
            "mode": mode,
            "workflow_status": "error",
            "error": str(exc),
            "trace_id": trace_id,
            "source": "collections_working_demo.wrapper",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Mode handlers
# ─────────────────────────────────────────────────────────────────────────────

def _pre_call(payload: Dict[str, Any], account_id: str, trace_id: str) -> Dict[str, Any]:
    """
    Run full pre-call intelligence:
    Scores → Persona → Trust Gate → Policy → NBA.
    Also loads PTP history and risk flags for the pre-call context panel.
    """
    override_persona = payload.get("override_persona")
    new_claims = payload.get("new_claims") or []

    workflow_result = run_account_workflow(
        account_id,
        override_persona=override_persona,
        new_claims=new_claims,
    )

    # Enrich with rich pre-call context (PTP history, claims, risk flags)
    pre_call_context = _build_pre_call_context(account_id)

    return {
        "mode": "pre_call",
        "account_id": account_id,
        "pre_call": {
            **workflow_result,
            "pre_call_context": pre_call_context,
        },
        "workflow_status": workflow_result.get("workflow_status", "completed"),
        "trace_id": trace_id,
        "source": "collections_working_demo.wrapper",
        "control_evidence": {
            "extraction_method": "deterministic_rules",
            "scoring_method": "evidence_based_five_score_engine",
            "persona_method": "signal_threshold_classification",
            "trust_gate_method": "rule_based_trust_evaluator",
            "nba_method": "llm_who_what_when" if _groq_available() else "deterministic_nba_rules",
        },
    }


def _post_call(payload: Dict[str, Any], account_id: str, trace_id: str) -> Dict[str, Any]:
    """
    Run full post-call pipeline with server-side transcript extraction.

    Flow:
      transcript text
        → ConversationIntelligenceAgent (LLM extraction)
        → post_call_pipeline (trust / persona / NBA / persist)
        → return structured result

    The frontend must NOT send pre-extracted evidence fields.
    """
    transcript = _resolve_transcript(payload)
    if not transcript:
        return {
            "mode": "post_call",
            "workflow_status": "error",
            "error": "transcript or captured_transcript_id is required for post_call mode",
            "trace_id": trace_id,
            "source": "collections_working_demo.wrapper",
        }

    ensure_seeded()
    account_data = load_account(account_id)

    # ── Server-side extraction (LLM or labelled keyword fallback) ─────────────
    extraction = extract(transcript, account_data)

    # Build evidence dict for post-call pipeline from extracted fields
    evidence = {
        "sentiment": extraction.get("sentiment", "neutral"),
        "intent": extraction.get("intent", "general_response"),
        "ptp_date": extraction.get("ptp_date"),
        "ptp_amount": extraction.get("ptp_amount"),
        "life_event_detected": extraction.get("life_event_detected", False),
        "life_event_type": extraction.get("life_event_type"),
        "life_event_details": extraction.get("life_event_details"),
        "hostility_detected": extraction.get("hostile_signal", False),
        "negotiation_detected": extraction.get("negotiation_signal", False),
        "compliance_flags": extraction.get("compliance_flags", []),
        "summary": None,  # will be generated by post-call pipeline
        "transcript": transcript,
    }

    # ── Post-call pipeline (trust / persona / score update / persist) ─────────
    post_result = process_recorded_call(account_id, transcript, evidence)

    # ── History snapshot ──────────────────────────────────────────────────────
    history = _safe_history(account_id)

    return {
        "mode": "post_call",
        "account_id": account_id,
        "transcript_analysis": {
            **extraction,
            # Sanitize — do not expose raw LLM output in summary view
            "raw_llm_output": None,
        },
        "post_call": post_result,
        "updates": _extract_updates(post_result),
        "history": history,
        "workflow_status": "completed",
        "trace_id": trace_id,
        "source": "collections_working_demo.wrapper",
        "control_evidence": {
            "extraction_method": extraction.get("extraction_method"),
            "evidence_source": extraction.get("evidence_source"),
            "frontend_evidence_accepted": False,
            "call_id": post_result.get("call_id"),
            "review_case_id": post_result.get("review_case_id"),
        },
    }


def _full_lifecycle(payload: Dict[str, Any], account_id: str, trace_id: str) -> Dict[str, Any]:
    """
    Run pre_call → call stage → post_call in sequence.
    Demonstrates the full governance lifecycle in one harness invoke.
    """
    # Stage 1: Pre-call
    pre_result = _pre_call(payload, account_id, trace_id)

    # Stage 2: Resolve transcript
    transcript = _resolve_transcript(payload)
    sample_meta = _load_sample_meta(payload.get("captured_transcript_id"))

    call_stage = {
        "type": "captured_transcript_replay" if sample_meta else "provided_transcript",
        "transcript_id": payload.get("captured_transcript_id"),
        "transcript_title": sample_meta.get("title") if sample_meta else "Custom Transcript",
        "persona_context": sample_meta.get("persona_context") if sample_meta else None,
        "transcript_preview": (transcript or "")[:300] + ("…" if len(transcript or "") > 300 else ""),
        "full_transcript_available": bool(transcript),
    }

    if not transcript:
        return {
            "mode": "full_lifecycle",
            "account_id": account_id,
            "pre_call": pre_result.get("pre_call"),
            "call": {"error": "No transcript provided — post-call stage skipped"},
            "workflow_status": "partial",
            "trace_id": trace_id,
            "source": "collections_working_demo.wrapper",
        }

    # Stage 3: Post-call
    post_payload = {**payload, "transcript": transcript}
    post_result = _post_call(post_payload, account_id, trace_id)

    return {
        "mode": "full_lifecycle",
        "account_id": account_id,
        "pre_call": pre_result.get("pre_call"),
        "call": call_stage,
        "transcript_analysis": post_result.get("transcript_analysis"),
        "post_call": post_result.get("post_call"),
        "updates": post_result.get("updates"),
        "history": post_result.get("history"),
        "workflow_status": "completed",
        "trace_id": trace_id,
        "source": "collections_working_demo.wrapper",
        "control_evidence": {
            **pre_result.get("control_evidence", {}),
            **post_result.get("control_evidence", {}),
        },
    }


def _voice_greet(payload: Dict[str, Any], account_id: str, trace_id: str) -> Dict[str, Any]:
    """
    Generate ARIA voice greeting for an account.
    Backend: Groq LLaMA for text + Groq Orpheus for TTS.
    Frontend microphone wiring: integrated via browser MediaRecorder endpoints.
    """
    from banking_agents.external_plugins.collections_working_demo.vendor_src.voice_pipeline import (
        build_voice_prompt,
        generate_greeting,
        groq_configured,
    )

    ensure_seeded()
    account_data = load_account(account_id)
    prompt = payload.get("prompt") or build_voice_prompt(account_data)

    result = asyncio.run(generate_greeting(account_data, prompt))

    return {
        "mode": "voice_greet",
        "account_id": account_id,
        "greeting": result,
        "voice_pipeline_status": {
            "backend_available": True,
            "groq_configured": groq_configured(),
            "frontend_microphone_wiring": "mediarecorder_integrated",
            "note": "Voice backend (Groq Whisper STT + LLaMA + Orpheus TTS) is wired to the harness browser MediaRecorder session endpoints.",
        },
        "workflow_status": "completed",
        "trace_id": trace_id,
        "source": "collections_working_demo.wrapper",
    }


def _voice_analyze(payload: Dict[str, Any], account_id: str, trace_id: str) -> Dict[str, Any]:
    """
    Analyze a single transcript turn with ConversationIntelligenceAgent.
    Returns structured intelligence without running the full post-call pipeline.
    """
    transcript = payload.get("transcript", "")
    conversation_history = payload.get("conversation_history", [])

    ensure_seeded()
    account_data = load_account(account_id)

    extraction = extract(transcript, account_data, conversation_history)

    return {
        "mode": "voice_analyze",
        "account_id": account_id,
        "intelligence": extraction,
        "workflow_status": "completed",
        "trace_id": trace_id,
        "source": "collections_working_demo.wrapper",
    }


def _voice_turn(payload: Dict[str, Any], account_id: str, trace_id: str) -> Dict[str, Any]:
    """Process one governed live voice turn via the migrated voice backend."""
    from banking_agents.external_plugins.collections_working_demo.vendor_src.voice_pipeline import (
        process_voice_turn,
    )

    audio_b64 = payload.get("audio_b64", "")
    conversation = payload.get("conversation", [])
    if not audio_b64:
        return {
            "mode": "voice_turn",
            "workflow_status": "error",
            "error": "audio_b64 required",
            "trace_id": trace_id,
            "source": "collections_working_demo.wrapper",
        }

    ensure_seeded()
    account_data = load_account(account_id)
    result = asyncio.run(process_voice_turn(account_data, audio_b64, conversation))
    return {
        "mode": "voice_turn",
        "account_id": account_id,
        "turn": result,
        "workflow_status": "completed",
        "trace_id": trace_id,
        "source": "collections_working_demo.wrapper",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_transcript(payload: Dict[str, Any]) -> Optional[str]:
    """Return transcript text — from payload or from sample library."""
    direct = payload.get("transcript", "")
    if direct and direct.strip():
        return direct.strip()

    sample_id = payload.get("captured_transcript_id")
    if sample_id:
        sample = _load_sample(sample_id)
        if sample:
            return sample.get("transcript", "")
    return None


def _load_sample(sample_id: str) -> Optional[Dict[str, Any]]:
    path = _SAMPLES_DIR / f"{sample_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _load_sample_meta(sample_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not sample_id:
        return None
    sample = _load_sample(sample_id)
    if not sample:
        return None
    return {k: v for k, v in sample.items() if k != "transcript"}


def _build_pre_call_context(account_id: str) -> Dict[str, Any]:
    """Pull PTP history and risk flags from Collections DB."""
    try:
        from banking_agents.collections_domain.db.database import SessionLocal
        from banking_agents.collections_domain.db.models import (
            Claim, LoanAccount, PTPHistory, ReviewCase,
        )
        from sqlalchemy import desc

        db = SessionLocal()
        try:
            acc_row = db.query(LoanAccount).filter(LoanAccount.id == account_id).first()
            if not acc_row:
                return {}

            ptps = (
                db.query(PTPHistory)
                .filter(PTPHistory.account_id == account_id)
                .order_by(desc(PTPHistory.timestamp))
                .limit(5)
                .all()
            )
            ptp_summary = [
                {
                    "status": p.status,
                    "date": p.ptp_date.isoformat() if p.ptp_date else None,
                    "amount": p.ptp_amount,
                }
                for p in ptps
            ]

            claims = (
                db.query(Claim)
                .filter(Claim.account_id == account_id)
                .order_by(desc(Claim.timestamp))
                .limit(5)
                .all()
            )
            claims_summary = [
                {
                    "type": c.claim_type,
                    "status": c.verification_state,
                    "details": c.claim_details,
                }
                for c in claims
            ]

            open_cases = (
                db.query(ReviewCase)
                .filter(
                    ReviewCase.account_id == account_id,
                    ReviewCase.status.in_(["OPEN", "IN_REVIEW", "PENDING_DOCUMENTS"]),
                )
                .all()
            )

            account_data = load_account(account_id)
            dpd = account_data.get("dpd", 0)
            risk_flags = []
            if dpd >= 60:
                risk_flags.append(f"Account is {dpd} days past due — elevated risk")
            if any(
                (c.get("status") or "").upper() in ("CLAIMED", "UNDER_REVIEW")
                for c in claims_summary
            ):
                risk_flags.append("Unverified claim on record — handle with care")
            if any((p.get("status") or "").upper() == "BROKEN" for p in ptp_summary):
                risk_flags.append("Previous payment commitment was not honoured")
            if open_cases:
                risk_flags.append(f"{len(open_cases)} open review case(s) pending supervisor decision")

            return {
                "ptp_history": ptp_summary,
                "claims": claims_summary,
                "open_review_cases": len(open_cases),
                "open_case_ids": [c.id for c in open_cases],
                "risk_flags": risk_flags,
            }
        finally:
            db.close()
    except Exception:
        return {}


def _extract_updates(post_result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "persona_before": post_result.get("current_persona", ""),
        "persona_before_label": post_result.get("current_persona_label", ""),
        "persona_proposed": post_result.get("proposed_persona", ""),
        "persona_proposed_label": post_result.get("proposed_persona_label", ""),
        "persona_applied": post_result.get("persona_applied", ""),
        "review_required": post_result.get("review_required", False),
        "review_case_id": post_result.get("review_case_id"),
        "review_triggers": post_result.get("review_triggers", []),
        "recommended_action": post_result.get("recommended_action", ""),
        "recommended_action_code": post_result.get("recommended_action_code", ""),
        "call_outcome": post_result.get("call_outcome", {}),
        "business_assessment": post_result.get("business_assessment", ""),
    }


def _safe_history(account_id: str) -> Dict[str, Any]:
    try:
        return account_post_call_history(account_id)
    except Exception:
        return {"account_id": account_id, "calls": [], "review_cases": []}


def _groq_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY", "").strip())


# ─────────────────────────────────────────────────────────────────────────────
# Transcript library (for UI selection)
# ─────────────────────────────────────────────────────────────────────────────

def list_captured_transcripts() -> list:
    """Return metadata for all sample transcripts (without transcript text)."""
    results = []
    if not _SAMPLES_DIR.exists():
        return results
    for path in sorted(_SAMPLES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append({
                "id": data.get("id", path.stem),
                "title": data.get("title", path.stem),
                "description": data.get("description", ""),
                "persona_context": data.get("persona_context"),
                "metadata": data.get("metadata", {}),
            })
        except Exception:
            pass
    return results
