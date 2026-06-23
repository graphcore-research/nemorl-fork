def add_timestamp(string: str) -> str:
    """
    Add timestamp to a string

    Args:
        string: Base string (e.g., "samot-dev" or "my-experiment")

    Returns:
        Run name with timestamp appended (e.g., "samot-dev-20260417t153210")
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S")
    return f"{string}-{timestamp}"
