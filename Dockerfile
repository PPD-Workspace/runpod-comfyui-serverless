FROM runpod/worker-comfyui:latest-base

ENV PYTHONUNBUFFERED=1
ENV HUGGINGFACE_HUB_CACHE=/comfyui/models/huggingface

RUN apt-get update && apt-get install -y wget curl cmake build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

ARG CIVITAI_TOKEN
RUN wget --no-verbose -O /comfyui/models/checkpoints/juggernautXL.safetensors \
    "https://civitai.com/api/download/models/1759168?fileId=1659952&token=${CIVITAI_TOKEN}"

RUN mkdir -p /comfyui/models/llm && \
    wget --no-verbose -O /comfyui/models/llm/llama-3-8b-instruct.Q4_K_M.gguf \
    "https://huggingface.co/bartowski/Meta-Llama-3-8B-Instruct-GGUF/resolve/main/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf"

RUN pip install --no-cache-dir llama-cpp-python requests pydantic

COPY workflows /workflows
COPY handler.py /handler.py

CMD ["python", "-u", "/handler.py"]
