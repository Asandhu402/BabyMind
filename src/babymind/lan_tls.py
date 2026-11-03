"""Short-lived HTTPS certificates for BabyMind's trusted LAN mode."""
from __future__ import annotations

import ipaddress
import os
import ssl
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .secure_store import SecureTextStore


def _subject(common_name: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BabyMind Local"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])


def _load_or_create_ca(cert_dir: Path) -> tuple[x509.Certificate, object]:
    cert_path = cert_dir / "lan-ca.crt"
    sealed_key_path = cert_dir / "lan-ca-private.pem.enc"
    protector = SecureTextStore(cert_dir / "lan-ca-seal.key")

    if cert_path.is_file() and sealed_key_path.is_file():
        certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
        private_pem = protector.decrypt(sealed_key_path.read_text(encoding="ascii"))
        private_key = serialization.load_pem_private_key(
            private_pem.encode("ascii"), password=None
        )
        if certificate.public_key().public_numbers() != private_key.public_key().public_numbers():
            raise RuntimeError("BabyMind's local LAN certificate and private key do not match.")
        return certificate, private_key

    if sealed_key_path.is_file():
        private_pem = protector.decrypt(sealed_key_path.read_text(encoding="ascii"))
        private_key = serialization.load_pem_private_key(
            private_pem.encode("ascii"), password=None
        )
    else:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        sealed_key_path.write_text(protector.encrypt(private_pem), encoding="ascii")
        try:
            os.chmod(sealed_key_path, 0o600)
        except OSError:
            pass

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    subject = _subject("BabyMind Local LAN Root CA")
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return certificate, private_key


def create_lan_tls_context(data_home: str | Path, lan_ip: str) -> tuple[ssl.SSLContext, Path]:
    """Return a TLS server context and the public CA certificate to trust on clients."""
    address = ipaddress.ip_address(lan_ip)
    cert_dir = Path(data_home) / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_cert, ca_key = _load_or_create_ca(cert_dir)

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(_subject("BabyMind LAN Server"))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(address),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    pem = (
        server_cert.public_bytes(serialization.Encoding.PEM)
        + server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".pem", prefix="babymind-tls-", delete=False
        ) as temporary:
            temporary.write(pem)
            temporary.flush()
            temporary_path = temporary.name
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(temporary_path)
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass

    return context, cert_dir / "lan-ca.crt"
