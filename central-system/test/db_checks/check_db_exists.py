"""
仔细检查数据库是否真的存在
"""
import psycopg2

DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"

print("=" * 80)
print("重新检查数据库")
print("=" * 80)

try:
    # 连接到 postgres 数据库
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database="postgres"
    )
    conn.autocommit = True
    cur = conn.cursor()

    print("\n🔍 查询所有数据库...")
    cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname")
    databases = cur.fetchall()

    print(f"\n找到 {len(databases)} 个数据库:\n")
    for idx, (db_name,) in enumerate(databases, 1):
        print(f"  {idx}. {db_name}")

    # 检查 central_system 是否存在
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'central_system'")
    exists = cur.fetchone()

    print("\n" + "=" * 80)
    if exists:
        print("✅ central_system 数据库 EXISTS（存在）")
    else:
        print("❌ central_system 数据库 DOES NOT EXIST（不存在）")
        print("\n🔧 正在创建 central_system 数据库...")

        try:
            cur.execute("CREATE DATABASE central_system")
            print("✅ 数据库创建成功！")
        except Exception as e:
            print(f"❌ 创建失败: {e}")

    cur.close()
    conn.close()

except Exception as e:
    print(f"❌ 连接错误: {e}")
    import traceback
    traceback.print_exc()

print("=" * 80)
