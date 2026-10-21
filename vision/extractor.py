"""Extracción estructurada de documentos con un modelo de visión — SCAFFOLD [C19].

    imagen → modelo de visión (structured output = schema de vision/schemas.py) → reglas de negocio
           → ¿relectura indicando qué revisar? → status "valido" | "requiere_revision"
           → guardar en store para que lo consulten las tools MCP

El documento procesado se guarda así (las tools ya lo leen con este formato):

    with store.edit(domain.id, tools_module.seed) as db:
        db["documentos"][referencia] = {"status": ..., "data": modelo.model_dump(mode="json"),
                                        "errores": [...], "vigente": bool  # solo orden médica}
"""

from __future__ import annotations


class VisionError(Exception):
    pass


async def process_document(domain, referencia: str, image: bytes, mime: str) -> dict:
    """TODO: domain.meta["documento_vision"] dice qué schema usar (vision/schemas.py → SCHEMAS).
    Tip OpenAI: client.chat.completions.parse(..., response_format=Schema) con la imagen en base64."""
    raise NotImplementedError
