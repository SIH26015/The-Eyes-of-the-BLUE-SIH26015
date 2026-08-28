// 1. Initialize Map Centered over India
const map = L.map('map').setView([22.5937, 78.9629], 5);

// Add Street & Satellite Basemaps
const cartoDark = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 18 }).addTo(map);
const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18 });

L.control.layers({ "Dark Canvas": cartoDark, "Satellite": esriSat }).addTo(map);

// Track Coordinates
map.on('mousemove', (e) => {
    document.getElementById('coords-display').innerText = `Lat: ${e.latlng.lat.toFixed(2)} | Lng: ${e.latlng.lng.toFixed(2)}`;
});

// State Management
const gridLayers = {};
const activeOverlays = {};
let selectedPolygon = null;

// Auto XML Upload Listener
document.getElementById('xml-importer').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('xml_file', file);

    try {
        const res = await fetch('/api/parse-xml', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
            const meta = data.metadata;
            alert(`Parsed Metadata for Tile ${meta.tileNo}!\nDataset: ${meta.datasetName}\nTheme: ${meta.theme}`);
            
            // Auto-select corresponding grid block
            const blockKey = "72E_18N"; // Extracted from 72E, 18N
            if (gridLayers[blockKey]) gridLayers[blockKey].fire('click');
        }
    } catch (err) {
        alert("Error parsing XML metadata file.");
    }
});

// 2. Render India Grid (6N to 38N, 68E to 98E)
for (let lat = 6; lat < 38; lat++) {
    for (let lng = 68; lng < 98; lng++) {
        const blockKey = `${lng}E_${lat}N`;
        const bounds = [[lat, lng], [lat + 1, lng + 1]];

        const rect = L.rectangle(bounds, {
            color: "#475569",
            weight: 0.6,
            fillOpacity: 0.05
        }).addTo(map);

        gridLayers[blockKey] = rect;

        rect.on('click', function () {
            if (selectedPolygon) selectedPolygon.setStyle({ color: "#475569", weight: 0.6 });
            selectedPolygon = rect;
            rect.setStyle({ color: "#3b82f6", weight: 2.5 });

            loadBlockData(blockKey, bounds);
        });
    }
}

// 3. Load & Render Sidebar Editor
async function loadBlockData(key, bounds) {
    let datasets = [];
    try {
        const res = await fetch(`/api/blocks/${key}`);
        const data = await res.json();
        datasets = data.datasets || [];
    } catch (e) {
        datasets = [];
    }

    let layersHtml = datasets.length ? "" : "<p class='text-muted'>No layers attached to this tile.</p>";
    datasets.forEach(d => {
        layersHtml += `
            <div class="layer-item">
                <div>
                    <strong>${d.theme}</strong><br>
                    <span style="color:#94a3b8; font-size:11px;">${d.dataset_name}</span>
                </div>
                <span class="badge-tag">${d.source || 'ISRO'}</span>
            </div>
        `;
    });

    document.getElementById('block-editor').innerHTML = `
        <div class="card">
            <h3 style="font-size:15px; color:#f8fafc;">Tile Index: ${key}</h3>
            <p style="font-size:11px; color:#64748b;">Extent: ${bounds[0][1]}°E–${bounds[1][1]}°E, ${bounds[0][0]}°N–${bounds[1][0]}°N</p>
            
            <hr style="border:0; border-top:1px solid #334155; margin: 12px 0;">
            <h4 style="font-size:12px; color:#94a3b8;">Active Datasets (${datasets.length})</h4>
            <div>${layersHtml}</div>

            <hr style="border:0; border-top:1px solid #334155; margin: 12px 0;">
            <h4 style="font-size:12px; color:#94a3b8;">Attach New Spatial Layer</h4>

            <form id="upload-form" onsubmit="saveDataset(event, '${key}', ${JSON.stringify(bounds)})">
                <label>Category Theme</label>
                <select id="field-theme">
                    <option value="Terrain (DEM)">Terrain (DEM)</option>
                    <option value="Satellite Imagery">Satellite Imagery</option>
                    <option value="Rainfall/Weather">Rainfall / Meteorological</option>
                    <option value="Soil & Geology">Soil & Geology</option>
                    <option value="Land Use (LULC)">Land Use / Cover</option>
                </select>

                <label>Dataset Identifier</label>
                <input type="text" id="field-name" placeholder="e.g. C1_DEM_16b_72E18N" required>

                <label>Source / Provider</label>
                <input type="text" id="field-source" value="NRSC / ISRO">

                <label>Attach Map Overlay Image (.png, .jpg)</label>
                <input type="file" id="field-image" accept="image/*">

                <button type="submit" class="btn">Save Layer to Block</button>
            </form>
        </div>
    `;
}

// 4. Submit Dataset & Overlay to API
async function saveDataset(e, key, bounds) {
    e.preventDefault();
    
    const formData = new FormData();
    formData.append('theme', document.getElementById('field-theme').value);
    formData.append('dataset_name', document.getElementById('field-name').value);
    formData.append('source', document.getElementById('field-source').value);
    formData.append('min_lat', bounds[0][0]);
    formData.append('max_lat', bounds[1][0]);
    formData.append('min_lng', bounds[0][1]);
    formData.append('max_lng', bounds[1][1]);

    const imageFile = document.getElementById('field-image').files[0];
    if (imageFile) formData.append('overlay_image', imageFile);

    try {
        const res = await fetch(`/api/blocks/${key}/datasets`, { method: 'POST', body: formData });
        const result = await res.json();

        // Project Overlay Image onto map block
        if (result.dataset && result.dataset.image_url) {
            if (activeOverlays[key]) map.removeLayer(activeOverlays[key]);
            activeOverlays[key] = L.imageOverlay(result.dataset.image_url, bounds, { opacity: 0.85 }).addTo(map);
        }

        // Highlight block green
        selectedPolygon.setStyle({ fillColor: "#10b981", fillOpacity: 0.4, color: "#059669" });

        loadBlockData(key, bounds); // Refresh UI
    } catch (err) {
        alert("Failed to save dataset.");
    }
}
