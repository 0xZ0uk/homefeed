from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Homefeed API")


class Health(BaseModel):
    status: Literal["ok"]


@app.get("/health")
def health() -> Health:
    return Health(status="ok")
