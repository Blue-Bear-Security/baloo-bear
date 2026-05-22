"""Tests for INSTALLATION_IDS setting parsing and backward compatibility."""


class TestInstallationIds:
    def test_empty_by_default(self):
        from baloo.config.settings import get_settings

        assert get_settings().installation_ids == []

    def test_parses_comma_separated(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_IDS", "111,222,333")
        from baloo.config.settings import get_settings

        assert get_settings().installation_ids == ["111", "222", "333"]

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_IDS", " 111 , 222 ")
        from baloo.config.settings import get_settings

        assert get_settings().installation_ids == ["111", "222"]

    def test_single_value(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_IDS", "42")
        from baloo.config.settings import get_settings

        assert get_settings().installation_ids == ["42"]

    def test_empty_string_gives_empty_list(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_IDS", "")
        from baloo.config.settings import get_settings

        assert get_settings().installation_ids == []

    def test_backfilled_from_installation_id(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_ID", "99")
        from baloo.config.settings import get_settings

        assert get_settings().installation_ids == ["99"]

    def test_installation_ids_takes_precedence_over_installation_id(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_ID", "99")
        monkeypatch.setenv("INSTALLATION_IDS", "100,200")
        from baloo.config.settings import get_settings

        assert get_settings().installation_ids == ["100", "200"]
