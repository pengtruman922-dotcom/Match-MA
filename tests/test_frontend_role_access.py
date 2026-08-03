from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_admin_navigation_is_not_rendered_for_consultants() -> None:
    source = (REPO / "frontend/src/components/Layout.tsx").read_text(encoding="utf-8")
    base_nav, admin_nav = source.split("const adminNavItems", 1)

    assert "'/settings'" not in base_nav
    for path in ("/settings", "/users", "/tasks"):
        assert f"'{path}'" in admin_nav


def test_missing_role_does_not_default_to_admin() -> None:
    source = (REPO / "frontend/src/lib/auth.ts").read_text(encoding="utf-8")

    assert "return user?.role === 'admin'" in source
    assert "return true" not in source.split("export function isAdmin", 1)[1]
