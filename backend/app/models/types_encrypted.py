"""SQLAlchemy 自定义类型：透明加解密的字符串列。

为什么用 TypeDecorator 而不是在 ORM 属性上挂 property / 在每个 service 里手动加解密：
`provider.api_key` 的读取点散布在 6 个供应商适配器、任务运行器与准备度检查里
（见 `grep -rn "\\.api_key" app/`），逐个改必然漏。
TypeDecorator 让「写入即加密、读取即解密」对所有访问路径一致生效，
业务代码继续按普通字符串使用，不会因为忘记解密而把密文发给供应商。

与 `app/core/crypto.py` 的分工：
- crypto.py 负责算法与密钥；
- 本模块负责把算法接到 SQLAlchemy 的读写生命周期上。
"""

from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.crypto import decrypt_secret, encrypt_secret


class EncryptedString(TypeDecorator):
    """写入时加密、读取时解密的文本列。

    存储类型用 `Text` 而非固定长度：Fernet 密文比明文长约 40%~60%，
    用 VARCHAR 定长容易在长密钥上静默截断。

    `cache_ok = True`：SQLAlchemy 允许缓存本类型的表达式，
    本类不携带实例状态，安全。
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        """写入前加密。

        `None` 与空串保持原样：空 api_key 在业务上表示「未配置」，
        加密成密文会让 `if not provider.api_key` 这类判断全部失效。
        """
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        """读取后解密（兼容历史明文）。"""
        return decrypt_secret(value)
