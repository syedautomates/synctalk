import os
import tempfile
import uuid
from typing import Any

import cv2
import mediapipe as mp

from app.db.models import MediaAsset
from app.services.storage import build_object_key, put_object_bytes

TARGET_FRAME_COUNT = 12
SAMPLE_INTERVAL_S = 0.5  # candidate pool sampling rate
MIN_FRONTAL_SYMMETRY = 0.6

_face_detector = mp.solutions.face_detection.FaceDetection(
    model_selection=1, min_detection_confidence=0.6
)


def _sharpness(image_bgr) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _frontal_symmetry(detection) -> float | None:
    """1.0 = perfectly frontal (nose centered between eyes), lower = more turned away."""
    keypoints = detection.location_data.relative_keypoints
    if len(keypoints) < 3:
        return None
    right_eye, left_eye, nose_tip = keypoints[0], keypoints[1], keypoints[2]
    eye_span = abs(right_eye.x - left_eye.x)
    if eye_span < 1e-6:
        return None
    eye_mid_x = (right_eye.x + left_eye.x) / 2
    return max(0.0, 1.0 - abs(nose_tip.x - eye_mid_x) / eye_span)


def extract_and_store_frames(
    video_bytes: bytes, profile_id: uuid.UUID
) -> tuple[list[MediaAsset], str | None]:
    """Extracts the sharpest, most frontal frames from a reference video, uploads each
    as an `extracted_frame` asset, and returns (assets, best_frame_s3_key)."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        tmp_path = tmp.name

    try:
        cap = cv2.VideoCapture(tmp_path)
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        frame_interval = max(int(round(native_fps * SAMPLE_INTERVAL_S)), 1)

        candidates: list[tuple[float, float, Any]] = []  # (sharpness, symmetry, frame)
        frame_index = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_index % frame_interval == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = _face_detector.process(rgb)
                if result.detections and len(result.detections) == 1:
                    symmetry = _frontal_symmetry(result.detections[0])
                    if symmetry is not None and symmetry >= MIN_FRONTAL_SYMMETRY:
                        candidates.append((_sharpness(frame), symmetry, frame.copy()))
            frame_index += 1
        cap.release()

        # Sharpest first among frontal-enough candidates.
        candidates.sort(key=lambda c: c[0], reverse=True)
        top = candidates[:TARGET_FRAME_COUNT]

        assets: list[MediaAsset] = []
        best_key: str | None = None
        for sharpness, symmetry, frame in top:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                continue
            s3_key = build_object_key(profile_id, "extracted_frame", "frame.jpg")
            put_object_bytes(s3_key, buf.tobytes(), "image/jpeg")
            asset = MediaAsset(
                profile_id=profile_id,
                kind="extracted_frame",
                s3_key=s3_key,
                meta={
                    "sharpness_score": round(sharpness, 2),
                    "frontal_symmetry": round(symmetry, 3),
                },
                validation="passed",
            )
            assets.append(asset)
            if best_key is None:
                best_key = s3_key  # first = sharpest among frontal candidates

        return assets, best_key
    finally:
        os.unlink(tmp_path)
