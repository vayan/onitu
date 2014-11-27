import pytest

from tests.utils.loop import BooleanLoop, CounterLoop


@pytest.fixture(autouse=True)
def _(module_launcher_launch):
    pass


def copy_file(launcher, filename, size):
    src, dest = launcher.get_entries('rep1', 'rep2')
    launcher.unset_all_events()
    loop = BooleanLoop()
    launcher.on_transfer_ended(
        loop.stop, d_from=src, d_to=dest, filename=filename
    )
    src.generate(filename, size)
    loop.run(timeout=10)
    assert dest.exists(filename)


def delete_file(launcher, src, dest):
    copy_file(launcher, 'to_delete', 100)
    loop = CounterLoop(2)
    launcher.on_file_deleted(
        loop.check, driver=src, filename='to_delete'
    )
    launcher.on_deletion_completed(
        loop.check, driver=dest, filename='to_delete'
    )
    src.unlink('to_delete')
    loop.run(timeout=5)
    assert not dest.exists('to_delete')


def test_deletion_from_rep1(module_launcher):
    delete_file(module_launcher, *module_launcher.get_entries('rep2', 'rep1'))


def test_deletion_from_rep2(module_launcher):
    delete_file(module_launcher, *module_launcher.get_entries('rep1', 'rep2'))


def test_delete_dir(module_launcher):
    src, dest = module_launcher.get_entries('rep1', 'rep2')
    src.mkdir('dir')
    copy_file(module_launcher, 'dir/foo', 100)
    copy_file(module_launcher, 'dir/bar', 100)
    loop = CounterLoop(4)
    module_launcher.on_file_deleted(
        loop.check, driver=src, filename='dir/foo'
    )
    module_launcher.on_file_deleted(
        loop.check, driver=src, filename='dir/bar'
    )
    module_launcher.on_deletion_completed(
        loop.check, driver=dest, filename='dir/foo'
    )
    module_launcher.on_deletion_completed(
        loop.check, driver=dest, filename='dir/bar'
    )
    src.rmdir('dir')
    loop.run(timeout=5)
    assert not dest.exists('dir/foo')
    assert not dest.exists('dir/bar')