# pip install replicate fastapi uvicorn python-multipart

import replicate
import base64
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse
import httpx
import io

app = FastAPI()

# Replicate API key chahiye — replicate.com pe free account banao
# Environment variable mein daalo: REPLICATE_API_TOKEN=r8_xxxx

@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    contents = await file.read()
    
    # Base64 encode karo image ko
    b64 = base64.b64encode(contents).decode()
    data_uri = f"data:image/jpeg;base64,{b64}"
    
    output = replicate.run(
        "stability-ai/stable-diffusion-inpainting:latest",
        input={
            "image": data_uri,
            "prompt": "realistic human skin, photographic, high quality",
            "negative_prompt": "clothes, fabric, blur, artifacts, deformed",
            "num_inference_steps": 50,
            "guidance_scale": 7.5,
        }
    )
    
    # Output URL se image download karo
    async with httpx.AsyncClient() as client:
        resp = await client.get(output[0])
    
    return StreamingResponse(
        io.BytesIO(resp.content),
        media_type="image/png"
    )