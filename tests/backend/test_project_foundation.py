from pathlib import Path


def test_backend_foundation_files_exist():
    root = Path(__file__).parents[2] / "backend"
    for relative in ("manage.py", "config/urls.py", "core/views.py"):
        assert (root / relative).is_file()
