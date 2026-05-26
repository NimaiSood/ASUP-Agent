"""Interactive and CLI credential collection for ONTAP REST."""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass


@dataclass
class OntapCredentials:
    cluster_ip: str
    username: str
    password: str
    verify_ssl: bool = True

    @property
    def mgmt_host(self) -> str:
        return normalize_mgmt_host(self.cluster_ip)


def normalize_mgmt_host(cluster_ip: str) -> str:
    """Turn cluster IP/hostname into ONTAP REST base URL."""
    value = cluster_ip.strip()
    if not value:
        raise ValueError("Cluster IP/hostname is required")
    if value.startswith("http://") or value.startswith("https://"):
        return value.rstrip("/")
    return f"https://{value}"


def credentials_configured() -> bool:
    return bool(
        os.environ.get("ONTAP_MGMT_HOST")
        and os.environ.get("ONTAP_USERNAME")
        and os.environ.get("ONTAP_PASSWORD")
    )


def apply_credentials(creds: OntapCredentials) -> None:
    """Set process environment for ontap_mcp client."""
    os.environ["ONTAP_MGMT_HOST"] = creds.mgmt_host
    os.environ["ONTAP_USERNAME"] = creds.username
    os.environ["ONTAP_PASSWORD"] = creds.password
    os.environ["ONTAP_VERIFY_SSL"] = "true" if creds.verify_ssl else "false"


def prompt_credentials(
    *,
    cluster_ip: str | None = None,
    username: str | None = None,
    password: str | None = None,
    verify_ssl: bool | None = None,
) -> OntapCredentials:
    """Prompt on the command line for any missing ONTAP connection fields."""
    print("\n--- ONTAP Cluster Connection ---\n")

    ip = cluster_ip
    while not ip or not ip.strip():
        ip = input("Cluster management IP or hostname: ").strip()
        if not ip:
            print("  Cluster IP is required.")

    user = username
    while not user or not user.strip():
        user = input("Username: ").strip()
        if not user:
            print("  Username is required.")

    if password:
        pwd = password
    else:
        while True:
            pwd = getpass.getpass("Password: ")
            if pwd:
                break
            print("  Password is required.")

    if verify_ssl is None:
        ssl_answer = input("Verify TLS certificate? [Y/n]: ").strip().lower()
        verify = ssl_answer not in ("n", "no")
    else:
        verify = verify_ssl

    creds = OntapCredentials(
        cluster_ip=ip,
        username=user,
        password=pwd,
        verify_ssl=verify,
    )
    print(f"\nConnecting to {creds.mgmt_host} as {creds.username}\n")
    return creds


def resolve_credentials(
    *,
    cluster_ip: str | None = None,
    username: str | None = None,
    password: str | None = None,
    verify_ssl: bool | None = None,
    interactive: bool = True,
    use_env: bool = True,
) -> OntapCredentials | None:
    """
    Resolve credentials from CLI args, environment, and/or interactive prompts.

    Returns None when not interactive and credentials are incomplete.
    """
    if use_env and credentials_configured() and not any((cluster_ip, username, password)):
        return OntapCredentials(
            cluster_ip=os.environ["ONTAP_MGMT_HOST"],
            username=os.environ["ONTAP_USERNAME"],
            password=os.environ["ONTAP_PASSWORD"],
            verify_ssl=os.environ.get("ONTAP_VERIFY_SSL", "true").lower() == "true",
        )

    if cluster_ip and username and password:
        return OntapCredentials(
            cluster_ip=cluster_ip,
            username=username,
            password=password,
            verify_ssl=True if verify_ssl is None else verify_ssl,
        )

    if not interactive:
        return None

    return prompt_credentials(
        cluster_ip=cluster_ip,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )
