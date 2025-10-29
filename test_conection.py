import urllib
from sqlalchemy import create_engine, text

params = urllib.parse.quote_plus(
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=204.232.237.135;"
    "DATABASE=Recsolog_wms;"
    "UID=recsolog;"
    "PWD=8_HaZ!2Z;"
    "TrustServerCertificate=yes;"
)
engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")

with engine.begin() as conn:
    result = conn.execute(text("SELECT GETDATE() AS fecha"))
    print([dict(row) for row in result])
