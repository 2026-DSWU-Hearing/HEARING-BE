from pydantic import BaseModel


# --- 프론트(home) 응답 계약: snake_case + 카테고리 평탄화 + 리스트 래핑 ---


class CategoryItem(BaseModel):
    category_id: int
    name: str


class CategoryListResponse(BaseModel):
    categories: list[CategoryItem]


class SoundItem(BaseModel):
    sound_id: int
    name: str
    category_id: int
    category_name: str
    icon_key: str | None = None


class SoundListResponse(BaseModel):
    sounds: list[SoundItem]
