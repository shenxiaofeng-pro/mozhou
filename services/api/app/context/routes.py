from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from app.context.models import ContextPacket, CreativeContextCompileRequest
from app.context.service import CreativeContextService
from app.repository import NotFoundError

creative_context_router = APIRouter(tags=["creative-context"])


@creative_context_router.post(
    "/api/projects/{project_id}/creative-context/packets",
    response_model=ContextPacket,
    status_code=status.HTTP_201_CREATED,
)
def compile_creative_context(
    project_id: UUID,
    body: CreativeContextCompileRequest,
    request: Request,
) -> ContextPacket:
    service: CreativeContextService = request.app.state.creative_context_service
    repository = request.app.state.repository
    try:
        workspace = repository.get_workspace(str(project_id))
        return service.compile(workspace, body)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail="作品或上下文主体不存在") from error
    except ValueError as error:
        code = str(error)
        status_code = 409 if "changed" in code or "mismatch" in code else 422
        raise HTTPException(status_code=status_code, detail=code) from error
