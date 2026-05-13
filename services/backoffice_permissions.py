from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from utils.helpers import json_loads


GLOBAL_SCOPE = "global"
COMPANY_SCOPE = "company"
SUPER_ADMIN_ROLE = "super_admin"
LEGACY_ADMIN_ROLE = "admin"
COMPANY_ADMIN_ROLE = "company_admin"


@dataclass(frozen=True)
class BackofficeAccess:
    role: str
    scope_type: str
    company_ids: frozenset[str]

    @property
    def is_global(self) -> bool:
        return self.scope_type == GLOBAL_SCOPE


def _split_company_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parsed = json_loads(value, default=None)
        if isinstance(parsed, list):
            raw_items = parsed
        else:
            raw_items = value.replace("\n", ",").replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]

    company_ids: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        company_id = str(item or "").strip()
        if not company_id:
            continue
        key = company_id.lower()
        if key in seen:
            continue
        seen.add(key)
        company_ids.append(company_id)
    return company_ids


def resolve_access(user: dict[str, Any]) -> BackofficeAccess:
    role = str(user.get("role", "") or "").strip().lower() or COMPANY_ADMIN_ROLE
    company_ids = _split_company_ids(user.get("company_ids"))
    single_company_id = str(user.get("company_id", "") or "").strip()
    if single_company_id:
        company_ids = _split_company_ids([*company_ids, single_company_id])

    raw_scope_type = str(user.get("scope_type", "") or "").strip().lower()
    if role == SUPER_ADMIN_ROLE or raw_scope_type == GLOBAL_SCOPE:
        scope_type = GLOBAL_SCOPE
    elif role == LEGACY_ADMIN_ROLE and not company_ids and raw_scope_type != COMPANY_SCOPE:
        scope_type = GLOBAL_SCOPE
    else:
        scope_type = COMPANY_SCOPE

    return BackofficeAccess(
        role=role,
        scope_type=scope_type,
        company_ids=frozenset(company_ids),
    )


def serialize_access(user: dict[str, Any]) -> dict[str, Any]:
    access = resolve_access(user)
    return {
        "scope_type": access.scope_type,
        "company_ids": sorted(access.company_ids),
    }


def can_access_company(user: dict[str, Any], company_id: Any) -> bool:
    access = resolve_access(user)
    if access.is_global:
        return True
    normalized = str(company_id or "").strip().lower()
    if not normalized:
        return False
    return normalized in {item.lower() for item in access.company_ids}


def filter_by_access(
    user: dict[str, Any],
    items: Iterable[dict[str, Any]],
    company_id_getter: Callable[[dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    if resolve_access(user).is_global:
        return list(items)
    return [item for item in items if can_access_company(user, company_id_getter(item))]
