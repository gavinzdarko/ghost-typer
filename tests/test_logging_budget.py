import logging
from logging.handlers import RotatingFileHandler
import run


def test_logging_rotation_bounds_storage_and_reconfiguration(monkeypatch, tmp_path):
    logger = logging.Logger('isolated')
    external = logging.NullHandler()
    logger.addHandler(external)
    monkeypatch.setattr(run.logging, 'getLogger', lambda: logger)
    monkeypatch.setattr(run, 'LOG_DIR', tmp_path)
    monkeypatch.setattr(run, 'LOG_FILE', tmp_path / 'test.log')
    run.setup_logging()
    first_handlers = [h for h in logger.handlers if h is not external]
    run.setup_logging()
    assert len(logger.handlers) == 3
    assert external in logger.handlers
    assert all(h not in logger.handlers for h in first_handlers)
    file_handler = next(h for h in logger.handlers if isinstance(h, RotatingFileHandler))
    assert file_handler.maxBytes == 2 * 1024 * 1024
    assert file_handler.backupCount == 3
    # Exercise rollover with a small budget; use synthetic content only.
    file_handler.maxBytes = 150
    for _ in range(30):
        logger.info('x' * 50)
    for h in logger.handlers:
        h.close()
    logs = list(tmp_path.glob('test.log*'))
    assert len(logs) == 4
    assert sum(p.stat().st_size for p in logs) <= 600
    assert logger.level == logging.INFO
