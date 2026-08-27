from __future__ import annotations

import pytest

from application.services.public import PublicService
from domain.slug import normalize_slug, slug_error, slug_from_name


class FakeRepo:
    """Минимальный репозиторий: повторяет семантику nullable из
    SupabasePinglyRepository.update_tutor_profile, чтобы тесты ловили именно
    «затёрли/не затёрли поле», а не расхождение с реальной реализацией."""

    def __init__(self, profiles: dict[str, dict]) -> None:
        self.profiles = profiles
        self.last_patch: dict | None = None

    async def get_tutor_profile(self, uid):
        return self.profiles.get(uid)

    async def get_tutor_profile_by_slug(self, slug):
        return next((p for p in self.profiles.values() if p.get("slug") == slug), None)

    async def update_tutor_profile(self, uid, patch, nullable=()):
        allow_null = set(nullable)
        clean = {k: v for k, v in patch.items() if v is not None or k in allow_null}
        self.last_patch = clean
        self.profiles[uid] = {**self.profiles.get(uid, {}), **clean}
        return self.profiles[uid]


@pytest.fixture
def repo():
    return FakeRepo({
        "tutor": {"user_id": "tutor", "slug": "ivan-math", "price_per_hour": 1500,
                  "price_note": "старое", "telegram_username": "old_name",
                  "reviews": [{"author": "A", "text": "t", "position": 0}]},
        "other": {"user_id": "other", "slug": "taken-slug"},
    })


@pytest.fixture
def service(repo):
    return PublicService(repo)


# ---------------- slug ----------------

def test_slug_from_name_transliterates():
    assert slug_from_name("Иван Петров") == "ivan-petrov"
    assert slug_from_name("Пётр Щукин") == "petr-schukin"


def test_slug_from_name_gives_up_on_unusable_names():
    # Пустая строка = «подставь случайный», это забота репозитория.
    assert slug_from_name("🙂🙂") == ""
    assert slug_from_name("Эл") == ""


def test_normalize_slug_cleans_input():
    assert normalize_slug("  Ivan__Math !! ") == "ivan-math"
    assert normalize_slug("Ваня Математик") == "vanya-matematik"


def test_slug_error_enforces_3_30():
    assert slug_error("ab") is not None
    assert slug_error("a" * 31) is not None
    assert slug_error("a" * 30) is None
    assert slug_error("ivan-math") is None


# ---------------- цена / длительность / telegram ----------------

def test_parse_price_accepts_formatted_input():
    assert PublicService.parse_price("1200") == (1200, None)
    assert PublicService.parse_price("1 200 ₽") == (1200, None)
    assert PublicService.parse_price("1 200") == (1200, None)


def test_parse_price_empty_is_not_an_error():
    assert PublicService.parse_price("") == (None, None)
    assert PublicService.parse_price(None) == (None, None)


@pytest.mark.parametrize("raw", ["0", "100000", "-5", "12.5", "дорого", "1200 руб"])
def test_parse_price_rejects_out_of_range_and_garbage(raw):
    price, err = PublicService.parse_price(raw)
    assert price is None and err


def test_parse_price_boundaries():
    assert PublicService.parse_price("1") == (1, None)
    assert PublicService.parse_price("99999") == (99999, None)


def test_parse_duration_defaults_to_60():
    assert PublicService.parse_duration("") == (60, None)
    assert PublicService.parse_duration(None) == (60, None)
    assert PublicService.parse_duration("90") == (90, None)


@pytest.mark.parametrize("raw", ["4", "601", "час"])
def test_parse_duration_rejects_out_of_range(raw):
    assert PublicService.parse_duration(raw)[1]


def test_normalize_telegram_strips_prefixes():
    assert PublicService.normalize_telegram("@ivan_math") == ("ivan_math", None)
    assert PublicService.normalize_telegram("https://t.me/ivan_math/") == ("ivan_math", None)
    assert PublicService.normalize_telegram("t.me/ivan_math") == ("ivan_math", None)
    assert PublicService.normalize_telegram("  ") == (None, None)


@pytest.mark.parametrize("raw", ["@abc", "@иван", "@has-dash", "@" + "x" * 33])
def test_normalize_telegram_rejects_invalid(raw):
    assert PublicService.normalize_telegram(raw)[1]


# ---------------- отзывы ----------------

def test_parse_reviews_sorts_by_position_and_renumbers():
    out = PublicService.parse_reviews([
        {"author": "B", "text": "два", "position": 5},
        {"author": "A", "text": "один", "position": 1},
    ])
    assert [r["author"] for r in out] == ["A", "B"]
    assert [r["position"] for r in out] == [0, 1]


def test_parse_reviews_survives_garbage_jsonb():
    # Колонка jsonb: туда можно руками положить что угодно, а страница публичная.
    assert PublicService.parse_reviews("хак") == []
    assert PublicService.parse_reviews(None) == []
    assert PublicService.parse_reviews(["строка", None, {"text": "  "}]) == []
    assert PublicService.parse_reviews([{"author": "X", "text": "ок", "position": "нет"}]) == [
        {"author": "X", "text": "ок", "position": 0}
    ]


def test_parse_reviews_defaults_author_and_caps_count():
    assert PublicService.parse_reviews([{"text": "т"}])[0]["author"] == "Ученик"
    many = [{"author": f"A{i}", "text": f"t{i}"} for i in range(15)]
    assert len(PublicService.sanitize_reviews(many)) == 10


# ---------------- update_profile ----------------

@pytest.mark.asyncio
async def test_update_profile_saves_new_fields(service, repo):
    _, err = await service.update_profile(
        "tutor", "ivan-math", "био", "Математика", True, "clock|Быстро", "light",
        price_per_hour="1200", price_duration_min="90", price_note="Первое бесплатно",
        telegram_username="@ivan_math",
        reviews=[{"author": "Мама Пети", "text": "Отлично"}, {"author": "", "text": ""}],
    )
    assert err is None
    assert repo.last_patch["price_per_hour"] == 1200
    assert repo.last_patch["price_duration_min"] == 90
    assert repo.last_patch["telegram_username"] == "ivan_math"
    # Пустая строка формы — не отзыв.
    assert repo.last_patch["reviews"] == [{"author": "Мама Пети", "text": "Отлично", "position": 0}]


@pytest.mark.asyncio
async def test_update_profile_can_clear_optional_fields(service, repo):
    _, err = await service.update_profile(
        "tutor", "", "", "", True, "", "auto",
        price_per_hour="", price_duration_min="", price_note="", telegram_username="",
    )
    assert err is None
    assert repo.last_patch["price_per_hour"] is None
    assert repo.last_patch["price_note"] is None
    assert repo.last_patch["telegram_username"] is None
    assert repo.last_patch["price_duration_min"] == 60


@pytest.mark.asyncio
async def test_update_profile_leaves_untouched_fields_alone(service, repo):
    """Форма, не приславшая новые поля, не должна их стирать."""
    await service.update_profile("tutor", "", "био", "Математика", True)
    for field in ("price_per_hour", "price_note", "telegram_username", "reviews", "price_duration_min"):
        assert field not in repo.last_patch
    assert repo.profiles["tutor"]["price_per_hour"] == 1500
    assert len(repo.profiles["tutor"]["reviews"]) == 1


@pytest.mark.asyncio
async def test_update_profile_never_clears_slug(service, repo):
    # На адрес уже могут вести ссылки — пустое поле означает «не трогать».
    await service.update_profile("tutor", "", "", "", True)
    assert "slug" not in repo.last_patch
    assert repo.profiles["tutor"]["slug"] == "ivan-math"


@pytest.mark.asyncio
async def test_update_profile_rejects_taken_slug(service):
    profile, err = await service.update_profile("tutor", "taken-slug", "", "", True)
    assert profile is None
    assert "занят" in err


@pytest.mark.asyncio
async def test_update_profile_allows_own_slug(service):
    _, err = await service.update_profile("tutor", "ivan-math", "", "", True)
    assert err is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"slug": "ab"},
    {"price_per_hour": "дорого"},
    {"price_duration_min": "999"},
    {"telegram_username": "@x"},
])
async def test_update_profile_reports_validation_errors(service, kwargs):
    slug = kwargs.pop("slug", "")
    profile, err = await service.update_profile("tutor", slug, "", "", True, **kwargs)
    assert profile is None and err


@pytest.mark.asyncio
async def test_enabling_page_without_any_slug_fails(service, repo):
    repo.profiles["fresh"] = {"user_id": "fresh"}
    profile, err = await service.update_profile("fresh", "", "", "", True)
    assert profile is None and err
    # Выключенную страницу без адреса сохранить можно.
    _, err = await service.update_profile("fresh", "", "", "", False)
    assert err is None
