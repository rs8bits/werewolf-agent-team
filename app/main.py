from fastapi import FastAPI

app = FastAPI(title="Werewolf Agent Team")


@app.get("/health")
def health():
    return {"status": "ok"}
