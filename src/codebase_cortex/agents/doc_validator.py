"""DocValidator agent — quality check comparing docs against source code."""

from __future__ import annotations

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.config import Settings
from codebase_cortex.state import CortexState
from codebase_cortex.utils.json_parsing import parse_json_array

SYSTEM_PROMPT = """You are a documentation quality validator. Given a documentation section
and the actual source code it describes, check for factual accuracy.

For each section, respond with a JSON object:
- "confidence": "high" (accurate), "medium" (minor discrepancies), or "low" (factual errors)
- "issues": array of issue strings (empty if confidence is "high")

Only flag real factual errors — don't flag stylistic preferences, missing detail,
or documentation that's correct but could be more comprehensive.

Common factual errors to catch:
- Wrong function signatures, parameter names, or return types
- References to nonexistent classes, methods, or endpoints
- Incorrect descriptions of behavior (e.g., "synchronous" when it's async)
- Stale information about removed or renamed components

Respond with ONLY the JSON object."""

LOW_CONFIDENCE_MARKER = (
    "> :mag: **Cortex confidence: low** — This section may contain inaccuracies.\n"
    "> Please verify against the source code before relying on it.\n\n"
)


class DocValidatorAgent(BaseAgent):
    """Validates generated documentation against source code.

    Assigns confidence scores and flags potential factual errors.
    Skipped at detail_level="standard".
    """

    async def run(self, state: CortexState) -> dict:
        doc_updates = state.get("doc_updates", [])
        if not doc_updates:
            return {"validated_updates": [], "validation_issues": []}

        detail_level = state.get("detail_level", "standard")
        if detail_level == "standard":
            # At standard detail level, skip validation — pass through
            return {
                "validated_updates": [
                    {**update, "confidence": "high"} for update in doc_updates
                ],
                "validation_issues": [],
            }

        analysis = state.get("analysis", "")
        validated: list[dict] = []
        issues: list[dict] = []
        confidence_counts = {"high": 0, "medium": 0, "low": 0}

        for update in doc_updates:
            title = update.get("title", "Untitled")
            content = update.get("content", "")

            if not content:
                validated.append({**update, "confidence": "high"})
                confidence_counts["high"] += 1
                continue

            prompt = f"""Validate this documentation section for factual accuracy.

## Documentation Section: {title}
```markdown
{content[:3000]}
```

## Code Analysis (for reference)
{analysis[:2000]}

Check if the documentation accurately describes the code. Respond with a JSON object:
{{"confidence": "high"|"medium"|"low", "issues": ["issue1", ...]}}"""

            try:
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
                raw = await self._invoke_llm(messages, node_name="doc_validator")

                # Parse as JSON array (utility handles single objects too)
                results = parse_json_array(raw)
                result = results[0] if results else {"confidence": "high", "issues": []}

            except Exception as e:
                self._logger.warning(f"Validation failed for {title}: {e}")
                result = {"confidence": "high", "issues": []}

            confidence = result.get("confidence", "high")
            section_issues = result.get("issues", [])
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

            if confidence == "low" and section_issues:
                # Check if fundamentally wrong (references nonexistent things)
                is_fundamentally_wrong = any(
                    "nonexistent" in issue.lower() or "does not exist" in issue.lower()
                    for issue in section_issues
                )

                if is_fundamentally_wrong:
                    # Exclude from output, create task instead
                    issues.append({
                        "page": title,
                        "confidence": "low",
                        "issues": section_issues,
                        "action": "excluded",
                        "reason": "Documentation references nonexistent components",
                    })
                    continue

                # Add review marker for low confidence
                marked_content = LOW_CONFIDENCE_MARKER + content
                validated.append({
                    **update,
                    "content": marked_content,
                    "confidence": "low",
                })
            else:
                validated.append({**update, "confidence": confidence})

            if section_issues:
                issues.append({
                    "page": title,
                    "confidence": confidence,
                    "issues": section_issues,
                })

        return {
            "validated_updates": validated,
            "validation_issues": issues,
        }
