#!/usr/bin/env python3
"""
数据库配置检查脚本
用于诊断正式环境和测试环境的数据库配置差异
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.model.wechat.app import WechatApp
from app.model.wechat.mp_config import WechatMpConfig


async def check_database(db_url: str, env_name: str):
    """检查数据库配置"""
    print(f"\n{'='*60}")
    print(f"检查 {env_name} 环境数据库")
    print(f"{'='*60}")
    print(f"数据库URL: {db_url}")
    print()

    try:
        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # 检查 wechat_app 表
            print("1. 检查 wechat_app 表")
            print("-" * 60)
            result = await session.execute(select(WechatApp))
            apps = result.scalars().all()

            if apps:
                for app in apps:
                    print(f"  ✓ app_code: {app.app_code}")
                    print(f"    app_name: {app.app_name}")
                    print(f"    mp_appid: {app.mp_appid}")
                    print(f"    status: {app.status}")
                    print()
            else:
                print("  ✗ 表为空，没有任何应用配置")
                print()

            # 检查 wechat_mp_config 表
            print("2. 检查 wechat_mp_config 表")
            print("-" * 60)
            result = await session.execute(select(WechatMpConfig))
            configs = result.scalars().all()

            if configs:
                for config in configs:
                    print(f"  ✓ appid: {config.appid}")
                    print(f"    name: {config.name}")
                    print(f"    status: {config.status}")
                    print(f"    secret: {config.secret[:10]}..." if config.secret else "    secret: (空)")
                    print()
            else:
                print("  ✗ 表为空，没有任何公众号配置")
                print()

            # 交叉检查：验证 app 关联的 mp_appid 是否存在于 mp_config 中
            print("3. 交叉验证：应用关联的公众号配置")
            print("-" * 60)
            for app in apps:
                if app.mp_appid:
                    result = await session.execute(
                        select(WechatMpConfig).where(
                            WechatMpConfig.appid == app.mp_appid,
                            WechatMpConfig.status == 1
                        )
                    )
                    mp_config = result.scalar_one_or_none()

                    if mp_config:
                        print(f"  ✓ {app.app_code} -> {app.mp_appid} (配置存在)")
                    else:
                        print(f"  ✗ {app.app_code} -> {app.mp_appid} (配置缺失或未启用)")
                else:
                    print(f"  ⚠ {app.app_code} 未绑定公众号")
            print()

        await engine.dispose()
        return True

    except Exception as e:
        print(f"✗ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数"""
    print("数据库配置检查工具")

    # 测试环境数据库
    test_db_url = "postgresql+asyncpg://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system_test"
    await check_database(test_db_url, "测试环境")

    # 正式环境数据库
    prod_db_url = "postgresql+asyncpg://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system"
    await check_database(prod_db_url, "正式环境")

    print("\n" + "="*60)
    print("检查完成")
    print("="*60)
    print("\n建议：")
    print("如果正式环境缺少配置，请运行以下命令初始化数据：")
    print("  python3 init_db.py --env prod")
    print()


if __name__ == "__main__":
    asyncio.run(main())
