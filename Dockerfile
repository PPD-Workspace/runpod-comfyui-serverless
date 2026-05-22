# Base Image for RunPod Serverless (Includes ComfyUI pre-installed)
FROM runpod/worker-comfyui:latest-base

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV HUGGINGFACE_HUB_CACHE=/comfyui/models/huggingface

# Install required system packages and clean up apt cache immediately
RUN apt-get update && apt-get install -y wget curl cmake build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Download Juggernaut XL Base Model into ComfyUI Checkpoints directory
RUN wget --no-verbose -O /comfyui/models/checkpoints/juggernautXL.safetensors \
    "https://civitai.com/api/download/models/288012"

# Download Llama 3 8B Quantized GGUF (smaller Q4 quantization to save space)
RUN mkdir -p /comfyui/models/llm && \
    wget --no-verbose -O /comfyui/models/llm/llama-3-8b-instruct.Q4_K_M.gguf \
    "https://huggingface.co/bartowski/Meta-Llama-3-8B-Instruct-GGUF/resolve/main/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf"

# Install python dependencies for our custom LLM routing
RUN pip install --no-cache-dir llama-cpp-python requests pydantic

# Copy our custom workflows and handler
COPY workflows /workflows
COPY handler.py /handler.py

# Start the RunPod serverless worker using our custom handler
CMD ["python", "-u", "/handler.py"]
