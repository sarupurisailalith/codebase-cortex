"""Robust JSON array parsing from LLM responses."""

from __future__ import annotations

import json
import re


def parse_json_array(raw: str) -> list[dict]:
    """Extract a JSON array from an LLM response, handling common quirks.

    Handles:
    - Raw JSON arrays
    - JSON wrapped in markdown code blocks (```json ... ```)
    - Trailing commas
    - Text before/after the JSON array

    Args:
        raw: Raw LLM response text.

    Returns:
        Parsed list of dicts.

    Raises:
        ValueError: If no valid JSON array can be extracted.
    """
    # Try direct parse first
    text = raw.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Extract from markdown code blocks
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if code_block_match:
        try:
            result = json.loads(code_block_match.group(1).strip())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Find the outermost [ ... ] in the response
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        candidate = bracket_match.group(0)
        # Remove trailing commas before ] (common LLM mistake)
        candidate = re.sub(r",\s*\]", "]", candidate)
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON array from LLM response: {text[:200]}")
