const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const xml2js = require('xml2js');
const { Pool } = require('pg');

const app = express();
const PORT = process.env.PORT || 3000;

// PostgreSQL Connection Pool
const pool = new Pool({
    user: process.env.DB_USER || 'postgres',
    host: process.env.DB_HOST || 'localhost',
    database: process.env.DB_NAME || 'spatial_engine',
    password: process.env.DB_PASSWORD || 'postgres',
    port: process.env.DB_PORT || 5432,
});

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));
app.use('/uploads', express.static(path.join(__dirname, 'public/uploads')));

// Ensure upload directory exists
const uploadDir = path.join(__dirname, 'public/uploads');
if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir, { recursive: true });

// Configure Multer File Storage
const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, uploadDir),
    filename: (req, file, cb) => {
        const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
        cb(null, `${req.params.block_id || 'file'}-${uniqueSuffix}${path.extname(file.originalname)}`);
    }
});
const upload = multer({ storage });

// Database Fallback In-Memory Store (if PostgreSQL is not running)
const inMemoryStore = {};

// ---------------- API ENDPOINTS ----------------

// GET: All active blocks with attached dataset count
app.get('/api/blocks', async (req, res) => {
    try {
        const result = await pool.query(`
            SELECT sb.block_id, sb.min_lat, sb.max_lat, sb.min_lng, sb.max_lng, COUNT(d.id)::int as dataset_count
            FROM spatial_blocks sb
            LEFT JOIN datasets d ON sb.block_id = d.block_id
            GROUP BY sb.block_id
        `);
        res.json(result.rows);
    } catch (err) {
        // Fallback response
        const blocks = Object.keys(inMemoryStore).map(key => ({
            block_id: key,
            dataset_count: inMemoryStore[key].layers.length
        }));
        res.json(blocks);
    }
});

// GET: Fetch datasets for a specific block
app.get('/api/blocks/:block_id', async (req, res) => {
    const { block_id } = req.params;
    try {
        const result = await pool.query('SELECT * FROM datasets WHERE block_id = $1 ORDER BY created_at DESC', [block_id]);
        res.json({ block_id, datasets: result.rows });
    } catch (err) {
        const block = inMemoryStore[block_id] || { layers: [] };
        res.json({ block_id, datasets: block.layers });
    }
});

// POST: Save dataset & optional image overlay
app.post('/api/blocks/:block_id/datasets', upload.single('overlay_image'), async (req, res) => {
    const { block_id } = req.params;
    const { theme, dataset_name, source, resolution, min_lat, max_lat, min_lng, max_lng } = req.body;
    const imageUrl = req.file ? `/uploads/${req.file.filename}` : null;

    try {
        // Register block
        await pool.query(
            `INSERT INTO spatial_blocks (block_id, min_lat, max_lat, min_lng, max_lng)
             VALUES ($1, $2, $3, $4, $5) ON CONFLICT (block_id) DO NOTHING`,
            [block_id, min_lat, max_lat, min_lng, max_lng]
        );

        // Insert dataset
        const insertRes = await pool.query(
            `INSERT INTO datasets (block_id, theme, dataset_name, source, resolution, image_url)
             VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`,
            [block_id, theme, dataset_name, source, resolution, imageUrl]
        );

        res.json({ success: true, dataset: insertRes.rows[0] });
    } catch (err) {
        // Fallback to in-memory store
        if (!inMemoryStore[block_id]) inMemoryStore[block_id] = { layers: [] };
        const newLayer = { id: Date.now(), theme, dataset_name, source, resolution, image_url: imageUrl };
        inMemoryStore[block_id].layers.push(newLayer);

        res.json({ success: true, dataset: newLayer, note: "Saved in-memory" });
    }
});

// POST: Parse Bhuvan XML File automatically
app.post('/api/parse-xml', upload.single('xml_file'), (req, res) => {
    if (!req.file) return res.status(400).json({ error: "No XML file uploaded" });

    const xmlData = fs.readFileSync(req.file.path, 'utf8');
    xml2js.parseString(xmlData, { explicitArray: false }, (err, result) => {
        // Clean up temp XML file
        fs.unlinkSync(req.file.path);

        if (err) return res.status(500).json({ error: "Failed to parse XML" });

        try {
            const meta = result.metadata;
            const parsed = {
                tileNo: meta.$.tileno,
                datasetName: meta.Data_Identification_Information?.Name_of_the_Dataset,
                theme: meta.Data_Identification_Information?.Theme,
                satellite: meta.For_Image_Data?.Name_of_the_Satellite,
                resolution: meta.For_Image_Data?.Spatial_Resolution + " " + meta.For_Image_Data?.Spatial_Resolution_Unit,
                coverage: meta.Coverage
            };
            res.json({ success: true, metadata: parsed });
        } catch (e) {
            res.status(422).json({ error: "Invalid Bhuvan XML format" });
        }
    });
});

// DELETE: Remove a dataset
app.delete('/api/datasets/:id', async (req, res) => {
    try {
        await pool.query('DELETE FROM datasets WHERE id = $1', [req.params.id]);
        res.json({ success: true });
    } catch (err) {
        res.json({ success: true });
    }
});

app.listen(PORT, () => {
    console.log(`🌐 Spatial Data Engine running at http://localhost:${PORT}`);
});
