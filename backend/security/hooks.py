import re
import logging

logger = logging.getLogger(__name__)

class SecurityViolation(Exception):
    """Raised when a security hook blocks a potentially malicious action."""
    pass

class AmbiguousPromptError(Exception):
    """Raised when a prompt is too vague to produce a meaningful query."""
    pass


# Patterns that indicate the prompt is too vague to act on
AMBIGUOUS_PATTERNS = [
    r"^how are things",
    r"^what('s| is) (up|going on|happening)",
    r"^show (me )?(everything|all|stuff|things|data)$",
    r"^(give|show) me (a |the )?report$",
    r"^(tell|show) me (something|anything)",
]

INJECTION_PATTERNS = [
    "ignore previous",
    "disregard previous",
    "system prompt",
    "you are a",
    "forget all",
    "bypass",
    "sudo",
    "delete",
    "drop",
    "trick"
]


def sanitize_prompt(prompt: str) -> str:
    """
    PRE-MODEL HOOK
    1. Rejects empty prompts.
    2. Detects prompt injection patterns.
    3. Detects ambiguous prompts that cannot produce a meaningful query.
    Logs every hook decision.
    """
    if not prompt or not prompt.strip():
        logger.warning("Hook decision: DENY — empty prompt")
        raise SecurityViolation("Prompt cannot be empty.")

    prompt_lower = prompt.lower().strip()

    for pattern in INJECTION_PATTERNS:
        if pattern in prompt_lower:
            logger.warning(f"Hook decision: DENY — injection pattern '{pattern}'")
            raise SecurityViolation(f"🚨 WARNING: Do not try to trick me! I am a strong AI agent built with strict security hooks. Malicious input detected: pattern '{pattern}' is not allowed.")

    for pattern in AMBIGUOUS_PATTERNS:
        if re.search(pattern, prompt_lower):
            logger.info(f"Hook decision: WARN — ambiguous/conversational prompt matched '{pattern}'")
            # We no longer block this. The LLM intent node will route it appropriately.


    logger.info("Hook decision: ALLOW — prompt passed all checks")
    return prompt


def validate_sql(sql: str) -> str:
    """
    PRE-TOOL HOOK
    Validates SQL queries before they hit the database.
    Only allows SELECT statements and strictly blocks destructive keywords.
    Logs every hook decision.
    """
    sql_clean = sql.strip()
    sql_upper = sql_clean.upper()

    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("SUMMARIZE")):
        logger.warning("Hook decision: DENY — SQL does not start with SELECT or SUMMARIZE")
        raise SecurityViolation("Only SELECT and SUMMARIZE queries are allowed. Query must start with SELECT or SUMMARIZE.")

    forbidden_keywords = [
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
        "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "MERGE"
    ]

    for keyword in forbidden_keywords:
        if re.search(rf"\b{keyword}\b", sql_upper):
            logger.warning(f"Hook decision: DENY — forbidden keyword '{keyword}' in SQL")
            raise SecurityViolation(f"Query contains forbidden keyword: '{keyword}'. Only read operations are permitted.")

    logger.info("Hook decision: ALLOW — SQL passed all checks")
    return sql_clean


def validate_tool_output(data: list, max_rows: int = 100) -> list:
    """
    POST-TOOL HOOK
    Ensures returned data is a non-empty list and doesn't exceed the context window limit.
    Logs every hook decision.
    """
    if not isinstance(data, list):
        raise ValueError("Data must be a list of records.")

    if len(data) == 0:
        logger.warning("Hook decision: WARN — query returned 0 rows")
        return data

    if len(data) > max_rows:
        logger.warning(f"Hook decision: MASK — truncating {len(data)} rows to {max_rows}")
        return data[:max_rows]

    logger.info(f"Hook decision: ALLOW — {len(data)} rows passed output validation")
    return data
