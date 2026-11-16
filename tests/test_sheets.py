from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from analecta.sheets import MAX_VERSIONS, SheetError, SheetStore, clean_name, parse_sheet

FIXTURE = Path(__file__).parent / "fixtures" / "sheets" / "synthetic_pathbuilder.json"
ALEX, BLAIR, GM = 1001, 1002, 9001


def sheet_bytes(name="Test Hero", **changes) -> bytes:
    data = json.loads(FIXTURE.read_text())
    data["build"]["name"] = name
    data["build"].update(changes)
    return json.dumps(data).encode()


@pytest.fixture()
def store(tmp_path):
    return SheetStore(tmp_path / "sheets", gm_ids=[GM])


def test_add_saves_the_raw_file_untouched_and_reports_it(store):
    raw = FIXTURE.read_bytes()
    result = store.add(ALEX, raw)
    assert result.created and result.versions == 1 and result.level == 5 and result.class_name == "Cleric"
    assert store.raw(result.info) == raw
    assert store.get("test hero").owner_id == ALEX


def test_files_and_folders_are_private(store):
    result = store.add(ALEX, sheet_bytes())
    mode = lambda p: stat.S_IMODE(p.stat().st_mode)
    assert mode(store.root) == 0o750 and mode(store.root / result.info.id) == 0o750
    assert mode(store.root / result.info.id / "meta.json") == 0o640
    assert all(mode(p) == 0o640 for p in (store.root / result.info.id / "versions").iterdir())


def test_folder_names_are_random_ids_never_the_character_name(store):
    store.add(ALEX, sheet_bytes("../../etc/passwd"))
    store.add(BLAIR, sheet_bytes("Zuhri"))
    names = {p.name for p in store.root.iterdir()}
    assert all(len(n) == 16 or n == "registrations.json" for n in names)
    assert not (store.root.parent / "etc").exists()


def test_owner_updates_make_a_new_version_and_keep_the_last_ten(store):
    for n in range(MAX_VERSIONS + 4):
        result = store.add(ALEX, sheet_bytes(level=n + 1))
    assert not result.created and result.versions == MAX_VERSIONS
    assert json.loads(store.raw(result.info))["build"]["level"] == MAX_VERSIONS + 4
    assert len(list((store.root / result.info.id / "versions").iterdir())) == MAX_VERSIONS


def test_name_collisions_are_refused_case_insensitively(store):
    store.add(ALEX, sheet_bytes("Test Hero"))
    with pytest.raises(SheetError, match="already saved"):
        store.add(BLAIR, sheet_bytes("test  HERO"))
    assert store.get("Test Hero").owner_id == ALEX and store.version_count(store.get("Test Hero")) == 1


def test_gm_may_update_someone_elses_sheet_and_ownership_stays(store):
    store.add(ALEX, sheet_bytes())
    result = store.add(GM, sheet_bytes(level=6))
    assert not result.created and store.get("Test Hero").owner_id == ALEX and result.versions == 2


@pytest.mark.parametrize("raw, message", [
    (b"not json at all", "not JSON"),
    (b"[1, 2]", "Pathbuilder"),
    (b'{"success": false}', "Pathbuilder"),
    (b'{"success": true, "build": []}', "no character"),
    (b'{"success": true, "build": {"name": "X", "level": 1}}', "no character"),
    (b'{"success": true, "build": {"name": "  ", "level": 1, "abilities": {}}}', "no name"),
    (b"\xff\xfe\x00", "not JSON"),
    (b"[" * 100000, "not JSON"),
    (b" " * (2 * 1024 * 1024 + 1), "too big"),
])
def test_bad_uploads_are_refused_and_nothing_is_written(store, raw, message):
    with pytest.raises(SheetError, match=message):
        store.add(ALEX, raw)
    assert store.list() == []


def test_names_are_cleaned(store):
    assert clean_name("  Zu‮hri\n  Vale\x00 ") == "Zu hri Vale"
    assert len(clean_name("x" * 500)) == 60
    store.add(ALEX, sheet_bytes("Zuhri‮ Vale"))
    assert "‮" not in store.list()[0].name


def test_bom_is_accepted():
    name, _ = parse_sheet(b"\xef\xbb\xbf" + FIXTURE.read_bytes())
    assert name == "Test Hero"


def test_uploader_is_registered_to_their_first_character_only(store):
    first = store.add(ALEX, sheet_bytes("One"))
    second = store.add(ALEX, sheet_bytes("Two"))
    assert first.registered and not second.registered
    assert store.character_name_for(ALEX) == "One"


def test_registration_rules(store):
    store.add(ALEX, sheet_bytes("One"))                 # Alex owns and holds One
    store.add(GM, sheet_bytes("Two"))                   # GM owns Two (and holds it)
    store.add(ALEX, sheet_bytes("Three"))               # Alex owns Three, unheld
    # anyone may take an unheld character for themselves
    info, user = store.register(BLAIR, "three")
    assert (info.name, user) == ("Three", BLAIR) and store.character_name_for(BLAIR) == "Three"
    # but not one someone else holds
    with pytest.raises(SheetError, match="already registered"):
        store.register(BLAIR, "One")
    # nor register other people to a character they do not own
    with pytest.raises(SheetError, match="owner or a GM"):
        store.register(BLAIR, "Three", user_id=ALEX)
    # the owner may register another person to their character, and a GM may reassign
    store.register(ALEX, "Three", user_id=GM)
    assert store.character_name_for(GM) == "Three"
    store.register(GM, "One", user_id=BLAIR)
    assert store.character_name_for(BLAIR) == "One"


def test_registering_again_replaces_the_old_mapping_and_unknown_names_fail(store):
    store.add(ALEX, sheet_bytes("One"))
    store.add(ALEX, sheet_bytes("Two"))
    store.register(ALEX, "Two")
    assert store.character_name_for(ALEX) == "Two"
    with pytest.raises(SheetError, match="no saved character"):
        store.register(ALEX, "Nobody")
    assert store.character_name_for(ALEX) == "Two"


def test_unregister_permissions(store):
    store.add(ALEX, sheet_bytes("One"))
    store.register(ALEX, "One", user_id=BLAIR)
    with pytest.raises(SheetError, match="owner or a GM"):
        store.unregister(BLAIR + 1, BLAIR)
    store.unregister(GM, BLAIR)
    assert store.character_name_for(BLAIR) is None
    with pytest.raises(SheetError, match="no registered character"):
        store.unregister(BLAIR)
    assert store.character_name_for(ALEX) == "One"       # the owner's own mapping is untouched


def test_delete_needs_owner_or_gm_and_erases_everything(store):
    store.add(ALEX, sheet_bytes())
    store.add(ALEX, sheet_bytes(level=6))
    folder = store.root / store.get("Test Hero").id
    with pytest.raises(SheetError, match="owner or a GM"):
        store.delete(BLAIR, "Test Hero")
    assert folder.exists()
    store.delete(ALEX, "Test Hero")
    assert not folder.exists() and store.list() == [] and store.character_name_for(ALEX) is None
    store.add(ALEX, sheet_bytes())
    store.delete(GM, "Test Hero")
    assert store.list() == []


def test_a_deleted_name_can_be_taken_by_someone_else(store):
    store.add(ALEX, sheet_bytes())
    store.delete(ALEX, "Test Hero")
    store.add(BLAIR, sheet_bytes())
    assert store.get("Test Hero").owner_id == BLAIR


def test_one_damaged_sheet_does_not_break_the_others(store):
    store.add(ALEX, sheet_bytes("Good"))
    bad = store.add(BLAIR, sheet_bytes("Bad")).info
    (store.root / bad.id / "meta.json").write_text("{broken")
    assert [i.name for i in store.list()] == ["Good"]
    (store.root / "registrations.json").write_text("not json")
    assert store.character_name_for(ALEX) is None and store.registrations() == []


def test_a_damaged_saved_file_gives_a_clear_error(store):
    info = store.add(ALEX, sheet_bytes()).info
    for p in (store.root / info.id / "versions").iterdir():
        p.write_text("{nope")
    with pytest.raises(SheetError, match="damaged"):
        store.load(info)


def test_empty_store_and_missing_folder_are_fine(tmp_path):
    store = SheetStore(tmp_path / "does" / "not" / "exist")
    assert store.list() == [] and store.registrations() == [] and store.character_for(1) is None
    assert store.find("") is None


def test_error_messages_escape_character_names(store):
    store.add(ALEX, sheet_bytes("**Bold** @everyone"))
    with pytest.raises(SheetError) as err:
        store.add(BLAIR, sheet_bytes("**Bold** @everyone"))
    assert "**Bold**" not in str(err.value) and "@everyone" not in str(err.value)
    with pytest.raises(SheetError) as err:
        store.get("_nobody_ @here")
    assert "@here" not in str(err.value) and "_nobody_" not in str(err.value)
