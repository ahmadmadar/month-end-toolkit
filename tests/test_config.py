"""Rules loading, month parsing, paths and the API key check. Uses temp files only."""

from datetime import date
from pathlib import Path

import pytest

from toolkit.apikey import KEY_NAME, load_api_key
from toolkit.config import load_rules
from toolkit.errors import ToolkitError
from toolkit.paths import check_inputs_exist, month_paths, parse_month

ROOT = Path(__file__).resolve().parents[1]

VALID_RULES = """
version: 1
client: Test Client
inputs:
  dispatch_file: dispatch.csv
  tickets_folder: tix
  ticket_extensions: [.TXT, .pdf, .txt]
fees:
  extra_bin: 40
matching:
  date_tolerance_days: 1
review: {}
model:
  name: some-model
  max_tokens: 100
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# --- rules ---

def test_repo_rules_file_loads():
    rules = load_rules(ROOT / "rules" / "rules.yaml")
    assert rules.inputs.dispatch_file == "dispatch_export.csv"
    assert ".txt" in rules.inputs.ticket_extensions


def test_rules_values_and_extension_normalising(tmp_path):
    rules = load_rules(write(tmp_path, VALID_RULES))
    assert rules.version == "1"
    assert rules.inputs.ticket_extensions == (".txt", ".pdf")
    assert rules.fees == {"extra_bin": 40.0}


def test_missing_rules_file(tmp_path):
    with pytest.raises(ToolkitError, match="not found"):
        load_rules(tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    "old, new, message",
    [
        ("  dispatch_file: dispatch.csv\n", "", "dispatch_file"),
        ("[.TXT, .pdf, .txt]", "[]", "ticket_extensions"),
        ("[.TXT, .pdf, .txt]", "[txt]", "look like"),
        ("extra_bin: 40", "extra_bin: -5", "fee 'extra_bin'"),
        ("max_tokens: 100", "max_tokens: lots", "max_tokens"),
        ("client: Test Client\n", "", "client"),
    ],
)
def test_invalid_rules(tmp_path, old, new, message):
    assert old in VALID_RULES
    with pytest.raises(ToolkitError, match=message):
        load_rules(write(tmp_path, VALID_RULES.replace(old, new)))


def test_invalid_yaml(tmp_path):
    with pytest.raises(ToolkitError, match="not valid YAML"):
        load_rules(write(tmp_path, "inputs: [unclosed"))


# --- month and paths ---

def test_parse_month():
    assert parse_month("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert parse_month("2028-02")[1] == date(2028, 2, 29)


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026-1", "26-11", "", "2026/11"])
def test_parse_month_rejects(bad):
    with pytest.raises(ToolkitError):
        parse_month(bad)


def test_paths_come_from_rules(tmp_path):
    rules = load_rules(write(tmp_path, VALID_RULES))
    paths = month_paths("2026-11", rules, tmp_path)
    assert paths.dispatch_file == tmp_path / "inputs" / "2026-11" / "dispatch.csv"
    assert paths.tickets_dir == tmp_path / "inputs" / "2026-11" / "tix"
    assert paths.workbook == tmp_path / "outputs" / "2026-11" / "reconciliation_2026-11.xlsx"


def test_check_inputs_exist_names_what_is_missing(tmp_path):
    rules = load_rules(write(tmp_path, VALID_RULES))
    paths = month_paths("2026-11", rules, tmp_path)
    with pytest.raises(ToolkitError, match="No input folder"):
        check_inputs_exist(paths)
    paths.input_dir.mkdir(parents=True)
    with pytest.raises(ToolkitError, match="Dispatch file"):
        check_inputs_exist(paths)
    paths.dispatch_file.write_text("x")
    with pytest.raises(ToolkitError, match="Tickets folder"):
        check_inputs_exist(paths)
    paths.tickets_dir.mkdir()
    check_inputs_exist(paths)


# --- API key ---

@pytest.fixture
def no_key(monkeypatch):
    """Start with the key unset and remove anything load_dotenv adds once the test ends."""
    monkeypatch.setenv(KEY_NAME, "placeholder")  # recorded, so teardown restores the original
    monkeypatch.delenv(KEY_NAME)


def test_key_read_from_env_file(tmp_path, monkeypatch, no_key):
    env = tmp_path / ".env"
    env.write_text(f"{KEY_NAME}=test-key-123\n")
    assert load_api_key(env) == "test-key-123"


def test_missing_key_fails_and_ignores_anthropic_api_key(tmp_path, monkeypatch, no_key):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-be-used")
    with pytest.raises(ToolkitError, match=KEY_NAME):
        load_api_key(tmp_path / ".env")  # file doesn't exist


def test_blank_key_fails(tmp_path, monkeypatch, no_key):
    env = tmp_path / ".env"
    env.write_text(f"{KEY_NAME}=   \n")
    with pytest.raises(ToolkitError):
        load_api_key(env)
