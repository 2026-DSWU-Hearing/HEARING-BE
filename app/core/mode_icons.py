from typing import NamedTuple


class ModeIcon(NamedTuple):
    mode_id: int
    name_ko: str
    name_key: str
    icon_key: str


MODE_ICONS: list[ModeIcon] = [
    ModeIcon(1, "직장", "workplace", "ic_workplace"),
    ModeIcon(2, "운동", "exercise", "ic_exercise"),
    ModeIcon(3, "요리", "cooking", "ic_cooking"),
    ModeIcon(4, "자연", "nature", "ic_nature"),
    ModeIcon(5, "여행", "travel", "ic_travel"),
    ModeIcon(6, "긴급", "emergency", "ic_emergency"),
    ModeIcon(7, "동물", "animal", "ic_animal"),
    ModeIcon(8, "카페", "cafe", "ic_cafe"),
    ModeIcon(9, "병원", "hospital", "ic_hospital"),
    ModeIcon(10, "교통", "transportation", "ic_transportation"),
    ModeIcon(11, "외출", "goingOut", "ic_goingOut"),
    ModeIcon(12, "수면", "sleep", "ic_sleep"),
    ModeIcon(13, "가정", "home", "ic_home"),
    ModeIcon(14, "학교", "school", "ic_school"),
    ModeIcon(15, "공부", "study", "ic_study"),
]
