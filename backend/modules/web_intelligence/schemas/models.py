"""Pydantic request/response models for the Web Intelligence API."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ReadRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    render_js: bool = False                       # force Playwright rendering
    output: str = Field("markdown", pattern="^(markdown|json|text)$")
    include_tables: bool = True
    include_links: bool = False
    include_images: bool = False
    use_cache: bool = True


class CrawlRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    max_depth: int = Field(1, ge=0, le=4)
    max_pages: int = Field(10, ge=1, le=100)
    same_site_only: bool = True
    respect_robots: bool = True
    rate_limit_seconds: float = Field(1.0, ge=0.0, le=10.0)


class IngestRequest(CrawlRequest):
    save_to_kb: bool = True
    category: str = Field("web_intelligence", max_length=80)


class Citation(BaseModel):
    source_url: str
    domain: str
    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    accessed_at: str


class ReadResult(BaseModel):
    success: bool
    url: str
    final_url: Optional[str] = None
    status: Optional[int] = None
    title: Optional[str] = None
    content_type: Optional[str] = None
    method: Optional[str] = None                   # extraction method used
    rendered: bool = False
    text: Optional[str] = None
    markdown: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    tables: list[Any] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    images: list[Any] = Field(default_factory=list)
    citation: Optional[Citation] = None
    confidence: dict = Field(default_factory=dict)
    monitoring: dict = Field(default_factory=dict)
    error: Optional[str] = None
