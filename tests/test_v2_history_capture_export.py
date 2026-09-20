from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

from picot.v2.diagnostic_downloads import diagnostic_zip
from picot.v2.passive_history.evidence import publish, verify
from picot.v2.passive_history.storage import own_directory

PREFIX = 'picot_history_capture_trial'


def test_trial_export_is_explicit_and_preserves_published_bytes(tmp_path):
    root = own_directory(tmp_path / PREFIX)
    source = publish(root, '{"poll":{}}', free_reserve=0, storage_limit=1_000_000)
    (root / '.pending-keep').write_text('unfinished')
    (root / 'secret.json').write_text('not allowed')
    with ZipFile(BytesIO(diagnostic_zip(()))) as archive:
        assert archive.namelist() == []
    with ZipFile(BytesIO(diagnostic_zip((root,)))) as archive:
        name = PREFIX + '/' + str(source.relative_to(root))
        assert archive.read(name) == source.read_bytes()
        manifest = json.loads(archive.read(PREFIX + '/export-manifest.json'))
        assert manifest['scan_complete'] is True
        assert manifest['content_verified'] is False
        assert len(manifest['objects']) == 1
        assert not any('pending' in n or 'secret' in n for n in archive.namelist())
    assert verify(source) == b'{"poll":{}}'
    assert (root / '.pending-keep').read_text() == 'unfinished'


def test_trial_export_budget_reports_incomplete_without_deletion(tmp_path, monkeypatch):
    import picot.v2.passive_history.export as export
    root = own_directory(tmp_path / PREFIX)
    source = publish(root, '{}', free_reserve=0, storage_limit=1_000_000)
    monkeypatch.setattr(export, 'MAX_EXPORT_BYTES', 1)
    with ZipFile(BytesIO(diagnostic_zip((root,)))) as archive:
        manifest = json.loads(archive.read(PREFIX + '/export-manifest.json'))
        assert manifest['issues']
        assert manifest['objects'] == []
    assert source.exists()


def test_trial_export_refuses_symlinked_object(tmp_path):
    root = own_directory(tmp_path / PREFIX)
    source = publish(root, '{}', free_reserve=0, storage_limit=1_000_000)
    source.unlink()
    foreign = tmp_path / 'private'
    foreign.write_text('private')
    source.symlink_to(foreign)
    with ZipFile(BytesIO(diagnostic_zip((root,)))) as archive:
        manifest = json.loads(archive.read(PREFIX + '/export-manifest.json'))
        assert manifest['issues']
        assert manifest['objects'] == []
        assert all(b'private' not in archive.read(n) for n in archive.namelist())


def test_missing_trial_directory_does_not_get_created(tmp_path):
    root = tmp_path / PREFIX
    with ZipFile(BytesIO(diagnostic_zip((root,)))) as archive:
        manifest = json.loads(archive.read(PREFIX + '/export-manifest.json'))
        assert manifest['status'] == 'not_present'
    assert not root.exists()


def test_exported_three_record_fixture_can_be_verified_and_indexed_offline(tmp_path):
    from test_v2_passive_history import plan, poll

    from picot.v2.passive_history.storage import HistoryStore
    from picot.v2.passive_history.worker import discover, process_batch

    root = own_directory(tmp_path / PREFIX)
    for record in [poll(), poll('later'), {'execution_plans': {'p': plan()}}]:
        publish(root, json.dumps(record), free_reserve=0, storage_limit=1_000_000)
    target = HistoryStore(tmp_path / 'offline')
    try:
        with ZipFile(BytesIO(diagnostic_zip((root,)))) as archive:
            manifest = json.loads(archive.read(PREFIX + '/export-manifest.json'))
            assert len(manifest['objects']) == 3
            for item in manifest['objects']:
                path = target.root / item['member'].removeprefix(PREFIX + '/')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(item['member']))
                assert isinstance(json.loads(verify(path)), dict)
        for _ in range(256):
            discover(target)
        assert process_batch(target, free_reserve=0) == {'done': 3}
        assert target.db.execute('SELECT count(*) FROM usable_plan_objects').fetchone()[0] == 1
        assert target.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        target.close()


def test_object_count_limit_is_explicit(tmp_path, monkeypatch):
    import picot.v2.passive_history.export as export
    root = own_directory(tmp_path / PREFIX)
    for i in range(3):
        publish(root, json.dumps({'n': i}), free_reserve=0, storage_limit=1_000_000)
    monkeypatch.setattr(export, 'MAX_EXPORT_OBJECTS', 1)
    with ZipFile(BytesIO(diagnostic_zip((root,)))) as archive:
        manifest = json.loads(archive.read(PREFIX + '/export-manifest.json'))
        assert manifest['status'] == 'partial'
        assert manifest['scan_complete'] is False
        assert len(manifest['objects']) == 1
    assert len(list(root.glob('objects/*/*.json.gz'))) == 3


def test_trial_root_file_link_never_enters_archive(tmp_path):
    secret = tmp_path / 'secret'
    secret.write_bytes(b'not for export')
    root = tmp_path / PREFIX
    root.symlink_to(secret)
    with ZipFile(BytesIO(diagnostic_zip((root,)))) as archive:
        assert archive.namelist() == [PREFIX + '/export-manifest.json']
        manifest = json.loads(archive.read(archive.namelist()[0]))
        assert manifest['status'] == 'unavailable'
