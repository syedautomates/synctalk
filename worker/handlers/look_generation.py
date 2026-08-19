"""Look generation via Qwen-Image-Edit-2511.

Pipeline usage (class, dtype, generation kwargs) verified against the live HF model card
at M3 build time (2026-08-19) per claude.md §2's "never invent API parameters" rule — see
DECISIONS.md's M3 entry. Do not tweak these kwargs without re-checking the card, since an
alpha-stage model's recommended defaults can shift between cards.
"""
import io

import requests
import torch
from PIL import Image

PROMPT_TEMPLATE = (
    "Photorealistic portrait of the same person as in the reference image, "
    "identity and face unchanged, {user_prompt}, upper-body framing suitable for a "
    "talking-head video, subject facing camera, sharp focus, natural lighting"
)

# Different seeds per candidate, per claude.md M3 ("4 candidates (different seeds)") —
# not num_images_per_prompt=4, which doesn't guarantee seed diversity. Fixed fallback
# seeds (only used if the job payload doesn't supply its own — e.g. an old/manual test
# job): a real reroll must send fresh random seeds via the payload, since fixed seeds
# against the same reference image + prompt regenerate byte-identical candidates,
# defeating M3's "reroll re-queues with new seeds" mitigation.
DEFAULT_SEEDS = [0, 1, 2, 3]

# Both the 2509 and 2511 model cards note "optimal performance ... with 1 to 3 input
# images" — capped here even though the API can hand us up to 4 (primary + garment + 2
# extra photos) so we stay in the documented-good range.
MAX_INPUT_IMAGES = 3

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from diffusers import QwenImageEditPlusPipeline

        _pipeline = QwenImageEditPlusPipeline.from_pretrained(
            "Qwen/Qwen-Image-Edit-2511", torch_dtype=torch.bfloat16
        )
        _pipeline.to("cuda")
        _pipeline.set_progress_bar_config(disable=None)
    return _pipeline


def _download_image(url: str) -> Image.Image:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def run(job: dict, ctx) -> dict:
    payload = job["payload"]
    user_prompt = payload["prompt"]
    output_prefix = payload["output_prefix"]

    images = [_download_image(payload["reference_image_url"])]
    if payload.get("garment_image_url"):
        images.append(_download_image(payload["garment_image_url"]))
    for url in payload.get("extra_reference_image_urls", []):
        if len(images) >= MAX_INPUT_IMAGES:
            break
        images.append(_download_image(url))

    full_prompt = PROMPT_TEMPLATE.format(user_prompt=user_prompt)
    pipeline = _get_pipeline()
    seeds = payload.get("seeds") or DEFAULT_SEEDS

    candidate_keys = []
    for i, seed in enumerate(seeds):
        generator = torch.manual_seed(seed)
        with torch.inference_mode():
            output = pipeline(
                image=images,
                prompt=full_prompt,
                generator=generator,
                true_cfg_scale=4.0,
                negative_prompt=" ",
                num_inference_steps=40,
                guidance_scale=1.0,
                num_images_per_prompt=1,
            )
        candidate_image = output.images[0]
        buf = io.BytesIO()
        candidate_image.save(buf, format="PNG")
        s3_key = ctx.upload_output(
            output_prefix, f"candidate_{i}.png", buf.getvalue(), "image/png"
        )
        candidate_keys.append(s3_key)
        ctx.report_progress(int((i + 1) / len(seeds) * 100))

    return {"candidate_keys": candidate_keys}
