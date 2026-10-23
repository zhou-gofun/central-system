"""
列出所有数据库及其中的表
"""
import psycopg2

DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"

# 连接到 postgres 获取所有数据库
conn = psycopg2.connect(
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database="postgres"
)
cur = conn.cursor()

print("=" * 80)
print("所有数据库列表")
print("=" * 80)

cur.execute("""
    SELECT datname FROM pg_database
    WHERE datistemplate = false
    ORDER BY datname
""")
databases = cur.fetchall()

for db_name, in databases:
    print(f"\n📦 数据库: {db_name}")
    print("-" * 80)

    try:
        # 连接到每个数据库
        db_conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=db_name
        )
        db_cur = db_conn.cursor()

        # 获取用户表（排除系统表）
        db_cur.execute("""
            SELECT schemaname, tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        tables = db_cur.fetchall()

        if tables:
            print(f"   📊 在 public schema 中找到 {len(tables)} 个表:")
            for schema, table in tables:
                # 获取表的行数
                db_cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
                count = db_cur.fetchone()[0]
                print(f"      • {table} ({count} 行)")
        else:
            print("   ⚠️  在 public schema 中没有表")

        db_cur.close()
        db_conn.close()

    except Exception as e:
        print(f"   ❌ 无法连接: {e}")

cur.close()
conn.close()

print("\n" + "=" * 80)
print("✅ 检查完成！")
print("\n💡 提示:")
print("   如果要在数据库工具中查看表，请确保:")
print("   1. 在左侧数据库列表中找到 'central_system' 数据库")
print("   2. 展开 central_system → public → 表")
print("   3. 就能看到 wechat_app, wechat_mp_config, wechat_scan_session")
print("=" * 80)
