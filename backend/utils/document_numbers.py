def normalize_document_number(value: str) -> str:
    normalized = " ".join(str(value).strip().upper().split())
    if not normalized:
        raise ValueError("DOCUMENT_NUMBER_REQUIRED")
    return normalized
