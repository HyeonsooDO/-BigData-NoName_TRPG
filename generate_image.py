from __future__ import annotations

from io import BytesIO
from pathlib import Path
from threading import Lock

import torch
from diffusers import StableDiffusionXLPipeline
from PIL import Image
from rembg import remove

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "catTowerNoobaiXL_chenkinnoobV10.safetensors"

DEFAULT_PROMPT = (
    "anime character, young adult, solo, normal face, front view, "
    "facing viewer, looking at viewer, waist up, upper body, "
    "centered composition, tidy appearance, simple clothing, "
    "plain light background, no text"
)

DEFAULT_NEGATIVE_PROMPT = (
    "full body, child, loli, chibi, text, logo, watermark, signature, "
    "multiple people, extra character, close-up, face close-up, "
    "cropped face, black background"
)


class IllustrationGenerator:
    def __init__(self, model_path: str | Path = MODEL_PATH):
        self.model_path = Path(model_path)
        self.pipeline: StableDiffusionXLPipeline | None = None
        self.lock = Lock()

    def load(self) -> None:
        if self.pipeline is not None:
            return
        if not self.model_path.exists():
            raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {self.model_path}")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA를 사용할 수 없습니다.")

        self.pipeline = StableDiffusionXLPipeline.from_single_file(
            str(self.model_path),
            torch_dtype=torch.float16,
            use_safetensors=True,
        )
        self.pipeline.enable_model_cpu_offload()
        self.pipeline.enable_attention_slicing()

    def generate(
        self,
        prompt: str,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        width: int = 768,
        height: int = 768,
        steps: int = 25,
        guidance_scale: float = 7.0,
        seed: int | None = None,
        remove_bg: bool = True,
    ) -> bytes:
        with self.lock:
            self.load()
            if self.pipeline is None:
                raise RuntimeError("이미지 생성 파이프라인을 불러오지 못했습니다.")

            if seed is None:
                seed = torch.seed()

            generator = torch.Generator(device="cpu").manual_seed(int(seed))

            result = self.pipeline(
                prompt=prompt.strip() or DEFAULT_PROMPT,
                negative_prompt=negative_prompt,
                width=int(width),
                height=int(height),
                num_inference_steps=int(steps),
                guidance_scale=float(guidance_scale),
                generator=generator,
            )

            image: Image.Image = result.images[0]

            if remove_bg:
                source = BytesIO()
                image.save(source, format="PNG")
                image = Image.open(BytesIO(remove(source.getvalue()))).convert("RGBA")

            output = BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
