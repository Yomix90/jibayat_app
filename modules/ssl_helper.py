# -*- coding: utf-8 -*-
"""
Module de gestion SSL / HTTPS pour Jibayat.
Génère et maintient un certificat SSL persistant avec SAN (Subject Alternative Names)
pour localhost, jibayat.local, jibayat et l'adresse IP locale.
"""

import datetime
import ipaddress
import logging
import os
import ssl

logger = logging.getLogger('jibayat.ssl')

SSL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ssl')
CERT_FILE = os.path.join(SSL_DIR, 'cert.pem')
KEY_FILE = os.path.join(SSL_DIR, 'key.pem')


def get_or_create_ssl_files(hostname="jibayat", local_ip=None):
    """
    Vérifie l'existence d'un certificat SSL ou en génère un nouveau
    valide 10 ans avec les noms de domaine locaux.
    Retourne le tuple (cert_path, key_path).
    """
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return CERT_FILE, KEY_FILE

    os.makedirs(SSL_DIR, exist_ok=True)

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        logger.info("Génération du certificat SSL persistant pour HTTPS...")

        # Clé privée RSA 2048 bits
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # Sujet et émetteur
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "MA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Jibayat Application Fiscale"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{hostname.lower()}.local"),
        ])

        # Noms alternatifs du sujet (SAN)
        san_list = [
            x509.DNSName("localhost"),
            x509.DNSName(hostname.lower()),
            x509.DNSName(f"{hostname.lower()}.local"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]

        if local_ip and local_ip not in ("127.0.0.1", "localhost"):
            try:
                san_list.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
            except Exception:
                pass

        # Certificat valide 10 ans
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .sign(key, hashes.SHA256())
        )

        # Sauvegarde de la clé privée
        with open(KEY_FILE, "wb") as f:
            f.write(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        # Sauvegarde du certificat public
        with open(CERT_FILE, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.info(f"Certificat SSL généré avec succès dans : {SSL_DIR}")
        return CERT_FILE, KEY_FILE

    except Exception as e:
        logger.error(f"Erreur lors de la génération du certificat SSL : {e}")
        return None, None
