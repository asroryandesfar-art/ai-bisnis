"""Unit test untuk konfigurasi connection pool (Phase 1: horizontal scaling).

Menguji build_pool_kwargs (pure) tanpa database live: default backward-compat,
override ukuran pool via Settings, kompatibilitas PgBouncer, dan normalisasi
nilai salah konfigurasi.
"""
import main


def _settings(**over):
    s = main.Settings()
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_default_pool_kwargs_preserve_legacy_behavior():
    # Default historis 2..20 harus dipertahankan (tidak boleh regresi).
    kwargs = main.build_pool_kwargs(_settings())
    assert kwargs == {"min_size": 2, "max_size": 20}


def test_pool_sizes_are_configurable():
    kwargs = main.build_pool_kwargs(_settings(db_pool_min_size=5, db_pool_max_size=50))
    assert kwargs["min_size"] == 5
    assert kwargs["max_size"] == 50


def test_pgbouncer_disables_statement_cache():
    kwargs = main.build_pool_kwargs(_settings(db_pgbouncer=True))
    assert kwargs["statement_cache_size"] == 0


def test_pgbouncer_off_leaves_statement_cache_default():
    kwargs = main.build_pool_kwargs(_settings(db_pgbouncer=False))
    assert "statement_cache_size" not in kwargs


def test_misconfigured_sizes_are_clamped_to_valid_range():
    # max_size tidak boleh < 1; min_size tidak boleh > max_size.
    kwargs = main.build_pool_kwargs(_settings(db_pool_min_size=99, db_pool_max_size=0))
    assert kwargs["max_size"] >= 1
    assert kwargs["min_size"] <= kwargs["max_size"]
