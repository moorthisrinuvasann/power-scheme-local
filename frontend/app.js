// Initialize mermaid
mermaid.initialize({ startOnLoad: false, theme: 'default' });

// Store mermaid codes and full LLM data for export
var rawMermaidCodes = [];
var lastGeneratedData = null;

// File reader - populates textarea from file
document.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'fileInput') {
        var file = e.target.files[0];
        if (!file) return;

        var statusEl = document.getElementById('fileStatus');
        if (statusEl) {
            statusEl.innerHTML = '<span style="color:#10b981;font-weight:600;">&#10003; Loaded: ' + file.name + ' (' + (file.size/1024).toFixed(1) + ' KB)</span>';
        }

        var reader = new FileReader();
        reader.onload = function(ev) {
            var ta = document.getElementById('reqText');
            if (ta) ta.value = ev.target.result;
        };
        reader.readAsText(file);
    }
});

// Generate button click
document.getElementById('generateBtn').onclick = function() {
    var apiKey = document.getElementById('apiKey').value.trim();
    var reqText = document.getElementById('reqText').value.trim();

    if (!apiKey) { alert('Please enter your OpenRouter API key.'); return; }
    if (!reqText) { alert('Please enter requirements in the text area or upload a file.'); return; }

    document.getElementById('loader').classList.remove('hidden');
    document.getElementById('results').classList.add('hidden');
    document.getElementById('generateBtn').disabled = true;

    var blob = new Blob([reqText], { type: 'text/plain' });
    var formData = new FormData();
    formData.append('file', blob, 'requirements.txt');
    formData.append('api_key', apiKey);

    fetch('/api/generate', { method: 'POST', body: formData })
    .then(function(response) {
        if (!response.ok) {
            return response.json().then(function(err) {
                throw new Error(err.detail || 'Server error ' + response.status);
            });
        }
        return response.json();
    })
    .then(function(data) {
        console.log('LLM Data:', JSON.stringify(data, null, 2));
        lastGeneratedData = data;
        renderResults(data);
    })
    .catch(function(err) {
        alert('Error: ' + err.message);
        console.error(err);
    })
    .finally(function() {
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('generateBtn').disabled = false;
    });
};

// ── Build rail analysis table (browser view, dark theme) ─────────────────────
function buildRailAnalysisTable(rails) {
    if (!rails || !Array.isArray(rails) || rails.length === 0) {
        return '<p style="color:#f59e0b;padding:1rem;">&#9888; No rail analysis data returned by the AI. Check the browser console (F12) for the raw response.</p>';
    }
    var html = '<div style="overflow-x:auto;"><table class="thermal-table"><thead><tr>'
        + '<th>Rail</th><th>Component</th><th>Analysis</th><th>Engineering Calculation</th><th>Result</th><th>Status</th>'
        + '</tr></thead><tbody>';

    rails.forEach(function(r) {
        var safeRipple  = r.ripple  || { calculation: 'N/A', value: 'N/A', status: 'N/A' };
        var safePsrr    = r.psrr    || { calculation: 'N/A', value: 'N/A', status: 'N/A' };
        var safeThermal = r.thermal || { calculation: 'N/A', value: 'N/A', status: 'N/A' };

        function statusClass(s) {
            if (!s) return '';
            return s.toLowerCase().includes('pass') ? 'status-pass' : 'status-fail';
        }

        html += '<tr>'
            + '<td rowspan="3" style="font-weight:700;vertical-align:top;border-right:2px solid rgba(99,102,241,0.3);min-width:90px;">' + (r.rail || 'N/A') + '</td>'
            + '<td rowspan="3" style="vertical-align:top;border-right:2px solid rgba(99,102,241,0.3);font-size:0.85rem;min-width:120px;">' + (r.component || 'N/A') + '</td>'
            + '<td style="font-weight:600;color:#60a5fa;">Voltage Ripple</td>'
            + '<td style="font-size:0.82rem;color:#94a3b8;">' + safeRipple.calculation + '</td>'
            + '<td style="font-weight:700;">' + safeRipple.value + '</td>'
            + '<td class="' + statusClass(safeRipple.status) + '">' + (safeRipple.status || '—') + '</td>'
            + '</tr>';

        html += '<tr>'
            + '<td style="font-weight:600;color:#a78bfa;">PSRR</td>'
            + '<td style="font-size:0.82rem;color:#94a3b8;">' + safePsrr.calculation + '</td>'
            + '<td style="font-weight:700;">' + safePsrr.value + '</td>'
            + '<td class="' + statusClass(safePsrr.status) + '">' + (safePsrr.status || '—') + '</td>'
            + '</tr>';

        html += '<tr style="border-bottom:3px solid rgba(99,102,241,0.3);">'
            + '<td style="font-weight:600;color:#f472b6;">Thermal (Tj)</td>'
            + '<td style="font-size:0.82rem;color:#94a3b8;">' + safeThermal.calculation + '</td>'
            + '<td style="font-weight:700;">' + safeThermal.value + '</td>'
            + '<td class="' + statusClass(safeThermal.status) + '">' + (safeThermal.status || '—') + '</td>'
            + '</tr>';
    });

    html += '</tbody></table></div>';
    return html;
}

// ── Build components list (browser view) ─────────────────────────────────────
function buildComponents(comps) {
    if (!comps) return '';
    return comps.map(function(c) {
        var price = c.price > 0 ? 'INR ' + c.price : 'Price N/A';
        return '<div class="component-item">'
            + '<div class="comp-header"><span class="comp-title">' + c.part_name + '</span><span class="comp-price">' + price + '</span></div>'
            + '<div class="comp-reason">' + (c.reasoning || '') + '</div>'
            + '</div>';
    }).join('');
}

// ── Render results in the browser ─────────────────────────────────────────────
async function renderResults(data) {
    rawMermaidCodes = [];
    document.getElementById('finalSummaryText').textContent = data.final_summary || '';
    var container = document.getElementById('schemesContainer');
    container.innerHTML = '';

    if (!data.schemes || !Array.isArray(data.schemes)) return;

    for (var i = 0; i < data.schemes.length; i++) {
        var s = data.schemes[i];

        // Clean mermaid code
        var mCode = (s.schematics_mermaid || '').trim()
            .replace(/^```mermaid/, '').replace(/^```/, '').replace(/```$/, '').trim();
        rawMermaidCodes[i] = mCode;

        // Render mermaid diagram
        var svgOut = '';
        try {
            var rendered = await mermaid.render('mermaid-svg-' + i, mCode);
            svgOut = rendered.svg;
        } catch(err) {
            svgOut = '<pre style="text-align:left;font-size:0.8rem;color:#aaa;overflow-x:auto;white-space:pre-wrap;">' + mCode + '</pre>';
        }

        var block = '<div class="scheme-block" style="margin-bottom:3rem;border:2px solid var(--primary);padding:2rem;border-radius:16px;background:rgba(30,41,59,0.4);">'
            + '<h2 style="color:var(--primary);font-size:1.5rem;margin-bottom:0.5rem;">' + (s.scheme_name || 'Scheme ' + (i+1))
            + ' <span style="font-size:1rem;color:#10b981;">(Total: INR ' + (s.total_price || 0) + ')</span></h2>'
            + '<div style="color:#94a3b8;font-size:0.9rem;margin-bottom:1.5rem;"><strong style="color:#e2e8f0;">Switching Frequency:</strong> ' + (s.switching_frequency || 'N/A') + '</div>'
            + '<div class="result-card diagram-card" style="margin-bottom:1.5rem;background:white;"><h2 style="color:#1e293b;">Schematics</h2><div class="mermaid-view">' + svgOut + '</div></div>'
            + '<div class="results-grid">'
            + '<div class="result-card"><h2>Selected Components</h2><div>' + buildComponents(s.selected_components) + '</div></div>'
            + '<div class="result-card" style="grid-column: span 1;"><h2>Engineering Analysis — Per Rail</h2>' + buildRailAnalysisTable(s.rail_analysis) + '</div>'
            + '</div></div>';

        container.innerHTML += block;
    }
    document.getElementById('results').classList.remove('hidden');
}

// ── Build rail analysis table for HTML REPORT (light theme) ──────────────────
function buildReportRailTable(rails) {
    if (!rails || !Array.isArray(rails) || rails.length === 0) {
        return '<p style="color:#f59e0b;">No rail analysis data available.</p>';
    }

    var html = '<table style="width:100%;border-collapse:collapse;font-size:0.88rem;margin-top:0.5rem;">'
        + '<thead><tr style="background:#1e3a5f;color:white;">'
        + '<th style="padding:0.6rem 0.8rem;text-align:left;border:1px solid #cbd5e1;">Rail</th>'
        + '<th style="padding:0.6rem 0.8rem;text-align:left;border:1px solid #cbd5e1;">Component</th>'
        + '<th style="padding:0.6rem 0.8rem;text-align:left;border:1px solid #cbd5e1;">Analysis</th>'
        + '<th style="padding:0.6rem 0.8rem;text-align:left;border:1px solid #cbd5e1;">Engineering Calculation</th>'
        + '<th style="padding:0.6rem 0.8rem;text-align:left;border:1px solid #cbd5e1;">Result</th>'
        + '<th style="padding:0.6rem 0.8rem;text-align:left;border:1px solid #cbd5e1;">Status</th>'
        + '</tr></thead><tbody>';

    rails.forEach(function(r, idx) {
        var bg = idx % 2 === 0 ? '#f8fafc' : '#ffffff';
        var safeRipple  = r.ripple  || { calculation: 'N/A', value: 'N/A', status: 'N/A' };
        var safePsrr    = r.psrr    || { calculation: 'N/A', value: 'N/A', status: 'N/A' };
        var safeThermal = r.thermal || { calculation: 'N/A', value: 'N/A', status: 'N/A' };

        function sColor(s) {
            if (!s) return '#64748b';
            return s.toLowerCase().includes('pass') ? '#16a34a' : '#dc2626';
        }
        function statusBadge(s) {
            return '<span style="background:' + sColor(s) + ';color:white;padding:2px 8px;border-radius:999px;font-size:0.8rem;font-weight:bold;">' + (s || '—') + '</span>';
        }

        var td = 'style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;vertical-align:top;"';
        var tdCenter = 'style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;vertical-align:middle;background:' + bg + ';"';

        html += '<tr style="background:' + bg + ';">'
            + '<td ' + td + ' rowspan="3" style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;vertical-align:middle;font-weight:700;min-width:80px;background:#eff6ff;border-left:4px solid #3b82f6;">' + (r.rail || 'N/A') + '</td>'
            + '<td ' + td + ' rowspan="3" style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;vertical-align:middle;font-size:0.82rem;background:#eff6ff;">' + (r.component || 'N/A') + '</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;background:#dbeafe;font-weight:600;color:#1d4ed8;">Voltage Ripple</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;font-size:0.82rem;color:#475569;font-family:monospace;">' + safeRipple.calculation + '</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;font-weight:700;">' + safeRipple.value + '</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;text-align:center;">' + statusBadge(safeRipple.status) + '</td>'
            + '</tr>';

        html += '<tr style="background:' + bg + ';">'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;background:#ede9fe;font-weight:600;color:#6d28d9;">PSRR</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;font-size:0.82rem;color:#475569;font-family:monospace;">' + safePsrr.calculation + '</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;font-weight:700;">' + safePsrr.value + '</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;text-align:center;">' + statusBadge(safePsrr.status) + '</td>'
            + '</tr>';

        html += '<tr style="background:' + bg + ';border-bottom:3px solid #cbd5e1;">'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;background:#fce7f3;font-weight:600;color:#be185d;">Thermal (Tj)</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;font-size:0.82rem;color:#475569;font-family:monospace;">' + safeThermal.calculation + '</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;font-weight:700;">' + safeThermal.value + '</td>'
            + '<td style="padding:0.6rem 0.8rem;border:1px solid #e2e8f0;text-align:center;">' + statusBadge(safeThermal.status) + '</td>'
            + '</tr>';
    });

    html += '</tbody></table>';
    return html;
}

// ── Build components for HTML REPORT (light theme) ───────────────────────────
function buildReportComponents(comps) {
    if (!comps || comps.length === 0) return '<p>No components listed.</p>';
    return comps.map(function(c) {
        var price = c.price > 0 ? 'INR ' + c.price : 'Price N/A';
        return '<div style="display:flex;justify-content:space-between;align-items:flex-start;padding:0.8rem 0;border-bottom:1px solid #f1f5f9;">'
            + '<div style="flex:1;"><div style="font-weight:700;font-size:1rem;color:#1e293b;">' + c.part_name + '</div>'
            + '<div style="color:#64748b;font-size:0.9rem;margin-top:0.3rem;">' + (c.reasoning || '') + '</div></div>'
            + '<span style="margin-left:1rem;background:#10b981;color:white;padding:0.2rem 0.8rem;border-radius:999px;font-size:0.85rem;white-space:nowrap;font-weight:600;">' + price + '</span>'
            + '</div>';
    }).join('');
}

// ── Download HTML Report ──────────────────────────────────────────────────────
document.getElementById('downloadBtn').onclick = function() {
    try {
        if (!lastGeneratedData || !lastGeneratedData.schemes) {
            alert('No generated data found. Please generate a power scheme first.');
            return;
        }

        var dateStr = new Date().toLocaleString();
        var summary = lastGeneratedData.final_summary || 'No summary available.';
        var schemesHtml = '';

        lastGeneratedData.schemes.forEach(function(s, i) {
            var railTableHtml = buildReportRailTable(s.rail_analysis);
            var componentsHtml = buildReportComponents(s.selected_components);
            var mCode = rawMermaidCodes[i] || '';

            schemesHtml += '<div class="scheme-block">'
                + '<h2>' + (s.scheme_name || 'Scheme ' + (i+1)) + ' <span class="price-badge">Total: INR ' + (s.total_price || 0) + '</span></h2>'
                + '<p class="freq-info"><strong>Switching Frequency:</strong> ' + (s.switching_frequency || 'N/A') + '</p>'

                // Schematics
                + '<div class="card"><h3>Schematics</h3><div class="mermaid">' + mCode + '</div></div>'

                // Components
                + '<div class="card"><h3>Selected Components</h3>' + componentsHtml + '</div>'

                // Per-Rail Engineering Analysis
                + '<div class="card"><h3>Engineering Analysis — Per Rail</h3>' + railTableHtml + '</div>'

                + '</div>';
        });

        var html = '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            + '<meta charset="UTF-8">\n'
            + '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            + '<title>Power Scheme Engineering Report</title>\n'
            + '<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"><\/script>\n'
            + '<script>mermaid.initialize({startOnLoad:true,theme:"default",securityLevel:"loose"});<\/script>\n'
            + '<style>\n'
            + '  * { box-sizing: border-box; margin: 0; padding: 0; }\n'
            + '  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 1300px; margin: 0 auto; padding: 2rem; background: #f1f5f9; color: #1e293b; }\n'
            + '  h1 { font-size: 2rem; color: #1d4ed8; border-bottom: 3px solid #3b82f6; padding-bottom: 0.75rem; margin-bottom: 0.5rem; }\n'
            + '  h2 { font-size: 1.35rem; color: #1e3a5f; margin: 1.5rem 0 0.5rem; }\n'
            + '  h3 { font-size: 1.1rem; color: #334155; margin-bottom: 0.8rem; border-left: 4px solid #3b82f6; padding-left: 0.6rem; }\n'
            + '  .card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 6px rgba(0,0,0,0.07); }\n'
            + '  .scheme-block { background: white; border: 1px solid #e2e8f0; border-radius: 12px; border-left: 6px solid #3b82f6; padding: 2rem; margin-bottom: 2.5rem; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }\n'
            + '  .scheme-block h2 { color: #1d4ed8; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }\n'
            + '  .price-badge { background: #10b981; color: white; padding: 0.2rem 0.8rem; border-radius: 999px; font-size: 0.85rem; font-weight: 600; }\n'
            + '  .freq-info { color: #64748b; font-size: 0.9rem; margin: 0.5rem 0 1.5rem; }\n'
            + '  .summary-card { background: linear-gradient(135deg, #eef2ff, #ede9fe); border: 1px solid #818cf8; border-radius: 10px; padding: 1.5rem; margin-bottom: 2rem; }\n'
            + '  .summary-card h2 { color: #4338ca; margin: 0 0 0.75rem; }\n'
            + '  .summary-card p { color: #374151; line-height: 1.7; white-space: pre-wrap; }\n'
            + '  footer { text-align: center; color: #94a3b8; margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid #e2e8f0; font-size: 0.9rem; }\n'
            + '</style>\n'
            + '</head>\n<body>\n'
            + '<h1>&#9889; Power Scheme Engineering Report</h1>\n'
            + '<p style="color:#64748b;margin-bottom:1.5rem;"><strong>Generated On:</strong> ' + dateStr + '</p>\n'
            + '<div class="summary-card"><h2>Executive Summary</h2><p>' + summary + '</p></div>\n'
            + schemesHtml
            + '<footer>Generated by AI Power Scheme Engineering System &mdash; Powered by OpenRouter LLM</footer>\n'
            + '</body>\n</html>';

        var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'Power-Engineering-Report.html';
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        setTimeout(function() {
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }, 1000);
        console.log('Report downloaded successfully.');
    } catch (e) {
        console.error('Download error:', e);
        alert('Failed to generate report: ' + e.message);
    }
};
