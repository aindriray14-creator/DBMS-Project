import oracledb

conn = oracledb.connect(user="system", password="dbms123", dsn="localhost:1521/XE")
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM EVENT")
print("Events in database:", cur.fetchone()[0])
conn.close()