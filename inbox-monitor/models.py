from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class Message(BaseModel):
    thread_id: str
    user_id: str
    username: str
    text: str
    timestamp: datetime
    item_id: str


class InboxCheckResult(BaseModel):
    persona_id: int
    account_username: str
    new_messages: List[Message]
    check_time: datetime
    success: bool
    error: Optional[str] = None

