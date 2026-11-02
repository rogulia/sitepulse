import pytest

from config import ConfigError, load_config

VALID = """
[settings]
ssl_warn_days = 30

[[project]]
name = "acme"
url = "https://acme.com/"

  [[project.domain]]
  name = "Acme.com"
  hosts = ["acme.com", "WWW.acme.com"]
  nameservers = ["ns1.example.net"]
  expiry_fallback = 2027-03-01

  [[project.domain]]
  name = "acme.fi"
"""


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_loads_projects_and_defaults(tmp_path):
    config = load_config(write(tmp_path, VALID))

    assert config.settings.ssl_warn_days == 30
    assert config.settings.domain_warn_days == 60
    project = config.projects[0]
    assert project.url == "https://acme.com"
    assert project.sitemap == "https://acme.com/sitemap.xml"
    first, second = project.domains
    assert first.name == "acme.com"
    assert first.hosts == ("acme.com", "www.acme.com")
    assert first.expiry_fallback == "2027-03-01"
    assert second.hosts == ("acme.fi",)


@pytest.mark.parametrize(
    "text",
    [
        "[settings]\nunknown = 1\n[[project]]\nname='a'\nurl='https://a.com'\n",
        "[settings]\nssl_warn_days = 3\nssl_critical_days = 7\n"
        "[[project]]\nname='a'\nurl='https://a.com'\n",
        "[settings]\nmax_workers = '10'\n[[project]]\nname='a'\nurl='https://a.com'\n",
        "[[project]]\nname='a'\n",
        "[[project]]\nname='a'\nurl='https://a.com'\n[[project]]\nname='a'\nurl='https://b.com'\n",
        "[[project]]\nname='a'\nurl='https://a.com'\n"
        "[[project.domain]]\nname='a.com'\nexpiry_fallback='soon'\n",
        "[settings]\n",
    ],
)
def test_invalid_config_is_rejected(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_health_urls_keep_case_and_default_to_empty(tmp_path):
    config = load_config(
        write(
            tmp_path,
            "[[project]]\nname='a'\nurl='https://a.com'\n"
            "health=['https://a.com/Health']\n"
            "[[project]]\nname='b'\nurl='https://b.com'\n",
        )
    )
    assert config.projects[0].health == ("https://a.com/Health",)
    assert config.projects[1].health == ()


def test_health_url_must_be_http(tmp_path):
    with pytest.raises(ConfigError):
        load_config(
            write(
                tmp_path,
                "[[project]]\nname='a'\nurl='https://a.com'\nhealth=['/health']\n",
            )
        )


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.toml")
