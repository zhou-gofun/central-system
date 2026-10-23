"""
验证ULID格式和特性
"""
import psycopg2
from ulid import ULID
from datetime import datetime

DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"
DB_NAME = "central_system"

def verify_ulid(ulid_str):
    """验证字符串是否为有效的ULID并解析时间戳"""
    try:
        ulid_obj = ULID.from_str(ulid_str)
        # timestamp是属性，不是方法
        timestamp = ulid_obj.timestamp
        dt = datetime.fromtimestamp(timestamp)
        return True, dt
    except Exception as e:
        return False, None

print("=" * 60)
print("验证ULID格式和特性")
print("=" * 60)

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    cur = conn.cursor()

    tables = [
        'wechat_app',
        'wechat_mp_config',
        'wechat_scan_session'
    ]

    total_valid = 0
    total_invalid = 0

    for table in tables:
        print(f"\n📊 表: {table}")
        print("-" * 60)

        cur.execute(f"""
            SELECT id, created_at
            FROM {table}
            ORDER BY created_at ASC
            LIMIT 5
        """)

        records = cur.fetchall()

        for id_val, created_at in records:
            is_valid, ulid_timestamp = verify_ulid(id_val)

            if is_valid:
                total_valid += 1
                time_diff = abs((ulid_timestamp - created_at).total_seconds())
                status = "✅" if time_diff < 1 else "⚠️"
                print(f"  {status} {id_val}")
                print(f"     ULID时间: {ulid_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     数据库时间: {created_at.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     时间差: {time_diff:.2f}秒")
            else:
                total_invalid += 1
                print(f"  ❌ {id_val} - 不是有效的ULID")

    print("\n" + "=" * 60)
    print(f"验证结果: {total_valid} 个有效ULID, {total_invalid} 个无效")
    print("=" * 60)

    cur.close()
    conn.close()

except Exception as e:
    print(f"❌ 错误: {e}")
