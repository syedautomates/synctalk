import json
import os
import subprocess
import tempfile

import cv2
import mediapipe as mp
import numpy as np

MIN_PHOTO_SHORT_SIDE = 768
PHOTO_SHARPNESS_THRESHOLD = 100.0
MIN_FACE_HEIGHT_RATIO = 0.25

VIDEO_MIN_DURATION_S = 25.0
VIDEO_MAX_DURATION_S = 75.0
VIDEO_TARGET_MIN_DURATION_S = 30.0
VIDEO_TARGET_MAX_DURATION_S = 60.0
VIDEO_MIN_SHORT_SIDE = 720
VIDEO_MIN_FPS = 24.0
VIDEO_MIN_SINGLE_FACE_RATIO = 0.90
VIDEO_MIN_HANDS_RATIO = 0.30

VOICE_MIN_DURATION_S = 30.0
VOICE_MIN_MEAN_VOLUME_DB = -40.0

_face_detector = mp.solutions.face_detection.FaceDetection(
    model_selection=1, min_detection_confidence=0.6
)
_hands_detector = mp.solutions.hands.Hands(
    static_image_mode=True, max_num_hands=2, min_detection_confidence=0.5
)


class ValidationResult:
    def __init__(self, passed: bool, errors: list[str], meta: dict):
        self.passed = passed
        self.errors = errors
        self.meta = meta


def _detect_faces(image_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Returns pixel-space (x, y, w, h) boxes for each detected face."""
    height, width = image_bgr.shape[:2]
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    result = _face_detector.process(rgb)
    boxes = []
    if result.detections:
        for detection in result.detections:
            box = detection.location_data.relative_bounding_box
            boxes.append(
                (
                    int(box.xmin * width),
                    int(box.ymin * height),
                    int(box.width * width),
                    int(box.height * height),
                )
            )
    return boxes


def _has_hands(image_bgr: np.ndarray) -> bool:
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    result = _hands_detector.process(rgb)
    return bool(result.multi_hand_landmarks)


def _sharpness(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def validate_photo(image_bytes: bytes) -> ValidationResult:
    errors: list[str] = []
    meta: dict = {}

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return ValidationResult(
            False, ["Could not read this file as an image. Please upload a JPG or PNG photo."], {}
        )

    height, width = image.shape[:2]
    meta["width"] = width
    meta["height"] = height

    if min(width, height) < MIN_PHOTO_SHORT_SIDE:
        errors.append(
            f"Photo resolution is too low ({width}x{height}). The shorter side must be "
            f"at least {MIN_PHOTO_SHORT_SIDE}px — try a less zoomed-out shot."
        )

    faces = _detect_faces(image)
    meta["face_count"] = len(faces)

    # Score sharpness on the face region when we have exactly one clean face to crop —
    # scoring the whole frame penalizes zoomed-in shots with a plain/flat background,
    # since a large low-detail area drags down the frame-wide Laplacian variance even
    # when the face itself is perfectly in focus.
    if len(faces) == 1:
        fx, fy, fw, fh = faces[0]
        fx, fy = max(fx, 0), max(fy, 0)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        face_crop = gray[fy : fy + fh, fx : fx + fw]
        sharpness = float(cv2.Laplacian(face_crop, cv2.CV_64F).var()) if face_crop.size else 0.0
    else:
        sharpness = _sharpness(image)
    meta["sharpness_score"] = round(sharpness, 2)
    if sharpness < PHOTO_SHARPNESS_THRESHOLD:
        errors.append(
            "This photo looks blurry. Retake it with better focus and lighting, "
            "and hold the camera steady."
        )

    if len(faces) == 0:
        errors.append(
            "No face detected in this photo. Make sure your face is clearly visible and well-lit."
        )
    elif len(faces) > 1:
        errors.append(
            f"Detected {len(faces)} faces in this photo. Upload a solo photo of just yourself."
        )
    else:
        _, _, _, face_h = faces[0]
        face_height_ratio = face_h / height
        meta["face_height_ratio"] = round(face_height_ratio, 3)
        if face_height_ratio < MIN_FACE_HEIGHT_RATIO:
            errors.append(
                "Your face isn't zoomed in enough. Move closer to the camera, "
                "or crop the photo tighter around your face."
            )

    return ValidationResult(len(errors) == 0, errors, meta)


def ffprobe_info(path: str) -> dict:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    duration = float(data["format"]["duration"])
    video_stream = next(
        (s for s in data["streams"] if s.get("codec_type") == "video"), None
    )
    width = height = fps = None
    rotation = 0
    if video_stream is not None:
        width = int(video_stream["width"])
        height = int(video_stream["height"])
        rate_parts = video_stream.get("r_frame_rate", "0/1").split("/")
        fps = float(rate_parts[0]) / float(rate_parts[1]) if float(rate_parts[1]) else 0.0
        rotation = extract_rotation(video_stream)
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "rotation": rotation,
    }


def extract_rotation(video_stream: dict) -> int:
    """Phones commonly store landscape sensor frames plus a rotation flag rather than
    rotating pixels — OpenCV's VideoCapture ignores that flag, so we read it ourselves
    and rotate each decoded frame back to upright before running any detection on it."""
    for side_data in video_stream.get("side_data_list", []):
        if "rotation" in side_data:
            angle = round(float(side_data["rotation"]) / 90) * 90
            return angle % 360
    legacy_tag = video_stream.get("tags", {}).get("rotate")
    if legacy_tag is not None:
        return int(legacy_tag) % 360
    return 0


def rotate_frame(frame: np.ndarray, rotation: int) -> np.ndarray:
    # ffmpeg's rotation side-data is the clockwise angle applied at capture, so we
    # undo it with the opposite turn (verified empirically against a real 90°-tagged
    # phone recording — this mapping is not just a naive assumption).
    if rotation == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if rotation in (180, -180):
        return cv2.rotate(frame, cv2.ROTATE_180)
    if rotation in (270, -90):
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    return frame


def validate_video(video_bytes: bytes) -> ValidationResult:
    errors: list[str] = []
    meta: dict = {}

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        tmp_path = tmp.name

    try:
        try:
            info = ffprobe_info(tmp_path)
        except (subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError):
            return ValidationResult(
                False,
                ["Could not read this video file. Please upload a standard MP4/MOV file."],
                {},
            )

        duration = info["duration"]
        width, height, fps, rotation = info["width"], info["height"], info["fps"], info["rotation"]
        if rotation in (90, 270, -90) and width is not None and height is not None:
            width, height = height, width  # ffprobe reports the raw sensor frame, pre-rotation
        meta.update(
            {"duration_s": round(duration, 1), "width": width, "height": height, "fps": fps}
        )

        if duration < VIDEO_MIN_DURATION_S:
            errors.append(
                f"Your video is {duration:.0f}s — "
                f"record at least {VIDEO_TARGET_MIN_DURATION_S:.0f}s."
            )
        elif duration > VIDEO_MAX_DURATION_S:
            errors.append(
                f"Your video is {duration:.0f}s — keep it under {VIDEO_TARGET_MAX_DURATION_S:.0f}s "
                f"(up to {VIDEO_MAX_DURATION_S:.0f}s is accepted)."
            )
        elif duration < VIDEO_TARGET_MIN_DURATION_S or duration > VIDEO_TARGET_MAX_DURATION_S:
            meta["duration_warning"] = (
                f"{duration:.0f}s is outside the ideal "
                f"{VIDEO_TARGET_MIN_DURATION_S:.0f}-{VIDEO_TARGET_MAX_DURATION_S:.0f}s range "
                "but was accepted."
            )

        if width is None or height is None:
            errors.append("Could not detect a video stream in this file.")
        elif min(width, height) < VIDEO_MIN_SHORT_SIDE:
            errors.append(
                f"Video resolution is too low ({width}x{height}). "
                f"Record at ≥720p (short side ≥{VIDEO_MIN_SHORT_SIDE}px)."
            )

        if fps is not None and fps < VIDEO_MIN_FPS:
            errors.append(
                f"Video frame rate is too low ({fps:.0f}fps) — record at ≥{VIDEO_MIN_FPS:.0f}fps."
            )

        # Sample ~1 frame/sec for face + hand detection.
        cap = cv2.VideoCapture(tmp_path)
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        frame_interval = max(int(round(native_fps)), 1)

        sampled = 0
        single_face_count = 0
        hands_count = 0
        frame_index = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_index % frame_interval == 0:
                sampled += 1
                frame = rotate_frame(frame, rotation)
                faces = _detect_faces(frame)
                if len(faces) == 1:
                    single_face_count += 1
                if _has_hands(frame):
                    hands_count += 1
            frame_index += 1
        cap.release()

        if sampled == 0:
            errors.append("Could not sample any frames from this video.")
        else:
            single_face_ratio = single_face_count / sampled
            hands_ratio = hands_count / sampled
            meta["single_face_ratio"] = round(single_face_ratio, 3)
            meta["hands_ratio"] = round(hands_ratio, 3)
            meta["sampled_frames"] = sampled

            if single_face_ratio < VIDEO_MIN_SINGLE_FACE_RATIO:
                errors.append(
                    "Your face wasn't consistently visible throughout the video. "
                    "Stay in frame and face the camera for the whole recording."
                )
            if hands_ratio < VIDEO_MIN_HANDS_RATIO:
                errors.append(
                    "Not enough hand movement detected. Talk with your hands visible "
                    "and gesturing naturally for at least part of the video."
                )

        return ValidationResult(len(errors) == 0, errors, meta)
    finally:
        os.unlink(tmp_path)


def validate_voice(audio_bytes: bytes, suffix: str = ".mp3") -> ValidationResult:
    errors: list[str] = []
    meta: dict = {}

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        try:
            info = ffprobe_info(tmp_path)
        except (subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError):
            return ValidationResult(
                False,
                ["Could not read this audio file. Please upload a standard MP3/WAV/M4A file."],
                {},
            )

        duration = info["duration"]
        meta["duration_s"] = round(duration, 1)
        if duration < VOICE_MIN_DURATION_S:
            errors.append(
                f"Your voice sample is {duration:.0f}s — "
                f"record at least {VOICE_MIN_DURATION_S:.0f}s of speech."
            )

        proc = subprocess.run(
            ["ffmpeg", "-i", tmp_path, "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True,
            text=True,
        )
        mean_volume = None
        for line in proc.stderr.splitlines():
            if "mean_volume:" in line:
                try:
                    mean_volume = float(line.split("mean_volume:")[1].strip().split(" ")[0])
                except (IndexError, ValueError):
                    pass
        meta["mean_volume_db"] = mean_volume

        if mean_volume is not None and mean_volume < VOICE_MIN_MEAN_VOLUME_DB:
            errors.append(
                "Audio is too quiet or near-silent. Re-record speaking at a normal volume, "
                "closer to the microphone."
            )

        return ValidationResult(len(errors) == 0, errors, meta)
    finally:
        os.unlink(tmp_path)
