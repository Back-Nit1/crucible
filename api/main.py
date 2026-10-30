from fastapi import FastAPI

app = FastAPI(title="Crucible Agent API")


@app.get("/health")
def health():
    return {"status": "ok"}
