"""Exact decimal calculations shared by browser and integration entries."""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal('0.01')


def calculate_totals(cash, card, hours, sales):
    cash, card, hours, sales = [Decimal(str(v or 0)) for v in (cash, card, hours, sales)]
    total = cash + card
    return {
        'total_tips': total.quantize(CENT, rounding=ROUND_HALF_UP),
        'tips_per_hour': (total / hours if hours > 0 else Decimal(0)).quantize(CENT, rounding=ROUND_HALF_UP),
        'tip_percentage': (total / sales * 100 if sales > 0 else Decimal(0)).quantize(CENT, rounding=ROUND_HALF_UP),
    }
