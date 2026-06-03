"""The language layer (M6): LiteLLM gateway client, PII masking, narration.

Hard boundary: the LLM never computes a business number (prompts carry finished
SQL numbers; a validator rejects any narration containing other numbers), and
no raw PII ever enters a prompt (the masking layer pseudonymises identity and
strips contact data before every call).
"""
