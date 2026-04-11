"""LLM-powered enrichment of incident records using LangChain + Anthropic.

Uses LangChain's .with_structured_output() so the model can be swapped by
changing the config — replace ChatAnthropic with ChatOpenAI (or any other
LangChain chat model) without touching this logic.
"""

from datetime import datetime, timezone
from typing import List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from models.incident_record import IncidentRecord
from utils.logger import get_logger

log = get_logger("llm_enricher")

# System prompt is defined once here; it is the same for every call in a run,
# which makes it a good candidate for prompt caching on the provider side.
SYSTEM_PROMPT = """\
You are an expert analyst of software incident post-mortems.
You will be given the full text of an incident post-mortem page alongside
some existing metadata already extracted from the index that linked to it.

Extract structured information as accurately as possible from the post-mortem text.
Only include information that is explicitly stated or clearly implied — do not infer
or fabricate details. If a field cannot be determined, omit it.\
"""


class IncidentExtraction(BaseModel):
    """Schema for the structured data the LLM extracts from a post-mortem page.

    Used as the .with_structured_output() target — LangChain enforces that the
    model response conforms to this shape before returning it.
    """

    # A clean, descriptive title that includes company and rough date where known
    title: str = Field(
        description="Concise descriptive title, e.g. 'AWS S3 us-east-1 Outage — February 2017'"
    )

    # 2-4 sentence factual summary covering what failed, impact, and resolution
    summary: str = Field(
        description="Factual summary: what failed, what the impact was, and how it was resolved"
    )

    # Named services/systems that were directly impacted
    affected_services: List[str] = Field(
        description="Specific services, APIs, or infrastructure components that were impacted"
    )

    # Root causes and contributing factors as stated in the post-mortem
    root_causes: List[str] = Field(
        description="Root causes and contributing factors described in the post-mortem"
    )

    # Concrete steps taken to resolve or mitigate the incident
    remediation_actions: List[str] = Field(
        description="Specific actions taken to resolve or mitigate the incident"
    )

    # Total incident duration — omitted if not explicitly stated
    duration_minutes: Optional[int] = Field(
        None,
        description="Total duration of the incident in minutes. Omit if not stated."
    )

    # Severity characterisation from the post-mortem itself
    severity: Optional[str] = Field(
        None,
        description="Severity description as used in the post-mortem, e.g. 'complete outage'"
    )

    # Incident date — only included when the post-mortem states it clearly
    date: Optional[str] = Field(
        None,
        description="Date of the incident in YYYY-MM-DD format. Omit if not determinable."
    )

    # Taxonomy classification — values must come from the taxonomy provided in the prompt
    taxonomy_category: Optional[str] = Field(
        None,
        description="Top-level taxonomy category (e.g. infrastructure, application, operational)"
    )
    taxonomy_subcategory: Optional[str] = Field(
        None,
        description="Second-level taxonomy subcategory (e.g. network, compute, memory)"
    )
    taxonomy_type: Optional[str] = Field(
        None,
        description="Leaf-level taxonomy type (e.g. latency, oom, deadlock)"
    )


def _format_taxonomy(taxonomy: dict) -> str:
    """Render the config taxonomy as an indented text block for the LLM prompt.

    The config structure is: {category: [{subcategory: [type, ...]}, ...], ...}
    Output example:
      infrastructure:
        network: latency, partition, dns_failure
        compute: cpu_saturation, host_failure
    """
    lines = []
    for category, subcategories in taxonomy.items():
        lines.append(f"  {category}:")
        for item in subcategories or []:
            if isinstance(item, dict):
                for subcategory, types in item.items():
                    type_list = ", ".join(types) if types else ""
                    lines.append(f"    {subcategory}: {type_list}")
    return "\n".join(lines)


def build_llm(config: dict, api_key: str) -> ChatAnthropic:
    """Construct the LangChain chat model from config.

    The model name comes from config so it can be changed without code edits.
    The api_key is passed explicitly (read from .env by main.py) rather than
    relying on the environment variable being set at import time.
    temperature=0 keeps extractions deterministic across runs.
    """
    enrichment_config = config.get("enrichment", {})
    model_name = enrichment_config.get("model", "claude-sonnet-4-6")
    timeout = enrichment_config.get("request_timeout_seconds", 30)

    return ChatAnthropic(
        model=model_name,
        api_key=api_key,     # key loaded from .env via main.py
        temperature=0,       # deterministic output for data extraction
        max_tokens=1024,
        timeout=timeout,
    )


def enrich(
    record: IncidentRecord,
    page_content: str,
    llm: ChatAnthropic,
    config: dict,
) -> IncidentRecord:
    """Extract structured incident details from a fetched post-mortem page.

    Calls the LLM with the page content and existing record metadata, then
    overwrites record fields with the higher-quality LLM-extracted values.
    Existing field values are only replaced when the LLM returns something
    non-empty, so partial failures degrade gracefully.

    Args:
        record: The IncidentRecord to enrich (mutated in place).
        page_content: Plain text fetched from the record's source_url.
        llm: LangChain chat model instance (built once per pipeline run).
        config: Full application config dict.

    Returns:
        The same record with enriched fields and llm_enriched=True.
    """
    # Bind structured output schema — LangChain will enforce the response shape
    structured_llm = llm.with_structured_output(IncidentExtraction)

    # Format the taxonomy from config for inclusion in the prompt
    taxonomy = config.get("taxonomy", {})
    taxonomy_block = _format_taxonomy(taxonomy) if taxonomy else "  (no taxonomy configured)"

    # Include existing metadata so the LLM has context about what we already know
    user_message = f"""\
Please extract the structured incident details from this post-mortem.

Existing metadata (from the index page that linked here):
- Company / Service: {record.company or "Unknown"}
- Current title: {record.title or "Unknown"}
- Current description: {record.description or "Unknown"}
- Source URL: {record.source_url}

Taxonomy — classify this incident using exactly these values:
{taxonomy_block}

Post-mortem content:
<content>
{page_content}
</content>"""

    messages = [
        # System message is constant across calls — good for provider-side caching
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    try:
        extracted: IncidentExtraction = structured_llm.invoke(messages)
    except Exception as exc:
        log.error(
            "LLM enrichment call failed",
            record_id=record.id,
            error=str(exc),
        )
        return record

    # Overwrite existing fields only when the LLM returned a non-empty value,
    # so a failed or partial extraction doesn't blank out what we already have
    if extracted.title:
        record.title = extracted.title
    if extracted.summary:
        record.description = extracted.summary
        record.llm_summary = extracted.summary   # keep the LLM summary separately too
    if extracted.affected_services:
        record.affected_services = extracted.affected_services
    if extracted.root_causes:
        record.root_causes_raw = extracted.root_causes
    if extracted.remediation_actions:
        record.remediation_actions_raw = extracted.remediation_actions
    if extracted.duration_minutes is not None:
        record.duration_minutes = extracted.duration_minutes
    if extracted.severity:
        record.severity_raw = extracted.severity
    if extracted.date:
        record.date = extracted.date
    if extracted.taxonomy_category:
        record.taxonomy_category = extracted.taxonomy_category
    if extracted.taxonomy_subcategory:
        record.taxonomy_subcategory = extracted.taxonomy_subcategory
    if extracted.taxonomy_type:
        record.taxonomy_type = extracted.taxonomy_type

    # Mark the record so downstream stages and storage know it was LLM-enriched
    record.llm_enriched = True
    record.llm_enriched_at = datetime.now(tz=timezone.utc).isoformat()

    log.info("Record enriched by LLM", record_id=record.id, model=llm.model)

    return record
