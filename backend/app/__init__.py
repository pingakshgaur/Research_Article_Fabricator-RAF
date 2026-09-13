"""RAF — Research Article Fabricator backend."""

try:  # Use the operating system's certificate store (corporate proxies, antivirus TLS inspection, Windows roots).
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - fall back to certifi's bundle
    pass
