import runpod
import json
import base64
import requests
import time
import subprocess
import os
import gc
import random
from PIL import Image
import io

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
    system_prompt = (
        "You are an expert AI image prompt engineer. Combine the user's base prompt and the requested art style "
        "into a single, cohesive, highly-detailed comma-separated prompt for Stable Diffusion XL.\n"
        "IMPORTANT RULES:\n"
        "1. DO NOT write instructions like 'Turn this into', 'Modify this', 'Change this', 'Make this', 'Create a', or 'Apply style'. "
        "Stable Diffusion does not understand commands; it only understands visual descriptions. "
        "Describe the final scene visually using comma-separated descriptive keywords, artistic styles, and rich adjectives.\n"
        "2. Do not include introductory text, conversational text, prefixes, or explanations (e.g., do not say 'Here is the combined prompt:').\n"
        "3. Output ONLY the final descriptive prompt text itself, starting directly with the visual description."
    )
    
    # Few-shot prompt sequence to prime Llama-3 to follow formatting perfectly
    prompt = (
        f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|>"
        # Example 1
        f"<|start_header_id|>user<|end_header_id|>\n\nBase Prompt: A futuristic cityscape of sleek skyscrapers and neon-lit buildings\nStyle: cartoon<|eot_id|>"
        f"<|start_header_id|>assistant<|end_header_id|>\n\nA futuristic cityscape of sleek skyscrapers and neon-lit buildings floating amidst a sea of clouds, vibrant colors, whimsical cartoon style, smooth cell shading, 2D vector art, highly detailed textures, playful perspective, high contrast, clean lines, professional digital artwork.<|eot_id|>"
        # Example 2
        f"<|start_header_id|>user<|end_header_id|>\n\nBase Prompt: A cute cat sitting on a comfy chair\nStyle: realistic<|eot_id|>"
        f"<|start_header_id|>assistant<|end_header_id|>\n\nA highly detailed and realistic cute domestic cat sitting on a plush comfy velvet armchair, photorealistic rendering, soft cinematic lighting, intricate fur texture, 8k resolution, crisp focus, lifelike eyes, cozy interior setting, premium quality photograph.<|eot_id|>"
        # Example 3
        f"<|start_header_id|>user<|end_header_id|>\n\nBase Prompt: A sports car on a winding mountain road\nStyle: pencil sketch<|eot_id|>"
        f"<|start_header_id|>assistant<|end_header_id|>\n\nA detailed pencil drawing of a modern sports car on a winding mountain road, fine graphite lines, hand-drawn sketch style, realistic shading, cross-hatching textures, monochrome art, elegant paper texture, artistic and classic look.<|eot_id|>"
        # Actual User Query
        f"<|start_header_id|>user<|end_header_id|>\n\nBase Prompt: {raw_prompt}\nStyle: {art_style}<|eot_id|>"
        f"<|start_header_id|>assistant<|end_header_id|>\n\n"
    )
    
    response = llm(prompt, max_tokens=150, temperature=0.5, stop=["<|eot_id|>"])
    fused = response['choices'][0]['text'].strip()
    
    # --- Robust Python Cleaning of LLM Response ---
    prefixes_to_strip = [
        "here is the combined prompt:",
        "here is the prompt:",
        "combined prompt:",
        "here is the descriptive prompt:",
        "descriptive prompt:",
        "sure! here is the prompt:",
        "sure, here is the prompt:",
        "here's the combined prompt:",
        "here's the prompt:",
        "here is a combined prompt:",
        "here's a combined prompt:"
    ]
    
    # Strip quotes if the LLM wrapped the entire prompt in quotes
    if fused.startswith('"') and fused.endswith('"'):
        fused = fused[1:-1].strip()
    if fused.startswith("'") and fused.endswith("'"):
        fused = fused[1:-1].strip()
        
    # Split by newline and robustly filter out conversational lines
    lines = [line.strip() for line in fused.split("\n") if line.strip()]
    cleaned_lines = []
    for line in lines:
        line_lower = line.lower()
        # Skip purely conversational header lines
        if any(line_lower.startswith(p) for p in prefixes_to_strip) or \
           line_lower.startswith("here is") or \
           line_lower.startswith("sure, ") or \
           line_lower.startswith("this prompt") or \
           line_lower.startswith("combined prompt"):
            continue
        cleaned_lines.append(line)
        
    # Re-join valid visual descriptive lines with a comma and space
    fused = ", ".join(cleaned_lines).strip()
    
    # Strip quotes again in case they were inside lines
    if fused.startswith('"') and fused.endswith('"'):
        fused = fused[1:-1].strip()
        
    # Strip instructional phrases if they somehow sneaked through
    instructional_phrases = [
        "turn this into a", "turn this into",
        "make this a", "make this",
        "change this to a", "change this to",
        "create a", "modify this to"
    ]
    lower_fused = fused.lower()
    for phrase in instructional_phrases:
        if lower_fused.startswith(phrase):
            fused = fused[len(phrase):].strip()
            # Capitalize first letter of remaining string
            if fused:
                fused = fused[0].upper() + fused[1:]
            lower_fused = fused.lower()
            
    print(f"Fused and cleaned prompt: {fused}")
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
            
            # Decode base64 bytes
            decoded_bytes = base64.b64decode(img_data)
            
            # Open with PIL, convert to RGB, and resize to 1024x1024 (SDXL native resolution)
            img = Image.open(io.BytesIO(decoded_bytes)).convert("RGB")
            img_resized = img.resize((1024, 1024), Image.Resampling.LANCZOS)
            
            # Save the resized image as PNG
            img_resized.save("/comfyui/input/input_img.png", "PNG")
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
                # Check meta title or just assume it's the positive prompt if we haven't found it
                if "_meta" in node and "Positive" in node.get("_meta", {}).get("title", ""):
                    node["inputs"]["text"] = fused_prompt
                elif "text" in node["inputs"] and "negative" not in str(node).lower():
                    # Fallback if _meta is missing
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
