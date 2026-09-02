document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const browseBtn = document.getElementById('browseBtn');
    
    const fileStatusContainer = document.getElementById('fileStatusContainer');
    const fileNameEl = document.getElementById('fileName');
    const fileSizeEl = document.getElementById('fileSize');
    const clearFileBtn = document.getElementById('clearFileBtn');
    
    const parseBtn = document.getElementById('parseBtn');
    const copyBtn = document.getElementById('copyBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    
    const emptyState = document.getElementById('emptyState');
    const loaderState = document.getElementById('loaderState');
    const jsonCodeContainer = document.getElementById('jsonCodeContainer');
    const jsonContent = document.getElementById('jsonContent');
    const progressBar = document.getElementById('progressBar');
    
    const matchJobsBtn = document.getElementById('matchJobsBtn');
    const matchesCard = document.getElementById('matchesCard');
    const matchesList = document.getElementById('matchesList');
    const loaderTitle = document.getElementById('loaderTitle');
    const loaderDesc = document.getElementById('loaderDesc');

    let selectedFile = null;
    let parsedData = null;

    // Trigger browse file dialog
    browseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });

    dropZone.addEventListener('click', () => {
        fileInput.click();
    });

    // File Selection handling
    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });

    // Drag and Drop event handlers
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('highlight');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('highlight');
        }, false);
    });

    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        handleFiles(dt.files);
    });

    function handleFiles(files) {
        if (files.length === 0) return;
        
        const file = files[0];
        if (file.type !== 'application/pdf' && !file.name.endsWith('.pdf')) {
            alert('Please upload a PDF file.');
            return;
        }

        selectedFile = file;
        fileNameEl.textContent = file.name;
        fileSizeEl.textContent = formatBytes(file.size);

        // Update UI state
        dropZone.classList.add('hidden');
        fileStatusContainer.classList.remove('hidden');
    }

    // Clear selected file
    clearFileBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        selectedFile = null;
        fileInput.value = '';
        
        dropZone.classList.remove('hidden');
        fileStatusContainer.classList.add('hidden');
        resetOutput();
    });

    // Parse action
    parseBtn.addEventListener('click', async () => {
        if (!selectedFile) return;

        showLoading("Parsing Resume", "Extracting text, consulting Groq API, and saving to SQLite...");

        const formData = new FormData();
        formData.append('file', selectedFile);

        // Start progressive loading simulation
        let progress = 0;
        const progressInterval = setInterval(() => {
            if (progress < 85) {
                progress += Math.floor(Math.random() * 15) + 5;
                if (progress > 85) progress = 85;
                progressBar.style.width = `${progress}%`;
            }
        }, 300);

        try {
            const response = await fetch('/api/parse-resume', {
                method: 'POST',
                body: formData
            });

            clearInterval(progressInterval);
            progressBar.style.width = '100%';

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || `HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            
            // Format and show result after a small delay to make the transition smooth
            setTimeout(() => {
                showResult(data);
            }, 500);

        } catch (error) {
            clearInterval(progressInterval);
            console.error('Error parsing resume:', error);
            showError(error.message);
        }
    });

    // Find Matches action
    matchJobsBtn.addEventListener('click', async () => {
        if (!parsedData || !parsedData.id) return;

        showLoading("Finding Matches", "Searching jobs, parsing descriptions, and computing embeddings...");
        matchesCard.classList.add('hidden');

        // Fake progress
        let progress = 0;
        const progressInterval = setInterval(() => {
            if (progress < 90) {
                progress += Math.floor(Math.random() * 10) + 2;
                if (progress > 90) progress = 90;
                progressBar.style.width = `${progress}%`;
            }
        }, 500);

        try {
            const response = await fetch('/api/match-jobs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ resume_id: parsedData.id })
            });

            clearInterval(progressInterval);
            progressBar.style.width = '100%';

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || `HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            
            setTimeout(() => {
                showResult(parsedData); // Restore json view
                renderMatches(data.matches);
            }, 500);

        } catch (error) {
            clearInterval(progressInterval);
            console.error('Error matching jobs:', error);
            showError(error.message);
        }
    });

    // Copy to clipboard
    copyBtn.addEventListener('click', () => {
        if (!parsedData) return;
        
        const jsonStr = JSON.stringify(parsedData.parsed_json, null, 2);
        navigator.clipboard.writeText(jsonStr).then(() => {
            const originalText = copyBtn.innerHTML;
            copyBtn.innerHTML = `<i data-lucide="check" class="text-success"></i><span>Copied!</span>`;
            lucide.createIcons();
            setTimeout(() => {
                copyBtn.innerHTML = originalText;
                lucide.createIcons();
            }, 2000);
        }).catch(err => {
            alert('Failed to copy text: ' + err);
        });
    });

    // Download JSON file
    downloadBtn.addEventListener('click', () => {
        if (!parsedData) return;
        
        const jsonStr = JSON.stringify(parsedData.parsed_json, null, 2);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = parsedData.filename.replace('.pdf', '') + '_parsed.json';
        document.body.appendChild(a);
        a.click();
        
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

    // Helpers
    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    function showLoading(title = "Loading", desc = "Please wait...") {
        emptyState.classList.add('hidden');
        loaderState.classList.remove('hidden');
        jsonCodeContainer.classList.add('hidden');
        copyBtn.classList.add('hidden');
        downloadBtn.classList.add('hidden');
        matchJobsBtn.classList.add('hidden');
        progressBar.style.width = '0%';
        parseBtn.disabled = true;
        
        loaderTitle.textContent = title;
        loaderDesc.textContent = desc;
    }

    function showResult(data) {
        parsedData = data;
        loaderState.classList.add('hidden');
        jsonCodeContainer.classList.remove('hidden');
        
        // Pretty print with syntax highlighting
        const formattedJson = syntaxHighlight(data.parsed_json);
        jsonContent.innerHTML = formattedJson;
        
        copyBtn.classList.remove('hidden');
        downloadBtn.classList.remove('hidden');
        matchJobsBtn.classList.remove('hidden');
        parseBtn.disabled = false;
    }

    function renderMatches(matches) {
        matchesList.innerHTML = '';
        if (matches.length === 0) {
            matchesList.innerHTML = '<p class="text-secondary">No specific matches found online.</p>';
        } else {
            matches.forEach(match => {
                const item = document.createElement('div');
                item.className = 'match-item';
                
                // Determine score color
                let scoreColor = 'text-success';
                if (match.score < 50) scoreColor = 'text-danger';
                else if (match.score < 75) scoreColor = 'text-warning';
                
                const matchedSkills = match.matched_skills || [];
                const missingSkills = match.missing_skills || [];
                const reasoning = match.reasoning || "No reasoning details generated.";

                const matchedPills = matchedSkills.map(s => `<span class="skill-pill matched">${s}</span>`).join('');
                const missingPills = missingSkills.map(s => `<span class="skill-pill missing">${s}</span>`).join('');
                
                // Determine Apply Button UI state based on application status
                let applyBtnHtml = '';
                if (match.application_status === 'COMPLETED') {
                    applyBtnHtml = `
                        <button class="btn btn-success btn-sm btn-apply" disabled title="Application completed by Agent">
                            <i data-lucide="check-circle"></i>
                            <span>Applied</span>
                        </button>
                    `;
                } else if (match.application_status === 'PROCESSING' || match.application_status === 'QUEUED' || match.application_status === 'RETRY') {
                    applyBtnHtml = `
                        <button class="btn btn-secondary btn-sm btn-apply" disabled title="Agent is working on application">
                            <i data-lucide="loader" class="icon-spin"></i>
                            <span>Applying...</span>
                        </button>
                    `;
                } else {
                    applyBtnHtml = `
                        <button class="btn btn-primary btn-sm btn-apply" data-job-id="${match.job_id}">
                            <i data-lucide="send"></i>
                            <span>Apply</span>
                        </button>
                    `;
                }

                const locationHtml = match.location ? `<span class="match-location-pill"><i data-lucide="map-pin" style="width:0.7rem;height:0.7rem;display:inline-block;margin-right:2px;"></i>${match.location}</span>` : '';

                item.innerHTML = `
                    <div class="match-header">
                        <h4>${match.title}</h4>
                        <span class="match-score ${scoreColor}">${match.score}% Match</span>
                    </div>
                    <div class="match-company">
                        <span>${match.company}</span>
                        ${locationHtml}
                    </div>
                    <div class="match-actions" style="display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap;">
                        <a href="${match.url}" target="_blank" class="btn btn-secondary btn-sm"><i data-lucide="external-link" style="width:0.85rem;height:0.85rem;"></i><span>View Job</span></a>
                        ${applyBtnHtml}
                        <button class="btn-details-toggle" type="button">
                            <span>Show Details</span>
                            <i data-lucide="chevron-down" style="width: 0.9rem; height: 0.9rem;"></i>
                        </button>
                    </div>
                    <div class="match-details hidden">
                        <div>
                            <div class="details-section-title">Matched Skills</div>
                            <div class="pills-container">
                                ${matchedPills || '<span class="text-secondary" style="font-size:0.75rem;">None identified</span>'}
                            </div>
                        </div>
                        <div>
                            <div class="details-section-title">Missing from Resume</div>
                            <div class="pills-container">
                                ${missingPills || '<span class="text-secondary" style="font-size:0.75rem;">None identified</span>'}
                            </div>
                        </div>
                        <div>
                            <div class="details-section-title">Match Analysis</div>
                            <div class="reasoning-text">${reasoning}</div>
                        </div>
                    </div>
                `;

                // Handle Apply button click
                const applyBtn = item.querySelector('.btn-apply');
                if (applyBtn && !applyBtn.disabled) {
                    applyBtn.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        const jobId = applyBtn.getAttribute('data-job-id');
                        if (!parsedData || !parsedData.id || !jobId) return;

                        applyBtn.disabled = true;
                        applyBtn.className = 'btn btn-secondary btn-sm btn-apply';
                        applyBtn.innerHTML = `<i data-lucide="loader" class="icon-spin"></i><span>Queuing...</span>`;
                        lucide.createIcons();

                        try {
                            const response = await fetch('/api/apply-job', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json'
                                },
                                body: JSON.stringify({
                                    resume_id: parsedData.id,
                                    job_id: jobId
                                })
                            });

                            if (!response.ok) {
                                const errData = await response.json();
                                throw new Error(errData.error || `HTTP error! status: ${response.status}`);
                            }

                            applyBtn.className = 'btn btn-secondary btn-sm btn-apply';
                            applyBtn.innerHTML = `<i data-lucide="loader" class="icon-spin"></i><span>Applying...</span>`;
                            lucide.createIcons();
                        } catch (err) {
                            console.error('Error applying for job:', err);
                            alert(`Failed to submit application: ${err.message}`);
                            applyBtn.disabled = false;
                            applyBtn.className = 'btn btn-primary btn-sm btn-apply';
                            applyBtn.innerHTML = `<i data-lucide="send"></i><span>Apply</span>`;
                            lucide.createIcons();
                        }
                    });
                }

                // Handle details toggle
                const toggleBtn = item.querySelector('.btn-details-toggle');
                const detailsPanel = item.querySelector('.match-details');
                toggleBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const isHidden = detailsPanel.classList.contains('hidden');
                    if (isHidden) {
                        detailsPanel.classList.remove('hidden');
                        toggleBtn.innerHTML = `<span>Hide Details</span><i data-lucide="chevron-up" style="width: 0.9rem; height: 0.9rem;"></i>`;
                    } else {
                        detailsPanel.classList.add('hidden');
                        toggleBtn.innerHTML = `<span>Show Details</span><i data-lucide="chevron-down" style="width: 0.9rem; height: 0.9rem;"></i>`;
                    }
                    lucide.createIcons();
                });

                matchesList.appendChild(item);
            });
            lucide.createIcons();
        }
        matchesCard.classList.remove('hidden');
    }

    function showError(message) {
        loaderState.classList.add('hidden');
        emptyState.classList.remove('hidden');
        parseBtn.disabled = false;
        alert(`Error: ${message}`);
    }

    function resetOutput() {
        parsedData = null;
        emptyState.classList.remove('hidden');
        loaderState.classList.add('hidden');
        jsonCodeContainer.classList.add('hidden');
        copyBtn.classList.add('hidden');
        downloadBtn.classList.add('hidden');
        matchJobsBtn.classList.add('hidden');
        matchesCard.classList.add('hidden');
        parseBtn.disabled = false;
    }

    function syntaxHighlight(json) {
        if (typeof json !== 'string') {
            json = JSON.stringify(json, undefined, 2);
        }
        json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, function (match) {
            let cls = 'json-number';
            if (/^"/.test(match)) {
                if (/:$/.test(match)) {
                    cls = 'json-key';
                } else {
                    cls = 'json-string';
                    // Extract the string value without quotes
                    let strVal = match.slice(1, -1);
                    
                    // Check for email
                    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(strVal) || /^mailto:[^\s]+$/.test(strVal)) {
                        let href = strVal.startsWith('mailto:') ? strVal : 'mailto:' + strVal;
                        return '<span class="' + cls + '">"<a href="' + href + '" class="json-link">' + strVal + '</a>"</span>';
                    }
                    
                    // Check for URL (http/https, www, or domain with path)
                    if (/^(https?:\/\/[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.(com|org|net|io|co|me|dev|in)(\/[^\s]*)?)$/i.test(strVal)) {
                        let href = strVal.startsWith('http') ? strVal : 'https://' + strVal;
                        return '<span class="' + cls + '">"<a href="' + href + '" target="_blank" rel="noopener noreferrer" class="json-link">' + strVal + '</a>"</span>';
                    }
                }
            } else if (/true|false/.test(match)) {
                cls = 'json-boolean';
            } else if (/null/.test(match)) {
                cls = 'json-null';
            }
            return '<span class="' + cls + '">' + match + '</span>';
        });
    }

    // EventSource for Real-time Agent Logs
    const agentTerminal = document.getElementById('agentTerminal');
    const agentStatusBadge = document.getElementById('agentStatusBadge');

    function connectAgentStream() {
        agentStatusBadge.textContent = "CONNECTING";
        agentStatusBadge.className = "status-badge";
        
        const eventSource = new EventSource('/api/agent/stream');

        eventSource.onopen = () => {
            agentStatusBadge.textContent = "LIVE";
            agentStatusBadge.className = "status-badge live";
            appendTerminalLine(new Date().toTimeString().split(' ')[0], "Connected to agent event stream.", "system");
        };

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                appendTerminalLine(data.time, data.message, data.type);
                
                // If the agent found a new match, silently reload job matching list
                if (data.type === "match" || data.type === "success") {
                    fetchMatchesSilent();
                }
            } catch (err) {
                console.error("Failed to parse SSE message:", err);
            }
        };

        eventSource.onerror = (err) => {
            console.error("SSE connection error:", err);
            agentStatusBadge.textContent = "ERROR";
            agentStatusBadge.className = "status-badge error";
            appendTerminalLine(new Date().toTimeString().split(' ')[0], "Connection lost. Retrying...", "error");
            eventSource.close();
            setTimeout(connectAgentStream, 5000);
        };
    }

    function appendTerminalLine(time, message, type) {
        if (!agentTerminal) return;
        const line = document.createElement('span');
        line.className = `terminal-line ${type}`;
        line.textContent = `[${time}] ${message}`;
        agentTerminal.appendChild(line);
        agentTerminal.scrollTop = agentTerminal.scrollHeight;
    }

    async function fetchMatchesSilent() {
        if (!parsedData || !parsedData.id) return;
        try {
            const response = await fetch('/api/match-jobs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ resume_id: parsedData.id })
            });
            if (response.ok) {
                const data = await response.json();
                renderMatches(data.matches);
            }
        } catch (error) {
            console.error('Silent match fetch failed:', error);
        }
    }

    connectAgentStream();
});
