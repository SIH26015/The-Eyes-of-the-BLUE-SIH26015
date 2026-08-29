from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Date, Boolean, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from pathlib import Path
from module0.models import DatasetType, BlockStatus, RequirementStatus

DB_PATH = Path(__file__).resolve().parent.parent.parent / "module0.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class StudyAreaDB(Base):
    __tablename__ = "study_areas"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    min_lat = Column(Float, nullable=False)
    max_lat = Column(Float, nullable=False)
    min_lon = Column(Float, nullable=False)
    max_lon = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class DataRequirementDB(Base):
    __tablename__ = "data_requirements"
    id = Column(String, primary_key=True)
    study_area_id = Column(String, ForeignKey("study_areas.id"), nullable=False)
    dataset_type = Column(SQLEnum(DatasetType), nullable=False)
    status = Column(SQLEnum(RequirementStatus), default=RequirementStatus.REQUIRED)

    temporal = Column(Text, default="{}")
    spatial_coverage = Column(String, default="entire_watershed")
    source_primary = Column(String)
    source_alternative = Column(String)
    source_backup = Column(String)
    required_bands = Column(Text, default="[]")
    purpose = Column(Text)
    expected_count = Column(Integer, default=0)
    collected_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class GridBlockDB(Base):
    __tablename__ = "grid_blocks"
    id = Column(String, primary_key=True)
    study_area_id = Column(String, ForeignKey("study_areas.id"), nullable=False)
    grid_id = Column(String, nullable=False)
    lat_min = Column(Float, nullable=False)
    lat_max = Column(Float, nullable=False)
    lon_min = Column(Float, nullable=False)
    lon_max = Column(Float, nullable=False)
    status = Column(SQLEnum(BlockStatus), default=BlockStatus.MISSING)
    locked = Column(Boolean, default=False)
    datasets = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AcquisitionGridDB(Base):
    __tablename__ = "acquisition_grids"
    id = Column(String, primary_key=True)
    study_area_id = Column(String, ForeignKey("study_areas.id"), nullable=False)
    name = Column(String, nullable=False)
    grid_size_lat = Column(Float, nullable=False)
    grid_size_lon = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CollectionSessionDB(Base):
    __tablename__ = "collection_sessions"
    id = Column(String, primary_key=True)
    date = Column(Date, nullable=False)
    collector = Column(String, nullable=False)
    source = Column(String, nullable=False)
    dataset_type = Column(SQLEnum(DatasetType), nullable=False)
    files_collected = Column(Integer, default=0)
    area = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class CatalogEntryDB(Base):
    __tablename__ = "catalog"
    id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    dataset_type = Column(SQLEnum(DatasetType), nullable=False)
    tile_or_block = Column(String)
    bounds_min_lat = Column(Float)
    bounds_max_lat = Column(Float)
    bounds_min_lon = Column(Float)
    bounds_max_lon = Column(Float)
    crs = Column(String)
    resolution = Column(String)
    date_collected = Column(Date)
    source_used = Column(String)
    session_id = Column(String, ForeignKey("collection_sessions.id"))
    dataset_metadata = Column("metadata", Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
