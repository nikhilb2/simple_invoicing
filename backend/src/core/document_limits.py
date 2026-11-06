"""Storage limits for money and quantity columns."""

MONEY_LIMIT = 100_000_000  # NUMERIC(10, 2)
QUANTITY_LIMIT = 1_000_000_000  # NUMERIC(12, 3)

# PostgreSQL rounds to the column scale before checking for overflow.
MONEY_STORAGE_CUTOFF = MONEY_LIMIT - 0.005
QUANTITY_STORAGE_CUTOFF = QUANTITY_LIMIT - 0.0005
