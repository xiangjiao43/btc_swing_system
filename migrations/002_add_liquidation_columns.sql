-- Sprint 2.6-B Commit 2:扩展 derivatives_snapshots 宽表加 3 个 liquidation 列
-- 配合 src/data/storage/dao.py 的 _DERIVATIVES_WIDE_COLUMNS + DerivativesDAO.upsert_batch
-- ON CONFLICT 子句必须 COALESCE 这 3 个新列(否则增量 UPSERT 会覆盖回 NULL)

ALTER TABLE derivatives_snapshots ADD COLUMN liquidation_long  REAL;
ALTER TABLE derivatives_snapshots ADD COLUMN liquidation_short REAL;
ALTER TABLE derivatives_snapshots ADD COLUMN liquidation_total REAL;
