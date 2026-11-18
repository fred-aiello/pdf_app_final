#!/usr/bin/env python3
"""Generate a TOTP MFA secret and otpauth:// URI for a PDF App user.

Usage:
    python enroll_totp.py <username>

Prints the base32 secret (to paste into .streamlit/secrets.toml as `totp_secret`)
and an otpauth:// URI / QR code to add to an authenticator app (Google
Authenticator, Authy, 1Password, etc.).
"""
import sys

import pyotp


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    username = sys.argv[1]
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="PDF App")

    print(f"username:    {username}")
    print(f"totp_secret: {secret}")
    print(f"otpauth URI: {uri}")
    print()

    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"(install 'qrcode[pil]' to render a QR code: {exc})")


if __name__ == "__main__":
    main()