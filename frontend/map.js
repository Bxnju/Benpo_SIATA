class MapManager {
    constructor() {
        this.map = null;
        this.markers = [];
        this.stationsData = {};
        this.heatmapLayer = null;
        this.currentHeatmapType = null; // ninguno al inicio
        this.stationsVisible = true;
    }

    initMap() {
        // Inicializar mapa centrado en Medellín
        if (this.map) return this.map;
        this.map = L.map('map').setView([6.2442, -75.5812], 11);

        // Agregar capa de OpenStreetMap
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(this.map);

        // Crear controles del heatmap
        this.createHeatmapControls();

        return this.map;
    }

    createHeatmapControls() {
        const controlsHTML = `
            <div class="heatmap-controls">
                <h3>🗺️ Controles del Mapa</h3>
                <div class="heatmap-status" id="heatmap-status">Heatmap: <span class="status-value">Ninguno</span></div>
                <div class="control-section">
                    <h4>Heatmap</h4>
                    <div class="heatmap-buttons">
                        <button class="heatmap-btn" data-type="temperature" onclick="mapManager.showHeatmap('temperature')">
                            🌡️ Temperatura
                        </button>
                        <button class="heatmap-btn" data-type="humidity" onclick="mapManager.showHeatmap('humidity')">
                            💧 Humedad
                        </button>
                        <button class="heatmap-btn clear" onclick="mapManager.clearHeatmap()">
                            ❌ Limpiar
                        </button>
                    </div>
                </div>
                <div class="control-section">
                    <h4>Estaciones</h4>
                    <button class="control-btn" onclick="mapManager.toggleStations()" id="toggle-stations-btn">
                        👁️ Ocultar Estaciones
                    </button>
                    <button class="control-btn" onclick="mapManager.refreshData()">
                        🔄 Actualizar Datos
                    </button>
                </div>
                <div id="heatmap-legend" class="heatmap-legend" style="display:none;">
                    <h4>Leyenda</h4>
                    <div class="legend-gradient"></div>
                    <div class="legend-labels"><span class="legend-min"></span><span class="legend-max"></span></div>
                </div>
            </div>`;

        // Agregar controles al mapa
        const controlsDiv = document.createElement('div');
        controlsDiv.innerHTML = controlsHTML;
        controlsDiv.className = 'map-controls-container';
        
        const mapContainer = document.getElementById('map');
        if (mapContainer && mapContainer.parentNode) {
            mapContainer.parentNode.insertBefore(controlsDiv, mapContainer);
        }
    }

    async loadStationsData(silent=false) {
        try {
            if (!silent) console.log('Cargando datos de estaciones...');
            const response = await apiClient.getAllStationsData();
            if (response.success) {
                this.stationsData = response.data;
                if (!silent) console.log('Estaciones:', Object.keys(this.stationsData).length);
                this.addStationsToMap();
                if (!this.currentHeatmapType) this.showHeatmap('temperature');
            } else if (!silent) console.error('Error estaciones:', response.error);
            return this.stationsData;
        } catch (e) { if (!silent) console.error(e); throw e; }
    }

    addStationsToMap() {
        // Limpiar marcadores existentes
        this.clearMarkers();

        if (!this.stationsData || typeof this.stationsData !== 'object') {
            console.warn('No hay datos de estaciones válidos');
            return;
        }

        Object.keys(this.stationsData).forEach(id => {
            const station = this.stationsData[id];
            if (station && station.info) {
                const marker = this.createStationMarker(station);
                if (marker) { this.markers.push(marker); if (this.stationsVisible) marker.addTo(this.map); }
            }
        });

        console.log(`Agregados ${this.markers.length} marcadores al mapa`);
    }

    createStationMarker(stationData) {
        const info = stationData.info;
        const lat = info.latitud, lng = info.longitud;

        if (!lat || !lng) return null;

        // Crear icono personalizado basado en el tipo de datos disponibles
        const hasTemp = stationData.t && stationData.t !== '-999';
        const hasHum = stationData.h && stationData.h !== '-999';
        const hasRain = stationData.p1h !== undefined || stationData['1h'] !== undefined;

        let tone = 'var(--marker-blue, #4cb3ff)';
        if (hasTemp && hasHum && hasRain) tone = 'var(--marker-full, #2bd4ff)';
        else if (hasTemp || hasHum) tone = 'var(--marker-partial, #5a85ff)';

        const customIcon = L.divIcon({
            className: 'custom-station-marker',
            html: `<div class="station-chip" style="background:${tone};"></div>`,
            iconSize: [14,14],
            iconAnchor: [7,7]
        });

        const marker = L.marker([lat,lng], { icon: customIcon, keyboard:false });

        const tooltipHtml = this.createTooltipContent(stationData);
        marker.bindTooltip(tooltipHtml, { direction:'top', offset:[0,-4], opacity:0.95, className:'station-tooltip', permanent:false, sticky:true });

        return marker;
    }

    createTooltipContent(stationData) {
        const info = stationData.info;
        const parts = [];
        parts.push(`<div class='tt-name'>${info.nombre || 'Estación'}</div>`);
        if (stationData.t && stationData.t !== '-999') parts.push(`<div class='tt-line'>🌡️ ${stationData.t}°C</div>`);
        if (stationData.h && stationData.h !== '-999') parts.push(`<div class='tt-line'>💧 ${stationData.h}%</div>`);
        if (stationData.wd !== undefined && stationData.ws !== undefined && stationData.wd !== '-999' && stationData.ws !== '-999') {
            // Calcular dirección cardinal del viento
            const wd = parseFloat(stationData.wd);
            const ws = parseFloat(stationData.ws);
            const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW', 'N'];
            const idx = Math.round(((wd % 360) / 22.5));
            const cardinal = directions[idx];
            parts.push(`<div class='tt-line'>💨 ${ws} m/s (${cardinal})</div>`);
        }
        if (stationData.p && stationData.p !== '-999') {
            parts.push(`<div class='tt-line'>🌬️ ${stationData.p} hPa</div>`);
        }
        return `<div class='station-tt'>${parts.join('')}</div>`;
    }

    showHeatmap(type) {
        this.currentHeatmapType = type;
        
        // Actualizar botones activos
        document.querySelectorAll('.heatmap-btn').forEach(b=>b.classList.remove('active'));
        const btn = document.querySelector(`.heatmap-btn[data-type="${type}"]`);
        if (btn) btn.classList.add('active');

        // Limpiar heatmap anterior
        this.clearHeatmap(false);

        // Crear datos del heatmap
        const data = this.generateHeatmapData(type);
        
        if (!data.length) { this.updateHeatmapStatus('Ninguno (sin datos)'); return; }
        // Verificar si L.heatLayer está disponible
        if (typeof L.heatLayer !== 'function') { this.updateHeatmapStatus('Plugin faltante'); return; }

        // Crear el heatmap
        try {
            this.heatmapLayer = L.heatLayer(data, { radius:38, blur:24, maxZoom:15, gradient:this.getHeatmapGradient(type) }).addTo(this.map);

            // Mostrar leyenda
            this.showHeatmapLegend(type, data);
            this.updateHeatmapStatus(type === 'temperature' ? 'Temperatura' : 'Humedad');
        } catch (e) { console.error(e); this.updateHeatmapStatus('Error'); }
    }

    updateHeatmapStatus(label) {
        const el = document.getElementById('heatmap-status');
        if (el) el.querySelector('.status-value').textContent = label;
    }

    toggleStations() {
        this.stationsVisible = !this.stationsVisible;
        const btn = document.getElementById('toggle-stations-btn');
        if (this.stationsVisible) {
            this.markers.forEach(m=> m.addTo(this.map));
            if (btn) btn.textContent = '👁️ Ocultar Estaciones';
        } else {
            this.markers.forEach(m=> this.map.removeLayer(m));
            if (btn) btn.textContent = '👁️ Mostrar Estaciones';
        }
    }

    generateHeatmapData(type) {
        const data = [];
        
        if (!this.stationsData || typeof this.stationsData !== 'object') {
            console.warn('No hay datos de estaciones para generar heatmap');
            return data;
        }
        
        Object.values(this.stationsData).forEach(station => {
            if (!station || !station.info || !station.info.latitud || !station.info.longitud) {
                return;
            }
            
            let value;
            switch (type) {
                case 'temperature':
                    value = station.t && station.t !== '-999' ? parseFloat(station.t) : null;
                    break;
                case 'humidity':
                    value = station.h && station.h !== '-999' ? parseFloat(station.h) : null;
                    break;
                default:
                    return;
            }

            if (value !== null && !isNaN(value)) {
                data.push([
                    parseFloat(station.info.latitud),
                    parseFloat(station.info.longitud),
                    this.normalizeValue(value, type)
                ]);
            }
        });

        console.log(`Generados ${data.length} puntos para heatmap de ${type}`);
        return data;
    }

    normalizeValue(value, type) {
        // Normalizar valores para el heatmap (0-1)
        switch (type) {
            case 'temperature':
                // Temperatura típica en Medellín: 15-35°C
                return Math.max(0, Math.min(1, (value - 15) / 20));
            case 'humidity':
                // Humedad: 0-100%
                return Math.max(0, Math.min(1, value / 100));
            default:
                return 0.5;
        }
    }

    getHeatmapGradient(type) {
        switch (type) {
            case 'temperature':
                return {
                    0.0: '#0000ff',  // Azul (frío)
                    0.3: '#00ffff',  // Cian
                    0.5: '#00ff00',  // Verde
                    0.7: '#ffff00',  // Amarillo
                    0.9: '#ff8000',  // Naranja
                    1.0: '#ff0000'   // Rojo (caliente)
                };
            case 'humidity':
                return {
                    0.0: '#8B4513',  // Marrón (seco)
                    0.2: '#DAA520',  // Dorado
                    0.4: '#FFFF00',  // Amarillo
                    0.6: '#00FF00',  // Verde
                    0.8: '#0080FF',  // Azul claro
                    1.0: '#0000FF'   // Azul (húmedo)
                };
            default:
                return {};
        }
    }

    showHeatmapLegend(type, data) {
        const legend = document.getElementById('heatmap-legend');
        if (!legend) return;

        const values = data.map(point => point[2]);
        const minValue = Math.min(...values);
        const maxValue = Math.max(...values);

        let unit, minLabel, maxLabel;
        switch (type) {
            case 'temperature':
                unit = '°C';
                minLabel = '15°C';
                maxLabel = '35°C';
                break;
            case 'humidity':
                unit = '%';
                minLabel = '0%';
                maxLabel = '100%';
                break;
        }

        const gradient = this.getHeatmapGradient(type);
        const gradientColors = Object.values(gradient);
        
        legend.querySelector('.legend-gradient').style.background = 
            `linear-gradient(to right, ${gradientColors.join(', ')})`;
        legend.querySelector('.legend-min').textContent = minLabel;
        legend.querySelector('.legend-max').textContent = maxLabel;
        
        legend.style.display = 'block';
    }

    showHeatmapMessage(message) {
        // Mostrar mensaje temporal
        const messageDiv = document.createElement('div');
        messageDiv.className = 'heatmap-message';
        messageDiv.textContent = message;
        messageDiv.style.cssText = `
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(0,0,0,0.8);
            color: white;
            padding: 10px;
            border-radius: 5px;
            z-index: 1000;
        `;
        
        document.getElementById('map').appendChild(messageDiv);
        setTimeout(() => messageDiv.remove(), 3000);
    }

    clearHeatmap(updateStatus=true) {
        if (this.heatmapLayer) { this.map.removeLayer(this.heatmapLayer); this.heatmapLayer = null; }
        const legend = document.getElementById('heatmap-legend'); if (legend) legend.style.display='none';
        if (updateStatus) this.updateHeatmapStatus('Ninguno');
        document.querySelectorAll('.heatmap-btn').forEach(btn=>btn.classList.remove('active'));
        this.currentHeatmapType = null;
    }

    clearMarkers(){ this.markers.forEach(m=> this.map.removeLayer(m)); this.markers=[]; }

    refreshData(){ return this.loadStationsData(); }
}
const mapManager = new MapManager();