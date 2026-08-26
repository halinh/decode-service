from fastapi import FastAPI

app = FastAPI(title="decode-service")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
