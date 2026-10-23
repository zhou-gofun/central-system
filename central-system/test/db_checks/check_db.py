"""
检查数据库和表的实际情况
"""
import psycopg2

DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"

print("=" * 60)
print("数据库检查")
print("=" * 60)

# 连接到 postgres 数据库
conn = psycopg2.connect(
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database="postgres"
)
cur = conn.cursor()

# 列出所有数据库
print("\n📦 所有数据库:")
cur.execute("""
    SELECT datname FROM pg_database
    WHERE datistemplate = false
    ORDER BY datname
""")
databases = cur.fetchall()
for db in databases:
    print(f"  - {db[0]}")

cur.close()
conn.close()

# 检查 central_system 数据库
print("\n" + "=" * 60)
print("检查 central_system 数据库")
print("=" * 60)

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database="central_system"
    )
    cur = conn.cursor()

    # 列出所有表
    print("\n📊 central_system 数据库中的所有表:")
    cur.execute("""
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schemaname, tablename
    """)
    tables = cur.fetchall()

    if tables:
        for schema, table in tables:
            print(f"  - {schema}.{table}")
    else:
        print("  ⚠️ 没有找到任何表！")

    # 检查所有 schema
    print("\n📂 所有 schema:")
    cur.execute("""
        SELECT schema_name
        FROM information_schema.schemata
        ORDER BY schema_name
    """)
    schemas = cur.fetchall()
    for schema in schemas:
        print(f"  - {schema[0]}")

    cur.close()
    conn.close()

except Exception as e:
    print(f"❌ 错误: {e}")

print("\n" + "=" * 60)
