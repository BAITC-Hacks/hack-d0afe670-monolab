from __future__ import annotations

from fastapi import HTTPException, UploadFile

from app.config import CV_ALLOWED_CONTENT_TYPES, CV_MAX_IMAGE_BYTES


async def read_validated_image(file: UploadFile) -> bytes:
    content_type = (file.content_type or "").lower()
    if content_type not in CV_ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid image type. Only JPEG and PNG are accepted.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty image upload.")
    if len(data) > CV_MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Image exceeds maximum size of {CV_MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )
    return data
