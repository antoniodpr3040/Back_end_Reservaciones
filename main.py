import re

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from auth_service import router as auth_router
from config import get_cors_origins
from outlook_calendar import router as outlook_router
from security import get_current_user

app = FastAPI()
origins = get_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(outlook_router)


@app.middleware("http")
async def normalize_duplicate_slashes(request: Request, call_next):
    path = request.scope.get("path", "")
    normalized_path = re.sub(r"/{2,}", "/", path or "/")

    if normalized_path != path:
        request.scope["path"] = normalized_path
        request.scope["raw_path"] = normalized_path.encode("utf-8")

    return await call_next(request)


@app.get("/")
def root():
    return {"message": "Backend funcionando"}


@app.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
