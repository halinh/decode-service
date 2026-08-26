import os

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

JWT_DEV_SECRET = os.environ["JWT_DEV_SECRET"]

app = FastAPI(title="decode-service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DecodeRequest(BaseModel):
    id_token: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/decode")
def decode_token(payload: DecodeRequest) -> dict:
    try:
        claims = jwt.decode(payload.id_token, JWT_DEV_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return claims
