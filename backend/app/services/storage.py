"""Almacenamiento de objetos compatible con S3. Si no está configurado, falla de forma explícita."""
import uuid
from app.core.config import settings


class StorageNotConfigured(Exception):
    pass


class InvalidUpload(Exception):
    pass


_MAGIC = [(b"\xff\xd8\xff", "image/jpeg", "jpg"), (b"\x89PNG\r\n\x1a\n", "image/png", "png")]


def sniff_image(data: bytes) -> tuple[str, str]:
    """Determina el tipo por el contenido real (no por el nombre ni el Content-Type enviado)."""
    for sig, mime, ext in _MAGIC:
        if data.startswith(sig):
            return mime, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise InvalidUpload("Formato no permitido. Usa JPG, PNG o WEBP")


def configured() -> bool:
    return bool(settings.s3_bucket and settings.s3_access_key and settings.s3_secret_key and settings.s3_public_base_url)


def _client():
    import boto3
    return boto3.client("s3", endpoint_url=settings.s3_endpoint or None, region_name=settings.s3_region,
                        aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key)


def put_image(prefix: str, data: bytes, private: bool = False) -> dict:
    if not configured():
        raise StorageNotConfigured("El almacenamiento de imágenes no está configurado (variables S3_*)")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise InvalidUpload(f"La imagen supera {settings.max_upload_mb} MB")
    mime, ext = sniff_image(data)
    key = f"{prefix}/{uuid.uuid4().hex}.{ext}"
    extra = {} if private else {"CacheControl": "public, max-age=31536000, immutable"}
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=mime, **extra)
    url = None if private else f"{settings.s3_public_base_url.rstrip('/')}/{key}"
    return {"key": key, "url": url, "mime": mime, "size": len(data)}


def presigned_url(key: str, seconds: int = 300) -> str | None:
    """URL temporal para ver un comprobante privado (no se guarda ni se comparte)."""
    if not configured():
        return None
    return _client().generate_presigned_url("get_object", Params={"Bucket": settings.s3_bucket, "Key": key},
                                            ExpiresIn=seconds)


def delete_object(key: str) -> None:
    if configured():
        _client().delete_object(Bucket=settings.s3_bucket, Key=key)
