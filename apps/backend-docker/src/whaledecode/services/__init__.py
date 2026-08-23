"""Active-rotation engine and ingestion decoder services.

These sit between the Alchemy webhook (active triggers) and PostgreSQL
(passive attribution): the rotation service keeps ≤300 high-conviction wallets
on the webhook and the decoder drops low-value noise + records per-address
velocity so the next rotation can demote noisy wallets.
"""
