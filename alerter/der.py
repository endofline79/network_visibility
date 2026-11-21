"""Read an X.509 notAfter without a third-party certificate library."""

from datetime import datetime, timezone


class CertParseError(ValueError):
    pass


def _tlv(data, index):
    if index >= len(data):
        raise CertParseError("Certificate is truncated")
    tag = data[index]
    index += 1
    if index >= len(data):
        raise CertParseError("Certificate is truncated")
    length = data[index]
    index += 1
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 3 or index + count > len(data):
            raise CertParseError("Certificate length is invalid")
        length = int.from_bytes(data[index:index + count], "big")
        index += count
    end = index + length
    if length < 0 or end > len(data):
        raise CertParseError("Certificate length is invalid")
    return tag, data[index:end], end


def _time(tag, raw):
    try:
        text = raw.decode("ascii")
    except UnicodeError as exc:
        raise CertParseError("Certificate time is not text") from exc
    if not text.endswith("Z"):
        raise CertParseError("Certificate time is not UTC")
    if tag == 0x17:  # UTCTime, YYMMDDHHMMSSZ
        if len(text) < 13 or not text[:12].isdigit():
            raise CertParseError("Certificate UTCTime is short")
        year = int(text[0:2])
        year += 1900 if year >= 50 else 2000
        digits = f"{year:04d}{text[2:12]}"
    elif tag == 0x18:  # GeneralizedTime
        digits = text.split("Z", 1)[0][:14]
    else:
        raise CertParseError("Certificate validity is not a time")
    if len(digits) < 14 or not digits[:14].isdigit():
        raise CertParseError("Certificate time is invalid")
    return datetime.strptime(digits[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def not_after(der):
    """Return the certificate expiry as a timezone-aware UTC datetime."""
    if not isinstance(der, (bytes, bytearray)) or len(der) < 32 or len(der) > 65536:
        raise CertParseError("Certificate size is unexpected")
    tag, certificate, _ = _tlv(der, 0)
    if tag != 0x30:
        raise CertParseError("Certificate is not a sequence")
    tag, tbs, _ = _tlv(certificate, 0)
    if tag != 0x30:
        raise CertParseError("Certificate body is not a sequence")
    index = 0
    if tbs and tbs[0] == 0xA0:
        _, _, index = _tlv(tbs, index)
    for _ in range(3):
        _, _, index = _tlv(tbs, index)
    tag, validity, _ = _tlv(tbs, index)
    if tag != 0x30:
        raise CertParseError("Certificate validity is missing")
    _, _, index = _tlv(validity, 0)
    tag, raw, _ = _tlv(validity, index)
    return _time(tag, raw)
