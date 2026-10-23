"""
数据库基础模型和Mixin类
"""
from sqlalchemy import String
from sqlalchemy.orm import mapped_column, Mapped
from ulid import ULID


class ULIDBaseMixin:
    """ULID主键混入类 - 为模型提供ULID主键

    ULID特点:
    - 26位字符串，比UUID更短
    - 时间有序（前10位是时间戳）
    - 大小写敏感
    - URL安全，不包含特殊字符
    - 全局唯一，适合分布式系统

    使用方法:
    ```python
    class MyModel(ULIDBaseMixin, Base):
        __tablename__ = "my_table"
        name: Mapped[str] = mapped_column(String(100))
    ```

    会自动生成ULID作为主键，无需手动传入
    """
    id: Mapped[str] = mapped_column(
        String(26),  # ULID固定长度26位
        primary_key=True,
        nullable=False,
        comment="ULID主键"
    )

    def __init__(self, **kwargs):
        # 如果没有传入id，自动生成ULID
        if 'id' not in kwargs or kwargs['id'] is None:
            kwargs['id'] = str(ULID())
        super().__init__(**kwargs)
