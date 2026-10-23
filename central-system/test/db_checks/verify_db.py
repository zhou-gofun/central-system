"""
验证数据库表结构和数据
"""
import psycopg2

DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"
DB_NAME = "central_system"

conn = psycopg2.connect(
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME
)
cur = conn.cursor()

print("=" * 60)
print("数据库验证报告")
print("=" * 60)

# 检查表
print("\n📊 表列表:")
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name LIKE 'wechat%'
    ORDER BY table_name
""")
tables = cur.fetchall()
for table in tables:
    print(f"  ✓ {table[0]}")

# 检查每个表的结构
for table in tables:
    table_name = table[0]
    print(f"\n📋 {table_name} 表结构:")
    cur.execute(f"""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = '{table_name}'
        ORDER BY ordinal_position
    """)
    columns = cur.fetchall()
    for col in columns:
        nullable = "NULL" if col[2] == 'YES' else "NOT NULL"
        print(f"  - {col[0]:<20} {col[1]:<20} {nullable}")

# 检查示例数据
print("\n" + "=" * 60)
print("📦 示例数据:")
print("=" * 60)

cur.execute("SELECT COUNT(*) FROM wechat_mp_config")
mp_count = cur.fetchone()[0]
print(f"\n微信公众号配置: {mp_count} 条")
if mp_count > 0:
    cur.execute("SELECT appid, name FROM wechat_mp_config LIMIT 3")
    for row in cur.fetchall():
        print(f"  - {row[0]}: {row[1]}")

cur.execute("SELECT COUNT(*) FROM wechat_app")
app_count = cur.fetchone()[0]
print(f"\n业务应用: {app_count} 条")
if app_count > 0:
    cur.execute("SELECT app_code, app_name, mp_appid FROM wechat_app LIMIT 3")
    for row in cur.fetchall():
        print(f"  - {row[0]}: {row[1]} (绑定公众号: {row[2]})")

cur.execute("SELECT COUNT(*) FROM wechat_scan_session")
session_count = cur.fetchone()[0]
print(f"\n扫码会话: {session_count} 条")

print("\n" + "=" * 60)
print("✅ 数据库验证完成！")
print("=" * 60)

cur.close()
conn.close()
