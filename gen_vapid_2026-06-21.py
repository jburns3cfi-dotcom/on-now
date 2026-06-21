#!/usr/bin/env python3
# gen_vapid_2026-06-21.py - generate a VAPID keypair for Web Push. Banner: 2026-06-21
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

priv = ec.generate_private_key(ec.SECP256R1())
priv_der = priv.private_numbers().private_value.to_bytes(32, "big")
pub = priv.public_key().public_bytes(
    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
pem = priv.private_bytes(serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()

print("VAPID_PUBLIC_KEY (put in the app):")
print(b64u(pub))
print()
print("VAPID_PRIVATE_KEY (GitHub secret, base64url):")
print(b64u(priv_der))
print()
print("VAPID_PRIVATE_KEY_PEM (alternative form):")
print(pem)
