"""SQLAlchemy models for the staging schema (raw ERP imports, M2)."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base


class ImportRun(Base):
    """One row per import: source, status, per-entity stats, and the quality report."""

    __tablename__ = "import_run"
    __table_args__ = {"schema": "staging"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'running'")
    )  # running / completed / failed
    stats: Mapped[dict | None] = mapped_column(JSONB)
    report: Mapped[dict | None] = mapped_column(JSONB)


class StagingKupac(Base):
    """Raw customer row from the export (all payload columns TEXT)."""

    __tablename__ = "kupci"
    __table_args__ = (
        Index("ix_staging_kupci_run", "import_run_id"),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("staging.import_run.id"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sifra: Mapped[str | None] = mapped_column(Text)
    naziv: Mapped[str | None] = mapped_column(Text)
    jib: Mapped[str | None] = mapped_column(Text)
    naziv_pravnog_lica: Mapped[str | None] = mapped_column(Text)
    segment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    komercijalista: Mapped[str | None] = mapped_column(Text)


class StagingArtikal(Base):
    """Raw article row from the export."""

    __tablename__ = "artikli"
    __table_args__ = (
        Index("ix_staging_artikli_run", "import_run_id"),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("staging.import_run.id"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sifra: Mapped[str | None] = mapped_column(Text)
    naziv: Mapped[str | None] = mapped_column(Text)
    kategorija: Mapped[str | None] = mapped_column(Text)
    aktivan: Mapped[str | None] = mapped_column(Text)


class StagingFaktura(Base):
    """Raw invoice-header row from the export."""

    __tablename__ = "fakture"
    __table_args__ = (
        Index("ix_staging_fakture_run", "import_run_id"),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("staging.import_run.id"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    broj_fakture: Mapped[str | None] = mapped_column(Text)
    sifra_kupca: Mapped[str | None] = mapped_column(Text)
    datum: Mapped[str | None] = mapped_column(Text)
    ukupno: Mapped[str | None] = mapped_column(Text)


class StagingStavka(Base):
    """Raw invoice-line row from the export."""

    __tablename__ = "stavke"
    __table_args__ = (
        Index("ix_staging_stavke_run", "import_run_id"),
        {"schema": "staging"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("staging.import_run.id"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    broj_fakture: Mapped[str | None] = mapped_column(Text)
    sifra_artikla: Mapped[str | None] = mapped_column(Text)
    kolicina: Mapped[str | None] = mapped_column(Text)
    cijena: Mapped[str | None] = mapped_column(Text)
    iznos: Mapped[str | None] = mapped_column(Text)
