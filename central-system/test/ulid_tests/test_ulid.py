"""
测试ULID生成和验证
"""
from ulid import ULID
from datetime import datetime

# 测试1: 生成新的ULID
print("测试1: 生成新的ULID")
new_ulid = ULID()
print(f"新ULID: {new_ulid}")
print(f"字符串形式: {str(new_ulid)}")
print(f"长度: {len(str(new_ulid))}")

# 测试2: 从时间戳生成ULID
print("\n测试2: 从时间戳生成ULID")
now = datetime.now()
print(f"时间: {now}")
ulid_from_ts = ULID.from_timestamp(now.timestamp())
print(f"ULID: {ulid_from_ts}")
print(f"字符串形式: {str(ulid_from_ts)}")

# 测试3: 解析ULID
print("\n测试3: 解析ULID")
ulid_str = str(new_ulid)
try:
    parsed = ULID.from_str(ulid_str)
    print(f"原始: {ulid_str}")
    print(f"解析: {parsed}")
    print(f"时间戳: {parsed.timestamp()}")
    print(f"日期时间: {datetime.fromtimestamp(parsed.timestamp())}")
except Exception as e:
    print(f"错误: {e}")

# 测试4: 验证迁移生成的ID
print("\n测试4: 验证迁移生成的ID")
test_ids = [
    "01KEGNQ7H1S8QABJM0Y9R4HMK7",
    "01KEHDFMMEXS23K7FGW0WG3365"
]

for test_id in test_ids:
    print(f"\nID: {test_id}")
    print(f"长度: {len(test_id)}")
    try:
        parsed = ULID.from_str(test_id)
        print(f"✅ 有效 - 时间戳: {datetime.fromtimestamp(parsed.timestamp())}")
    except Exception as e:
        print(f"❌ 无效 - 错误: {e}")
        # 尝试手动解析
        print(f"前10位(时间戳): {test_id[:10]}")
        print(f"后16位(随机): {test_id[10:]}")
