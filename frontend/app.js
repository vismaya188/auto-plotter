document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const input = document.getElementById('prompt-input');
    const btn = document.getElementById('analyze-btn');
    const statusContainer = document.getElementById('status-container');
    const errorContainer = document.getElementById('error-container');
    const errorText = document.getElementById('error-text');
    const resultsSection = document.getElementById('results-section');
    
    const plotlyDiv = document.getElementById('plotly-div');
    const factText = document.getElementById('fact-text');
    const insightText = document.getElementById('insight-text');
    const actionText = document.getElementById('action-text');
    const sqlText = document.getElementById('sql-text');

    // Data Source Elements
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const dsStatus = document.getElementById('ds-status');
    const currentDsBadge = document.getElementById('current-ds-badge');
    
    // Connect Buttons
    const uploadBtn = document.getElementById('upload-btn');
    const urlBtn = document.getElementById('url-btn');
    const pgBtn = document.getElementById('pg-btn');

    let currentSessionId = null;

    // --- Tab Switching ---
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
            dsStatus.classList.add('hidden');
        });
    });

    // --- Data Source Connection Logic ---
    function showDsStatus(message, isError = false) {
        dsStatus.textContent = message;
        dsStatus.className = `ds-status ${isError ? 'error' : 'success'}`;
        dsStatus.classList.remove('hidden');
    }

    function handleConnectSuccess(data) {
        currentSessionId = data.session_id;
        currentDsBadge.textContent = data.source_label;
        currentDsBadge.classList.remove('default-badge');
        currentDsBadge.classList.add('active-badge');
        showDsStatus(`Connected! Found ${data.row_count} rows and ${data.columns.length} columns.`);
    }

    // 1. File Upload
    uploadBtn.addEventListener('click', async () => {
        const fileInput = document.getElementById('file-input');
        if (!fileInput.files.length) {
            showDsStatus('Please select a file first.', true);
            return;
        }

        uploadBtn.disabled = true;
        uploadBtn.textContent = 'Uploading...';
        showDsStatus('Uploading and parsing file...', false);

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        if (currentSessionId) formData.append('session_id', currentSessionId);

        try {
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Upload failed');
            handleConnectSuccess(data);
        } catch (err) {
            showDsStatus(err.message, true);
        } finally {
            uploadBtn.disabled = false;
            uploadBtn.textContent = 'Load File';
        }
    });

    // 2. URL Connect
    urlBtn.addEventListener('click', async () => {
        const urlInput = document.getElementById('url-input');
        if (!urlInput.value.trim()) {
            showDsStatus('Please enter a URL.', true);
            return;
        }

        urlBtn.disabled = true;
        urlBtn.textContent = 'Connecting...';
        showDsStatus('Fetching from URL...', false);

        try {
            const response = await fetch('/connect/url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    url: urlInput.value.trim(),
                    session_id: currentSessionId 
                })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Connection failed');
            handleConnectSuccess(data);
        } catch (err) {
            showDsStatus(err.message, true);
        } finally {
            urlBtn.disabled = false;
            urlBtn.textContent = 'Connect';
        }
    });

    // 3. PostgreSQL Connect
    pgBtn.addEventListener('click', async () => {
        const host = document.getElementById('pg-host').value.trim();
        const port = document.getElementById('pg-port').value;
        const dbname = document.getElementById('pg-dbname').value.trim();
        const user = document.getElementById('pg-user').value.trim();
        const password = document.getElementById('pg-password').value;
        const table_name = document.getElementById('pg-table').value.trim();

        if (!host || !dbname || !user || !password || !table_name) {
            showDsStatus('Please fill in all database fields.', true);
            return;
        }

        pgBtn.disabled = true;
        pgBtn.textContent = 'Connecting...';
        showDsStatus('Connecting and syncing table...', false);

        try {
            const response = await fetch('/connect/postgres', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    host, port: parseInt(port), dbname, user, password, table_name,
                    session_id: currentSessionId
                })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Connection failed');
            handleConnectSuccess(data);
        } catch (err) {
            showDsStatus(err.message, true);
        } finally {
            pgBtn.disabled = false;
            pgBtn.textContent = 'Connect DB';
        }
    });


    // --- Agent Query Logic ---
    const darkLayout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#f8fafc', family: 'Inter, sans-serif' },
        xaxis: { 
            gridcolor: 'rgba(255,255,255,0.1)',
            zerolinecolor: 'rgba(255,255,255,0.2)'
        },
        yaxis: { 
            gridcolor: 'rgba(255,255,255,0.1)',
            zerolinecolor: 'rgba(255,255,255,0.2)'
        }
    };

    btn.addEventListener('click', runQuery);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') runQuery();
    });

    async function runQuery() {
        const prompt = input.value.trim();
        if (!prompt) return;

        btn.disabled = true;
        input.disabled = true;
        errorContainer.classList.add('hidden');
        resultsSection.classList.add('hidden');
        statusContainer.classList.remove('hidden');
        Plotly.purge(plotlyDiv);

        try {
            const body = { prompt };
            if (currentSessionId) body.session_id = currentSessionId;

            const response = await fetch('/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Failed to process request (HTTP Error)');
            }

            if (data.status === 'failed' || data.errors) {
                throw new Error(data.errors || 'The agent completely failed to process the request.');
            }

            // Populate Insights
            const insights = data.insights || {};
            factText.textContent = insights.fact || 'No data facts found.';
            insightText.textContent = insights.insight || 'No insights generated.';
            actionText.textContent = insights.action || 'No actions recommended.';

            // Populate SQL Trace
            sqlText.textContent = data.generated_sql || 'No SQL generated.';

            // Render Visualization
            const viz = data.visualization || {};
            const insightContainer = document.querySelector('.insight-container');
            const sqlContainer = document.querySelector('.sql-container');

            if (viz.chart_type === 'message') {
                plotlyDiv.innerHTML = `<div style="color: #f8fafc; font-size: 1.2rem; text-align: center; margin-top: 150px; padding: 0 20px;">${viz.message}</div>`;
                if (insightContainer) insightContainer.style.display = 'none';
                if (sqlContainer) sqlContainer.style.display = 'none';
            } else {
                if (insightContainer) insightContainer.style.display = 'block';
                if (sqlContainer) sqlContainer.style.display = 'block';

                if (viz.plotly_json) {
                    const parsedFig = viz.plotly_json;
                    const layout = Object.assign({}, parsedFig.layout, darkLayout);
                    Plotly.newPlot(plotlyDiv, parsedFig.data, layout, {responsive: true, displayModeBar: false});
                } else if (viz.chart_type === 'kpi' && viz.plotly_json) {
                    const kpiData = viz.plotly_json.data[0];
                    const value = kpiData.value;
                    const titleText = (kpiData.title && kpiData.title.text) ? kpiData.title.text : 'Metric';
                    const title = titleText.replace(/_/g, ' ').toUpperCase();
                    
                    let formattedValue = value;
                    if (typeof value === 'number') {
                        if (value >= 1e9) formattedValue = (value / 1e9).toFixed(2) + 'B';
                        else if (value >= 1e6) formattedValue = (value / 1e6).toFixed(2) + 'M';
                        else if (value >= 1000) formattedValue = (value / 1000).toFixed(1) + 'K';
                        else formattedValue = value.toLocaleString();
                    }

                    plotlyDiv.innerHTML = `
                        <div class="custom-kpi-container">
                            <div class="kpi-glass-card">
                                <h3 class="kpi-title">${title}</h3>
                                <div class="kpi-value">${formattedValue}</div>
                                <div class="kpi-glow"></div>
                            </div>
                        </div>
                    `;
                } else {
                    plotlyDiv.innerHTML = '<div style="color: #94a3b8; text-align: center; margin-top: 200px;">Table output generated. Please refer to raw data or adjust query for a chart.</div>';
                }
            }

            resultsSection.classList.remove('hidden');

        } catch (err) {
            errorText.textContent = err.message;
            errorContainer.classList.remove('hidden');
        } finally {
            statusContainer.classList.add('hidden');
            btn.disabled = false;
            input.disabled = false;
            input.focus();
        }
    }
});
