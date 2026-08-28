-- Enable PostGIS extension if available (optional for basic bounds)
CREATE EXTENSION IF NOT EXISTS postgis;

-- Spatial Blocks Registry
CREATE TABLE IF NOT EXISTS spatial_blocks (
    block_id VARCHAR(20) PRIMARY KEY, -- e.g., '72E_18N'
    min_lat NUMERIC(6,3) NOT NULL,
    max_lat NUMERIC(6,3) NOT NULL,
    min_lng NUMERIC(6,3) NOT NULL,
    max_lng NUMERIC(6,3) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Datasets & Layers attached to blocks
CREATE TABLE IF NOT EXISTS datasets (
    id SERIAL PRIMARY KEY,
    block_id VARCHAR(20) REFERENCES spatial_blocks(block_id) ON DELETE CASCADE,
    theme VARCHAR(50) NOT NULL,            -- 'Terrain (DEM)', 'Satellite', 'Rainfall', 'Soil'
    dataset_name VARCHAR(200) NOT NULL,   -- e.g., 'C1_DEM_16b_2006-2008_v1_72E18N_e43g'
    source VARCHAR(100) DEFAULT 'ISRO/NRSC',
    resolution VARCHAR(50),               -- e.g., '1 arc sec'
    image_url TEXT,                        -- Path to uploaded map overlay file
    raw_xml_metadata JSONB,               -- Stores parsed Bhuvan XML attributes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast spatial queries
CREATE INDEX IF NOT EXISTS idx_block_coords ON spatial_blocks (min_lng, min_lat, max_lng, max_lat);
