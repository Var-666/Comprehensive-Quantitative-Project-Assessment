"""Prepare local-only HTTPS and an encryption master key; never generates MaaS API keys."""

import argparse
import os
import subprocess
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]


def initialize(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    master = directory / "llm-master.key"
    if not master.exists():
        fd = os.open(master, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(Fernet.generate_key() + b"\n")
    master.chmod(0o600)
    cert = directory / "localhost.crt"
    key = directory / "localhost.key"
    needs_certificate = not cert.exists() or not key.exists()
    if not needs_certificate:
        info = subprocess.run(
            ["openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName"],
            capture_output=True,
            text=True,
        )
        needs_certificate = info.returncode != 0 or "DNS:backend" not in info.stdout
    if needs_certificate:
        # A development CA/server certificate only. Production must use approved TLS termination.
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-nodes",
                "-days",
                "365",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,DNS:backend,IP:127.0.0.1",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        key.chmod(0o600)
        cert.chmod(0o644)
    return master, cert, key


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / ".local-secrets")
    parser.add_argument("--no-env", action="store_true")
    args = parser.parse_args()
    master, cert, key = initialize(args.directory.resolve())
    if not args.no_env:
        env = ROOT / ".env"
        content = env.read_text() if env.exists() else ""
        if not any(
            line.strip().startswith(("LLM_ENCRYPTION_KEY=", "LLM_ENCRYPTION_KEY_FILE="))
            and line.split("=", 1)[1].strip()
            for line in content.splitlines()
        ):
            with env.open("a") as stream:
                stream.write("\nLLM_ENCRYPTION_KEY_FILE=" + str(master) + "\n")
        env.chmod(0o600)
    print("本地HTTPS证书和加密主密钥已就绪；未创建或输出任何MaaS API Key。")
