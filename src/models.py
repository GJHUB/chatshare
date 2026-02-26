from pydantic import BaseModel
from typing import Optional


class RegisterRequest(BaseModel):
    username: str
    password: str
    nickname: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = "gpt-4o"


class ConversationUpdate(BaseModel):
    title: str


class MessageCreate(BaseModel):
    content: str
    model: str = "gpt-4o"
    attachments: list[dict] = []
    force_new_chatshare_context: bool = False
