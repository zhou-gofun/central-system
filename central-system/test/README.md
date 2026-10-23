# 测试和工具脚本目录

本目录包含项目的测试脚本、数据库检查工具和迁移脚本。

## 目录结构

### test/db_checks/
数据库检查和验证脚本

- **check_db.py** - 检查数据库和表的实际情况
- **check_db_config.py** - 检查数据库配置
- **check_db_exists.py** - 检查数据库是否存在
- **check_existing_data.py** - 检查数据库中现有数据和ID格式
- **db_report.py** - 生成数据库报告
- **list_all_dbs.py** - 列出所有数据库
- **verify_db.py** - 验证数据库连接和状态

### test/migrations/
数据库迁移和初始化脚本

- **init_db.py** - 数据库初始化脚本
- **init_db_simple.py** - 简化版数据库初始化
- **migrate.py** - 通用迁移脚本
- **migrate_uuid_to_ulid.py** - UUID到ULID的数据迁移脚本
- **id_mapping_backup.json** - UUID到ULID的ID映射备份文件

### test/ulid_tests/
ULID功能测试脚本

- **test_ulid.py** - ULID生成和验证测试
- **verify_ulid.py** - 验证数据库中ULID格式和特性

## 使用方法

### 数据库检查
```bash
# 激活虚拟环境
source venv/bin/activate

# 检查数据库状态
python test/db_checks/check_db.py

# 检查现有数据
python test/db_checks/check_existing_data.py
```

### 数据库迁移
```bash
# 初始化数据库
python test/migrations/init_db.py

# 执行UUID到ULID迁移
python test/migrations/migrate_uuid_to_ulid.py
```

### ULID测试
```bash
# 测试ULID功能
python test/ulid_tests/test_ulid.py

# 验证数据库中的ULID
python test/ulid_tests/verify_ulid.py
```

## 注意事项

1. 所有脚本都需要在激活虚拟环境后执行
2. 数据库迁移脚本会修改数据，执行前请备份
3. 迁移脚本会生成备份文件（如 id_mapping_backup.json）
4. 所有数据库操作脚本都使用相同的数据库配置
