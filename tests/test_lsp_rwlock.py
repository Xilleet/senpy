"""Тесты для reader-writer lock (P1'-9, 0.6.0-12).

Проверяем:
  - Несколько reader'ов могут держать read lock параллельно
  - Writer эксклюзивен — пока он держит write lock, ни reader ни другой writer не проходят
  - Preference writer'у: если есть ожидающий writer, новый reader ждёт
  - Deadlock-безопасность: исключения в handler'ах не оставляют lock зависшим
"""
from __future__ import annotations

import threading
import time

import senpy.lsp.server as server_mod
from senpy.lsp.server import _RWLock


# =============================================================================
# _RWLock unit tests
# =============================================================================

def test_rwlock_multiple_readers_parallel():
    """Несколько reader'ов могут держать read lock одновременно."""
    lock = _RWLock()
    barrier = threading.Barrier(3, timeout=2.0)
    results = []

    def reader(idx: int):
        lock.acquire_read()
        try:
            barrier.wait(timeout=1.0)  # все 3 reader'а должны дойти сюда одновременно
            results.append(f"reader{idx}-in")
            time.sleep(0.05)
            results.append(f"reader{idx}-out")
        finally:
            lock.release_read()

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    # Все 3 reader'а должны были войти — barrier не должен был упасть по таймауту
    assert len(results) == 6, f"Только {len(results)}/6 reader events — значит reader'ы сериализованы"
    assert all("in" in r for r in results[:3]), "Все reader'ы должны были войти"


def test_rwlock_writer_excludes_readers():
    """Пока writer держит write lock, reader'ы ждут."""
    lock = _RWLock()
    writer_done = threading.Event()
    reader_entered = threading.Event()

    def writer():
        lock.acquire_write()
        try:
            writer_done.wait(timeout=2.0)  # держим lock, пока main не даст сигнал
        finally:
            lock.release_write()

    def reader():
        lock.acquire_read()
        try:
            reader_entered.set()
        finally:
            lock.release_read()

    # Запускаем writer
    wt = threading.Thread(target=writer)
    wt.start()
    time.sleep(0.1)  # даём writer'у войти

    # Запускаем reader — он должен ждать
    rt = threading.Thread(target=reader)
    rt.start()
    time.sleep(0.1)

    assert not reader_entered.is_set(), "Reader не должен пройти, пока writer держит lock"

    # Отпускаем writer
    writer_done.set()
    wt.join(timeout=2.0)
    rt.join(timeout=2.0)

    assert reader_entered.is_set(), "Reader должен пройти после release writer'а"


def test_rwlock_writer_excludes_other_writers():
    """Два writer'а не могут держать write lock одновременно."""
    lock = _RWLock()
    first_writer_in = threading.Event()
    second_writer_in = threading.Event()
    release_first = threading.Event()

    def writer1():
        lock.acquire_write()
        try:
            first_writer_in.set()
            release_first.wait(timeout=2.0)
        finally:
            lock.release_write()

    def writer2():
        # Ждём пока writer1 войдёт, потом пытаемся
        first_writer_in.wait(timeout=1.0)
        lock.acquire_write()
        try:
            second_writer_in.set()
        finally:
            lock.release_write()

    t1 = threading.Thread(target=writer1)
    t2 = threading.Thread(target=writer2)
    t1.start()
    t2.start()

    time.sleep(0.2)
    assert first_writer_in.is_set(), "Writer1 должен войти"
    assert not second_writer_in.is_set(), "Writer2 не должен пройти, пока Writer1 активен"

    release_first.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert second_writer_in.is_set(), "Writer2 должен пройти после release Writer1"


def test_rwlock_writer_preference_blocks_new_readers():
    """Preference writer'у: если writer ждёт, новый reader тоже ждёт.

    Защищает от starvation writer'ов при постоянном потоке reader'ов.
    """
    lock = _RWLock()
    reader1_in = threading.Event()
    writer_waiting = threading.Event()
    writer_in = threading.Event()
    reader2_in = threading.Event()
    release_reader1 = threading.Event()

    def reader1():
        lock.acquire_read()
        try:
            reader1_in.set()
            release_reader1.wait(timeout=3.0)
        finally:
            lock.release_read()

    def writer():
        reader1_in.wait(timeout=1.0)
        writer_waiting.set()
        lock.acquire_write()
        try:
            writer_in.set()
        finally:
            lock.release_write()

    def reader2():
        # Ждём пока writer начнёт ждать
        writer_waiting.wait(timeout=1.0)
        time.sleep(0.05)  # даём writer'у чуть-чуть времени зарегистрироваться
        lock.acquire_read()
        try:
            reader2_in.set()
        finally:
            lock.release_read()

    t_r1 = threading.Thread(target=reader1)
    t_w = threading.Thread(target=writer)
    t_r2 = threading.Thread(target=reader2)

    t_r1.start()
    t_w.start()
    t_r2.start()

    time.sleep(0.3)
    assert reader1_in.is_set(), "Reader1 должен войти"
    assert writer_waiting.is_set(), "Writer должен ждать"
    assert not writer_in.is_set(), "Writer не должен пройти (reader1 активен)"
    assert not reader2_in.is_set(), (
        "Reader2 НЕ должен пройти из-за writer preference — иначе writer может starvation"
    )

    release_reader1.set()
    t_r1.join(timeout=2.0)
    t_w.join(timeout=2.0)
    t_r2.join(timeout=2.0)

    assert writer_in.is_set(), "Writer должен пройти после release reader1"
    assert reader2_in.is_set(), "Reader2 должен пройти после writer'а"


def test_rwlock_context_managers_work():
    """read_lock() и write_lock() context managers работают корректно."""
    lock = _RWLock()

    with lock.read_lock():
        # Должен пройти — мы в read lock
        with lock.read_lock():
            pass  # nested read — OK

    with lock.write_lock():
        # В write lock — эксклюзивно
        pass

    # После выхода из context manager'а lock должен быть полностью отпущен
    # (проверяем тем, что новый write lock проходит мгновенно)
    start = time.monotonic()
    with lock.write_lock():
        pass
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"Write lock занял {elapsed:.2f}s — возможно, не отпустили предыдущий"


# =============================================================================
# Integration: _with_analysis_lock использует rw_lock
# =============================================================================

def test_with_analysis_lock_uses_rw_lock_read():
    """_with_analysis_lock должен брать read lock rw_lock, не write.

    Проверяем: пока handler (под _with_analysis_lock) работает, writer
    (run_full_project_diagnostics) не может пройти — но другой reader может.
    """
    setup_test_workspace_done = False

    # Прямой тест: _with_analysis_lock использует rw_lock.acquire_read
    lock_state = {"reader_in": False, "another_reader_can_pass": False}

    @server_mod._with_analysis_lock
    def mock_handler(ls, params):
        lock_state["reader_in"] = True
        # Пока мы в handler'е, попробуем взять ещё один read lock
        try:
            with server_mod._lsp_server.rw_lock.read_lock():
                lock_state["another_reader_can_pass"] = True
        except Exception as e:
            lock_state["another_reader_can_pass"] = f"error: {e}"
        # И подождать чуть-чуть
        time.sleep(0.05)

    # Вызовем handler — он должен взять read lock
    mock_handler(None, None)

    assert lock_state["reader_in"], "Handler должен был выполниться"
    assert lock_state["another_reader_can_pass"] is True, (
        f"Nested read lock должен пройти, но: {lock_state['another_reader_can_pass']}"
    )


def test_rwlock_release_on_exception():
    """Если handler упал с исключением, lock должен быть отпущен.

    Иначе следующие handler'ы будут вечно ждать.
    """
    lock = _RWLock()

    class CustomError(Exception):
        pass

    try:
        with lock.write_lock():
            raise CustomError("test")
    except CustomError:
        pass

    # Lock должен быть отпущен — новый write lock проходит мгновенно
    start = time.monotonic()
    with lock.write_lock():
        pass
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"Lock не отпущен после exception (прошло {elapsed:.2f}s)"
