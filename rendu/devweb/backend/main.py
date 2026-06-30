"""
TechCorp AI Chat — Backend Proxy
=================================

Couche d'abstraction entre l'interface web et le serveur d'inférence choisi
par l'équipe INFRA (Ollama, Triton, ou un serveur maison).

Pourquoi un proxy plutôt qu'un appel direct depuis le navigateur ?
- Évite les soucis de CORS avec Ollama/Triton.
- Permet à DEV WEB de coder contre UNE seule API stable, peu importe le
  choix final de l'équipe INFRA (un seul fichier .env à changer).
- Centralise le streaming token-par-token vers le frontend (Server-Sent
  friendly, simple à consommer en JS).

Lancer :
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8080

Variables d'environnement (voir .env.example) :
    INFERENCE_BACKEND = ollama | triton | custom
    INFERENCE_URL      = URL de base du serveur d'inférence
    MODEL_NAME          = nom du modèle à interroger
"""

import json
import os
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "ollama").lower()
INFERENCE_URL = os.getenv("INFERENCE_URL", "http://localhost:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "phi3.5-financial")
SYSTEM_PROMPT_DEFAULT = os.getenv(
    "SYSTEM_PROMPT",
    "Tu es l'assistant financier de TechCorp Industries. Tu réponds de "
    "manière claire, professionnelle et concise aux questions de finance "
    "et de business.",
)

app = FastAPI(title="TechCorp AI Chat Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float = 0.4


# --------------------------------------------------------------------------
# Adapters: un par type de serveur d'inférence
# --------------------------------------------------------------------------

async def stream_ollama(req: ChatRequest) -> AsyncGenerator[str, None]:
    """Adapter pour Ollama (/api/chat), streaming JSON-lines."""
    payload = {
        "model": req.model or MODEL_NAME,
        "messages": [m.model_dump() for m in req.messages],
        "stream": True,
        "options": {"temperature": req.temperature},
    }
    url = f"{INFERENCE_URL.rstrip('/')}/api/chat"
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise HTTPException(resp.status_code, body.decode(errors="ignore"))
            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
                if chunk.get("done"):
                    yield "data: [DONE]\n\n"


async def stream_triton(req: ChatRequest) -> AsyncGenerator[str, None]:
    """Adapter pour Triton Inference Server (backend Python, generate_stream).

    NOTE: à adapter selon le nom exact du endpoint exposé par le modèle
    Triton de l'équipe INFRA (souvent /v2/models/<model>/generate_stream).
    """
    prompt = "\n".join(f"{m.role}: {m.content}" for m in req.messages)
    payload = {
        "text_input": prompt,
        "parameters": {"temperature": req.temperature, "stream": True},
    }
    model = req.model or MODEL_NAME
    url = f"{INFERENCE_URL.rstrip('/')}/v2/models/{model}/generate_stream"
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise HTTPException(resp.status_code, body.decode(errors="ignore"))
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if raw in ("", "[DONE]"):
                    continue
                chunk = json.loads(raw)
                token = chunk.get("text_output", "")
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
    yield "data: [DONE]\n\n"


async def stream_custom(req: ChatRequest) -> AsyncGenerator[str, None]:
    """Adapter générique pour un serveur maison exposant un endpoint
    compatible OpenAI (POST /v1/chat/completions, stream=True)."""
    payload = {
        "model": req.model or MODEL_NAME,
        "messages": [m.model_dump() for m in req.messages],
        "temperature": req.temperature,
        "stream": True,
    }
    url = f"{INFERENCE_URL.rstrip('/')}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise HTTPException(resp.status_code, body.decode(errors="ignore"))
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if raw == "[DONE]":
                    yield "data: [DONE]\n\n"
                    continue
                chunk = json.loads(raw)
                token = chunk["choices"][0]["delta"].get("content", "")
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"


ADAPTERS = {
    "ollama": stream_ollama,
    "triton": stream_triton,
    "custom": stream_custom,
}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "backend": INFERENCE_BACKEND,
        "inference_url": INFERENCE_URL,
        "model": MODEL_NAME,
    }


@app.get("/api/system-prompt")
async def get_system_prompt():
    return {"system_prompt": SYSTEM_PROMPT_DEFAULT}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    adapter = ADAPTERS.get(INFERENCE_BACKEND)
    if adapter is None:
        raise HTTPException(500, f"Backend inconnu: {INFERENCE_BACKEND}")

    # Injecte le system prompt par défaut si l'utilisateur n'en a pas fourni
    if not any(m.role == "system" for m in req.messages):
        req.messages.insert(0, ChatMessage(role="system", content=SYSTEM_PROMPT_DEFAULT))

    return StreamingResponse(adapter(req), media_type="text/event-stream")


# Sert le frontend statique (index.html, style.css, app.js) sur "/"
# Adapter ce chemin selon ton organisation : ici on suppose que
# index.html / style.css / app.js sont directement dans rendu/devweb/
# (au même niveau que le dossier backend/)
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
