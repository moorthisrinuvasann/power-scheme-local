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
    var apiKey  = document.getElementById('apiKey').value.trim();
    var reqText = document.getElementById('reqText').value.trim();

    if (!apiKey)  { alert('Please enter your OpenRouter API key.'); return; }
    if (!reqText) { alert('Please enter requirements in the text area or upload a file.'); return; }

    document.getElementById('loader').classList.remove('hidden');
    document.getElementById('results').classList.add('hidden');
    document.getElementById('generateBtn').disabled = true;

    // Reset any previous progress panel
    var old = document.getElementById('agentProgress');
    if (old) old.remove();

    updateProgress(0, 4, 'Starting AI agent pipeline...');

    var blob = new Blob([reqText], { type: 'text/plain' });
    var formData = new FormData();
    formData.append('file', blob, 'requirements.txt');
    formData.append('api_key', apiKey);

    // Use fetch to POST, then read SSE stream from response body
    fetch('/api/generate', { method: 'POST', body: formData })
    .then(function(response) {
        if (!response.ok) {
            return response.json().then(function(err) {
                throw new Error(err.detail || 'Server error ' + response.status);
            });
        }
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function read() {
            return reader.read().then(function(chunk) {
                if (chunk.done) return;
                buffer += decoder.decode(chunk.value, { stream: true });

                // ── SSE event-boundary parser ─────────────────────────────
                // Split on double-newline (end of SSE event), keep incomplete tail
                var events = buffer.split('\n\n');
                buffer = events.pop(); // last item may be incomplete — save for next chunk

                events.forEach(function(eventBlock) {
                    if (!eventBlock.trim()) return;

                    var eventType = '';
                    var dataLines = [];

                    // Parse all lines within this event block
                    eventBlock.split('\n').forEach(function(line) {
                        if (line.startsWith('event:')) {
                            eventType = line.slice(6).trim();
                        } else if (line.startsWith('data:')) {
                            dataLines.push(line.slice(5).trim());
                        }
                    });

                    if (!eventType || !dataLines.length) return;
                    var jsonStr = dataLines.join(''); // join data lines (handles chunked data)
                    if (!jsonStr) return;

                    try {
                        var payload = JSON.parse(jsonStr);
                        if (eventType === 'progress') {
                            updateProgress(payload.step, payload.total, payload.message);
                        } else if (eventType === 'result') {
                            console.log('LLM Data:', payload);
                            lastGeneratedData = payload;
                            renderResults(payload);
                            document.getElementById('loader').classList.add('hidden');
                            document.getElementById('generateBtn').disabled = false;
                        } else if (eventType === 'error') {
                            alert('Error: ' + payload.message);
                            document.getElementById('loader').classList.add('hidden');
                            document.getElementById('generateBtn').disabled = false;
                        }
                    } catch(e) {
                        console.warn('SSE JSON parse error for event [' + eventType + ']:', e.message, '\nRaw:', jsonStr.slice(0, 200));
                    }
                });

                return read();
            });
        }
        return read();
    })
    .catch(function(err) {
        alert('Error: ' + err.message);
        console.error(err);
        document.getElementById('loader').classList.add('hidden');
        document.getElementById('generateBtn').disabled = false;
    });
};

// ── Live progress bar ─────────────────────────────────────────────────────────
function updateProgress(step, total, message) {
    var loaderEl = document.getElementById('loader');
    // Inject progress UI if not already present
    if (!document.getElementById('agentProgress')) {
        loaderEl.insertAdjacentHTML('beforeend',
            '<div id="agentProgress" style="margin-top:1.5rem;width:100%;max-width:480px;">'
            + '<div id="progressMsg" style="color:#94a3b8;font-size:0.9rem;margin-bottom:0.75rem;text-align:center;min-height:1.4rem;"></div>'
            + '<div style="background:rgba(255,255,255,0.1);border-radius:999px;height:8px;overflow:hidden;">'
            + '<div id="progressBar" style="height:100%;background:linear-gradient(90deg,#6366f1,#8b5cf6);border-radius:999px;transition:width 0.5s ease;width:0%;"></div>'
            + '</div>'
            + '<div id="agentSteps" style="margin-top:1rem;display:flex;flex-direction:column;gap:0.5rem;"></div>'
            + '</div>'
        );
    }
    var pct = total > 0 ? Math.round((step / total) * 100) : 0;
    document.getElementById('progressBar').style.width = pct + '%';
    document.getElementById('progressMsg').textContent = message;

    // Add step chip
    var stepsEl = document.getElementById('agentSteps');
    var icons = ['', '🔍', '🏗️', '📐', '🧮', '🔬', '✅'];
    var chip = document.createElement('div');
    chip.style.cssText = 'background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);border-radius:8px;padding:0.4rem 0.8rem;font-size:0.82rem;color:#c4b5fd;display:flex;align-items:center;gap:0.5rem;';
    chip.innerHTML = '<span>' + (icons[step] || '✓') + '</span><span>' + message + '</span>';
    stepsEl.appendChild(chip);
}


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

// ── Scheme Comparison Table ───────────────────────────────────────────────────
function buildComparisonTable(comparison) {
    if (!comparison || !comparison.length) return '';

    // Helper: find which scheme index has the best (lowest) value for a metric
    function bestIdx(key, lowerIsBetter) {
        var vals = comparison.map(function(c) { return c[key]; });
        var valid = vals.filter(function(v) { return v !== null && v !== undefined; });
        if (!valid.length) return -1;
        var best = lowerIsBetter ? Math.min.apply(null, valid) : Math.max.apply(null, valid);
        return vals.indexOf(best);
    }

    function cell(val, isBest, suffix) {
        suffix = suffix || '';
        var display = (val === null || val === undefined) ? '—' : val + suffix;
        var style = isBest
            ? 'padding:0.7rem 1rem;text-align:center;font-weight:700;color:#10b981;background:rgba(16,185,129,0.1);'
            : 'padding:0.7rem 1rem;text-align:center;color:#cbd5e1;';
        return '<td style="' + style + '">' + display + (isBest ? ' ★' : '') + '</td>';
    }

    function drcCell(m, idx) {
        if (m.drc_errors > 0) {
            var isBest = bestIdx('drc_errors', true) === idx;
            return '<td style="padding:0.7rem 1rem;text-align:center;">'
                + '<span style="color:#f87171;font-weight:700;">' + m.drc_errors + ' ERR</span>'
                + (m.drc_warnings ? ' <span style="color:#fbbf24;font-size:0.8rem;">+' + m.drc_warnings + 'W</span>' : '')
                + '</td>';
        }
        if (m.drc_warnings > 0) {
            return '<td style="padding:0.7rem 1rem;text-align:center;color:#fbbf24;font-weight:700;">' + m.drc_warnings + ' WARN</td>';
        }
        return '<td style="padding:0.7rem 1rem;text-align:center;color:#10b981;font-weight:700;">✅ PASS</td>';
    }

    // Pre-compute best indices
    var bestPrice    = bestIdx('total_price',    true);
    var bestArea     = bestIdx('pcb_area_mm2',   true);
    var bestPassives = bestIdx('total_passives',  true);
    var bestTjMax    = bestIdx('tj_max_c',        true);
    var bestEff      = bestIdx('avg_efficiency', false);

    var schemeColors = ['#6366f1', '#8b5cf6', '#06b6d4'];

    // Header row
    var headerCols = comparison.map(function(m, i) {
        var shortName = (m.scheme_name || 'Scheme ' + (i+1)).replace(/^Scheme \d+:\s*/i, '');
        return '<th style="padding:1rem;background:' + schemeColors[i % 3] + ';color:white;text-align:center;font-size:0.95rem;border-radius:' + (i===0?'8px 0 0 0':i===comparison.length-1?'0 8px 0 0':'0') + ';">'
            + '<div style="font-weight:700;">Scheme ' + (i+1) + '</div>'
            + '<div style="font-size:0.8rem;opacity:0.85;margin-top:0.2rem;">' + shortName + '</div>'
            + '</th>';
    }).join('');

    function row(label, icon, cells) {
        return '<tr>'
            + '<td style="padding:0.7rem 1rem;color:#94a3b8;font-size:0.85rem;white-space:nowrap;border-right:1px solid rgba(255,255,255,0.06);">'
            + icon + ' ' + label + '</td>'
            + cells
            + '</tr>';
    }

    var priceRow    = row('Total Price (INR)',    '💰', comparison.map(function(m,i){ return cell(m.total_price,    bestPrice===i,    ''); }).join(''));
    var bucksRow    = row('Buck Converters',       '⚡', comparison.map(function(m,i){ return cell(m.num_bucks,     bestIdx('num_bucks',true)===i, ''); }).join(''));
    var ldosRow     = row('LDO Regulators',        '🔋', comparison.map(function(m,i){ return cell(m.num_ldos,      bestIdx('num_ldos',true)===i,  ''); }).join(''));
    var railsRow    = row('Total Rails',           '📊', comparison.map(function(m,i){ return cell(m.num_rails,     -1,                            ''); }).join(''));
    var areaRow     = row('Est. PCB Area',         '📐', comparison.map(function(m,i){ return cell(m.pcb_area_mm2,  bestArea===i,     ' mm²'); }).join(''));
    var capsRow     = row('Output Capacitors',     '🔌', comparison.map(function(m,i){ return cell(m.total_caps,    bestPassives===i, ''); }).join(''));
    var resRow      = row('Resistors',             '〰️', comparison.map(function(m,i){ return cell(m.total_resistors, -1,             ''); }).join(''));
    var indRow      = row('Inductors (ext.)',      '🌀', comparison.map(function(m,i){ return cell(m.total_inductors, -1,             ''); }).join(''));
    var tjMinRow    = row('Tj Min (°C)',           '🌡️', comparison.map(function(m,i){ return cell(m.tj_min_c,      bestIdx('tj_min_c',true)===i, '°C'); }).join(''));
    var tjMaxRow    = row('Tj Max (°C)',           '🔥', comparison.map(function(m,i){ return cell(m.tj_max_c,      bestTjMax===i,    '°C'); }).join(''));
    var effRow      = row('Avg Efficiency',        '✨', comparison.map(function(m,i){ return cell(m.avg_efficiency, bestEff===i,     '%'); }).join(''));
    var freqRow     = row('Switching Frequency',   '📡', comparison.map(function(m,i){ return '<td style="padding:0.7rem 1rem;text-align:center;color:#94a3b8;">' + (m.switching_freq||'N/A') + '</td>'; }).join(''));
    var drcRow      = row('DRC Status',            '🔬', comparison.map(function(m,i){ return drcCell(m, i); }).join(''));

    return '<div style="margin-bottom:2.5rem;">'
        + '<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem;">'
        + '<span style="font-size:1.4rem;">⚖️</span>'
        + '<h2 style="color:#e2e8f0;font-size:1.3rem;margin:0;">Scheme Comparison</h2>'
        + '<span style="background:rgba(99,102,241,0.2);color:#818cf8;font-size:0.78rem;padding:0.2rem 0.7rem;border-radius:999px;border:1px solid rgba(99,102,241,0.3);">★ = Best in class</span>'
        + '</div>'
        + '<div style="overflow-x:auto;border-radius:12px;border:1px solid rgba(255,255,255,0.08);">'
        + '<table style="width:100%;border-collapse:collapse;background:rgba(15,23,42,0.6);">'
        + '<thead><tr><th style="padding:1rem;background:rgba(30,41,59,0.8);text-align:left;color:#64748b;font-size:0.85rem;border-radius:8px 0 0 0;">Metric</th>' + headerCols + '</tr></thead>'
        + '<tbody>'
        + priceRow + bucksRow + ldosRow + railsRow + areaRow
        + capsRow  + resRow   + indRow  + tjMinRow + tjMaxRow
        + effRow   + freqRow  + drcRow
        + '</tbody></table></div></div>';
}

// ── DRC Panel builder ─────────────────────────────────────────────────────────
function buildDrcPanel(scheme) {
    var violations = scheme.drc_violations || [];
    var corrections = scheme.correction_log || [];
    var summary = scheme.drc_summary || '';
    if (!violations.length && !corrections.length) {
        return '<div style="margin-bottom:1rem;padding:0.6rem 1rem;background:rgba(16,185,129,0.1);border:1px solid #10b981;border-radius:8px;font-size:0.85rem;color:#10b981;">✅ DRC: All design rules passed</div>';
    }
    var html = '<div style="margin-bottom:1.5rem;">';

    // DRC violations table
    if (violations.length) {
        html += '<div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.4);border-radius:10px;padding:1rem;margin-bottom:0.75rem;">'
            + '<div style="font-weight:700;color:#f87171;margin-bottom:0.6rem;font-size:0.9rem;">⚠️ DRC Violations (' + violations.length + ')</div>'
            + '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr>'
            + '<th style="text-align:left;padding:0.4rem 0.6rem;color:#94a3b8;border-bottom:1px solid rgba(255,255,255,0.1);">Severity</th>'
            + '<th style="text-align:left;padding:0.4rem 0.6rem;color:#94a3b8;border-bottom:1px solid rgba(255,255,255,0.1);">Rail</th>'
            + '<th style="text-align:left;padding:0.4rem 0.6rem;color:#94a3b8;border-bottom:1px solid rgba(255,255,255,0.1);">Rule</th>'
            + '<th style="text-align:left;padding:0.4rem 0.6rem;color:#94a3b8;border-bottom:1px solid rgba(255,255,255,0.1);">Detail</th>'
            + '<th style="text-align:left;padding:0.4rem 0.6rem;color:#94a3b8;border-bottom:1px solid rgba(255,255,255,0.1);">Fix</th>'
            + '</tr></thead><tbody>';
        violations.forEach(function(v) {
            var sevColor = v.severity === 'ERROR' ? '#f87171' : '#fbbf24';
            html += '<tr>'
                + '<td style="padding:0.4rem 0.6rem;"><span style="background:' + sevColor + ';color:#000;font-size:0.75rem;font-weight:700;padding:1px 6px;border-radius:4px;">' + v.severity + '</span></td>'
                + '<td style="padding:0.4rem 0.6rem;color:#e2e8f0;font-weight:600;">' + v.rail + '</td>'
                + '<td style="padding:0.4rem 0.6rem;color:#cbd5e1;">' + v.rule + '</td>'
                + '<td style="padding:0.4rem 0.6rem;color:#94a3b8;font-size:0.8rem;">' + v.detail + '</td>'
                + '<td style="padding:0.4rem 0.6rem;color:#60a5fa;font-size:0.8rem;">' + v.fix + '</td>'
                + '</tr>';
        });
        html += '</tbody></table></div>';
    }

    // Correction log
    if (corrections.length) {
        html += '<div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.3);border-radius:10px;padding:1rem;">'
            + '<div style="font-weight:700;color:#818cf8;margin-bottom:0.5rem;font-size:0.9rem;">🔧 Auto-Corrections Applied (' + corrections.length + ')</div>';
        corrections.forEach(function(c) {
            html += '<div style="font-size:0.82rem;color:#94a3b8;padding:0.2rem 0;">✓ ' + c + '</div>';
        });
        html += '</div>';
    }
    html += '</div>';
    return html;
}

// ── Render results in the browser ─────────────────────────────────────────────
async function renderResults(data) {
    rawMermaidCodes = [];
    document.getElementById('finalSummaryText').textContent = data.final_summary || '';
    var container = document.getElementById('schemesContainer');
    container.innerHTML = '';

    if (!data.schemes || !Array.isArray(data.schemes)) return;

    // ── Render Comparison Table first ────────────────────────────────────────
    if (data.comparison && Array.isArray(data.comparison)) {
        container.innerHTML = buildComparisonTable(data.comparison);
    }

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
            + '<div style="color:#94a3b8;font-size:0.9rem;margin-bottom:0.5rem;"><strong style="color:#e2e8f0;">Switching Frequency:</strong> ' + (s.switching_frequency || 'N/A') + '</div>'
            + buildDrcPanel(s)
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

        // POST HTML to backend → returns proper Content-Disposition download
        fetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'text/plain' },
            body: html
        })
        .then(function(resp) {
            if (!resp.ok) throw new Error('Export failed: ' + resp.status);
            return resp.blob();
        })
        .then(function(blob) {
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
            }, 500);
            console.log('Report downloaded via server export.');
        })
        .catch(function(e) {
            console.error('Export error:', e);
            alert('Download failed: ' + e.message);
        });

    } catch (e) {
        console.error('Report build error:', e);
        alert('Failed to build report: ' + e.message);
    }
};
