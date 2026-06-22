from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from app.database import get_db
from app.models.models import Workflow, WorkflowInstance
from app.security import rate_limit
from app.workflows.engine import WorkflowEngine

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

class CreateWorkflowRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    owner_id: str = Field(..., min_length=1)
    group_id: str | None = Field(None, min_length=1)
    definition: dict | None = None
    trigger_type: str = Field("manual", pattern=r"^(manual|message|schedule)$")

class UpdateDefinitionRequest(BaseModel):
    definition: dict

@router.post("/")
async def create_workflow(req: CreateWorkflowRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, limit=20, window=60)

    workflow = Workflow(
        id=str(uuid.uuid4()),
        name=req.name,
        description=req.description,
        owner_id=req.owner_id,
        group_id=req.group_id,
        definition=req.definition or {"nodes": [], "edges": []},
        trigger_type=req.trigger_type,
    )
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)

    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "definition": workflow.definition,
        "trigger_type": workflow.trigger_type,
    }

@router.get("/")
async def list_workflows(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.is_active == True))
    workflows = result.scalars().all()

    return [{
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "trigger_type": w.trigger_type,
        "group_id": w.group_id,
        "created_at": str(w.created_at),
    } for w in workflows]

@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "definition": workflow.definition,
        "trigger_type": workflow.trigger_type,
        "trigger_config": workflow.trigger_config,
        "group_id": workflow.group_id,
    }

@router.put("/{workflow_id}/definition")
async def update_workflow_definition(workflow_id: str, req: UpdateDefinitionRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, limit=30, window=60)

    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow.definition = req.definition
    await db.commit()

    return {"status": "ok"}

@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, limit=10, window=60)

    # Verify workflow exists
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Execute workflow using the engine
    engine = WorkflowEngine(db)
    engine_result = await engine.run(workflow_id)

    if "error" in engine_result:
        raise HTTPException(status_code=400, detail=engine_result["error"])

    return engine_result
