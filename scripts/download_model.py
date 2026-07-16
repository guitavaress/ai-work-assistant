#!/usr/bin/env python3
"""Baixa o(s) modelo(s) GGUF para ~/.ai-work-assistant/models/.

Usa só a biblioteca padrão para funcionar antes de qualquer `pip install`.

    python3 scripts/download_model.py             # Qwen3.5 4B Q4_K_M (padrão, ~2.7GB)
    python3 scripts/download_model.py --quality   # Qwen3.5 9B Q4_K_M (~5.7GB)
"""

import argparse
import os
import sys
import urllib.request
from pathlib import Path

MODELS = {
    "default": (
        "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf",
        "Qwen3.5-4B-Q4_K_M.gguf",
    ),
    "quality": (
        "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf",
        "Qwen3.5-9B-Q4_K_M.gguf",
    ),
}

MODELS_DIR = Path(os.environ.get("WA_MODELS_DIR", Path.home() / ".ai-work-assistant" / "models"))


def download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"Já existe: {dest}")
        return
    print(f"Baixando {url}\n     para {dest}")
    tmp = dest.with_suffix(".part")

    def progress(blocks: int, block_size: int, total: int) -> None:
        done = blocks * block_size
        pct = min(100, done * 100 // total) if total > 0 else 0
        sys.stdout.write(f"\r  {pct:3d}% ({done / 1e9:.2f} GB)")
        sys.stdout.flush()

    urllib.request.urlretrieve(url, tmp, reporthook=progress)
    tmp.rename(dest)
    print("\nConcluído.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quality", action="store_true", help="Baixa também o Qwen3.5 9B (modo qualidade)"
    )
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    url, name = MODELS["default"]
    download(url, MODELS_DIR / name)
    if args.quality:
        url, name = MODELS["quality"]
        download(url, MODELS_DIR / name)


if __name__ == "__main__":
    main()
