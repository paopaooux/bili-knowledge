from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class InspectRequest(BaseModel):
    url: HttpUrl


class CreateJobRequest(BaseModel):
    video_id: str
    part_ids: list[str] = Field(min_length=1)
    profile_id: str | None = None
    draft_policy: Literal["reuse", "regenerate"] = "reuse"


class RetryRequest(BaseModel):
    stage: Literal["parse", "acquire", "transcribe", "generate", "organize", "publish"]
    part_id: str | None = None


class SettingsTestRequest(BaseModel):
    service: Literal["stt", "llm"]


class KnowledgeProfileTopicRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    path: str | None = Field(default=None, max_length=300)


class KnowledgeProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mode: Literal["open", "guided", "strict"] = "open"
    scope: str = Field(default="", max_length=2000)
    preferred_topics: list[KnowledgeProfileTopicRequest] = Field(
        default_factory=list, max_length=50
    )


class TopicSuggestionRequest(BaseModel):
    profile_id: str
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
