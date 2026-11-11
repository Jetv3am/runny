"""Write/interactive endpoints: Apple Health uploads and the coach chat stream."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from coach.assistant import demo
from coach.schemas import ChatRequest, ImportRecord
from coach.services import imports

router = APIRouter()

UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _read_chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
        yield chunk


@router.post("/imports", response_model=ImportRecord, status_code=202, tags=["imports"])
async def create_import(file: UploadFile, background: BackgroundTasks) -> ImportRecord:
    """Accepts the upload and returns at once; parsing runs in the background.
    Poll GET /imports for progress."""
    try:
        record = await imports.receive_upload(file.filename or "", _read_chunks(file))
    except imports.UploadRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    background.add_task(imports.run_import, record.id)  # sync fn -> worker thread
    return record


@router.get("/imports", response_model=list[ImportRecord], tags=["imports"])
def list_imports() -> list[ImportRecord]:
    return imports.list_imports()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/chat", tags=["coach"], response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}},
                              "description": "SSE stream of {delta} events, then {done}"}})
async def chat(request: ChatRequest) -> StreamingResponse:
    question = request.messages[-1].content

    async def events() -> AsyncIterator[str]:
        async for delta in demo.stream_answer(question):
            yield _sse({"delta": delta})
        yield _sse({"done": True, "source": "demo"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
