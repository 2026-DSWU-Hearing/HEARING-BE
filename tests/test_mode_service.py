"""mode_service 유닛테스트 — 실 세션(db fixture)으로 쿼리·관계·flush 를 검증한다.

핵심: update_mode/update_mode_sounds(_set_sound_links) 가 바뀐 부분만 반영하는지
— 유지되는 소리의 is_active 가 살아남고, 겹치는 sound_id 로 uq_mode_sound 충돌이 없어야 한다.
"""

import pytest

from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.models.user import User
from app.services import mode_service

OWNER = 1
OTHER = 2


async def _seed(db) -> None:
    """유저만 만든다 — sound_id 1..5 는 conftest 가 마이그레이션으로 깔아둔 실제 카탈로그
    (긴급 카테고리의 화재 경보·사이렌·경보음·응급차량·폭발·파열음)를 그대로 쓴다."""
    db.add(User(id=OWNER, email="owner@t.local", nickname="owner", terms_agreed=True))
    db.add(User(id=OTHER, email="other@t.local", nickname="other", terms_agreed=True))
    await db.commit()


def _sound_ids(mode) -> set[int]:
    return {link.sound_id for link in mode.sound_links}


def _link(mode, sound_id: int):
    return next(link for link in mode.sound_links if link.sound_id == sound_id)


def _active_map(mode) -> dict[int, bool]:
    return {link.sound_id: link.is_active for link in mode.sound_links}


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
async def test_update_mode_sounds_keeps_existing_links(db):
    """겹치는 sound_id 는 기존 링크를 그대로 둔다(재삽입 없음 → uq_mode_sound 충돌도 없음)."""
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1, 2])
    link_1_id = _link(mode, 1).id

    # 1 유지, 2 제거, 3 추가
    updated = await mode_service.update_mode_sounds(db, OWNER, mode.id, sound_ids=[1, 3])
    assert _sound_ids(updated) == {1, 3}
    assert _link(updated, 1).id == link_1_id  # 같은 행 — DELETE/INSERT 되지 않았다

    # 완전히 동일한 집합으로 재설정 — 아무것도 바뀌지 않아야 한다
    again = await mode_service.update_mode_sounds(db, OWNER, mode.id, sound_ids=[1, 3])
    assert _sound_ids(again) == {1, 3}
    assert _link(again, 1).id == link_1_id


# --- 꺼둔 소리(is_active=False)가 모드 수정 뒤에도 꺼진 채 남는지 (FE 버그리포트) -------------
# 전부 지우고 새로 만들면 ModeSound.is_active 기본값 True 로 되살아나, 사용자가 꺼둔 소리의
# 알림·진동이 다시 온다. 이름만 고쳐도 재현됐다.


@pytest.mark.asyncio
async def test_update_mode_keeps_inactive_sound_off(db):
    """[1, 2] 생성 → 1 끔 → update_mode([1, 3]) → 1 꺼짐 유지 / 3 켜짐 / 2 없음."""
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1, 2])
    await mode_service.set_mode_sound_active(db, OWNER, mode.id, 1, False)

    updated = await mode_service.update_mode(db, OWNER, mode.id, name="외출", icon="walk", sound_ids=[1, 3])

    assert _active_map(updated) == {1: False, 3: True}


@pytest.mark.asyncio
async def test_update_mode_sounds_keeps_inactive_sound_off(db):
    """같은 시나리오를 update_mode_sounds(PUT /modes/{id}/sounds)로."""
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1, 2])
    await mode_service.set_mode_sound_active(db, OWNER, mode.id, 1, False)

    updated = await mode_service.update_mode_sounds(db, OWNER, mode.id, sound_ids=[1, 3])

    assert _active_map(updated) == {1: False, 3: True}


@pytest.mark.asyncio
async def test_update_mode_name_only_keeps_inactive_sound_off(db):
    """소리 목록을 그대로 다시 보내며 이름만 고쳐도(FE 재현 케이스) 꺼짐이 유지된다."""
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1, 2])
    await mode_service.set_mode_sound_active(db, OWNER, mode.id, 2, False)

    updated = await mode_service.update_mode(db, OWNER, mode.id, name="산책", icon="walk", sound_ids=[1, 2])

    assert updated.name == "산책"
    assert _active_map(updated) == {1: True, 2: False}


@pytest.mark.asyncio
async def test_update_mode_sounds_dedupes_ids(db):
    """같은 sound_id 가 두 번 와도 링크는 하나(uq_mode_sound 위반으로 500 나지 않게)."""
    await _seed(db)
    mode = await mode_service.create_mode(db, OWNER, name="외출", icon="walk", sound_ids=[1])

    updated = await mode_service.update_mode_sounds(db, OWNER, mode.id, sound_ids=[2, 3, 2])

    assert sorted(link.sound_id for link in updated.sound_links) == [2, 3]


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
