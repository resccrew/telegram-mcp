"""Minimal Result type: functions return Ok(value) or Err(message) instead of raising."""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T


@dataclass(frozen=True)
class Err:
    error: str


type Result[T] = Ok[T] | Err
