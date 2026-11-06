"""Storage limits for money and quantity columns."""

MONEY_LIMIT = 100_000_000  # NUMERIC(10, 2)
QUANTITY_LIMIT = 1_000_000_000  # NUMERIC(12, 3)
PRODUCTION_COST_LIMIT = 10_000_000_000  # NUMERIC(12, 2)

# PostgreSQL rounds to the column scale before checking for overflow.
MONEY_STORAGE_CUTOFF = MONEY_LIMIT - 0.005
QUANTITY_STORAGE_CUTOFF = QUANTITY_LIMIT - 0.0005
# Rounding-aware cutoff for NUMERIC(12, 2): values >= 9,999,999,999.995 round up to 10^10.
PRODUCTION_COST_STORAGE_CUTOFF = PRODUCTION_COST_LIMIT - 0.005
