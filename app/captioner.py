# app/captioner.py - BLIP model loading and single-image captioning on CPU.
# AI-assisted (Claude); logic reviewed and understood by me.
import io
import time

import torch
from PIL import Image, ImageOps
from transformers import BlipForConditionalGeneration, BlipProcessor

MODEL_NAME = "Salesforce/blip-image-captioning-base"
MAX_SIDE = 768  # downscale big images: same caption quality, far less CPU


def load_model():
    t0 = time.perf_counter()
    processor = BlipProcessor.from_pretrained(MODEL_NAME)
    model = BlipForConditionalGeneration.from_pretrained(MODEL_NAME)
    model.eval()
    load_s = time.perf_counter() - t0
    param_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
    return processor, model, load_s, param_bytes


def caption_image(processor, model, image_bytes, max_new_tokens=30):
    t0 = time.perf_counter()
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    megapixels = img.width * img.height / 1e6
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    inputs = processor(images=img, return_tensors="pt")
    t1 = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens)
    t2 = time.perf_counter()
    return {
        "caption": processor.decode(out[0], skip_special_tokens=True),
        "preprocess_s": t1 - t0,
        "inference_s": t2 - t1,
        "tokens": int(out.shape[1]),
        "megapixels": megapixels,
    }
