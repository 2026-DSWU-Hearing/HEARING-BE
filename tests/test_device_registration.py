import pytest

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User


@pytest.mark.asyncio
async def test_manual_registration_uses_server_mac_and_allows_shared_device(api_client):
    client, session_factory = api_client
    async with session_factory() as db:
        db.add_all([
            User(id=1, email='first@t.local', nickname='first', terms_agreed=True),
            User(id=2, email='second@t.local', nickname='second', terms_agreed=True),
        ])
        await db.commit()

    first = await client.post(
        '/devices',
        headers={'Authorization': 'Bearer ' + create_access_token(1, source='user')},
        json={'nickname': '첫 기기'},
    )
    second = await client.post(
        '/devices',
        headers={'Authorization': 'Bearer ' + create_access_token(2, source='user')},
        json={'nickname': '둘째 기기'},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()['id'] != second.json()['id']
    assert first.json()['mac_address'] == settings.DEVICE_MAC_ADDRESS
    assert second.json()['mac_address'] == settings.DEVICE_MAC_ADDRESS
    assert first.json()['is_connected'] is False
    assert second.json()['is_connected'] is False


@pytest.mark.asyncio
async def test_reregistration_is_idempotent_and_renames(api_client):
    """재등록은 새 행을 만들지 않되(멱등), 사용자가 입력한 새 이름은 반영한다
    — 기존 행이 있는 계정의 등록 요청에서 이름이 조용히 무시되지 않도록."""
    client, session_factory = api_client
    async with session_factory() as db:
        db.add(User(id=1, email='r@t.local', nickname='r', terms_agreed=True))
        await db.commit()
    headers = {'Authorization': 'Bearer ' + create_access_token(1, source='user')}

    first = await client.post('/devices', headers=headers, json={'nickname': '처음 이름'})
    again = await client.post('/devices', headers=headers, json={'nickname': '바꾼 이름'})

    assert first.status_code == 200 and again.status_code == 200
    assert again.json()['id'] == first.json()['id']
    assert again.json()['nickname'] == '바꾼 이름'

    devices = await client.get('/devices', headers=headers)
    assert [d['nickname'] for d in devices.json()] == ['바꾼 이름']
