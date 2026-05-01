"""Quick script to check the identity mapping table schema and sample data."""
from dotenv import load_dotenv
from pathlib import Path
import os, pymssql

load_dotenv(Path(__file__).parent.parent / ".env")

conn = pymssql.connect(
    server=os.getenv("SQL_SERVER_HOST"),
    database=os.getenv("SQL_SERVER_DB"),
    user=os.getenv("SQL_SERVER_USER"),
    password=os.getenv("SQL_SERVER_PASS"),
    as_dict=True,
)
cur = conn.cursor()

print("=== Schema ===")
cur.execute(
    "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
    "WHERE TABLE_SCHEMA='cost_management' AND TABLE_NAME='anomaly_cost_email_subscribers' "
    "ORDER BY ORDINAL_POSITION"
)
for r in cur.fetchall():
    print(f"  {r['COLUMN_NAME']:30s} {r['DATA_TYPE']}")

print("\n=== Sample (3 rows) ===")
cur.execute("SELECT TOP 3 * FROM [cost_management].[anomaly_cost_email_subscribers]")
for r in cur.fetchall():
    print(r)

print("\n=== Distinct core_id count ===")
cur.execute("SELECT COUNT(DISTINCT core_id) AS cnt FROM [cost_management].[anomaly_cost_email_subscribers]")
print(cur.fetchone())

print("\n=== Sample: projects for a core_id ===")
cur.execute("SELECT TOP 1 core_id FROM [cost_management].[anomaly_cost_email_subscribers]")
sample_id = cur.fetchone()["core_id"]
cur.execute(
    "SELECT DISTINCT project_name FROM [cost_management].[anomaly_cost_email_subscribers] WHERE core_id = %s",
    (sample_id,),
)
print(f"core_id={sample_id} -> projects:")
for r in cur.fetchall():
    print(f"  {r['project_name']}")

conn.close()
