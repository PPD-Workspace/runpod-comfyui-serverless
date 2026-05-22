import runpod
import json
import base64
import requests
import time
import subprocess
import os
import gc
import random

# We start ComfyUI in the background. It will load Juggernaut XL dynamically when requested.
print("Starting ComfyUI locally...")
comfy_process = subprocess.Popen(["python", "/comfyui/main.py", "--listen", "127.0.0.1", "--port", "8188"])

comfy_url = "http://127.0.0.1:8188"
print("Waiting for ComfyUI to become ready...")
while True:
    try:
        if requests.get(comfy_url).status_code == 200:
            break
    except:
        pass
    time.sleep(1)
print("ComfyUI is ready!")

LLM_PATH = "/comfyui/models/llm/llama-3-8b-instruct.Q4_K_M.gguf"

# Load LLM globally at startup to keep it warm in VRAM
print("Loading LLM into VRAM globally...")
from llama_cpp import Llama
llm = Llama(model_path=LLM_PATH, n_gpu_layers=-1, verbose=False)
print("LLM successfully preloaded and ready!")

def fuse_prompt_with_llm(raw_prompt, art_style):
    print("Using pre-loaded LLM for instant prompt fusion...")
    system_prompt = "You are an expert AI image prompt engineer. Combine the user's base prompt and the requested art style into a single, cohesive, highly-detailed comma-separated prompt for Stable Diffusion. Do not include introductory text, conversational text, or prefixes. Output ONLY the final prompt."
    user_prompt = f"Base Prompt: {raw_prompt}\nStyle: {art_style}"
    
    # Simple chat format for Llama 3
    prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{user_prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    
    response = llm(prompt, max_tokens=150, temperature=0.7, stop=["<|eot_id|>"])
    fused = response['choices'][0]['text'].strip()
    
    print(f"Fused prompt: {fused}")
    return fused


def wait_for_comfyui_image(prompt_id):
    while True:
        resp = requests.get(f"{comfy_url}/history/{prompt_id}")
        if resp.status_code == 200:
            data = resp.json()
            if prompt_id in data:
                outputs = data[prompt_id].get("outputs", {})
                for node_id, node_output in outputs.items():
                    if "images" in node_output:
                        img_info = node_output["images"][0]
                        filename = img_info["filename"]
                        subfolder = img_info.get("subfolder", "")
                        
                        img_path = os.path.join("/comfyui/output", subfolder, filename)
                        with open(img_path, "rb") as f:
                            return base64.b64encode(f.read()).decode("utf-8")
        time.sleep(1)

def handler(job):
    job_input = job['input']
    raw_prompt = job_input.get('raw_prompt', '')
    art_style = job_input.get('art_style', 'realistic')
    base_image = job_input.get('base_image', None)
    
    try:
        # 1. LLM Prompt Fusion
        fused_prompt = fuse_prompt_with_llm(raw_prompt, art_style)
        
        # 2. Select workflow
        if base_image:
            workflow_path = "/workflows/img2img.json"
            img_data = base_image
            if "," in img_data:
                img_data = img_data.split(",")[1]
            with open("/comfyui/input/input_img.png", "wb") as f:
                f.write(base64.b64decode(img_data))
        else:
            workflow_path = "/workflows/txt2img.json"
            
        with open(workflow_path, "r") as f:
            workflow = json.load(f)
            
        # 3. Inject prompt into workflow and randomize seeds
        seed = random.randint(1, 999999999999999)
        for node_id, node in workflow.items():
            if node["class_type"] == "KSampler":
                node["inputs"]["seed"] = seed
            elif node["class_type"] == "CLIPTextEncode":
                if "_meta" in node and "Positive" in node.get("_meta", {}).get("title", ""):
                    node["inputs"]["text"] = fused_prompt
                elif "text" in node["inputs"] and "negative" not in str(node).lower():
                    node["inputs"]["text"] = fused_prompt

        # 4. Queue prompt to ComfyUI
        payload = {"prompt": workflow}
        resp = requests.post(f"{comfy_url}/prompt", json=payload)
        if resp.status_code != 200:
            return {"error": f"ComfyUI Error: {resp.text}"}
            
        prompt_id = resp.json()["prompt_id"]
        
        # 5. Wait for image and return
        base64_img = wait_for_comfyui_image(prompt_id)
        
        return {
            "success": True,
            "image": f"data:image/png;base64,{base64_img}",
            "fused_prompt": fused_prompt
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

runpod.serverless.start({"handler": handler})
