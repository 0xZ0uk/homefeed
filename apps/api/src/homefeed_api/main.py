from typing import Literal

from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel


def operation_id(route: APIRoute) -> str:
    """Use the handler name as the OpenAPI operation id, so the generated client reads well."""
    return route.name


app = FastAPI(title="Homefeed API", generate_unique_id_function=operation_id)


class Health(BaseModel):
    status: Literal["ok"]


@app.get("/health")
def health() -> Health:
    return Health(status="ok")
