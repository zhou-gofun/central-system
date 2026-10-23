"""
数据迁移脚本：将现有的UUID转换为真正的ULID

这个脚本会：
1. 读取每张表的现有数据
2. 根据created_at时间戳生成对应的ULID
3. 在事务中更新所有记录的ID
4. 保存ID映射以便回滚
"""
import psycopg2
from ulid import ULID
from datetime import datetime
import json

DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"
DB_NAME = "central_system"

# 保存ID映射到文件，以便需要时回滚
id_mapping = {}

def generate_ulid_from_timestamp(created_at):
    """
    根据时间戳生成ULID

    ULID的前10位是时间戳（毫秒），后16位是随机数
    这样可以保持时间顺序性
    """
    if created_at:
        # 将datetime转换为ULID
        return str(ULID.from_timestamp(created_at.timestamp()))
    else:
        # 如果没有created_at，使用当前时间
        return str(ULID())

def migrate_table(cur, table_name):
    """迁移单个表的ID"""
    print(f"\n📊 迁移表: {table_name}")
    print("-" * 60)

    # 检查表是否存在
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = %s
        )
    """, (table_name,))

    if not cur.fetchone()[0]:
        print(f"  ⚠️  表不存在，跳过")
        return

    # 获取所有记录
    cur.execute(f"""
        SELECT id, created_at
        FROM {table_name}
        ORDER BY created_at ASC
    """)

    records = cur.fetchall()
    print(f"  找到 {len(records)} 条记录")

    if len(records) == 0:
        print(f"  ℹ️  表为空，无需迁移")
        return

    table_mapping = {}

    # 为每条记录生成新的ULID
    for old_id, created_at in records:
        new_id = generate_ulid_from_timestamp(created_at)
        table_mapping[old_id] = new_id
        print(f"  {old_id} → {new_id}")

    # 保存映射
    id_mapping[table_name] = table_mapping

    # 更新ID（使用临时列方式避免主键冲突）
    print(f"\n  🔄 更新ID...")

    # 1. 添加临时列
    cur.execute(f"ALTER TABLE {table_name} ADD COLUMN new_id VARCHAR(26)")

    # 2. 填充新ID
    for old_id, new_id in table_mapping.items():
        cur.execute(f"""
            UPDATE {table_name}
            SET new_id = %s
            WHERE id = %s
        """, (new_id, old_id))

    # 3. 删除旧ID列的主键约束
    cur.execute(f"ALTER TABLE {table_name} DROP CONSTRAINT {table_name}_pkey")

    # 4. 删除旧ID列
    cur.execute(f"ALTER TABLE {table_name} DROP COLUMN id")

    # 5. 重命名新ID列
    cur.execute(f"ALTER TABLE {table_name} RENAME COLUMN new_id TO id")

    # 6. 重新添加主键约束
    cur.execute(f"ALTER TABLE {table_name} ADD PRIMARY KEY (id)")

    print(f"  ✅ 表 {table_name} 迁移完成")

def main():
    print("=" * 60)
    print("UUID → ULID 数据迁移")
    print("=" * 60)

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )

        # 设置自动提交为False，使用事务
        conn.autocommit = False
        cur = conn.cursor()

        print("\n⚠️  即将开始数据迁移，所有更改将在一个事务中执行")
        print("   如果出现错误，所有更改将自动回滚\n")

        # 迁移顺序：先迁移没有外键依赖的表
        tables = [
            'wechat_mp_config',  # 公众号配置
            'wechat_app',         # 应用
            'wechat_scan_session' # 扫码会话
        ]

        for table in tables:
            try:
                migrate_table(cur, table)
            except Exception as e:
                print(f"\n❌ 迁移表 {table} 时出错: {e}")
                raise

        # 保存ID映射到文件
        mapping_file = 'id_mapping_backup.json'
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(id_mapping, f, indent=2, ensure_ascii=False)

        print(f"\n💾 ID映射已保存到: {mapping_file}")

        # 提交事务
        print("\n" + "=" * 60)
        print("准备提交事务...")
        response = input("确认提交更改? (yes/no): ")

        if response.lower() == 'yes':
            conn.commit()
            print("✅ 事务已提交，迁移成功！")
        else:
            conn.rollback()
            print("❌ 已回滚，未做任何更改")

        cur.close()
        conn.close()

    except psycopg2.OperationalError as e:
        print(f"❌ 无法连接到数据库: {e}")
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        print("🔄 正在回滚所有更改...")
        if 'conn' in locals():
            conn.rollback()
            print("✅ 已回滚，数据库未被修改")
        raise

if __name__ == "__main__":
    main()
