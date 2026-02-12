from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Source:
    id: int
    name: str
    feed_url: str
    polling_interval_minutes: int
    status: str
    trust_score: int
    created_at: datetime
    updated_at: datetime


@dataclass
class Article:
    id: int
    source_id: int
    title: str
    summary: str
    original_url: str
    normalized_url: str
    title_hash: str
    published_at: Optional[datetime]
    fetched_at: datetime
    language: str
