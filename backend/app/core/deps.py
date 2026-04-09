from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Callable, Awaitable, Any
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.core.kernel import FerrymanKernel

@dataclass
class AgentDeps:
    kernel: "FerrymanKernel"
    session_id: str
    skill_name: Optional[str] = None
    emit_event_cb: Optional[Callable[..., Awaitable[None]]] = None

    async def emit_tool_event(self, run_id: str, tool_name: str, phase: str, **kwargs: Any) -> None:
        if self.emit_event_cb:
            from app.models.events import FerrymanEventEnvelope, EventNamespace, ToolActivityPayload, ToolPhase
            payload = ToolActivityPayload(
                run_id=run_id,
                tool_name=tool_name,
                phase=ToolPhase(phase),
                **kwargs
            )
            event = FerrymanEventEnvelope(
                namespace=EventNamespace.AGENT,
                event="tool_activity",
                session_id=self.session_id,
                payload=payload
            )
            await self.emit_event_cb(event)
