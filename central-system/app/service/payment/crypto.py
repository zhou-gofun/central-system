"""
支付相关加解密与签名工具

覆盖:
- RSA2 (SHA256WithRSA)：微信支付 APIv3 签名/验签、支付宝签名/验签
- AES-256-GCM：微信支付 APIv3 回调报文解密
- MD5：易支付(EasyPay)协议签名
- HMAC-SHA256：中心系统 -> 业务平台 的通知签名
"""
import base64
import hashlib
import hmac
import logging
from typing import Any, Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

__all__ = [
    'load_private_key',
    'load_public_key',
    'rsa_sha256_sign',
    'rsa_sha256_verify',
    'aes_gcm_decrypt',
    'md5_sign',
    'hmac_sha256',
    'build_sorted_query',
    'filter_sign_params',
]


def _normalize_pem(pem: Any) -> bytes:
    """把各种形态的 PEM 规整成可被 cryptography 解析的 bytes"""
    if pem is None:
        raise ValueError('PEM 内容为空')
    if isinstance(pem, bytes):
        text = pem.decode('utf-8', errors='ignore')
    else:
        text = str(pem)
    text = text.strip()
    # 兼容从 JSON / 环境变量里带引号或转义换行的情况
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    text = text.replace('\\n', '\n')

    if '-----BEGIN' not in text:
        # 裸 base64 的公钥/证书内容，补上 PEM 头尾
        body = ''.join(text.split())
        if 'CERTIFICATE' in body[:64]:
            text = f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----"
        else:
            text = f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----"
    return text.encode('utf-8')


def load_private_key(pem: Any) -> rsa.RSAPrivateKey:
    """加载 RSA 私钥，支持 PKCS#1 与 PKCS#8"""
    key = serialization.load_pem_private_key(_normalize_pem(pem), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError('不是 RSA 私钥')
    return key


def load_public_key(pem: Any) -> rsa.RSAPublicKey:
    """加载 RSA 公钥，支持公钥 PEM 与平台证书 PEM"""
    key = serialization.load_pem_public_key(_normalize_pem(pem))
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError('不是 RSA 公钥')
    return key


def rsa_sha256_sign(private_key: rsa.RSAPrivateKey, message: str) -> str:
    """RSA2 签名，返回 base64"""
    signature = private_key.sign(
        message.encode('utf-8'),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode('ascii')


def rsa_sha256_verify(public_key: rsa.RSAPublicKey, message: str, signature_b64: str) -> bool:
    """RSA2 验签"""
    try:
        signature = base64.b64decode(signature_b64)
    except Exception:  # noqa: BLE001
        return False
    try:
        public_key.verify(
            signature,
            message.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, UnsupportedAlgorithm, ValueError, TypeError):
        return False


def aes_gcm_decrypt(key: str, nonce: str, ciphertext_b64: str, associated_data: str = '') -> bytes:
    """AES-256-GCM 解密（微信支付 APIv3 回调）"""
    raw_key = key.encode('utf-8')
    if len(raw_key) != 32:
        raise ValueError(f'APIv3 密钥长度必须为 32 字节，当前 {len(raw_key)}')
    aesgcm = AESGCM(raw_key)
    return aesgcm.decrypt(
        nonce.encode('utf-8'),
        base64.b64decode(ciphertext_b64),
        associated_data.encode('utf-8'),
    )


def filter_sign_params(params: Dict[str, Any]) -> Dict[str, str]:
    """剔除 sign / sign_type 与空值，值统一转字符串"""
    result: Dict[str, str] = {}
    for key, value in params.items():
        if key in ('sign', 'sign_type') or value is None:
            continue
        if isinstance(value, bool):
            result[key] = 'true' if value else 'false'
        else:
            result[key] = str(value)
    return result


def build_sorted_query(params: Dict[str, Any], sep: str = '&') -> str:
    """按 key 字典序拼接待签名字符串"""
    items = sorted(filter_sign_params(params).items(), key=lambda kv: kv[0])
    return sep.join(f'{k}={v}' for k, v in items)


def md5_sign(params: Dict[str, Any], key: str) -> str:
    """易支付 MD5 签名：排序拼接后追加商户密钥，取 md5 小写"""
    query = build_sorted_query(params)
    return hashlib.md5(f'{query}{key}'.encode('utf-8')).hexdigest().lower()


def hmac_sha256(key: str, message: str) -> str:
    """HMAC-SHA256 十六进制签名"""
    return hmac.new(key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
