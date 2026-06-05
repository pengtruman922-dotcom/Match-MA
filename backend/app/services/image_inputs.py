from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

SUPPORTED_MULTIMODAL_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
SUPPORTED_MULTIMODAL_IMAGE_TYPES = {"jpg", "jpeg", "png", "webp"}


class ImageInputError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedImageInput:
    attachment_id: str
    file_name: str
    mime_type: str
    data_url: str
    original_bytes: int
    compressed_bytes: int
    original_width: int
    original_height: int
    width: int
    height: int

    def trace_summary(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "original_bytes": self.original_bytes,
            "compressed_bytes": self.compressed_bytes,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "width": self.width,
            "height": self.height,
        }


def is_supported_multimodal_image(attachment: dict[str, Any]) -> bool:
    file_type = str(attachment.get("file_type") or "").lower()
    mime_type = str(attachment.get("mime_type") or "").split(";")[0].strip().lower()
    return (
        mime_type in SUPPORTED_MULTIMODAL_IMAGE_MIME_TYPES
        or file_type in SUPPORTED_MULTIMODAL_IMAGE_TYPES
    )


def multimodal_image_constraints(
    *,
    max_count: int,
    max_upload_bytes: int,
    max_side: int,
    target_bytes: int,
) -> dict[str, Any]:
    return {
        "supported_types": ["image/jpeg", "image/png", "image/webp"],
        "max_count_per_business_update": max_count,
        "max_upload_bytes_per_image": max_upload_bytes,
        "max_upload_mb_per_image": round(max_upload_bytes / 1024 / 1024, 2),
        "model_preprocess_max_side_px": max_side,
        "model_preprocess_target_bytes": target_bytes,
        "evidence_policy": (
            "Images are passed directly to the multimodal LLM; evidence is recorded as "
            "image attachment plus model excerpt."
        ),
    }


def prepare_image_for_multimodal(
    image_bytes: bytes,
    *,
    attachment_id: str,
    file_name: str,
    mime_type: str | None,
    max_side: int,
    jpeg_quality: int,
    target_bytes: int,
) -> PreparedImageInput:
    original_size = len(image_bytes)
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            original_width, original_height = image.size
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            output = BytesIO()
            quality = max(min(jpeg_quality, 95), 40)
            image.save(output, format="JPEG", quality=quality, optimize=True)
            data = output.getvalue()
            while len(data) > target_bytes and quality > 45:
                quality -= 10
                output = BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                data = output.getvalue()
            width, height = image.size
    except UnidentifiedImageError as exc:
        raise ImageInputError(f"Unsupported or corrupt image: {file_name}") from exc

    encoded = base64.b64encode(data).decode("ascii")
    return PreparedImageInput(
        attachment_id=attachment_id,
        file_name=file_name,
        mime_type="image/jpeg",
        data_url=f"data:image/jpeg;base64,{encoded}",
        original_bytes=original_size,
        compressed_bytes=len(data),
        original_width=original_width,
        original_height=original_height,
        width=width,
        height=height,
    )
