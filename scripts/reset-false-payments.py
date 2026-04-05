#!/usr/bin/env python3
"""One-time fix: clear false payment_received_at for projects that haven't actually paid."""
import sqlite3
import os
import sys

DB_PATH = os.environ.get("PAYMENT_DB_PATH", "/Users/bob/AI-Server/data/openclaw/payments.db")

if not os.path.exists(DB_PATH):
    # Try Docker path
    DB_PATH = "/data/email-monitor/payments.db"
    if not os.path.exists(DB_PATH):
        print(f"DB not found at either path")
        sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print("Current payment records:")
for row in conn.execute("SELECT * FROM project_payments").fetchall():
    print(f"  {row['project_key']}: status={row['payment_status']}, "
          f"paid_at={row['payment_received_at'] or 'never'}, "
          f"signed_at={row['agreement_signed_at'] or 'never'}")

# Reset all falsely-marked-as-paid records back to their prior state
conn.execute("""
    UPDATE project_payments
    SET payment_received_at = '',
        payment_status = CASE
            WHEN agreement_signed_at != '' THEN 'awaiting_deposit'
            ELSE 'pending'
        END
    WHERE payment_status = 'paid'
""")
conn.commit()

print("\nAfter reset:")
for row in conn.execute("SELECT * FROM project_payments").fetchall():
    print(f"  {row['project_key']}: status={row['payment_status']}, "
          f"paid_at={row['payment_received_at'] or 'never'}")

conn.close()
print("\nDone — false payment alerts cleared.")
