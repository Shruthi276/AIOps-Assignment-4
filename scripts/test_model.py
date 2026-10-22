import time
import torch
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration

MODEL = "Salesforce/blip-image-captioning-base"

t0 = time.time()
processor = BlipProcessor.from_pretrained(MODEL)
model = BlipForConditionalGeneration.from_pretrained(MODEL)
model.eval()
print(f"Model loaded in {time.time() - t0:.1f}s")

img = Image.open("sample_data/sample.jpg").convert("RGB")
t0 = time.time()

with torch.no_grad():
    inputs = processor(images=img, return_tensors="pt")
    out = model.generate(**inputs, max_new_tokens=30)

print("Caption:", processor.decode(out[0], skip_special_tokens=True))
print(f"Inference time: {time.time() - t0:.2f}s")
