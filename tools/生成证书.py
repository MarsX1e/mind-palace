# -*- coding: utf-8 -*-
"""
生成自签名 HTTPS 证书
====================
用法：python 生成证书.py 1.2.3.4 [其他IP，如 100.x.x.x]
生成：server/cert.pem 与 server/key.pem
之后 uvicorn 加上 --ssl-certfile / --ssl-keyfile 即可用 HTTPS 访问。

说明：自签名证书浏览器会提示"不安全"，点"继续访问"即可；
     流量本身是强加密的，只是没有第三方机构背书。
"""

import datetime
import ipaddress
import os
import sys

脚本目录 = os.path.dirname(os.path.abspath(__file__))
服务器目录 = os.path.normpath(os.path.join(脚本目录, "..", "server"))
证书路径 = os.path.join(服务器目录, "cert.pem")
私钥路径 = os.path.join(服务器目录, "key.pem")


def 主流程():
    IP们 = sys.argv[1:] or ["127.0.0.1"]
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("缺少 cryptography 库，请先运行：pip install cryptography")
        sys.exit(1)

    if os.path.exists(证书路径) and os.path.exists(私钥路径):
        print(f"证书已存在，跳过生成：{证书路径}")
        return

    print(f"为这些地址生成证书：{', '.join(IP们)}")
    私钥 = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    主题 = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Personal Knowledge Base"),
        x509.NameAttribute(NameOID.COMMON_NAME, IP们[0]),
    ])

    备用名 = []
    for 地址 in IP们:
        try:
            备用名.append(x509.IPAddress(ipaddress.ip_address(地址)))
        except ValueError:
            备用名.append(x509.DNSName(地址))

    现在 = datetime.datetime.now(datetime.timezone.utc)
    证书 = (
        x509.CertificateBuilder()
        .subject_name(主题)
        .issuer_name(主题)
        .public_key(私钥.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(现在 - datetime.timedelta(days=1))
        .not_valid_after(现在 + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(备用名), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(私钥, hashes.SHA256())
    )

    os.makedirs(服务器目录, exist_ok=True)
    with open(私钥路径, "wb") as f:
        f.write(私钥.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()))
    with open(证书路径, "wb") as f:
        f.write(证书.public_bytes(serialization.Encoding.PEM))

    # 同时导出一份可以被手机"安装为受信任证书"的 .crt（内容与 cert.pem 相同）
    with open(os.path.join(服务器目录, "手机安装这个证书.crt"), "wb") as f:
        f.write(证书.public_bytes(serialization.Encoding.PEM))

    print(f"√ 已生成：{证书路径}")
    print(f"√ 已生成：{私钥路径}")
    print("√ 已生成：手机安装这个证书.crt（可选：装到手机上，浏览器就不再提示不安全）")


if __name__ == "__main__":
    主流程()
