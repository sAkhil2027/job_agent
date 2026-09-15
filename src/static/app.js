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
    const matchCountBadge = document.getElementById('matchCountBadge');
    const jobFilterInput = document.getElementById('jobFilterInput');
    
    const loaderTitle = document.getElementById('loaderTitle');
    const loaderDesc = document.getElementById('loaderDesc');

    // Visual profile and view tab elements
    const visualProfileContainer = document.getElementById('visualProfileContainer');
    const candidateSummaryCard = document.getElementById('candidateSummaryCard');
    const candidateAvatar = document.getElementById('candidateAvatar');
    const candidateQuickName = document.getElementById('candidateQuickName');
    const candidateQuickTitle = document.getElementById('candidateQuickTitle');
    
    const tabVisual = document.getElementById('tabVisual');
    const tabJson = document.getElementById('tabJson');
    let activeView = 'visual'; // 'visual' | 'json'

    let selectedFile = null;
    let parsedData = null;
    let rawMatchesList = [];

    // Tab Navigation
    if (tabVisual && tabJson) {
        tabVisual.addEventListener('click', () => {
            activeView = 'visual';
            tabVisual.classList.add('active');
            tabJson.classList.remove('active');
            if (parsedData) {
                if (visualProfileContainer) visualProfileContainer.classList.remove('hidden');
                if (jsonCodeContainer) jsonCodeContainer.classList.add('hidden');
            }
        });

        tabJson.addEventListener('click', () => {
            activeView = 'json';
            tabJson.classList.add('active');
            tabVisual.classList.remove('active');
            if (parsedData) {
                if (jsonCodeContainer) jsonCodeContainer.classList.remove('hidden');
                if (visualProfileContainer) visualProfileContainer.classList.add('hidden');
            }
        });
    }

    // Trigger browse file dialog
    if (browseBtn) {
        browseBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            fileInput.click();
        });
    }

    if (dropZone) {
        dropZone.addEventListener('click', () => {
            fileInput.click();
        });
    }

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
            alert('Please upload a valid PDF document.');
            return;
        }

        selectedFile = file;
        fileNameEl.textContent = file.name;
        fileSizeEl.textContent = formatBytes(file.size);

        // Update UI state
        dropZone.classList.add('hidden');
        fileStatusContainer.classList.remove('hidden');
        if (parseBtn) parseBtn.classList.remove('hidden');
    }

    // Clear selected file
    clearFileBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        selectedFile = null;
        fileInput.value = '';
        
        dropZone.classList.remove('hidden');
        fileStatusContainer.classList.add('hidden');
        if (parseBtn) parseBtn.classList.add('hidden');
        resetOutput();
    });

    // Parse resume action
    parseBtn.addEventListener('click', async () => {
        if (!selectedFile) return;

        showLoading("Analyzing Resume", "Extracting experience, skills, and building career profile...");

        const formData = new FormData();
        formData.append('file', selectedFile);

        // Progressive loading indicator
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
                throw new Error(errData.detail || errData.error || `HTTP ${response.status}`);
            }

            const data = await response.json();
            
            setTimeout(() => {
                showResult(data);
                // Trigger job matching search automatically after parse
                if (matchJobsBtn) {
                    matchJobsBtn.click();
                }
            }, 400);

        } catch (error) {
            clearInterval(progressInterval);
            console.error('Error parsing resume:', error);
            showError(error.message);
        }
    });

    // Find Matches action
    matchJobsBtn.addEventListener('click', async () => {
        if (!parsedData || !parsedData.id) return;

        matchJobsBtn.disabled = true;
        matchJobsBtn.innerHTML = `<i data-lucide="loader-2" class="spin"></i><span>Scanning Feeds...</span>`;
        if (window.lucide) lucide.createIcons();

        try {
            const response = await fetch('/api/match-jobs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ resume_id: parsedData.id })
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || errData.error || `HTTP ${response.status}`);
            }

            const data = await response.json();
            rawMatchesList = data.matches || [];
            renderMatches(rawMatchesList);

        } catch (error) {
            console.error('Error matching jobs:', error);
            appendTerminalLine(new Date().toTimeString().split(' ')[0], `Job search error: ${error.message}`, 'error');
        } finally {
            matchJobsBtn.disabled = false;
            matchJobsBtn.innerHTML = `<i data-lucide="search"></i><span>Scan Job Feeds</span>`;
            if (window.lucide) lucide.createIcons();
        }
    });

    // Live search filter input
    if (jobFilterInput) {
        jobFilterInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();
            if (!query) {
                renderFilteredMatches(rawMatchesList);
                return;
            }
            const filtered = rawMatchesList.filter(m => {
                const title = (m.title || '').toLowerCase();
                const company = (m.company || '').toLowerCase();
                const loc = (m.location || '').toLowerCase();
                return title.includes(query) || company.includes(query) || loc.includes(query);
            });
            renderFilteredMatches(filtered);
        });
    }

    // Copy JSON to clipboard
    copyBtn.addEventListener('click', () => {
        if (!parsedData) return;
        
        const jsonStr = JSON.stringify(parsedData.parsed_json, null, 2);
        navigator.clipboard.writeText(jsonStr).then(() => {
            const originalText = copyBtn.innerHTML;
            copyBtn.innerHTML = `<i data-lucide="check"></i><span>Copied</span>`;
            if (window.lucide) lucide.createIcons();
            setTimeout(() => {
                copyBtn.innerHTML = originalText;
                if (window.lucide) lucide.createIcons();
            }, 2000);
        }).catch(err => {
            alert('Failed to copy: ' + err);
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
        a.download = (parsedData.filename || 'resume').replace('.pdf', '') + '_profile.json';
        document.body.appendChild(a);
        a.click();
        
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

    function formatBytes(bytes, decimals = 1) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    function resetOutput() {
        emptyState.classList.remove('hidden');
        loaderState.classList.add('hidden');
        jsonCodeContainer.classList.add('hidden');
        if (visualProfileContainer) {
            visualProfileContainer.classList.add('hidden');
            visualProfileContainer.innerHTML = '';
        }
        if (candidateSummaryCard) candidateSummaryCard.classList.add('hidden');
        copyBtn.classList.add('hidden');
        downloadBtn.classList.add('hidden');
        matchJobsBtn.classList.add('hidden');
        matchesCard.classList.add('hidden');
        parsedData = null;
        rawMatchesList = [];
    }

    function showLoading(title = "Loading", desc = "Please wait...") {
        emptyState.classList.add('hidden');
        loaderState.classList.remove('hidden');
        jsonCodeContainer.classList.add('hidden');
        if (visualProfileContainer) visualProfileContainer.classList.add('hidden');
        copyBtn.classList.add('hidden');
        downloadBtn.classList.add('hidden');
        matchJobsBtn.classList.add('hidden');
        progressBar.style.width = '0%';
        parseBtn.disabled = true;
        
        loaderTitle.textContent = title;
        loaderDesc.textContent = desc;
    }

    function renderVisualProfile(parsed) {
        if (!visualProfileContainer) return;
        const ci = parsed.contact_info || {};
        const cp = parsed.coding_profiles || {};
        const skills = parsed.skills || {};
        const experience = parsed.experience || [];
        const projects = parsed.projects || [];
        const education = parsed.education || [];

        // Update Quick Candidate Card in sidebar
        if (candidateSummaryCard) {
            candidateSummaryCard.classList.remove('hidden');
            const initials = (ci.name || 'Candidate').split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'CA';
            if (candidateAvatar) candidateAvatar.textContent = initials;
            if (candidateQuickName) candidateQuickName.textContent = ci.name || 'Candidate';
            
            let primaryRole = 'Software Professional';
            if (experience.length > 0 && experience[0].role) {
                primaryRole = experience[0].role;
            }
            if (candidateQuickTitle) candidateQuickTitle.textContent = primaryRole;
        }

        let html = '';

        // 1. Candidate Hero Header
        html += `
            <div class="profile-card-section">
                <div class="candidate-header-banner">
                    <div class="candidate-hero-col">
                        <h1>${escapeHtml(ci.name || 'Candidate Profile')}</h1>
                        <div class="candidate-contact-row">
                            ${ci.email ? `<a href="mailto:${escapeHtml(ci.email)}" class="contact-pill"><i data-lucide="mail"></i>${escapeHtml(ci.email)}</a>` : ''}
                            ${ci.phone ? `<a href="tel:${escapeHtml(ci.phone)}" class="contact-pill"><i data-lucide="phone"></i>${escapeHtml(ci.phone)}</a>` : ''}
                            ${ci.location ? `<span class="contact-pill"><i data-lucide="map-pin"></i>${escapeHtml(ci.location)}</span>` : ''}
                        </div>
                    </div>

                    <!-- Social / Portfolio Badges -->
                    <div class="social-badges-deck">
                        ${ci.github ? `<a href="${escapeHtml(ci.github)}" target="_blank" rel="noopener noreferrer" class="profile-link-btn"><i data-lucide="github"></i><span>GitHub</span></a>` : ''}
                        ${ci.linkedin ? `<a href="${escapeHtml(ci.linkedin)}" target="_blank" rel="noopener noreferrer" class="profile-link-btn"><i data-lucide="linkedin"></i><span>LinkedIn</span></a>` : ''}
                        ${ci.portfolio ? `<a href="${escapeHtml(ci.portfolio)}" target="_blank" rel="noopener noreferrer" class="profile-link-btn"><i data-lucide="globe"></i><span>Portfolio</span></a>` : ''}
                        ${cp.leetcode ? `<a href="${escapeHtml(cp.leetcode)}" target="_blank" rel="noopener noreferrer" class="profile-link-btn"><i data-lucide="code-2"></i><span>LeetCode</span></a>` : ''}
                    </div>
                </div>
            </div>
        `;

        // 2. Summary
        if (parsed.professional_summary) {
            html += `
                <div class="profile-card-section">
                    <div class="section-label-row">
                        <i data-lucide="align-left"></i>
                        <span>Career Summary</span>
                    </div>
                    <p style="font-size:0.85rem; color:var(--text-muted); line-height:1.6;">${escapeHtml(parsed.professional_summary)}</p>
                </div>
            `;
        }

        // 3. Work Experience
        if (experience && experience.length > 0) {
            html += `
                <div class="profile-card-section">
                    <div class="section-label-row">
                        <i data-lucide="briefcase"></i>
                        <span>Work Experience (${experience.length})</span>
                    </div>
            `;
            experience.forEach(exp => {
                const dates = [exp.start_date, exp.end_date].filter(Boolean).join(' – ') || (exp.employment_type || 'Experience');
                const bullets = Array.isArray(exp.description) ? exp.description : (Array.isArray(exp.responsibilities) ? exp.responsibilities : [exp.description].filter(Boolean));
                const tech = Array.isArray(exp.technologies) ? exp.technologies : [];

                html += `
                    <div class="entry-card">
                        <div class="entry-header-row">
                            <div>
                                <div class="entry-role">${escapeHtml(exp.role || 'Role')}</div>
                                <div class="entry-company">${escapeHtml(exp.company || '')} ${exp.location ? `• ${escapeHtml(exp.location)}` : ''}</div>
                            </div>
                            <span class="entry-date">${escapeHtml(dates)}</span>
                        </div>
                        ${bullets.length > 0 ? `
                            <ul class="entry-bullets">
                                ${bullets.map(b => `<li>${escapeHtml(b)}</li>`).join('')}
                            </ul>
                        ` : ''}
                        ${tech.length > 0 ? `
                            <div class="tags-wrap">
                                ${tech.map(t => `<span class="skill-chip">${escapeHtml(t)}</span>`).join('')}
                            </div>
                        ` : ''}
                    </div>
                `;
            });
            html += `</div>`;
        }

        // 4. Projects
        if (projects && projects.length > 0) {
            html += `
                <div class="profile-card-section">
                    <div class="section-label-row">
                        <i data-lucide="folder-git-2"></i>
                        <span>Projects & Portfolio (${projects.length})</span>
                    </div>
            `;
            projects.forEach(proj => {
                const dates = [proj.start_date, proj.end_date].filter(Boolean).join(' – ');
                const bullets = Array.isArray(proj.description) ? proj.description : [proj.description].filter(Boolean);
                const tech = Array.isArray(proj.technologies) ? proj.technologies : [];
                const repoUrl = proj.repository || proj.url;

                html += `
                    <div class="entry-card">
                        <div class="entry-header-row">
                            <div class="entry-role">${escapeHtml(proj.name || 'Project')}</div>
                            ${dates ? `<span class="entry-date">${escapeHtml(dates)}</span>` : ''}
                        </div>
                        ${bullets.length > 0 ? `
                            <ul class="entry-bullets">
                                ${bullets.map(b => `<li>${escapeHtml(b)}</li>`).join('')}
                            </ul>
                        ` : ''}
                        ${tech.length > 0 ? `
                            <div class="tags-wrap">
                                ${tech.map(t => `<span class="skill-chip">${escapeHtml(t)}</span>`).join('')}
                            </div>
                        ` : ''}
                        ${repoUrl && !repoUrl.includes('/githubLink') ? `
                            <a href="${escapeHtml(repoUrl)}" target="_blank" rel="noopener noreferrer" class="profile-link-btn" style="margin-top:0.35rem; width:fit-content;">
                                <i data-lucide="github"></i>
                                <span>View Repository</span>
                            </a>
                        ` : ''}
                    </div>
                `;
            });
            html += `</div>`;
        }

        // 5. Education
        if (education && education.length > 0) {
            html += `
                <div class="profile-card-section">
                    <div class="section-label-row">
                        <i data-lucide="graduation-cap"></i>
                        <span>Education</span>
                    </div>
            `;
            education.forEach(edu => {
                const dates = edu.graduation_year || [edu.start_date, edu.end_date].filter(Boolean).join(' – ');
                html += `
                    <div class="entry-card">
                        <div class="entry-header-row">
                            <div>
                                <div class="entry-role">${escapeHtml(edu.degree || '')} ${edu.specialization ? `in ${escapeHtml(edu.specialization)}` : ''}</div>
                                <div class="entry-company">${escapeHtml(edu.institution || '')}</div>
                            </div>
                            ${dates ? `<span class="entry-date">${escapeHtml(dates)}</span>` : ''}
                        </div>
                    </div>
                `;
            });
            html += `</div>`;
        }

        // 6. Technical Skills
        const skillGroups = Object.entries(skills).filter(([_, list]) => Array.isArray(list) && list.length > 0);
        if (skillGroups.length > 0) {
            html += `
                <div class="profile-card-section">
                    <div class="section-label-row">
                        <i data-lucide="cpu"></i>
                        <span>Skills & Capabilities</span>
                    </div>
                    <div style="display:flex; flex-direction:column; gap:0.75rem;">
                        ${skillGroups.map(([cat, list]) => `
                            <div>
                                <div style="font-size:0.75rem; text-transform:uppercase; color:var(--text-dim); font-weight:700; margin-bottom:0.35rem;">
                                    ${escapeHtml(cat.replace(/_/g, ' '))}:
                                </div>
                                <div class="tags-wrap">
                                    ${list.map(s => `<span class="skill-chip">${escapeHtml(s)}</span>`).join('')}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        visualProfileContainer.innerHTML = html;
        if (window.lucide) {
            lucide.createIcons();
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function showResult(data) {
        parsedData = data;
        loaderState.classList.add('hidden');
        
        renderVisualProfile(data.parsed_json);
        
        const formattedJson = syntaxHighlight(data.parsed_json);
        jsonContent.innerHTML = formattedJson;
        
        if (activeView === 'visual') {
            if (visualProfileContainer) visualProfileContainer.classList.remove('hidden');
            jsonCodeContainer.classList.add('hidden');
        } else {
            jsonCodeContainer.classList.remove('hidden');
            if (visualProfileContainer) visualProfileContainer.classList.add('hidden');
        }
        
        copyBtn.classList.remove('hidden');
        downloadBtn.classList.remove('hidden');
        matchJobsBtn.classList.remove('hidden');
        parseBtn.disabled = false;
        
        if (window.lucide) {
            lucide.createIcons();
        }
    }

    function renderMatches(matches) {
        rawMatchesList = matches || [];
        renderFilteredMatches(rawMatchesList);
    }

    function renderFilteredMatches(matches) {
        matchesList.innerHTML = '';
        if (matchCountBadge) {
            matchCountBadge.textContent = `${matches.length} ${matches.length === 1 ? 'Job' : 'Jobs'}`;
        }

        if (matches.length === 0) {
            matchesList.innerHTML = '<div style="padding:2rem; text-align:center; color:var(--text-dim); font-size:0.85rem;">No matching job openings found for this filter.</div>';
        } else {
            matches.forEach(match => {
                const item = document.createElement('div');
                item.className = 'job-match-card';
                
                let scoreClass = '';
                if (match.score < 50) scoreClass = 'danger';
                else if (match.score < 75) scoreClass = 'warning';
                
                const matchedSkills = match.matched_skills || [];
                const missingSkills = match.missing_skills || [];
                const reasoning = match.reasoning || "No reasoning details generated.";
                const companyName = match.company || 'Tech Company';
                const initial = companyName.charAt(0).toUpperCase() || 'J';

                const matchedPills = matchedSkills.map(s => `<span class="badge-matched">${escapeHtml(s)}</span>`).join('');
                const missingPills = missingSkills.map(s => `<span class="badge-missing">${escapeHtml(s)}</span>`).join('');
                const locationHtml = match.location ? `<span class="location-chip"><i data-lucide="map-pin" style="width:0.7rem;height:0.7rem;display:inline-block;margin-right:2px;"></i>${escapeHtml(match.location)}</span>` : '';

                item.innerHTML = `
                    <div class="job-header-row">
                        <div class="company-avatar-col">
                            <div class="company-avatar-badge">${initial}</div>
                            <div>
                                <h3 class="job-title-text">${escapeHtml(match.title)}</h3>
                                <div class="job-company-text">
                                    <span>${escapeHtml(companyName)}</span>
                                    ${locationHtml}
                                </div>
                            </div>
                        </div>
                        <span class="fit-score-badge ${scoreClass}">${match.score}% Fit</span>
                    </div>

                    <div class="job-card-actions">
                        <a href="${escapeHtml(match.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm">
                            <i data-lucide="external-link"></i>
                            <span>View Job Posting</span>
                        </a>
                        <button class="btn-accordion-toggle" type="button">
                            <span>Recruiter Analysis</span>
                            <i data-lucide="chevron-down" style="width: 0.85rem; height: 0.85rem;"></i>
                        </button>
                    </div>

                    <div class="match-details-drawer hidden">
                        <div>
                            <div class="drawer-section-title">Matched Capabilities (${matchedSkills.length})</div>
                            <div class="pills-flow">
                                ${matchedPills || '<span style="color:var(--text-dim); font-size:0.75rem;">None identified</span>'}
                            </div>
                        </div>
                        <div>
                            <div class="drawer-section-title">Missing / Target Requirements (${missingSkills.length})</div>
                            <div class="pills-flow">
                                ${missingPills || '<span style="color:var(--text-dim); font-size:0.75rem;">None identified</span>'}
                            </div>
                        </div>
                        <div>
                            <div class="drawer-section-title">Recruiter Fit Memo</div>
                            <div class="analysis-memo-box">${escapeHtml(reasoning)}</div>
                        </div>
                    </div>
                `;

                // Handle accordion toggle
                const toggleBtn = item.querySelector('.btn-accordion-toggle');
                const detailsDrawer = item.querySelector('.match-details-drawer');
                toggleBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const isHidden = detailsDrawer.classList.contains('hidden');
                    if (isHidden) {
                        detailsDrawer.classList.remove('hidden');
                        toggleBtn.innerHTML = `<span>Hide Analysis</span><i data-lucide="chevron-up" style="width: 0.85rem; height: 0.85rem;"></i>`;
                    } else {
                        detailsDrawer.classList.add('hidden');
                        toggleBtn.innerHTML = `<span>Recruiter Analysis</span><i data-lucide="chevron-down" style="width: 0.85rem; height: 0.85rem;"></i>`;
                    }
                    if (window.lucide) lucide.createIcons();
                });

                matchesList.appendChild(item);
            });
            if (window.lucide) lucide.createIcons();
        }
        matchesCard.classList.remove('hidden');
    }

    function showError(message) {
        loaderState.classList.add('hidden');
        emptyState.classList.remove('hidden');
        parseBtn.disabled = false;
        alert(`Notice: ${message}`);
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
                    let strVal = match.slice(1, -1);
                    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(strVal) || /^mailto:[^\s]+$/.test(strVal)) {
                        let href = strVal.startsWith('mailto:') ? strVal : 'mailto:' + strVal;
                        return '<span class="' + cls + '">"<a href="' + href + '" class="json-link">' + strVal + '</a>"</span>';
                    }
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
    const agentStatusText = document.getElementById('agentStatusText');
    const topAgentStatus = document.getElementById('topAgentStatus');

    function connectAgentStream() {
        if (agentStatusText) agentStatusText.textContent = "Connecting";
        if (topAgentStatus) topAgentStatus.textContent = "Connecting";
        
        const eventSource = new EventSource('/api/agent/stream');

        eventSource.onopen = () => {
            if (agentStatusBadge) agentStatusBadge.className = "status-indicator-dot";
            if (agentStatusText) agentStatusText.textContent = "Online";
            if (topAgentStatus) topAgentStatus.textContent = "Live Monitoring";
            appendTerminalLine(new Date().toTimeString().split(' ')[0], "Connected to remote job feed monitor.", "system");
        };

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                appendTerminalLine(data.time, data.message, data.type);
                
                if (data.type === "match" || data.type === "success") {
                    fetchMatchesSilent();
                }
            } catch (err) {
                console.error("Failed to parse SSE event:", err);
            }
        };

        eventSource.onerror = (err) => {
            console.error("SSE connection error:", err);
            if (agentStatusBadge) agentStatusBadge.className = "status-indicator-dot error";
            if (agentStatusText) agentStatusText.textContent = "Reconnecting";
            if (topAgentStatus) topAgentStatus.textContent = "Reconnecting";
            appendTerminalLine(new Date().toTimeString().split(' ')[0], "Feed connection interrupted. Retrying in 5s...", "error");
            eventSource.close();
            setTimeout(connectAgentStream, 5000);
        };
    }

    function appendTerminalLine(time, message, type) {
        if (!agentTerminal) return;
        const line = document.createElement('div');
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
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ resume_id: parsedData.id })
            });
            if (response.ok) {
                const data = await response.json();
                rawMatchesList = data.matches || [];
                renderMatches(rawMatchesList);
            }
        } catch (error) {
            console.error('Silent match fetch failed:', error);
        }
    }

    connectAgentStream();
});
