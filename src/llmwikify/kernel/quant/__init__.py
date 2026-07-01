"""kernel/quant/ — quant-domain abstractions shared across apps/ and reproduction/.

This subpackage holds quant-specific code that:

  - Does NOT depend on apps/chat/ (no unified/, no runner_v2)
  - Does NOT depend on reproduction/ (no codegen/, no paper_understanding)
  - CAN be imported by either apps/ or reproduction/

This is the canonical home for quant-domain building blocks:

  - codegen/        — LLM-driven code generation (extract / validate / execute) [C1]
  - llm_client.py   — StreamableLLMClient construction from config [C2]
  - data_source/    — DataSource Protocol + DataRouter (added in C3)

C1 introduced this subpackage. PR scope: codegen/ + llm_client/ only.
"""

