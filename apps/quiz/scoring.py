from decimal import Decimal, ROUND_HALF_UP


def quiz_percentage(score, denominator):
    """One decimal place, half-up, matching SQL ROUND used by summaries."""
    if not denominator or denominator <= 0:
        return 0.0
    return float((Decimal(score) * 100 / Decimal(denominator)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
