from src.auth.session import SessionManager


def test_has_saved_session_without_crash() -> None:
    manager = SessionManager()
    assert manager.has_saved_session() in (True, False)
    assert manager.session_source_label() is None or isinstance(manager.session_source_label(), str)
