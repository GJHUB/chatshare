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
    title: Optional[str] = "新对话"
    model: Optional[str] = "gpt-4o"


class ConversationUpdate(BaseModel):
    title: Optional[str] = None


class MessageSend(BaseModel):
    content: str
    model: str = "gpt-4o"
