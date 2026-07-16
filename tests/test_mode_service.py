"""mode_service 유닛테스트 — 실 세션(db fixture)으로 쿼리·관계·flush 를 검증한다.

핵심: update_mode_sounds/_set_sound_links 의 flush 회귀
(SQLAlchemy UoW 는 flush 때 INSERT 를 DELETE 보다 먼저 처리하므로, clear() 후 flush 없이
동일 sound_id 를 재추가하면 uq_mode_sound 위반이 난다 — 엔진 무관하게 SQLite 에서도 재현).
"""

import pytest

from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.models.sound import Sound, SoundCategory
from app.models.user import User
from app.services import mode_service

OWNER = 1
OTHER = 2


async def _seed(db) -> None:
    db.add(User(id=OWNER, email="owner@t.local", nickname="owner", terms_agreed=True))
    db.add(User(id=OTHER, email="other@t.local", nickname="other", terms_agreed=True))
    db.add(SoundCategory(id=1, name="긴급"))
    await db.flush()
    for i in range(1, 6):  # sound id 1..5
        db.add(Sound(id=i, name=f"소리{i}", category_id=1))
    await db.commit()


def _sound_ids(mode) -> set[int]:
    return {link.sound_id for link in mode.sound_links}


@pytest.mark.asyncio
async def test_create_mode_persists_links_and_inactive(db):
    await _seed(db)

    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1, 2])

    assert mode.id is not None
    assert mode.name == "외출" and mode.icon == "walk"
    assert mode.is_active is False  # 생성 직후엔 비활성
    assert _sound_ids(mode) == {1, 2}


@pytest.mark.asyncio
async def test_create_mode_requires_at_least_one_sound(db):
    await _seed(db)

    with pytest.raises(ValidationException):
        await mode_service.create_mode(db, OWNER, name="빈모드", icon="x", sound_ids=[])


@pytest.mark.asyncio
async def test_create_mode_enforces_max_per_user(db):
    await _seed(db)
    for i in range(mode_service.MAX_MODES_PER_USER):  # 6개 채움
        await mode_service.create_mode(db, OWNER, name=f"m{i}", icon="x", sound_ids=[1])

    with pytest.raises(ValidationException):
        await mode_service.create_mode(db, OWNER, name="7번째", icon="x", sound_ids=[1])


@pytest.mark.asyncio
async def test_update_mode_replaces_name_icon_sounds(db):
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1, 2])

    updated = await mode_service.update_mode(db, OWNER, mode.id, name="수면", icon="moon", sound_ids=[3])

    assert updated.name == "수면" and updated.icon == "moon"
    assert _sound_ids(updated) == {3}


@pytest.mark.asyncio
async def test_update_mode_sounds_overlapping_ids_no_conflict(db):
    """flush 회귀 가드: 겹치는 sound_id 를 유지한 채 목록을 바꿔도 uq_mode_sound 충돌이 없어야 한다.
    _set_sound_links 의 `await db.flush()` 가 빠지면 여기서 IntegrityError 가 난다."""
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1, 2])

    # 1 은 유지(재삽입), 2 제거, 3 추가 — DELETE 전에 INSERT 되면 sound_id=1 에서 충돌
    updated = await mode_service.update_mode_sounds(db, OWNER, mode.id, sound_ids=[1, 3])
    assert _sound_ids(updated) == {1, 3}

    # 완전히 동일한 집합으로 재설정 — 전부 재삽입이라 가장 가혹한 케이스
    again = await mode_service.update_mode_sounds(db, OWNER, mode.id, sound_ids=[1, 3])
    assert _sound_ids(again) == {1, 3}


@pytest.mark.asyncio
async def test_update_mode_sounds_requires_at_least_one(db):
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1])

    with pytest.raises(ValidationException):
        await mode_service.update_mode_sounds(db, OWNER, mode.id, sound_ids=[])


@pytest.mark.asyncio
async def test_activate_mode_deactivates_others(db):
    await _seed(db)
    m1 = await mode_service.create_mode(db, OWNER, name="A", icon="x", sound_ids=[1])
    m2 = await mode_service.create_mode(db, OWNER, name="B", icon="x", sound_ids=[2])

    await mode_service.activate_mode(db, OWNER, m1.id)
    active = await mode_service.activate_mode(db, OWNER, m2.id)  # 활성 전환

    assert active.id == m2.id and active.is_active is True
    m1_reloaded = await mode_service.get_mode(db, OWNER, m1.id)
    assert m1_reloaded.is_active is False  # 이전 활성 모드는 꺼짐


@pytest.mark.asyncio
async def test_set_mode_sound_active_toggles(db):
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1, 2])

    await mode_service.set_mode_sound_active(db, OWNER, mode.id, sound_id=1, is_active=False)

    reloaded = await mode_service.get_mode(db, OWNER, mode.id)
    link = next(l for l in reloaded.sound_links if l.sound_id == 1)
    assert link.is_active is False


@pytest.mark.asyncio
async def test_set_mode_sound_active_404_when_sound_not_in_mode(db):
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1])

    with pytest.raises(NotFoundException):
        await mode_service.set_mode_sound_active(db, OWNER, mode.id, sound_id=5, is_active=False)


@pytest.mark.asyncio
async def test_other_user_cannot_access_mode(db):
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1])

    with pytest.raises(ForbiddenException):
        await mode_service.get_mode(db, OTHER, mode.id)
    with pytest.raises(ForbiddenException):
        await mode_service.update_mode(db, OTHER, mode.id, name="탈취", icon="x", sound_ids=[2])


@pytest.mark.asyncio
async def test_delete_mode(db):
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1])

    await mode_service.delete_mode(db, OWNER, mode.id)

    assert await mode_service.list_modes(db, OWNER) == []
