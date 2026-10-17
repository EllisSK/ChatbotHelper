def validate_amount(amount: int) -> int:
    """Require a whole-number amount."""
    if not isinstance(amount, int):
        raise TypeError("amount must be an integer")
    return amount
