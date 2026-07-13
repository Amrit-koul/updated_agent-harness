import logging
import math
from time import perf_counter
from groq import Groq
from typing import Optional
from banking_agents.config.settings import get_groq_client, MODEL_LOAN_ELIGIBILITY
from banking_agents.rag.base_rag import BaseRAG
from banking_agents.guardrails.rag_guard import RAGGuard
from banking_agents.communication.message import CustomerLoanProfile
from agent_harness.tracing import get_tracer
from agent_harness.model_gateway import get_model_gateway
from agent_harness.usage import usage_context
from banking_agents.prompts import prompt_registry
from banking_agents.evaluation.rag import build_citations, evaluate_rag_response

logger = logging.getLogger(__name__)


class LoanEligibilityRAGAgent:
    def __init__(self, guardrails_config: dict = None):
        logger.info("[LoanEligibilityRAGAgent] Initializing LoanEligibilityRAGAgent.")
        self.client: Groq = get_groq_client()
        self.model_id = MODEL_LOAN_ELIGIBILITY
        logger.debug("[LoanEligibilityRAGAgent] Using model: %s", self.model_id)
        self.rag = BaseRAG(collection_name="loan_docs")

        # Guardrails
        if guardrails_config and "rag" in guardrails_config:
            self.rag_guard = RAGGuard(guardrails_config["rag"])
        else:
            self.rag_guard = None

        logger.info("[LoanEligibilityRAGAgent] Initialized with RAG collection: 'loan_docs'")

    # ------------------------------------------------------------------
    # Core entry point — handles both structured and freeform input
    # ------------------------------------------------------------------
    def answer(
        self,
        task: str,
        loan_profile: Optional[CustomerLoanProfile] = None,
        session_id: str = "",
    ) -> str:
        return self.answer_with_evaluation(task, loan_profile=loan_profile, session_id=session_id)["eligibility_assessment"]

    def answer_with_evaluation(
        self, task: str, loan_profile: Optional[CustomerLoanProfile] = None, session_id: str = "", trace_id: str = ""
    ) -> dict:
        with usage_context(trace_id=trace_id or None, agent_id="loan_assessment_agent", agent_name="Loan Assessment Agent", business_function="Loan Eligibility"):
            raw = self._answer_raw(task, loan_profile=loan_profile, session_id=session_id)
        evaluation = evaluate_rag_response(query=task, answer=raw["answer"], context=raw["context"], citations=raw["citations"], rag=self.rag, agent_id="loan_assessment_agent", trace_id=trace_id)
        result = {"eligibility_assessment": raw["answer"], "citations": raw["citations"], "rag_evaluation": evaluation, "prompt_metadata": raw["prompt_metadata"]}
        if raw.get("usage"): result["usage"] = raw["usage"]
        return result

    def _answer_raw(
        self,
        task: str,
        loan_profile: Optional[CustomerLoanProfile] = None,
        session_id: str = "",
    ) -> dict:
        """
        Assess loan eligibility.
        - If loan_profile is provided: computes derived metrics from the profile
          and asks the LLM to validate them against the retrieved policy thresholds.
        - If loan_profile is None: falls back to freeform RAG-based assessment.
        """
        logger.info("[LoanEligibilityRAGAgent.answer] >>> Task: '%s'", task)
        tracer = get_tracer()
        application_meta = self._application_metadata(loan_profile)
        with tracer.span("receive_loan_application", inputs={"has_structured_profile": loan_profile is not None, "query_length": len(task)}, metadata=application_meta) as span:
            span.set_output({"accepted": True, **application_meta})
        with tracer.span("validate_application_fields", inputs={"field_names": sorted(loan_profile.model_dump()) if loan_profile else []}) as span:
            span.set_output({"valid": loan_profile is not None, "missing_required_fields": [] if loan_profile else ["structured_profile"]})

        # Retrieve relevant loan policy documents - INCREASED n_results for decision matrices
        with tracer.span("rag_retrieval", inputs={"loan_type": application_meta.get("loan_type"), "top_k": 8}, metadata={"retriever": "loan_docs"}, run_type="retriever") as span:
            retrieved_results = self.rag.query(task, n_results=8)
            span.set_output({"retrieved_doc_count": len(retrieved_results.get("documents", [[]])[0]), "top_k": 8})

        disclaimer = None
        if self.rag_guard:
            proceed, message = self.rag_guard.check(retrieved_results, session_id=session_id)
            if not proceed:
                logger.warning("[LoanEligibilityRAGAgent.answer] RAGGuard blocked: %s", message)
                return {"answer": message, "context": "", "citations": [], "prompt_metadata": {}}
            disclaimer = message

        documents = retrieved_results.get("documents", [[]])[0]
        metadatas = retrieved_results.get("metadatas", [[]])[0]
        distances = retrieved_results.get("distances", [[]])[0]
        context_parts = []
        for index, document in enumerate(documents):
            if (
                self.rag_guard
                and index < len(distances)
                and distances[index] > self.rag_guard.hard_threshold
            ):
                continue
            metadata = metadatas[index] if index < len(metadatas) else {}
            source = metadata.get("source", "Unknown loan policy document")
            context_parts.append(f"[Source: {source}]\n{document}")
        context_text = "\n\n".join(context_parts)
        citations = build_citations(retrieved_results)
        logger.info("[LoanEligibilityRAGAgent.answer] Using %d relevant document chunk(s).", len(context_parts))

        if loan_profile:
            answer, usage = self._assess_with_profile(task, loan_profile, context_text, disclaimer)
        else:
            answer, usage = self._assess_freeform(task, context_text, disclaimer)
        return {"answer": answer, "context": context_text, "citations": citations, "prompt_metadata": {"prompt_id": "loan_eligibility_reasoning", "prompt_version": "1.0.0", "prompt_source": "local_prompt_registry", "model": self.model_id, "model_name": self.model_id}, "usage": usage}

    # ------------------------------------------------------------------
    # Structured path — implements the 4-stage reasoning protocol
    # ------------------------------------------------------------------
    def _assess_with_profile(
        self, task: str, p: CustomerLoanProfile, context_text: str, disclaimer: Optional[str]
    ) -> tuple[str, dict | None]:
        logger.info("[LoanEligibilityRAGAgent] Running structured assessment for %s loan.", p.loan_type)

        # Pre-compute metrics as inputs for LLM validation
        if p.annual_interest_rate_percent is not None:
            monthly_rate = p.annual_interest_rate_percent / 1200
            proposed_emi = (p.loan_amount_requested * monthly_rate) / (
                1 - math.pow(1 + monthly_rate, -p.loan_tenure_months)
            )
        else:
            proposed_emi = None

        total_obligations    = p.existing_emi_amount + proposed_emi if proposed_emi is not None else None
        foir                 = total_obligations / p.monthly_income if total_obligations is not None else None
        ltv                  = (p.loan_amount_requested / p.property_value) if p.property_value else None
        age_at_maturity      = p.applicant_age + (p.loan_tenure_months / 12)

        derived_metrics = f"""
=== APPLICANT PROFILE ===
Loan Type:                  {p.loan_type}
Employment Type:            {p.employment_type}
Applicant Age:              {p.applicant_age} years
Monthly Income:             ₹{p.monthly_income:,.2f}
Existing Monthly EMI:       ₹{p.existing_emi_amount:,.2f}
Requested Loan Amount:      ₹{p.loan_amount_requested:,.2f}
Requested Tenure:           {p.loan_tenure_months} months
CIBIL Score:                {p.cibil_score}
Property / Asset Value:     {"₹{:,.2f}".format(p.property_value) if p.property_value else "Not Provided"}
Annual Interest Rate:       {f"{p.annual_interest_rate_percent:.2f}%" if p.annual_interest_rate_percent else "Not Provided"}

=== DERIVED CALCULATIONS ===
Approximate Proposed EMI:   {"₹{:,.2f}/month".format(proposed_emi) if proposed_emi is not None else "Not calculated (interest rate required)"}
Total EMI Obligations:      {"₹{:,.2f}/month".format(total_obligations) if total_obligations is not None else "Not calculated"}
FOIR:                       {f"{foir:.2%}" if foir is not None else "N/A"}
LTV Ratio:                  {f"{ltv:.2%}" if ltv is not None else "N/A"}
Age at Loan Maturity:       {age_at_maturity:.1f} years
=========================================
"""

        with get_tracer().span("prompt_template_load", inputs={"prompt_id": "loan_eligibility_reasoning"}) as span:
            prompt_def = prompt_registry.load("loan_eligibility_reasoning")
            span.set_output({"prompt_hash": prompt_def.prompt_hash, "prompt_version": prompt_def.version})

        user_message = (
            f"=== OFFICIAL BANK LOAN POLICY GUIDELINES ===\n{context_text}\n\n"
            f"{derived_metrics}\n"
            f"Original Question: {task}\n\n"
            "Provide a structured assessment following the 4-stage protocol."
        )
        with get_tracer().span("prompt_render", inputs={"path": "structured", "context_chars": len(context_text), "question_chars": len(task)}) as span:
            system_prompt = prompt_def.text
            span.set_output({"system_chars": len(system_prompt), "user_chars": len(user_message)})

        with get_tracer().span("compute_eligibility_factors", inputs=self._application_metadata(p)) as span:
            span.set_output({"foir": round(foir, 4) if foir is not None else None, "ltv": round(ltv, 4) if ltv is not None else None, "proposed_emi": round(proposed_emi, 2) if proposed_emi is not None else None, "age_at_maturity": round(age_at_maturity, 1)})
        with get_tracer().span("risk_assessment", inputs=self._application_metadata(p)) as span:
            span.set_output({"cibil_band": self._cibil_band(p.cibil_score), "foir_available": foir is not None, "ltv_available": ltv is not None, "reason_count": sum(value is None for value in (foir, ltv))})
        return self._call_llm(system_prompt, user_message, disclaimer, prompt_def=prompt_def)

    # ------------------------------------------------------------------
    # Freeform fallback path
    # ------------------------------------------------------------------
    def _assess_freeform(self, task: str, context_text: str, disclaimer: Optional[str]) -> tuple[str, dict | None]:
        logger.info("[LoanEligibilityRAGAgent] Running freeform assessment.")

        with get_tracer().span("prompt_template_load", inputs={"prompt_id": "loan_eligibility_reasoning"}) as span:
            prompt_def = prompt_registry.load("loan_eligibility_reasoning")
            span.set_output({"prompt_hash": prompt_def.prompt_hash, "prompt_version": prompt_def.version})

        user_message = (
            f"=== OFFICIAL BANK LOAN POLICY GUIDELINES ===\n{context_text}\n\n"
            f"User Question: {task}"
        )
        with get_tracer().span("prompt_render", inputs={"path": "freeform", "context_chars": len(context_text), "question_chars": len(task)}) as span:
            system_prompt = prompt_def.text
            span.set_output({"system_chars": len(system_prompt), "user_chars": len(user_message)})
        return self._call_llm(system_prompt, user_message, disclaimer, prompt_def=prompt_def)

    # ------------------------------------------------------------------
    # Shared LLM call
    # ------------------------------------------------------------------
    def _call_llm(self, system_prompt: str, user_message: str, disclaimer: Optional[str], prompt_def=None) -> tuple[str, dict | None]:
        try:
            logger.debug("[LoanEligibilityRAGAgent] Calling Groq API | Model: %s", self.model_id)
            metadata = {
                "model_name": self.model_id,
                **(
                    {
                        "prompt_id": prompt_def.prompt_id,
                        "prompt_version": prompt_def.version,
                        "prompt_hash": prompt_def.prompt_hash,
                    }
                    if prompt_def
                    else {"prompt_id": "inline_freeform", "prompt_version": "v1"}
                ),
            }
            with get_tracer().span("generate_recommendation", inputs={"prompt_character_count": len(user_message)}, metadata=metadata, run_type="llm") as span:
                response = get_model_gateway().chat_completions_create(self.client, provider="groq", model=self.model_id, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}], temperature=0.0, budget_metadata={"operation": "loan_eligibility"})
                span.set_output({"generated": True, "model_name": self.model_id})
            result = response.choices[0].message.content.strip()
            usage = getattr(response, "_agent_harness_usage", None)
            if usage:
                span.add_metadata({key: usage[key] for key in ("provider", "model", "prompt_tokens", "completion_tokens", "total_tokens", "estimated_total_cost", "latency_ms", "fallback_used", "usage_source")})
            logger.info("[LoanEligibilityRAGAgent] <<< Response received (%d chars).", len(result))
            if disclaimer:
                result += f"\n\n{disclaimer}"
            with get_tracer().span("final_loan_decision", inputs={"assessment_generated": True}) as span:
                span.set_output({"decision": self._decision_label(result), "confidence": None, "reason_count": result.count("\n") + 1})
            return result, usage

        except Exception as e:
            logger.error("[LoanEligibilityRAGAgent] Error: %s", e, exc_info=True)
            raise RuntimeError("Loan eligibility model request failed") from e

    @staticmethod
    def _cibil_band(score: int) -> str:
        return "EXCELLENT" if score >= 750 else "GOOD" if score >= 700 else "FAIR" if score >= 650 else "WEAK"

    @classmethod
    def _application_metadata(cls, profile: Optional[CustomerLoanProfile]) -> dict:
        if profile is None: return {"loan_type": None, "amount_bucket": None, "cibil_band": None}
        amount = profile.loan_amount_requested
        bucket = "<5L" if amount < 500000 else "5L-25L" if amount < 2500000 else "25L-1CR" if amount < 10000000 else "1CR+"
        return {"loan_type": profile.loan_type, "amount_bucket": bucket, "cibil_band": cls._cibil_band(profile.cibil_score)}

    @staticmethod
    def _decision_label(text: str) -> str:
        lowered = text.lower()
        for label in ("ineligible", "conditionally eligible", "eligible", "refer for review", "insufficient data"):
            if label in lowered: return label.upper().replace(" ", "_")
        return "UNSPECIFIED"
