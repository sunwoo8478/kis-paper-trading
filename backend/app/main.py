from fastapi import FastAPI

app = FastAPI(title="KIS Paper Trading API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
