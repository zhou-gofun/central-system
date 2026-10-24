"""
从 Excel 导入微信公众号配置，并创建/更新业务应用（wechat_app）

用法（在应用容器网络内执行）：
    python deploy/seed_from_xlsx.py \
        --xlsx /seed/wechat_mp_config.xlsx \
        --app-code doudouji_prod \
        --app-name "豆豆集-生产环境" \
        --app-secret <业务应用密钥>

只依赖标准库解析 xlsx（zip + XML），无需 openpyxl。
"""
import argparse
import asyncio
import secrets
import zipfile
import xml.etree.ElementTree as ET

from ulid import ULID
from sqlalchemy import select

from app.common.database import engine, AsyncSessionLocal
from app.model.wechat.mp_config import WechatMpConfig
from app.model.wechat.app import WechatApp

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_xlsx(path: str) -> list:
    """读取 xlsx 第一个工作表，返回 dict 列表"""
    with zipfile.ZipFile(path) as z:
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                      for si in sroot.findall("m:si", NS)]

    rows = []
    for row in sheet.findall(".//m:sheetData/m:row", NS):
        values = {}
        for cell in row.findall("m:c", NS):
            col = "".join(ch for ch in cell.get("r") if ch.isalpha())
            if cell.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
            elif cell.get("t") == "s":
                v = cell.find("m:v", NS)
                idx = int(v.text) if v is not None else -1
                text = shared[idx] if 0 <= idx < len(shared) else ""
            else:
                v = cell.find("m:v", NS)
                text = v.text if v is not None and v.text else ""
            values[col] = text
        rows.append(values)

    if not rows:
        return []

    headers = {col: name for col, name in rows[0].items()}
    result = []
    for values in rows[1:]:
        item = {headers[col]: val for col, val in values.items() if col in headers}
        if any(item.values()):
            result.append(item)
    return result


async def seed_mp_config(rows: list) -> int:
    """写入/更新 wechat_mp_config"""
    count = 0
    async with AsyncSessionLocal() as db:
        for row in rows:
            appid = (row.get("appid") or "").strip()
            if not appid:
                continue

            secret = (row.get("secret") or "").strip()
            token = (row.get("token") or "").strip()
            aes_key = (row.get("aes_key") or "").strip() or None
            name = (row.get("name") or "").strip() or None
            status = int(row.get("status") or 1)
            mp_id = (row.get("id") or "").strip() or str(ULID())

            result = await db.execute(
                select(WechatMpConfig).where(WechatMpConfig.appid == appid)
            )
            config = result.scalar_one_or_none()
            if config is None:
                config = WechatMpConfig(
                    id=mp_id,
                    appid=appid,
                    secret=secret,
                    token=token,
                    aes_key=aes_key,
                    name=name,
                    status=status,
                )
                db.add(config)
                action = "新增"
            else:
                config.secret = secret
                config.token = token
                config.aes_key = aes_key
                config.name = name
                config.status = status
                action = "更新"

            await db.flush()
            print(f"  [wechat_mp_config] {action} appid={appid} name={name} status={status}")
            count += 1
        await db.commit()
    return count


async def seed_app(app_code: str, app_name: str, app_secret: str | None,
                   mp_appid: str | None, status: int = 1) -> str:
    """写入/更新 wechat_app；app_secret 为 None 时保留已有密钥"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WechatApp).where(WechatApp.app_code == app_code)
        )
        app = result.scalar_one_or_none()
        if app is None:
            app = WechatApp(
                id=str(ULID()),
                app_code=app_code,
                app_name=app_name,
                app_secret=app_secret or secrets.token_hex(12),
                mp_appid=mp_appid,
                status=status,
            )
            db.add(app)
            action = "新增"
        else:
            app.app_name = app_name
            if app_secret:
                app.app_secret = app_secret
            app.mp_appid = mp_appid
            app.status = status
            action = "更新"

        await db.flush()
        await db.commit()
        print(f"  [wechat_app] {action} app_code={app_code} app_name={app_name} "
              f"mp_appid={mp_appid} status={status}")
        return app.id, (app.app_secret if action == "新增" else None)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True, help="wechat_mp_config.xlsx 路径")
    parser.add_argument("--app-code", required=True, help="业务应用 app_code")
    parser.add_argument("--app-name", required=True, help="业务应用 app_name")
    parser.add_argument("--app-secret", help="业务应用 app_secret")
    parser.add_argument("--app-secret-file", help="业务应用 app_secret 所在文件（优先于 --app-secret）")
    parser.add_argument("--mp-appid", default=None, help="绑定的公众号 appid，默认取 xlsx 中第一条")
    args = parser.parse_args()

    app_secret = args.app_secret
    if args.app_secret_file:
        with open(args.app_secret_file, encoding="utf-8") as f:
            app_secret = f.read().strip()

    rows = read_xlsx(args.xlsx)
    if not rows:
        raise SystemExit(f"xlsx 中没有可用数据: {args.xlsx}")

    print(f"读取到 {len(rows)} 条公众号配置")

    mp_count = await seed_mp_config(rows)
    mp_appid = args.mp_appid or (rows[0].get("appid") or "").strip() or None

    app_id, new_secret = await seed_app(args.app_code, args.app_name, app_secret, mp_appid, 1)

    print(f"完成：公众号配置 {mp_count} 条，业务应用 id={app_id}")
    if new_secret:
        print(f"自动生成的 app_secret（请妥善保存）：{new_secret}")


if __name__ == "__main__":
    asyncio.run(main())
