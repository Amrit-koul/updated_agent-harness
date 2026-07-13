import logging
import json
import re
from string import Template
from time import perf_counter
from groq import Groq
from banking_agents.config.settings import get_groq_client, MODEL_POLICY_RAG_DEFAULT, MODEL_POLICY_RAG_FALLBACK
from banking_agents.rag.base_rag import BaseRAG
from banking_agents.guardrails.rag_guard import RAGGuard
from agent_harness.tracing import get_tracer
from agent_harness.model_gateway import get_model_gateway
from agent_harness.usage import usage_context
from banking_agents.prompts import prompt_registry
from banking_agents.evaluation.rag import build_citations, evaluate_rag_response

logger = logging.getLogger(__name__)

# ─── Small-talk / non-policy query detection ──────────────────────────────────
# Queries that match these patterns are unsupported inputs, NOT policy failures.
# They must NOT be run through RAG evaluation or trigger degradation monitoring.
#
# Rule: if the normalized query is a greeting, acknowledgement, or clearly
# non-banking phrase, return a friendly redirect and skip evaluate_rag_response.
#
# This is intentionally conservative — only obvious non-policy inputs are caught
# here. Ambiguous queries (e.g. "what is NPA?") are passed through to the full
# RAG pipeline and evaluated normally.

_SMALL_TALK_PATTERNS = re.compile(
    r"""
    ^(
        # Greetings
        hi+|hello+|hey+|howdy|hiya|greetings|good\s*(morning|afternoon|evening|day|night)|
        # Acknowledgements / closings
        thanks?|thank\s*you|ok(?:ay)?|sure|got\s*it|sounds?\s*good|great|cool|nice|
        bye+|goodbye|see\s*ya|take\s*care|ciao|
        # Identity / meta
        who\s+are\s+you|what\s+are\s+you|are\s+you\s+(a\s+)?bot|are\s+you\s+ai|
        what\s+(can|do)\s+you\s+do|help\s*me|
        # Very short non-query tokens (handled separately by length check below)
        test|ping|yo|sup
    )
    [\s!?.]*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SMALL_TALK_FRIENDLY_RESPONSE = (
    "Hello! I'm the Bank Policy Assistant. Please ask a banking policy question "
    "and I'll answer using approved policy documents. "
    "For example: 'What are the KYC requirements for opening a savings account?'"
)


def _is_small_talk(query: str) -> bool:
    """Return True if the query is clearly non-policy small talk or unsupported input."""
    q = query.strip()
    # Very short queries (≤ 4 chars after stripping) are treated as non-policy
    if len(q) <= 4:
        return True
    return bool(_SMALL_TALK_PATTERNS.match(q))


class PolicyRAGAgent:
    def __init__(self, guardrails_config: dict = None):
        logger.info("[PolicyRAGAgent] Initializing PolicyRAGAgent.")
        self.client: Groq = get_groq_client()
        self.model_id = MODEL_POLICY_RAG_DEFAULT
        self.fallback_model_id = MODEL_POLICY_RAG_FALLBACK
        logger.debug("[PolicyRAGAgent] Primary model: %s | Fallback: %s", self.model_id, self.fallback_model_id)
        self.rag = BaseRAG(collection_name="policy_docs")
        
        # Guardrails
        if guardrails_config and "rag" in guardrails_config:
            self.rag_guard = RAGGuard(guardrails_config["rag"])
        else:
            self.rag_guard = None
            
        logger.info("[PolicyRAGAgent] Initialized with RAG collection: 'policy_docs'")

    def answer(self, task: str, session_id: str = "") -> str:
        """Retrieves relevant policy documents and generates an answer."""
        return self.answer_with_evaluation(task, session_id=session_id)["answer"]

    def answer_with_evaluation(self, task: str, session_id: str = "", trace_id: str = "") -> dict:
        """Structured RAG response used by the control plane; ``answer`` remains compatible."""
        tracer = get_tracer()
        category = self._query_category(task)

        # ── Small-talk / unsupported-input gate ───────────────────────────────
        # If the query is clearly non-policy (greeting, ack, identity question),
        # return a friendly redirect immediately.
        # IMPORTANT: we do NOT call evaluate_rag_response here — there is no
        # retrieval, no answer, and therefore no quality signal to record.
        # This prevents a 0-score RAG evaluation from being stored and triggering
        # rag_quality_degradation → lifecycle review for casual user input.
        if _is_small_talk(task):
            logger.info("[PolicyRAGAgent] Small-talk/non-policy query detected — skipping RAG pipeline. query=%r", task[:80])
            return {
                "answer": _SMALL_TALK_FRIENDLY_RESPONSE,
                "citations": [],
                "rag_evaluation": None,   # explicitly None — do not store or evaluate
                "prompt_metadata": {"query_type": "unsupported_input"},
            }
        # ─────────────────────────────────────────────────────────────────────

        with tracer.span("policy_assistant_flow", inputs={"query_length": len(task)}, metadata={"query_category": category, "session_id": session_id}) as flow_span:
            with usage_context(trace_id=trace_id or None, agent_id="policy_assistant_agent", agent_name="Policy Assistant Agent", business_function="Policy Assistance"):
                result = self._answer_impl(task, session_id, tracer, category)
            evaluation = evaluate_rag_response(query=task, answer=result["answer"], context=result["context"], citations=result["citations"], rag=self.rag, agent_id="policy_assistant_agent", trace_id=trace_id)
            structured = {"answer": result["answer"], "citations": result["citations"], "rag_evaluation": evaluation, "prompt_metadata": result["prompt_metadata"]}
            if result.get("usage"): structured["usage"] = result["usage"]
            flow_span.set_output({"answer_length": len(result["answer"]), "query_category": category, "evaluator_method": evaluation["evaluator_method"]})
            return structured

    def _answer_impl(self, task: str, session_id: str, tracer, category: str) -> dict:
        """Retrieves relevant policy documents and generates an answer."""
        logger.info("[PolicyRAGAgent.answer] >>> Task: '%s'", task)
        with tracer.span("receive_policy_query", inputs={"query_length": len(task)}, metadata={"query_category": category, "session_id": session_id}) as span:
            span.set_output({"accepted": True, "query_category": category})
        with tracer.span("classify_intent", inputs={"query_length": len(task)}) as span:
            span.set_output({"intent": "POLICY", "query_category": category})

        logger.debug("[PolicyRAGAgent.answer] Retrieving policy documents from ChromaDB...")
        # Get raw results to pass to RAGGuard (includes distances)
        with tracer.span("rag_retrieval", inputs={"query_category": category, "top_k": 5}, metadata={"retriever": "policy_docs"}, run_type="retriever") as span:
            retrieved_results = self.rag.query(task, n_results=5)
            retrieved_count = len(retrieved_results.get("documents", [[]])[0])
            span.set_output({"retrieved_doc_count": retrieved_count, "top_k": 5})
        
        disclaimer = None
        if self.rag_guard:
            with tracer.span("compliance_review", inputs={"retrieved_doc_count": retrieved_count}, metadata={"guardrail": "RAGGuard"}) as span:
                proceed, message = self.rag_guard.check(retrieved_results, session_id=session_id)
                span.set_output({"decision": "ALLOW" if proceed else "BLOCK", "disclaimer_added": bool(message and proceed)})
            if not proceed:
                logger.warning("[PolicyRAGAgent.answer] RAGGuard blocked the query: %s", message)
                return {"answer": message, "context": "", "citations": [], "prompt_metadata": {}}
            disclaimer = message # Store disclaimer to append later if it exists

        # Convert to list of dicts for backward compatibility in this method if needed, 
        # but here we just need the content.
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
            source = metadata.get("source", "Unknown policy document")
            context_parts.append(f"[Source: {source}]\n{document}")
        context_text = "\n\n".join(context_parts)
        citations = build_citations(retrieved_results)
        logger.info("[PolicyRAGAgent.answer] Using %d relevant document chunk(s).", len(context_parts))

        with tracer.span("prompt_template_load", inputs={"prompt_ids": ["policy_assistant_system", "policy_assistant_retrieval_answer"]}) as span:
            system_def = prompt_registry.load("policy_assistant_system")
            answer_def = prompt_registry.load("policy_assistant_retrieval_answer")
            span.set_output({
                "system_prompt_hash": system_def.prompt_hash,
                "answer_prompt_hash": answer_def.prompt_hash,
            })
        with tracer.span("prompt_render", inputs={"context_chars": len(context_text), "question_chars": len(task)}) as span:
            system_prompt = system_def.text
            user_message = Template(answer_def.developer).safe_substitute(
                context_text=context_text,
                user_question=task,
            )
            span.set_output({"system_chars": len(system_prompt), "user_chars": len(user_message)})
        prompt_metadata = {
            "prompt_id": system_def.prompt_id,
            "prompt_version": system_def.version,
            "prompt_hash": system_def.prompt_hash,
            "answer_prompt_id": answer_def.prompt_id,
            "answer_prompt_version": answer_def.version,
            "answer_prompt_hash": answer_def.prompt_hash,
            "prompt_source": "local_prompt_registry",
            "model": self.model_id,
            "model_name": self.model_id,
        }

        try:
            logger.debug("[PolicyRAGAgent.answer] Calling Groq API | Model: %s", self.model_id)
            with tracer.span("generate_policy_answer", inputs={"query_category": category, "retrieved_doc_count": len(context_parts)}, metadata=prompt_metadata, run_type="llm") as generation_span:
                response = get_model_gateway().chat_completions_create(self.client, provider="groq", model=self.model_id, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}], temperature=0.1, budget_metadata={"operation": "policy_rag"})
                generation_span.set_output({"generated": True, "model_name": self.model_id})
            output_text = response.choices[0].message.content.strip()
            primary_usage = getattr(response, "_agent_harness_usage", None)
            if primary_usage:
                generation_span.add_metadata({key: primary_usage[key] for key in ("provider", "model", "prompt_tokens", "completion_tokens", "total_tokens", "estimated_total_cost", "latency_ms", "fallback_used", "usage_source")})
            logger.debug("[PolicyRAGAgent.answer] Primary model response (preview): %s...", output_text[:200])

            # Escalate to fallback model if low confidence is expressed
            if any(marker in output_text.lower() for marker in ("not established", "does not clearly state", "conflicting policy")):
                logger.warning("[PolicyRAGAgent.answer] Low confidence detected. Escalating to fallback: %s", self.fallback_model_id)
                with tracer.span("generate_policy_answer", inputs={"reason": "low_confidence_fallback"}, metadata={**prompt_metadata, "model_name": self.fallback_model_id}, run_type="llm") as fallback_span:
                    fallback_response = get_model_gateway().chat_completions_create(self.client, provider="groq", model=self.fallback_model_id, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}], temperature=0.1, fallback_from_model=self.model_id, budget_metadata={"operation": "policy_rag", "reason": "low_confidence"})
                    fallback_span.set_output({"generated": True, "fallback": True})
                fallback_text = fallback_response.choices[0].message.content.strip()
                fallback_usage = getattr(fallback_response, "_agent_harness_usage", None)
                if fallback_usage:
                    fallback_span.add_metadata({key: fallback_usage[key] for key in ("provider", "model", "prompt_tokens", "completion_tokens", "total_tokens", "estimated_total_cost", "latency_ms", "fallback_used", "usage_source")})
                logger.info("[PolicyRAGAgent.answer] <<< Returning fallback model response.")
                with tracer.span("final_answer", inputs={"query_category": category}) as span: span.set_output({"answer_length": len(fallback_text), "model_name": self.fallback_model_id})
                return {"answer": fallback_text, "context": context_text, "citations": citations, "prompt_metadata": {**prompt_metadata, "model_name": self.fallback_model_id}, "usage": fallback_usage or primary_usage}

            logger.info("[PolicyRAGAgent.answer] <<< Returning primary model response.")
            if disclaimer:
                output_text += f"\n\n{disclaimer}"
            with tracer.span("final_answer", inputs={"query_category": category}) as span:
                span.set_output({"answer_length": len(output_text), "model_name": self.model_id, "retrieved_doc_count": len(context_parts)})
            return {"answer": output_text, "context": context_text, "citations": citations, "prompt_metadata": prompt_metadata, "usage": primary_usage}

        except Exception as e:
            logger.error("[PolicyRAGAgent.answer] Error: %s", e, exc_info=True)
            raise RuntimeError("Policy model request failed") from e

    @staticmethod
    def _query_category(task: str) -> str:
        lowered = task.lower()
        for category, terms in {"KYC": ("kyc", "identity", "onboarding"), "PAYMENTS": ("upi", "payment", "transfer"), "ACCOUNT_SERVICING": ("account", "nominee", "closure", "dormant"), "LENDING": ("loan", "credit", "emi")}.items():
            if any(term in lowered for term in terms): return category
        return "GENERAL_POLICY"
