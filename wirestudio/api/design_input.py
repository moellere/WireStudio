"""Designs arriving over HTTP: brought to the current schema version, then
validated, with either failure a 422."""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError

from wirestudio.library import Library
from wirestudio.migrate import MigrationError, migrate
from wirestudio.model import Design


def migrate_document(design: dict, library: Library) -> dict:
    """A request's document at the current schema version, so a design from
    an older release is accepted everywhere a current one is."""
    try:
        return migrate(design, library).document
    except MigrationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def validate_document(design: dict, library: Library) -> Design:
    try:
        return Design.model_validate(migrate_document(design, library))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e
