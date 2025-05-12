# scripts/cache_utils.py
"""
메모리 기반 캐싱 유틸리티

캐시 유효 시간:
- 메타데이터: 1시간 (거의 변경되지 않음)
- 예보 데이터: 15분 (정기적으로 업데이트)
- 현재 상태: 10분 (자주 조회됨)

기대 효과: Firestore 읽기 비용 80-90% 절감
"""

import time
import json
from typing import Any, Optional, Dict
from datetime import datetime, timedelta

# 캐시 저장소 (메모리)
_cache: Dict[str, Dict[str, Any]] = {}

# 캐시 유효 시간 설정 (초 단위)
CACHE_TTL = {
    "metadata": 3600,      # 1시간 (메타데이터는 거의 변경되지 않음)
    "forecast": 900,       # 15분 (예보 데이터는 정기적으로 업데이트)
    "current": 600,        # 10분 (현재 상태는 자주 조회됨)
    "beaches": 3600,       # 1시간 (해변 목록은 거의 변경되지 않음)
    "regions": 3600,       # 1시간 (지역 목록은 거의 변경되지 않음)
}


def _make_key(category: str, *args) -> str:
    """
    캐시 키 생성
    예: "metadata:busan:4001", "forecast:jeju:3001:24"
    """
    parts = [category] + [str(arg) for arg in args]
    return ":".join(parts)


def get(category: str, *args) -> Optional[Any]:
    """
    캐시에서 데이터 조회

    Args:
        category: 캐시 카테고리 (metadata, forecast, current, beaches, regions)
        *args: 키를 구성할 추가 인자들

    Returns:
        캐시된 데이터 또는 None (캐시 미스 또는 만료)
    """
    key = _make_key(category, *args)

    if key not in _cache:
        return None

    cache_entry = _cache[key]
    expires_at = cache_entry.get("expires_at", 0)

    # 만료 확인
    if time.time() > expires_at:
        # 만료된 항목 삭제
        del _cache[key]
        return None

    return cache_entry.get("data")


def set(category: str, *args, data: Any) -> None:
    """
    캐시에 데이터 저장

    Args:
        category: 캐시 카테고리
        *args: 키를 구성할 추가 인자들
        data: 저장할 데이터
    """
    key = _make_key(category, *args)
    ttl = CACHE_TTL.get(category, 600)  # 기본 10분

    _cache[key] = {
        "data": data,
        "expires_at": time.time() + ttl,
        "created_at": time.time()
    }


def invalidate(category: str, *args) -> None:
    """
    특정 캐시 항목 무효화

    Args:
        category: 캐시 카테고리
        *args: 키를 구성할 추가 인자들
    """
    key = _make_key(category, *args)

    if key in _cache:
        del _cache[key]


def invalidate_pattern(pattern: str) -> int:
    """
    패턴과 일치하는 모든 캐시 항목 무효화

    Args:
        pattern: 키 패턴 (예: "metadata:busan", "forecast:jeju")

    Returns:
        삭제된 항목 수
    """
    keys_to_delete = [key for key in _cache.keys() if key.startswith(pattern)]

    for key in keys_to_delete:
        del _cache[key]

    return len(keys_to_delete)


def clear_all() -> None:
    """모든 캐시 항목 삭제"""
    _cache.clear()


def get_stats() -> Dict[str, Any]:
    """
    캐시 통계 정보 반환

    Returns:
        캐시 항목 수, 카테고리별 분포 등
    """
    total_items = len(_cache)

    # 카테고리별 항목 수 계산
    category_counts = {}
    for key in _cache.keys():
        category = key.split(":")[0]
        category_counts[category] = category_counts.get(category, 0) + 1

    # 만료된 항목 수 계산
    now = time.time()
    expired_count = sum(1 for entry in _cache.values() if entry.get("expires_at", 0) <= now)

    return {
        "total_items": total_items,
        "active_items": total_items - expired_count,
        "expired_items": expired_count,
        "category_breakdown": category_counts,
        "cache_ttl_config": CACHE_TTL
    }


def cleanup_expired() -> int:
    """
    만료된 캐시 항목 정리

    Returns:
        삭제된 항목 수
    """
    now = time.time()
    keys_to_delete = [
        key for key, entry in _cache.items()
        if entry.get("expires_at", 0) <= now
    ]

    for key in keys_to_delete:
        del _cache[key]

    return len(keys_to_delete)


# 데코레이터를 사용한 캐싱 (선택적)
def cached(category: str, ttl: Optional[int] = None):
    """
    함수 결과를 캐싱하는 데코레이터

    Args:
        category: 캐시 카테고리
        ttl: 캐시 유효 시간 (초), None이면 카테고리 기본값 사용

    사용 예:
        @cached("metadata", ttl=3600)
        def get_beach_metadata(region, beach_id):
            # ... Firestore 조회
            return metadata
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # 캐시 키 생성 (함수 인자 기반)
            cache_key_args = args + tuple(sorted(kwargs.items()))

            # 캐시 조회
            cached_data = get(category, *cache_key_args)
            if cached_data is not None:
                return cached_data

            # 캐시 미스 - 실제 함수 실행
            result = func(*args, **kwargs)

            # 결과 캐싱
            set(category, *cache_key_args, data=result)

            return result

        return wrapper
    return decorator
