from .validation import validate_amount


def invoice(amount: int) -> str:
    """Format an invoice amount."""
    return f"Invoice: {validate_amount(amount)}"
